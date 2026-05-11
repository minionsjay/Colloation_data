#!/usr/bin/env python3
"""Download Juror A local models for each target language.

Usage:
  python download_models.py              # download all models
  python download_models.py en pt        # download specific languages
  python download_models.py --list       # show what's available
  python download_models.py --check      # check what's already downloaded
"""

import os
import sys
from pathlib import Path

# Use HF mirror for faster downloads in China
os.environ["HF_ENDPOINT"] = os.getenv("HF_ENDPOINT", "https://hf-mirror.com")

# Models will be stored in ./models/ directory
MODELS_DIR = Path(__file__).parent / "models"
MODELS_DIR.mkdir(exist_ok=True)


# ── Language → Model mapping ─────────────────────────────────

MODEL_MAP = {
    "en": {
        "name": "cardiffnlp/twitter-roberta-base-offensive",
        "local_dir": "en--twitter-roberta-offensive",
        "description": "English offensive content detection",
        "pipeline": "text-classification",
        "size": "~500MB",
        "test_text": "You are all stupid idiots, go away!",
    },
    "pt": {
        "name": "cardiffnlp/twitter-xlm-roberta-base-sentiment",
        "local_dir": "pt--xlm-roberta-sentiment",
        "description": "Multilingual sentiment (supports PT, hate speech proxy)",
        "pipeline": "text-classification",
        "size": "~1.1GB",
        "test_text": "Seu macaco nojento, volta pra senzala!",
    },
    "th": {
        "name": "scb10x/typhoon2-safety-preview",
        "local_dir": "th--typhoon2-safety",
        "description": "Thai/English harm detection (21 topics, mDeBERTa-v3)",
        "pipeline": "text-classification",
        "size": "~700MB",
        "test_text": "พวกมึงแม่งโง่ ไปตายซะ",
    },
    "id": {
        "name": "cahya/bert-base-indonesian-522M",
        "local_dir": "id--bert-base-indonesian",
        "description": "Indonesian BERT (base model, needs fine-tuning)",
        "pipeline": "text-classification",
        "size": "~500MB",
        "test_text": "Hari ini saya masak nasi goreng yang enak",
    },
    "tr": {
        "name": "dbmdz/bert-base-turkish-cased",
        "local_dir": "tr--bert-base-turkish",
        "description": "Turkish BERT (BERTurk, base model)",
        "pipeline": "text-classification",
        "size": "~500MB",
        "test_text": "Bugün hava çok güzel, yürüyüşe çıktım",
    },
    "es": {
        "name": "finiteautomata/beto-sentiment-analysis",
        "local_dir": "es--beto-sentiment",
        "description": "Spanish BETO sentiment/toxic content classifier",
        "pipeline": "text-classification",
        "size": "~300MB",
        "test_text": "Pinche indio de mierda, regrésate a tu pueblo",
    },
    "ar": {
        "name": "aubmindlab/bert-base-arabertv02",
        "local_dir": "ar--arabert-v02",
        "description": "Arabic AraBERT v2 (base model)",
        "pipeline": "text-classification",
        "size": "~500MB",
        "test_text": "مرحبا كيف حالك اليوم؟",
    },
}


# ── Download logic ──────────────────────────────────────────

def download_model(lang: str):
    """Download a single model to models/{local_dir}/"""
    from huggingface_hub import snapshot_download

    info = MODEL_MAP[lang]
    model_name = info["name"]
    local_dir = MODELS_DIR / info["local_dir"]

    print(f"\n{'='*60}")
    print(f"Downloading [{lang}] {info['description']}")
    print(f"  Model:  {model_name}")
    print(f"  Target: {local_dir}")
    print(f"  Size:   {info['size']}")
    print(f"{'='*60}")

    try:
        snapshot_download(
            repo_id=model_name,
            local_dir=str(local_dir),
            local_dir_use_symlinks=False,
            resume_download=True,
            max_workers=4,
        )
        print(f"  ✓ Downloaded to {local_dir}")
        return True
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        return False


def test_model(lang: str):
    """Quick test that a downloaded model works."""
    info = MODEL_MAP[lang]
    local_dir = MODELS_DIR / info["local_dir"]

    if not local_dir.exists() or not list(local_dir.glob("*")):
        print(f"  ✗ Model not downloaded yet")
        return False

    try:
        from transformers import pipeline, AutoTokenizer, AutoModelForCausalLM

        if info["pipeline"] == "text-classification":
            pipe = pipeline("text-classification", model=str(local_dir))
            result = pipe(info["test_text"][:512])
            print(f"  Test: '{info['test_text'][:50]}...' -> {result}")

        elif info["pipeline"] == "text-generation":
            tokenizer = AutoTokenizer.from_pretrained(str(local_dir))
            model = AutoModelForCausalLM.from_pretrained(str(local_dir))
            if tokenizer.pad_token is None:
                tokenizer.pad_token = tokenizer.eos_token
            # This is a base instruction model, so we prompt it
            prompt = f"Does the following text contain hate speech? Answer yes or no.\nText: {info['test_text']}\nAnswer:"
            inputs = tokenizer(prompt, return_tensors="pt")
            outputs = model.generate(**inputs, max_new_tokens=10, temperature=0.1)
            response = tokenizer.decode(outputs[0], skip_special_tokens=True)
            print(f"  Test prompt: {prompt[:80]}...")
            print(f"  Response: {response}")

        return True
    except Exception as e:
        print(f"  ✗ Test failed: {e}")
        return False


# ── Status check ────────────────────────────────────────────

def check_models():
    """Show download status for all models."""
    print(f"{'Language':<6} {'Status':<10} {'Path'}")
    print("-" * 60)
    for lang, info in MODEL_MAP.items():
        local_dir = MODELS_DIR / info["local_dir"]
        if local_dir.exists() and any(local_dir.glob("*.bin")) or any(local_dir.glob("*.safetensors")):
            size = sum(f.stat().st_size for f in local_dir.rglob("*") if f.is_file())
            print(f"{lang:<6} ✓ {size/1e9:.1f}GB  {local_dir}")
        else:
            print(f"{lang:<6} ✗ not yet   {local_dir}")
    print(f"\nTotal: {sum(1 for lang in MODEL_MAP if (MODELS_DIR / MODEL_MAP[lang]['local_dir']).exists())}/{len(MODEL_MAP)} models downloaded")
    print(f"Directory: {MODELS_DIR}")


def list_models():
    """Print model download commands."""
    print("Available Juror A models:")
    for lang, info in MODEL_MAP.items():
        print(f"\n  [{lang}] {info['description']}")
        print(f"       Model: {info['name']}")
        print(f"       Size:  {info['size']}")
        print(f"       Type:  {info['pipeline']}")
        print(f"       Download: python download_models.py {lang}")


# ── Main ──────────────────────────────────────────────────

if __name__ == "__main__":
    if "--list" in sys.argv:
        list_models()
        sys.exit(0)

    if "--check" in sys.argv:
        check_models()
        sys.exit(0)

    # Determine which languages to download
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    languages = args if args else list(MODEL_MAP.keys())

    print(f"Models will be saved to: {MODELS_DIR.resolve()}")
    print(f"Languages to download: {', '.join(languages)}\n")

    success = 0
    failed = 0

    for lang in languages:
        if lang not in MODEL_MAP:
            print(f"Unknown language: {lang}")
            continue
        if download_model(lang):
            test_model(lang)
            success += 1
        else:
            failed += 1

    print(f"\n{'='*60}")
    print(f"Done: {success} succeeded, {failed} failed")
    print(f"Models stored in: {MODELS_DIR.resolve()}")
    check_models()
