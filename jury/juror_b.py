"""Juror B: Open-source generalist model via API.

Calls open-source LLM APIs (Together AI, Groq, Fireworks).
These host Llama, Qwen, Mistral etc. at low cost.

Default: Qwen2.5-72B-Instruct via Together AI (strong multilingual, cheap).
"""

import json
import os
import time
from datetime import datetime, timezone

import httpx

from config import settings
from pipeline.schema import JurorVerdict

# ── Provider configurations ─────────────────────────────────────

PROVIDERS = {
    "together": {
        "url": "https://api.together.xyz/v1/chat/completions",
        "api_key_env": "TOGETHER_API_KEY",
        "default_model": "Qwen/Qwen2.5-72B-Instruct-Turbo",
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "api_key_env": "GROQ_API_KEY",
        "default_model": "llama-3.1-70b-versatile",
    },
    "fireworks": {
        "url": "https://api.fireworks.ai/inference/v1/chat/completions",
        "api_key_env": "FIREWORKS_API_KEY",
        "default_model": "accounts/fireworks/models/llama-v3p1-70b-instruct",
    },
    "custom": {
        "url": "",  # set via base_url param or JUROR_B_BASE_URL env
        "api_key_env": "JUROR_B_API_KEY",
        "default_model": "deepseek-chat",
    },
}


def call_juror_b(
    content_id: str,
    language: str,
    system_prompt: str,
    user_prompt: str,
    provider: str = "together",
    model_name: str = "",
    base_url: str = "",
    api_key: str = "",
    timeout: float = 30.0,
    no_proxy: bool = False,
) -> JurorVerdict:
    """Call juror B via an open-source model API provider.

    Args:
        provider: One of 'together', 'groq', 'fireworks', 'custom'
        model_name: Override default model for the provider
        base_url: Override API endpoint (for proxies, local vLLM, aggregators)
        api_key: Override API key
        no_proxy: If True, bypass system HTTP_PROXY/HTTPS_PROXY settings
    """
    cfg = PROVIDERS.get(provider)
    if cfg is None:
        return JurorVerdict(
            content_id=content_id,
            juror="B",
            model_name=f"unknown-provider:{provider}",
            violation=None,
            reasoning=f"Unknown provider: {provider}",
            language=language,
            judged_at=datetime.now(timezone.utc),
        )

    # Resolve URL: param > env > settings > provider default
    url = base_url or os.getenv("JUROR_B_BASE_URL", "") or settings.juror_b_base_url or cfg["url"]
    if not url:
        return JurorVerdict(
            content_id=content_id,
            juror="B",
            model_name=cfg["default_model"],
            violation=None,
            reasoning="Juror B base URL not set. Set JUROR_B_BASE_URL in .env or pass base_url param.",
            language=language,
            judged_at=datetime.now(timezone.utc),
        )
    # Ensure URL includes the chat completions path for OpenAI-compatible endpoints
    if not url.endswith("/chat/completions"):
        url = url.rstrip("/") + "/chat/completions"

    # Resolve API key: param > env > settings > provider env
    key = api_key or os.getenv("JUROR_B_API_KEY", "") or settings.juror_b_api_key or os.getenv(cfg["api_key_env"], "")
    if not key:
        return JurorVerdict(
            content_id=content_id,
            juror="B",
            model_name=cfg["default_model"],
            violation=None,
            reasoning=f"Juror B ({provider}) API key not set. Set {cfg['api_key_env']} or JUROR_B_API_KEY in .env",
            language=language,
            judged_at=datetime.now(timezone.utc),
        )

    model = model_name or cfg["default_model"]
    t0 = time.monotonic()

    try:
        client_kwargs = {"timeout": timeout}
        if no_proxy:
            client_kwargs["trust_env"] = False
        if provider == "custom" or url != cfg["url"]:
            client_kwargs["verify"] = False  # custom endpoints may have self-signed certs

        with httpx.Client(**client_kwargs) as client:
            resp = client.post(
                url,
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 512,
                },
            )
            resp.raise_for_status()
            body = resp.json()
            raw = body["choices"][0]["message"]["content"]
            tokens = body.get("usage", {}).get("total_tokens", 0)
    except Exception as e:
        return JurorVerdict(
            content_id=content_id,
            juror="B",
            model_name=model,
            violation=None,
            reasoning=f"Juror B API error: {type(e).__name__}: {e}",
            language=language,
            latency_ms=(time.monotonic() - t0) * 1000,
            judged_at=datetime.now(timezone.utc),
        )

    latency_ms = (time.monotonic() - t0) * 1000
    return _parse_verdict(raw, content_id, language, "B", model, latency_ms, tokens)


def _parse_verdict(
    raw: str,
    content_id: str,
    language: str,
    juror: str,
    model_name: str,
    latency_ms: float,
    tokens: int,
) -> JurorVerdict:
    """Parse the JSON response into a JurorVerdict."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:]) if len(lines) > 1 else text
        if text.endswith("```"):
            text = text[:-3]

    verdict = JurorVerdict(
        content_id=content_id,
        juror=juror,
        model_name=model_name,
        violation=None,
        language=language,
        latency_ms=latency_ms,
        tokens_used=tokens,
        judged_at=datetime.now(timezone.utc),
    )

    try:
        # Try to find JSON in the response
        data = json.loads(text)
        verdict.violation = data.get("violation")
        verdict.category = data.get("category", "none")
        verdict.confidence = float(data.get("confidence", 0.0))
        verdict.reasoning = data.get("reasoning", "")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        verdict.violation = None
        verdict.reasoning = f"Failed to parse response: {raw[:300]}"

    return verdict
