"""Juror A: Local lightweight specialist model.

Two modes:
  1. DIRECT MODE — load model in-process via transformers (no server needed)
  2. SERVER MODE — call a local vLLM/llama.cpp OpenAI-compatible endpoint

Usage:
  # Direct mode (simplest — model loaded in Python process):
  from jury.juror_a import classify_direct
  verdict = classify_direct("th", "พวกมึง...")

  # Server mode (production — one server, many clients):
  #   vllm serve TeenyTinyLlama-460m-HateBR --port 8080
  from jury.juror_a import call_juror_a
  verdict = call_juror_a(content_id, language, system_prompt, user_prompt)
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

from config import settings
from pipeline.schema import JurorVerdict

# Where downloaded models live
MODELS_DIR = Path(__file__).parent.parent / "models"

# Language → local model directory mapping
LANGUAGE_MODEL_MAP = {
    "en": MODELS_DIR / "en--twitter-roberta-offensive",
    "pt": MODELS_DIR / "pt--xlm-roberta-sentiment",
    "th": MODELS_DIR / "th--typhoon2-safety",
    "id": MODELS_DIR / "id--bert-base-indonesian",
    "tr": MODELS_DIR / "tr--bert-base-turkish",
    "es": MODELS_DIR / "es--beto-sentiment",
    "ar": MODELS_DIR / "ar--arabert-v02",
}

# HuggingFace model names (fallback when no local model exists)
LANGUAGE_MODEL_HF = {
    "en": "cardiffnlp/twitter-roberta-base-offensive",
    "pt": "cardiffnlp/twitter-xlm-roberta-base-sentiment",
    "th": "scb10x/typhoon2-safety-preview",
    "id": "cahya/bert-base-indonesian-522M",
    "tr": "dbmdz/bert-base-turkish-cased",
    "es": "finiteautomata/beto-sentiment-analysis",
    "ar": "aubmindlab/bert-base-arabertv02",
}


# ── Direct mode — load model in-process ─────────────────────

# Cache: keep loaded models in memory so we don't reload per query
_loaded_models: dict[str, object] = {}


def _load_model(language: str):
    """Load (or retrieve cached) model for a language."""
    if language in _loaded_models:
        return _loaded_models[language]

    # Prefer local model, fall back to HF name
    local_path = LANGUAGE_MODEL_MAP.get(language)
    model_id = str(local_path) if local_path and local_path.exists() else LANGUAGE_MODEL_HF.get(language)

    if model_id is None:
        return None

    # Import here so transformers is only needed when using direct mode
    from transformers import pipeline

    pipe = pipeline(
        "text-classification",
        model=model_id,
        tokenizer=model_id,
        truncation=True,
        max_length=512,
    )
    _loaded_models[language] = pipe
    return pipe


def classify_direct(
    language: str,
    text: str,
    content_id: str = "",
) -> Optional[dict]:
    """Classify a text using a locally loaded model.

    Returns a dict with violation/category/confidence/reasoning,
    or None if no model is available for this language.

    This is the simplest way to use Juror A:
        result = classify_direct("en", "You are an idiot!")
        # -> {"violation": True, "category": "hate_speech", "confidence": 0.94, "reasoning": "..."}
    """
    try:
        pipe = _load_model(language)
    except Exception:
        return None

    if pipe is None:
        return None

    try:
        result = pipe(text[:512])
        pred = result[0]
        label = pred["label"]
        score = pred["score"]
    except Exception:
        return None

    # Map model labels to our violation categories
    # Different models use different label schemes — normalize them
    label_lower = label.lower()

    # ── Violation indicators ──
    violation_signals = [
        "offensive" in label_lower and "non" not in label_lower,
        "hate" in label_lower,
        "toxic" in label_lower,
        label_lower in ("neg", "negative"),                  # es/pt sentiment: negative → violation proxy
        label_lower == "label_1",                             # th typhoon2: LABEL_1 = harmful
    ]
    # ── Clean indicators ──
    clean_signals = [
        "non-offensive" in label_lower,
        "neutral" in label_lower,
        label_lower in ("pos", "positive", "neu"),           # es/pt sentiment: positive/neutral → clean
        "clean" in label_lower,
        "not" in label_lower,
        label_lower == "label_0",                             # th typhoon2: LABEL_0 = safe
    ]

    if any(violation_signals):
        return {
            "violation": True,
            "category": "hate_speech",
            "confidence": score,
            "reasoning": f"Local model detects violation (label={label}, score={score:.3f}).",
        }
    elif any(clean_signals):
        return {
            "violation": False,
            "category": "none",
            "confidence": score,
            "reasoning": f"Local model finds no violation (label={label}, score={score:.3f}).",
        }
    else:
        # Unknown label, return raw result
        return {
            "violation": None,
            "category": "none",
            "confidence": score,
            "reasoning": f"Local model output: label={label}, score={score:.3f}. Unable to map to violation categories.",
        }


# ── Server mode — calls a local vLLM/llama.cpp API ──────────

def call_juror_a(
    content_id: str,
    language: str,
    system_prompt: str,
    user_prompt: str,
    model_name: str = "local-specialist",
    timeout: float = 30.0,
) -> JurorVerdict:
    """Call Juror A via local server (vLLM/llama.cpp).

    First tries the local server. If unavailable, falls back to
    direct model inference (if model is downloaded).
    """
    t0 = time.monotonic()

    # ── Try server mode first ──
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 512,
    }

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                f"{settings.juror_a_endpoint}/v1/chat/completions",
                json=payload,
            )
            resp.raise_for_status()
            body = resp.json()
            raw = body["choices"][0]["message"]["content"]
            tokens = body.get("usage", {}).get("total_tokens", 0)
        latency_ms = (time.monotonic() - t0) * 1000
        return _parse_response(raw, content_id, language, "A", model_name, latency_ms, tokens)
    except Exception:
        pass  # Server unavailable, try direct mode

    # ── Fallback: direct mode ──
    direct_result = classify_direct(language, user_prompt, content_id)
    if direct_result:
        return JurorVerdict(
            content_id=content_id,
            juror="A",
            model_name=LANGUAGE_MODEL_HF.get(language, "unknown"),
            violation=direct_result.get("violation"),
            category=direct_result.get("category", "none"),
            confidence=direct_result.get("confidence", 0.0),
            reasoning=direct_result.get("reasoning", ""),
            language=language,
            latency_ms=(time.monotonic() - t0) * 1000,
            judged_at=datetime.now(timezone.utc),
        )

    # ── Neither mode works ──
    return JurorVerdict(
        content_id=content_id,
        juror="A",
        model_name=LANGUAGE_MODEL_HF.get(language, "unknown"),
        violation=None,
        reasoning=f"Juror A unavailable for '{language}': no server and no local model. "
        f"Download with: python download_models.py {language}",
        language=language,
        latency_ms=(time.monotonic() - t0) * 1000,
        judged_at=datetime.now(timezone.utc),
    )


def _parse_response(
    raw: str,
    content_id: str,
    language: str,
    juror: str,
    model_name: str,
    latency_ms: float,
    tokens: int,
) -> JurorVerdict:
    """Parse the JSON response from a juror into a JurorVerdict."""
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
        data = json.loads(text)
        verdict.violation = data.get("violation")
        verdict.category = data.get("category", "none")
        verdict.confidence = float(data.get("confidence", 0.0))
        verdict.reasoning = data.get("reasoning", "")
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        verdict.violation = None
        verdict.reasoning = f"Failed to parse juror response: {raw[:300]}"

    return verdict
