#!/usr/bin/env python3
"""Test Juror A: Local lightweight specialist models per language.

Juror A runs ON-PREMISE — zero API cost, data never leaves your machine.
This test shows two approaches:

  1. transformers (direct) — load model in-process, no server needed
  2. API server (production) — vLLM/llama.cpp with OpenAI-compatible endpoint

Each target language has a recommended small model.
"""

import sys
import json
import os
from typing import Optional

sys.path.insert(0, ".")

# ── Language → Model mapping for Juror A ─────────────────────

# Each entry: (recommended_model, fallback_model, model_type, description)
JUROR_A_MODELS: dict[str, dict] = {
    "th": {
        "primary": "scb10x/typhoon2-safety-preview",
        "fallback": "airesearch/wangchanberta-base-att-spm-uncased",
        "type": "bert",
        "task": "text-classification",
        "description": "Thai/English safety classifier (mDeBERTa-v3). Covers 21 Thai-sensitive harm topics.",
        "max_length": 512,
    },
    "id": {
        "primary": "cahya/bert-base-indonesian-522M",
        "fallback": "indolem/indobert-base-uncased",
        "type": "bert",
        "task": "text-classification",
        "description": "Indonesian BERT. Can classify hate speech with fine-tuning.",
        "max_length": 512,
    },
    "tr": {
        "primary": "dbmdz/bert-base-turkish-cased",
        "fallback": "dbmdz/bert-base-turkish-128k-cased",
        "type": "bert",
        "task": "text-classification",
        "description": "Turkish BERT (BERTurk). Fine-tune on TR offensive language dataset.",
        "max_length": 512,
    },
    "pt": {
        "primary": "cardiffnlp/twitter-xlm-roberta-base-sentiment",
        "fallback": "neuralmind/bert-base-portuguese-cased",
        "type": "bert",
        "task": "text-classification",
        "description": "Multilingual XLM-RoBERTa sentiment. Detects negative/offensive tone in Portuguese.",
        "max_length": 512,
    },
    "es": {
        "primary": "finiteautomata/beto-sentiment-analysis",
        "fallback": "dccuchile/bert-base-spanish-wwm-uncased",
        "type": "bert",
        "task": "text-classification",
        "description": "Spanish BERT (BETO). Good base for toxic content detection.",
        "max_length": 512,
    },
    "ar": {
        "primary": "aubmindlab/bert-base-arabertv02",
        "fallback": "UBC-NLP/MARBERT",
        "type": "bert",
        "task": "text-classification",
        "description": "AraBERT v2. Strong Arabic NLU. Fine-tune on Arabic hate speech datasets.",
        "max_length": 512,
    },
    "en": {
        "primary": "cardiffnlp/twitter-roberta-base-offensive",
        "fallback": "unitary/toxic-bert",
        "type": "bert",
        "task": "text-classification",
        "description": "RoBERTa fine-tuned on offensive tweet detection. Good for English SG/ZA forums.",
        "max_length": 512,
    },
}


# ── Approach 1: Direct transformers (no server needed) ─────

