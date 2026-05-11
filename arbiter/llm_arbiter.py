"""Stage 2 arbiter: LLM judge reviews juror reasoning and makes final verdict.

Uses the strongest available model (default: Claude via Anthropic API)
to evaluate the three jurors' arguments and render a final judgment.
"""

import json
import os
import time
from datetime import datetime, timezone

import httpx

from pipeline.schema import JurorVerdict, FinalVerdict, ViolationCategory

ARBITER_SYSTEM_PROMPT = """You are the Chief Justice of a content moderation panel. Three jurors (A, B, C) have each reviewed a piece of internet content and rendered their verdicts with reasoning.

Your job is to:
1. Read the original content carefully
2. Review each juror's reasoning
3. Make the FINAL verdict — violation or not
4. Explain which juror you agree with and why

## Rules
- You are NOT bound by majority vote. If 2 jurors say "clean" but their reasoning is weak while the 1 dissenter has strong, specific evidence — adopt the dissenter.
- Pay special attention to Juror A (local language specialist) when the content contains local slang, cultural references, or code-switching.
- If the content genuinely contains harmful material (hate speech, violence, etc.), rule "violation" even if all jurors missed it.
- If all jurors are uncertain or their reasoning conflicts beyond resolution, set requires_human_review=true.
- Be specific in your reasoning: cite which juror made which points and evaluate their quality.
"""

ARBITER_USER_PROMPT = """## Original Content

**Source:** {source}
**Country:** {country}
**Detected Language:** {language}

### Content:
```
{content}
```

---

## Juror A Verdict (Local Language Specialist)
**Model:** {model_a}
**Ruling:** {ruling_a}
**Category:** {category_a}
**Confidence:** {confidence_a}

**Reasoning:**
{reasoning_a}

---

## Juror B Verdict (Generalist Reasoner)
**Model:** {model_b}
**Ruling:** {ruling_b}
**Category:** {category_b}
**Confidence:** {confidence_b}

**Reasoning:**
{reasoning_b}

---

## Juror C Verdict (Senior Moderator)
**Model:** {model_c}
**Ruling:** {ruling_c}
**Category:** {category_c}
**Confidence:** {confidence_c}

**Reasoning:**
{reasoning_c}

---

Please deliver your final judgment as JSON:

```json
{{
  "final_verdict": true,
  "category": "hate_speech",
  "confidence": 0.90,
  "adopted_juror": "A",
  "adopted_reason": "Juror A correctly identified the local slur 'XXX' which Jurors B and C missed. A's reasoning about the cultural context is specific and convincing.",
  "reasoning": "Detailed explanation of your analysis. Compare the jurors' arguments and explain why you agree or disagree with each.",
  "requires_human_review": false
}}
```

Output ONLY valid JSON — nothing else."""


