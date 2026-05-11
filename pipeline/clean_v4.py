"""Clean v4 batch data: HTML strip, Unicode normalize, language detect, quality filter, dedup."""

import argparse
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone

import pandas as pd

# ── text cleaning (same logic as cleaner.py) ──────────────────────────
_HTML_RE = re.compile(r"<[^>]+>")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_MULTI_SPACE_RE = re.compile(r"[ \t]{3,}")
_URL_RE = re.compile(r"https?://\S+")


def strip_html(text: str) -> str:
    return _HTML_RE.sub(" ", text)


def normalize_unicode(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("​", "").replace("‌", "").replace("‍", "")
    text = text.replace("﻿", "")
    text = "".join(ch for ch in text if ch.isprintable() or ch in "\n\t")
    return text


def collapse_whitespace(text: str) -> str:
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)
    text = _MULTI_SPACE_RE.sub(" ", text)
    return text.strip()


# Crawler artifacts that often appear in incomplete post bodies
_CRAWLER_ARTIFACTS = re.compile(r"\n*loading\.\.\.$", re.IGNORECASE)


def clean_text(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = strip_html(text)
    text = normalize_unicode(text)
    text = collapse_whitespace(text)
    text = _CRAWLER_ARTIFACTS.sub("", text).strip()
    return text


# ── quality check ─────────────────────────────────────────────────────
def quality_flag(text: str, lang_conf: float, min_chars: int = 10, max_chars: int = 5000) -> str:
    """Return quality flag. Note: low_conf_lang is NOT treated as discard — it's just a marker."""
    char_count = len(text)
    if char_count < min_chars:
        return "too_short"
    if char_count > max_chars:
        return "too_long"
    # Heuristic: if >50% of text is URLs, mark as low_quality
    url_chars = sum(len(m.group(0)) for m in _URL_RE.finditer(text))
    if url_chars > char_count * 0.5:
        return "mostly_urls"
    if lang_conf < 0.3:
        return "low_conf_lang"
    return "ok"


# ── language detection ─────────────────────────────────────────────────
_detector = None


def _get_detector():
    global _detector
    if _detector is None:
        from fast_langdetect import LangDetectConfig, LangDetector

        _detector = LangDetector(LangDetectConfig(cache_dir=None))
    return _detector


def detect_language(text: str) -> tuple[str, float]:
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


# ── dedup ──────────────────────────────────────────────────────────────
class DedupIndex:
    def __init__(self, threshold: float = 0.8, num_perm: int = 128):
        from datasketch import MinHash, MinHashLSH

        self.threshold = threshold
        self.num_perm = num_perm
        self.lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
        self._count = 0

    def _make_minhash(self, text: str):
        from datasketch import MinHash

        m = MinHash(num_perm=self.num_perm)
        for i in range(len(text) - 2):
            m.update(text[i : i + 3].encode("utf-8"))
        return m

    def is_duplicate(self, text: str, content_id: str) -> bool:
        if len(text) < 20:
            return False
        mh = self._make_minhash(text)
        results = self.lsh.query(mh)
        return len(results) > 0

    def add(self, text: str, key: str):
        if len(text) >= 20:
            mh = self._make_minhash(text)
            try:
                self.lsh.insert(key, mh)
                self._count += 1
            except ValueError:
                pass  # duplicate key, skip

    def __len__(self):
        return self._count


# ── remove prefix markers ──────────────────────────────────────────────
_MARKER_RE = re.compile(r"^\[(?:POST|COMMENT\s*#?\d*)\]\s*", re.IGNORECASE | re.MULTILINE)
_RE_PREFIX_RE = re.compile(r"^RE:\s*", re.IGNORECASE)

def strip_markers(text: str) -> str:
    """Remove [POST], [COMMENT #N] prefixes and RE: prefixes added by the crawler."""
    text = _MARKER_RE.sub("", text)
    text = _RE_PREFIX_RE.sub("", text)
    return text.strip()


# ── main cleaning pipeline ─────────────────────────────────────────────
def clean_batch(df: pd.DataFrame, dedup: DedupIndex | None = None) -> pd.DataFrame:
    rows = []
    skipped = {"too_short": 0, "too_long": 0, "mostly_urls": 0, "low_conf_lang": 0, "duplicate": 0}

    for i, row in df.iterrows():
        # Unique key per row (content_id may repeat for post + its comments)
        dedup_key = f"{row.get('content_id')}_{i}"

        # 1. Strip marker prefixes
        title = strip_markers(str(row.get("title", "") or ""))
        body = strip_markers(str(row.get("body", "") or ""))

        # Use body as the main text. Title is kept as a separate field.
        # Post and comment rows are independent — don't cross-join title from post.
        full_text = body if body else title

        # 2. Text cleaning
        clean = clean_text(full_text)
        clean_title = clean_text(title)

        # 3. Language detection on combined text
        lang, lang_conf = detect_language(clean)

        # 4. Quality check — only hard-drop too_short/too_long/mostly_urls
        qf = quality_flag(clean, lang_conf)

        if qf in ("too_short", "too_long", "mostly_urls"):
            skipped[qf] += 1
            continue

        # 5. Dedup
        if dedup is not None and dedup.is_duplicate(clean, dedup_key):
            skipped["duplicate"] += 1
            continue

        if dedup is not None:
            dedup.add(clean, dedup_key)

        # Build cleaned row
        rows.append({
            "content_id": row.get("content_id"),
            "source": row.get("source"),
            "country": row.get("country"),
            "url": row.get("url"),
            "title": clean_title,
            "body": row.get("body"),  # keep original
            "clean_text": clean,
            "language": lang,
            "language_confidence": round(lang_conf, 4),
            "quality_flag": "ok",
            "type": row.get("type"),
            "subreddit": row.get("subreddit"),
            "forum": row.get("forum") if "forum" in row else None,
            "sort": row.get("sort"),
            "created_at": row.get("created_at"),
            "cleaned_at": datetime.now(timezone.utc).isoformat(),
        })

    result = pd.DataFrame(rows)
    return result, skipped


# ── CLI ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean v4 batch data")
    parser.add_argument("--input", required=True, help="Path to input parquet file")
    parser.add_argument("--output", required=True, help="Path to output parquet file")
    parser.add_argument("--sample", type=int, default=0, help="Only process first N rows (for preview)")
    parser.add_argument("--no-dedup", action="store_true", help="Skip dedup (faster for testing)")
    args = parser.parse_args()

    df = pd.read_parquet(args.input)
    if args.sample > 0:
        df = df.head(args.sample)

    print(f"Processing {len(df)} rows from {os.path.basename(args.input)}...")

    dedup = None if args.no_dedup else DedupIndex()
    result, skipped = clean_batch(df, dedup=dedup)

    result.to_parquet(args.output, index=False)

    print(f"Kept:    {len(result):>8}")
    print(f"Skipped:")
    for reason, count in skipped.items():
        print(f"  {reason}: {count:>8}")
    if dedup:
        print(f"  (dedup index size: {len(dedup)})")
    print(f"Output:  {args.output}")
