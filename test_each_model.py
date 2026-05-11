#!/usr/bin/env python3
"""单独调用每种 Juror A 模型的原始代码示例。

每个函数展示如何用 transformers 直接加载和调用一个模型，
不经过 classify_direct 封装，便于理解和调试。

用法:
  python test_each_model.py          # 全部测试
  python test_each_model.py en       # 只测英语
  python test_each_model.py th       # 只测泰语
"""

import sys
sys.path.insert(0, ".")

MODELS_DIR = "models"


def test_en():
    """英语 — twitter-roberta-base-offensive | 标签: offensive / non-offensive"""
    from transformers import pipeline

    pipe = pipeline(
        "text-classification",
        model=f"{MODELS_DIR}/en--twitter-roberta-offensive",
        truncation=True,
        max_length=512,
    )

    for text in [
        "You are all stupid idiots, go away!",
        "Have a wonderful day my friend!",
    ]:
        result = pipe(text[:512])
        label = result[0]["label"]
        score = result[0]["score"]
        violation = "offensive" in label.lower() and "non" not in label.lower()
        print(f"[en] violation={violation} label={label} score={score:.4f} — {text[:60]}")


def test_pt():
    """葡萄牙语 — xlm-roberta-base-sentiment | 标签: positive / negative / neutral | 需要 sentencepiece + protobuf"""
    from transformers import pipeline

    pipe = pipeline(
        "text-classification",
        model=f"{MODELS_DIR}/pt--xlm-roberta-sentiment",
        truncation=True,
        max_length=512,
    )

    for text in [
        "Seu macaco nojento, volta pra senzala!",
        "Hoje o dia está lindo, fui à praia.",
    ]:
        result = pipe(text[:512])
        label = result[0]["label"]
        score = result[0]["score"]
        violation = label.lower() == "negative"
        print(f"[pt] violation={violation} label={label} score={score:.4f} — {text[:60]}")


def test_th():
    """泰语 — typhoon2-safety-preview (mDeBERTa-v3) | 标签: LABEL_0(安全) / LABEL_1(有害) | 覆盖21个敏感话题"""
    from transformers import pipeline

    pipe = pipeline(
        "text-classification",
        model=f"{MODELS_DIR}/th--typhoon2-safety",
        truncation=True,
        max_length=512,
    )

    for text in [
        "พวกมึงแม่งโง่ ไปตายซะ",
        "วันนี้อากาศดีมากเลยครับ",
    ]:
        result = pipe(text[:512])
        label = result[0]["label"]
        score = result[0]["score"]
        violation = label == "LABEL_1"
        print(f"[th] violation={violation} label={label} score={score:.4f} — {text[:60]}")


def test_es():
    """西班牙语 — beto-sentiment-analysis (Spanish BERT) | 标签: POS / NEG / NEU"""
    from transformers import pipeline

    pipe = pipeline(
        "text-classification",
        model=f"{MODELS_DIR}/es--beto-sentiment",
        truncation=True,
        max_length=512,
    )

    for text in [
        "Pinche indio de mierda, regrésate a tu pueblo",
        "Hoy hace muy buen día para pasear.",
    ]:
        result = pipe(text[:512])
        label = result[0]["label"]
        score = result[0]["score"]
        violation = label == "NEG"
        print(f"[es] violation={violation} label={label} score={score:.4f} — {text[:60]}")


def test_id():
    """印尼语 — bert-base-indonesian (base model, 未微调) | 标签随机 — 需等 Phase 4 微调"""
    from transformers import pipeline

    pipe = pipeline(
        "text-classification",
        model=f"{MODELS_DIR}/id--bert-base-indonesian",
        truncation=True,
        max_length=512,
    )

    for text in [
        "Dasar bodoh, tidak punya otak!",
        "Hari ini saya masak nasi goreng yang enak.",
    ]:
        result = pipe(text[:512])
        label = result[0]["label"]
        score = result[0]["score"]
        print(f"[id] ⚠ BASE MODEL(随机) label={label} score={score:.4f} — {text[:60]}")


def test_tr():
    """土耳其语 — bert-base-turkish (base model, 未微调) | 标签随机 — 需等 Phase 4 微调"""
    from transformers import pipeline

    pipe = pipeline(
        "text-classification",
        model=f"{MODELS_DIR}/tr--bert-base-turkish",
        truncation=True,
        max_length=512,
    )

    for text in [
        "Seni aptal geri zekalı!",
        "Bugün hava çok güzel.",
    ]:
        result = pipe(text[:512])
        label = result[0]["label"]
        score = result[0]["score"]
        print(f"[tr] ⚠ BASE MODEL(随机) label={label} score={score:.4f} — {text[:60]}")


def test_ar():
    """阿拉伯语 — arabert-v02 (base model, 未微调) | 标签随机 — 需等 Phase 4 微调"""
    from transformers import pipeline

    pipe = pipeline(
        "text-classification",
        model=f"{MODELS_DIR}/ar--arabert-v02",
        truncation=True,
        max_length=512,
    )

    for text in [
        "أنت غبي جدا، لا تفهم شيئا!",
        "مرحبا كيف حالك اليوم؟",
    ]:
        result = pipe(text[:512])
        label = result[0]["label"]
        score = result[0]["score"]
        print(f"[ar] ⚠ BASE MODEL(随机) label={label} score={score:.4f} — {text[:60]}")


# ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    lang = sys.argv[1] if len(sys.argv) > 1 else ""

    tests = {
        "en": test_en,
        "pt": test_pt,
        "th": test_th,
        "es": test_es,
        "id": test_id,
        "tr": test_tr,
        "ar": test_ar,
    }

    if lang and lang in tests:
        tests[lang]()
    else:
        for code, fn in tests.items():
            print(f"\n{'='*60}")
            print(f"  [{code}] {fn.__doc__}")
            print("=" * 60)
            try:
                fn()
            except Exception as e:
                print(f"  ✗ FAILED: {type(e).__name__}: {e}")
