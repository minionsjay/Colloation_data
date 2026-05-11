"""Language detection using fasttext-langdetect."""

from pipeline.schema import CleanedPost

# Lazy import — fasttext model is ~130MB, loaded on first use
_detector = None


def _get_detector():
    global _detector
    if _detector is None:
        from fast_langdetect import LangDetectConfig, LangDetector

        config = LangDetectConfig(cache_dir=None)
        # model is auto-downloaded on first use
        _detector = LangDetector(config)
    return _detector


def detect_language(text: str) -> tuple[str, float]:
    """Return (iso_code, confidence) for the given text.

    If text is too short or detection fails, returns ('un', 0.0).
    """
    if len(text.strip()) < 10:
        return ("un", 0.0)
    try:
        detector = _get_detector()
        results = detector.detect(text)
        if results and len(results) > 0:
            top = results[0]
            return (top["lang"], top["score"])
        return ("un", 0.0)
    except Exception:
        return ("un", 0.0)


def annotate_language(post: CleanedPost) -> CleanedPost:
    """Detect language for a CleanedPost and set language fields in-place. Returns the post."""
    lang, conf = detect_language(post.clean_text)
    post.language = lang
    post.language_confidence = conf
    return post
