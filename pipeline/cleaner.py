"""Text cleaning: strip HTML, normalize Unicode, filter low-quality content."""

import re
import unicodedata

from pipeline.schema import CleanedPost
from crawler.base_spider import RawPost


# Common HTML tag pattern (conservative — avoids stripping non-HTML angle brackets)
_HTML_RE = re.compile(r"<[^>]+>")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_MULTI_SPACE_RE = re.compile(r"[ \t]{3,}")


def strip_html(text: str) -> str:
    """Remove HTML tags from text."""
    return _HTML_RE.sub(" ", text)


def normalize_unicode(text: str) -> str:
    """NFC normalize, strip zero-width characters and control chars except newlines."""
    text = unicodedata.normalize("NFC", text)
    # Remove zero-width joiners, zero-width non-joiners, zero-width space
    text = text.replace("​", "").replace("‌", "").replace("‍", "")
    text = text.replace("﻿", "")  # BOM
    # Keep newlines, tabs; strip other control chars
    text = "".join(ch for ch in text if ch.isprintable() or ch in "\n\t")
    return text


def collapse_whitespace(text: str) -> str:
    """Normalize whitespace without merging all lines."""
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)
    text = _MULTI_SPACE_RE.sub(" ", text)
    return text.strip()


def quality_check(text: str, lang_confidence: float, min_chars: int = 5, min_lang_conf: float = 0.5) -> str:
    """Return quality flag for a cleaned text.

    Thresholds are intentionally low — we prefer false positives (letting
    borderline content through) over false negatives (missing violations).
    """
    char_count = len(text)
    if char_count < min_chars:
        return "too_short"
    if char_count > 5000:
        return "too_long"
    if lang_confidence < min_lang_conf:
        return "low_conf_lang"
    return "ok"


def clean_post(raw: RawPost) -> CleanedPost:
    """Full cleaning pipeline for a single RawPost.

    Language detection is done separately (language_detector module)
    and stitched in by the caller. This function handles text cleaning only.
    """
    raw_text = raw.body
    text = strip_html(raw_text)
    text = normalize_unicode(text)
    text = collapse_whitespace(text)

    return CleanedPost(
        content_id=raw.content_id,
        source=raw.source,
        country=raw.country,
        url=raw.url,
        title=raw.title,
        body=raw.body,
        clean_text=text,
        language="",  # filled by language_detector
        language_confidence=0.0,
        author_hash=raw.author_hash,
        created_at=raw.created_at,
    )