def test_transformers_direct(language: str, text: str) -> Optional[dict]:
    """Load a model directly via transformers and classify a text.

    This is the simplest way to test Juror A without setting up a server.
    Works for both BERT (classification) and causal LM (generation) models.
    """
    print(f"\n{'─'*50}")
    print(f"Testing transformers direct [{language}]: {text[:60]}...")

    model_info = JUROR_A_MODELS.get(language)
    if not model_info:
        print(f"  No model configured for language: {language}")
        return None

    model_name = model_info["primary"]
    model_type = model_info["type"]

    try:
        from transformers import pipeline, AutoTokenizer, AutoModelForSequenceClassification, AutoModelForCausalLM

        if model_type == "bert":
            # ── BERT-style: classification pipeline ──
            print(f"  Loading {model_name}...")
            pipe = pipeline(
                "text-classification",
                model=model_name,
                tokenizer=model_name,
                truncation=True,
                max_length=model_info["max_length"],
            )
            result = pipe(text[:model_info["max_length"]])
            print(f"  Result: {result}")
            return {"model": model_name, "text": text[:80], "result": result}

        elif model_type == "causal-lm":
            # ── Causal LM: prompt-based classification ──
            print(f"  Loading {model_name}...")
            tokenizer = AutoTokenizer.from_pretrained(model_name)
            model = AutoModelForCausalLM.from_pretrained(model_name)
            if tokenizer.pad_token is None:
                tokenizer.pad_token = tokenizer.eos_token

            prompt = f"""Classify if this text contains hate speech, offensive language, or is clean. Reply with just the label.
Text: {text[:500]}
Label (hate_speech/offensive/clean):"""

            inputs = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=model_info["max_length"])
            outputs = model.generate(**inputs, max_new_tokens=10, temperature=0.1)
            response = tokenizer.decode(outputs[0], skip_special_tokens=True)
            print(f"  Response: {response}")
            return {"model": model_name, "text": text[:80], "result": response}

    except ImportError:
        print(f"  ⚠ transformers not installed. pip install transformers torch")
        return None
    except Exception as e:
        print(f"  ✗ Error loading {model_name}: {type(e).__name__}: {e}")
        # Try fallback
        fallback = model_info.get("fallback")
        if fallback and fallback != model_name:
            print(f"  → Trying fallback: {fallback}")
            try:
                pipe = pipeline("text-classification", model=fallback, tokenizer=fallback)
                result = pipe(text[:model_info["max_length"]])
                print(f"  Fallback result: {result}")
                return {"model": fallback, "text": text[:80], "result": result}
            except Exception as e2:
                print(f"  ✗ Fallback also failed: {e2}")
        return None


# ── Approach 2: API server (production, vLLM/llama.cpp) ────

def test_api_server(language: str, text: str):
    """Test Juror A via a local OpenAI-compatible API server.

    Start the server first:
        # For GGUF models (llama.cpp):
        llama-server -m model.gguf --port 8080

        # For HF models (vLLM):
        vllm serve TeenyTinyLlama-460m-HateBR --port 8080 --dtype half

    Then this function calls it via HTTP.
    """
    print(f"\n{'─'*50}")
    print(f"Testing API server [{language}]: {text[:60]}...")

    endpoint = os.getenv("JUROR_A_ENDPOINT", "http://localhost:8080")
    model_info = JUROR_A_MODELS.get(language, {})

    try:
        import httpx

        payload = {
            "model": model_info.get("primary", "local-model"),
            "messages": [
                {
                    "role": "system",
                    "content": f"You are a content moderator specialized in {language} language. "
                    "Classify whether the user's text contains hate speech, violence, "
                    "adult content, fraud, illegal activity, or is politically sensitive. "
                    "Reply ONLY with a JSON: "
                    '{"violation": true/false, "category": "...", "confidence": 0.0-1.0, "reasoning": "..."}',
                },
                {"role": "user", "content": text},
            ],
            "temperature": 0.1,
            "max_tokens": 256,
        }

        with httpx.Client(timeout=30) as client:
            resp = client.post(f"{endpoint}/v1/chat/completions", json=payload)
            resp.raise_for_status()
            body = resp.json()
            response = body["choices"][0]["message"]["content"]
            tokens = body.get("usage", {}).get("total_tokens", 0)
            print(f"  Response: {response[:200]}")
            print(f"  Tokens used: {tokens}")
            return response

    except ImportError:
        print("  ⚠ httpx not installed")
    except httpx.ConnectError:
        print(f"  ⚠ No server at {endpoint}. Start vLLM or llama.cpp first.")
        print(f"    Example: vllm serve {model_info.get('primary', 'model')} --port 8080")
    except Exception as e:
        print(f"  ✗ API error: {e}")


# ── Approach 3: Mock test (no model, no server) ────────────