def call_arbiter(
    content_id: str,
    content: str,
    verdicts: list[JurorVerdict],
    source: str = "",
    country: str = "",
    language: str = "",
    provider: str = "anthropic",
    model: str = "",
    base_url: str = "",
    api_key: str = "",
    no_proxy: bool = False,
    timeout: float = 60.0,
) -> FinalVerdict:
    """Call the LLM judge to arbitrate between juror verdicts.

    Args:
        content_id: Unique content identifier
        content: The original content text
        verdicts: Three JurorVerdict objects (A, B, C)
        provider: 'anthropic', 'openai', 'gemini', or 'custom'
        model: Override default model
        base_url: Custom API endpoint (for custom provider)
        api_key: Override API key
        no_proxy: If True, bypass system proxy
        timeout: Max seconds for API call

    Returns a FinalVerdict. If the arbiter fails, falls back to
    majority voting and marks requires_human_review=True.
    """
    if len(verdicts) != 3:
        return _fallback_verdict(content_id, verdicts, "Expected 3 verdicts")

    # Build prompts
    def _ruling(v: JurorVerdict) -> str:
        if v.violation is True:
            return "VIOLATION"
        if v.violation is False:
            return "CLEAN"
        return "UNCERTAIN"

    user_prompt = ARBITER_USER_PROMPT.format(
        source=source or "unknown",
        country=country or "unknown",
        language=language or "unknown",
        content=content[:3000],
        model_a=verdicts[0].model_name, ruling_a=_ruling(verdicts[0]),
        category_a=verdicts[0].category, confidence_a=verdicts[0].confidence,
        reasoning_a=verdicts[0].reasoning[:1000],
        model_b=verdicts[1].model_name, ruling_b=_ruling(verdicts[1]),
        category_b=verdicts[1].category, confidence_b=verdicts[1].confidence,
        reasoning_b=verdicts[1].reasoning[:1000],
        model_c=verdicts[2].model_name, ruling_c=_ruling(verdicts[2]),
        category_c=verdicts[2].category, confidence_c=verdicts[2].confidence,
        reasoning_c=verdicts[2].reasoning[:1000],
    )

    t0 = time.monotonic()

    try:
        raw_response = _call_llm(
            ARBITER_SYSTEM_PROMPT, user_prompt, provider, model,
            base_url=base_url, api_key=api_key, no_proxy=no_proxy, timeout=timeout,
        )
    except Exception as e:
        return _fallback_verdict(content_id, verdicts, f"Arbiter API error: {e}")

    latency_ms = (time.monotonic() - t0) * 1000

    # Parse JSON response
    text = raw_response.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3]

    try:
        data = json.loads(text)
        return FinalVerdict(
            content_id=content_id,
            final_verdict=bool(data["final_verdict"]),
            category=ViolationCategory(data.get("category", "none")),
            confidence=float(data.get("confidence", 0.5)),
            adopted_juror=str(data.get("adopted_juror", "none")),
            adopted_reason=str(data.get("adopted_reason", "")),
            juror_agreement=_agreement_str(verdicts),
            reasoning=str(data.get("reasoning", "")),
            judge_model=f"{provider}:{model or 'default'}",
            judged_at=datetime.now(timezone.utc),
            requires_human_review=bool(data.get("requires_human_review", False)),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        return _fallback_verdict(content_id, verdicts, f"Failed to parse arbiter response: {e}")


def _call_llm(
    system: str,
    user: str,
    provider: str,
    model: str = "",
    base_url: str = "",
    api_key: str = "",
    no_proxy: bool = False,
    timeout: float = 60.0,
) -> str:
    """Call the LLM and return the text response."""
    from config import settings

    if provider == "custom":
        url = base_url or settings.juror_c_base_url or os.getenv("JUROR_C_BASE_URL", "")
        if not url:
            raise ValueError("Custom arbiter requires base_url. Set JUROR_C_BASE_URL in .env.")
        if not url.endswith("/chat/completions"):
            url = url.rstrip("/") + "/chat/completions"
        key = api_key or settings.juror_c_api_key or os.getenv("JUROR_C_API_KEY", "")
        model = model or "gpt-4o"
        kwargs = {"timeout": timeout, "verify": False}
        if no_proxy:
            kwargs["trust_env"] = False
        with httpx.Client(**kwargs) as client:
            resp = client.post(
                url,
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1024,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    elif provider == "anthropic":
        key = api_key or os.getenv("ANTHROPIC_API_KEY", "") or settings.anthropic_api_key
        model = model or "claude-sonnet-4-6-20250514"
        url = base_url or "https://api.anthropic.com/v1/messages"
        kwargs = {"timeout": timeout}
        if no_proxy:
            kwargs["trust_env"] = False
        with httpx.Client(**kwargs) as client:
            resp = client.post(
                url,
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                json={
                    "model": model,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                    "temperature": 0.2,
                    "max_tokens": 1024,
                },
            )
            resp.raise_for_status()
            return resp.json()["content"][0]["text"]

    elif provider == "openai":
        key = api_key or os.getenv("OPENAI_API_KEY", "") or settings.openai_api_key
        model = model or "gpt-4o"
        url = base_url or "https://api.openai.com/v1/chat/completions"
        kwargs = {"timeout": timeout}
        if no_proxy:
            kwargs["trust_env"] = False
        with httpx.Client(**kwargs) as client:
            resp = client.post(
                url,
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1024,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    elif provider == "gemini":
        key = api_key or os.getenv("GOOGLE_API_KEY", "") or settings.google_api_key
        model = model or "gemini-2.5-flash"
        kwargs = {"timeout": timeout}
        if no_proxy:
            kwargs["trust_env"] = False
        with httpx.Client(**kwargs) as client:
            resp = client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
                json={
                    "contents": [{"parts": [{"text": f"{system}\n\n{user}"}]}],
                    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024},
                },
            )
            resp.raise_for_status()
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]

    else:
        raise ValueError(f"Unknown arbiter provider: {provider}")


def _fallback_verdict(content_id: str, verdicts: list[JurorVerdict], reason: str) -> FinalVerdict:
    """Create a fallback verdict when arbitration fails."""
    return FinalVerdict(
        content_id=content_id,
        final_verdict=False,
        category=ViolationCategory.none,
        confidence=0.0,
        adopted_juror="none",
        adopted_reason=reason,
        juror_agreement=_agreement_str(verdicts),
        reasoning=f"Arbiter unavailable: {reason}. Requires human review.",
        judge_model="fallback",
        judged_at=datetime.now(timezone.utc),
        requires_human_review=True,
    )


def _agreement_str(verdicts: list[JurorVerdict]) -> str:
    parts = []
    for v in verdicts:
        val = "null" if v.violation is None else ("violation" if v.violation else "clean")
        parts.append(f"{v.juror}:{val}")
    return " / ".join(parts)
