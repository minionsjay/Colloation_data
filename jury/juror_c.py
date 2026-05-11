"""Juror C: Cloud premium model.

Calls commercial frontier models via litellm or direct API.
Default: Claude 3.5 Haiku (fast, cheap, strong multilingual).
"""

import json
import os
import time
from datetime import datetime, timezone

import httpx

from config import settings
from pipeline.schema import JurorVerdict

# ── Provider configurations ─────────────────────────────────────

PREMIUM_PROVIDERS = {
    "anthropic": {
        "url": "https://api.anthropic.com/v1/messages",
        "api_key_env": "ANTHROPIC_API_KEY",
        "default_model": "claude-sonnet-4-6-20250514",
        "build_request": lambda model, system, user: {
            "model": model,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "temperature": 0.1,
            "max_tokens": 1024,
        },
        "parse_response": lambda body: (
            body["content"][0]["text"],
            body.get("usage", {}).get("input_tokens", 0) + body.get("usage", {}).get("output_tokens", 0),
        ),
        "auth_header": lambda key: {"x-api-key": key, "anthropic-version": "2023-06-01"},
    },
    "gemini": {
        "url": "",  # built dynamically
        "api_key_env": "GOOGLE_API_KEY",
        "default_model": "gemini-2.5-flash",
        "build_request": lambda model, system, user: {
            "contents": [{"parts": [{"text": f"{system}\n\n{user}"}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 512},
        },
        "parse_response": lambda body: (
            body["candidates"][0]["content"]["parts"][0]["text"],
            body.get("usageMetadata", {}).get("totalTokenCount", 0),
        ),
        "auth_header": lambda key: {},  # Gemini uses query param
        "build_url": lambda model, key: (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            f"?key={key}"
        ),
    },
    "openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "api_key_env": "OPENAI_API_KEY",
        "default_model": "gpt-4o-mini",
        "build_request": lambda model, system, user: {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.1,
            "max_tokens": 512,
        },
        "parse_response": lambda body: (
            body["choices"][0]["message"]["content"],
            body.get("usage", {}).get("total_tokens", 0),
        ),
        "auth_header": lambda key: {"Authorization": f"Bearer {key}"},
    },
    "custom": {
        "url": "",  # set via base_url param or JUROR_C_BASE_URL env
        "api_key_env": "JUROR_C_API_KEY",
        "default_model": "gemini-2.5-flash",
        # custom uses OpenAI-compatible API format (most common for proxies/aggregators)
        "build_request": lambda model, system, user: {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.1,
            "max_tokens": 1024,
        },
        "parse_response": lambda body: (
            body["choices"][0]["message"]["content"],
            body.get("usage", {}).get("total_tokens", 0),
        ),
        "auth_header": lambda key: {"Authorization": f"Bearer {key}"},
    },
}


def call_juror_c(
    content_id: str,
    language: str,
    system_prompt: str,
    user_prompt: str,
    provider: str = "anthropic",
    model_name: str = "",
    base_url: str = "",
    api_key: str = "",
    timeout: float = 30.0,
    no_proxy: bool = False,
) -> JurorVerdict:
    """Call juror C via a premium cloud model.

    Args:
        provider: One of 'anthropic', 'gemini', 'openai', 'custom'
        model_name: Override default model
        base_url: Override API endpoint (for proxies, aggregators, local deployments).
                  Custom/anthropic provider uses this directly.
        api_key: Override API key
        no_proxy: If True, bypass system HTTP_PROXY/HTTPS_PROXY settings
    """
    cfg = PREMIUM_PROVIDERS.get(provider)
    if cfg is None:
        return JurorVerdict(
            content_id=content_id,
            juror="C",
            model_name=f"unknown:{provider}",
            violation=None,
            reasoning=f"Unknown provider: {provider}",
            language=language,
            judged_at=datetime.now(timezone.utc),
        )

    key = api_key or os.getenv("JUROR_C_API_KEY", "") or settings.juror_c_api_key or os.getenv(cfg["api_key_env"], "")
    if not key:
        return JurorVerdict(
            content_id=content_id,
            juror="C",
            model_name=cfg["default_model"],
            violation=None,
            reasoning=f"Juror C ({provider}) API key not set. Set {cfg['api_key_env']} or JUROR_C_API_KEY in .env",
            language=language,
            judged_at=datetime.now(timezone.utc),
        )

    model = model_name or cfg["default_model"]
    t0 = time.monotonic()

    try:
        request_body = cfg["build_request"](model, system_prompt, user_prompt)

        # Resolve URL: param > env > settings > provider default
        custom_url = base_url or os.getenv("JUROR_C_BASE_URL", "") or settings.juror_c_base_url
        if custom_url:
            url = custom_url
            # Ensure URL includes the chat completions path for OpenAI-compatible endpoints
            if provider == "custom" and not url.endswith("/chat/completions"):
                url = url.rstrip("/") + "/chat/completions"
        elif "build_url" in cfg:
            url = cfg["build_url"](model, key)
        else:
            url = cfg["url"]
            if not url:
                return JurorVerdict(
                    content_id=content_id, juror="C", model_name=model,
                    violation=None,
                    reasoning="Juror C base URL not set. Set JUROR_C_BASE_URL in .env or pass base_url param.",
                    language=language, judged_at=datetime.now(timezone.utc),
                )

        if no_proxy:
            client_kwargs = {"timeout": timeout, "trust_env": False}
        else:
            client_kwargs = {"timeout": timeout}
        if provider == "custom" or custom_url:
            client_kwargs["verify"] = False

        with httpx.Client(**client_kwargs) as client:
            resp = client.post(
                url,
                headers=cfg["auth_header"](key),
                json=request_body,
            )
            resp.raise_for_status()
            body = resp.json()
            raw, tokens = cfg["parse_response"](body)
    except Exception as e:
        return JurorVerdict(
            content_id=content_id,
            juror="C",
            model_name=model,
            violation=None,
            reasoning=f"Juror C API error: {type(e).__name__}: {e}",
            language=language,
            latency_ms=(time.monotonic() - t0) * 1000,
            judged_at=datetime.now(timezone.utc),
        )

    latency_ms = (time.monotonic() - t0) * 1000

    # Parse JSON from response
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:]) if len(lines) > 1 else text
        if text.endswith("```"):
            text = text[:-3]

    verdict = JurorVerdict(
        content_id=content_id,
        juror="C",
        model_name=model,
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
        verdict.reasoning = f"Failed to parse response: {raw[:300]}"

    return verdict