def test_juror_a_mock():
    """Test Juror A with mocked responses — validates the pipeline
    without requiring any model download or server."""
    print("=" * 60)
    print("JUROR A MOCK TEST — validates pipeline, no model needed")
    print("=" * 60)

    from jury.juror_a import call_juror_a
    from jury.prompt_builder import build_juror_prompt
    from pipeline.schema import JurorVerdict

    test_cases = [
        {
            "country": "TH", "language": "th",
            "text": "พวกมึงแม่งโง่ ไปตายซะ",
            "description": "Toxic Thai — should detect violation",
        },
        {
            "country": "ID", "language": "id",
            "text": "Hari ini saya masak nasi goreng yang enak",
            "description": "Benign Indonesian recipe — should be clean",
        },
        {
            "country": "TR", "language": "tr",
            "text": "Bugün hava çok güzel, yürüyüşe çıktım",
            "description": "Benign Turkish — should be clean",
        },
        {
            "country": "BR", "language": "pt",
            "text": "Seu macaco nojento, volta pra África",
            "description": "Racist Portuguese — should detect hate speech",
        },
        {
            "country": "SA", "language": "ar",
            "text": "مرحبا كيف حالك اليوم؟",
            "description": "Friendly Arabic greeting — should be clean",
        },
    ]

    print("\nSince no local model server is running, all calls will return")
    print("violation=None with an error message. This is expected behavior.\n")

    for tc in test_cases:
        print(f"── [{tc['country']}/{tc['language']}] {tc['description']} ──")
        print(f"    Text: {tc['text'][:80]}")

        verdict = call_juror_a(
            content_id="mock-test",
            language=tc["language"],
            system_prompt="You are a local language specialist.",  # simplified
            user_prompt=f"Judge this content:\n{tc['text']}",
            model_name=JUROR_A_MODELS.get(tc["language"], {}).get("primary", "unknown"),
            timeout=3.0,
        )

        print(f"    Violation: {verdict.violation}")
        print(f"    Reasoning: {verdict.reasoning[:120]}")
        print()

    print("─" * 60)
    print("To test with a real model:")
    print("  1. pip install transformers torch")
    print("  2. python test_juror_a.py transformers  # uses approach 1")
    print()
    print("For production (server-based):")
    print("  1. pip install vllm  (or build llama.cpp)")
    print(f"  2. vllm serve TeenyTinyLlama-460m-HateBR --port 8080")
    print("  3. python test_juror_a.py server  # uses approach 2")


# ── Show model info ──────────────────────────────────────

def show_model_map():
    """Display the model mapping for all target languages."""
    print("=" * 60)
    print("JUROR A MODEL MAP")
    print("=" * 60)

    for lang, info in JUROR_A_MODELS.items():
        print(f"\n▸ {lang}")
        print(f"  Primary:   {info['primary']}")
        print(f"  Fallback:  {info['fallback']}")
        print(f"  Type:      {info['type']} ({info['task']})")
        print(f"  {info['description']}")

    print(f"\n{'─'*60}")
    print("DOWNLOAD COMMANDS (for testing):")
    print("─" * 60)
    for lang, info in JUROR_A_MODELS.items():
        if lang in ("pt",):  # causal LM — need different pipeline
            print(f"# {lang}: {info['primary']}")
            print(f"python -c \"from transformers import AutoTokenizer, AutoModelForCausalLM; \\")
            print(f"    tokenizer = AutoTokenizer.from_pretrained('{info['primary']}'); \\")
            print(f"    model = AutoModelForCausalLM.from_pretrained('{info['primary']}')\"")
        else:
            print(f"# {lang}: {info['primary']}")
            print(f"python -c \"from transformers import pipeline; \\")
            print(f"    pipe = pipeline('text-classification', model='{info['primary']}')\"")


# ── Main ──────────────────────────────────────────────────

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "mock"

    if mode == "models":
        show_model_map()

    elif mode == "transformers":
        print("Testing with transformers (direct model loading)...")
        print("Models will be downloaded on first use (~500MB each).\n")

        samples = [
            ("th", "พวกมึงแม่งโง่ ไปตายซะ"),
            ("id", "Hari ini saya masak nasi goreng yang enak"),
            ("tr", "Bugün hava çok güzel, yürüyüşe çıktım"),
            ("pt", "Seu macaco nojento, volta pra África"),
            ("es", "Pinche indio de mierda, regrésate a tu pueblo"),
            ("ar", "مرحبا كيف حالك اليوم؟"),
            ("en", "You are all stupid idiots and I hate you"),
        ]
        for lang, text in samples:
            test_transformers_direct(lang, text)

    elif mode == "server":
        print("Testing with local API server...")
        print(f"Server: {os.getenv('JUROR_A_ENDPOINT', 'http://localhost:8080')}\n")

        samples = [
            ("th", "พวกมึงแม่งโง่ ไปตายซะ"),
            ("pt", "Seu macaco nojento, volta pra África"),
        ]
        for lang, text in samples:
            test_api_server(lang, text)

    else:
        # Default: mock test (no model/download needed)
        test_juror_a_mock()
        print()
        show_model_map()
