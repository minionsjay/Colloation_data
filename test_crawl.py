#!/usr/bin/env python3
"""Smoke test: validates the crawl pipeline without requiring real credentials."""

import sys
from datetime import datetime

# ── 1. Test imports ─────────────────────────────────────────────
print("=" * 50)
print("1. Testing imports...")

from config import settings, COUNTRY_SUBREDDITS, COUNTRY_NAMES
from crawler.base_spider import RawPost
from crawler.exporter import posts_to_dataframe, export_to_parquet
from pipeline.cleaner import clean_post, strip_html, normalize_unicode, quality_check
from pipeline.language_detector import detect_language, annotate_language
from pipeline.dedup import DedupIndex, text_to_minhash
from pipeline.schema import CleanedPost, JurorVerdict, FinalVerdict, ViolationCategory

print("   All imports OK")

# ── 2. Test data model ─────────────────────────────────────────
print("\n2. Testing data model...")

raw = RawPost(
    source="reddit",
    country="ID",
    url="https://reddit.com/r/indonesia/comments/test",
    title="Apa kabar?",
    body="Apa kabar?\n\nHari ini saya pergi ke pasar dan membeli nasi goreng yang sangat enak.",
    author_hash=RawPost.hash_author("testuser"),
    created_at=datetime.utcnow(),
    metadata={"subreddit": "indonesia", "score": 42, "num_comments": 7},
)
print(f"   RawPost: {raw.content_id[:8]}... source={raw.source} country={raw.country}")

# ── 3. Test cleaning ───────────────────────────────────────────
print("\n3. Testing text cleaning...")

html_text = "<div>Halo <b>dunia</b>!</div><script>alert('xss')</script>"
stripped = strip_html(html_text)
print(f"   HTML strip: '{stripped}'")

zw_text = "hel​lo‍"  # zero-width joiner and zwsp
normalized = normalize_unicode(zw_text)
print(f"   Unicode normalize: '{zw_text}' ({len(zw_text)} chars) -> '{normalized}' ({len(normalized)} chars)")

cleaned = clean_post(raw)
print(f"   CleanedPost: clean_text len={len(cleaned.clean_text)}, title='{cleaned.title}'")

# ── 4. Test language detection ─────────────────────────────────
print("\n4. Testing language detection...")

texts = [
    ("English", "This is a test sentence for language detection."),
    ("Indonesian", "Hari ini saya pergi ke pasar membeli nasi goreng."),
    ("Thai", "วันนี้อากาศดีมากเลยครับ"),
    ("Turkish", "Bugün hava çok güzel arkadaşlar."),
    ("Portuguese", "Hoje o dia está muito bonito no Brasil."),
    ("Spanish", "Hoy hace muy buen tiempo en México."),
    ("Arabic", "اليوم الجو جميل جدا في الرياض"),
]

for expected, text in texts:
    lang, conf = detect_language(text)
    status = "✓" if conf > 0.5 else "✗"
    print(f"   {status} Expected={expected:15s} Detected={lang:5s} conf={conf:.4f}")

# Test on our mock post
post_with_lang = annotate_language(cleaned)
print(f"   CleanedPost language: {post_with_lang.language} (conf={post_with_lang.language_confidence:.4f})")
quality = quality_check(post_with_lang.clean_text, post_with_lang.language_confidence)
print(f"   Quality flag: {quality}")

# ── 5. Test dedup ──────────────────────────────────────────────
print("\n5. Testing MinHash dedup...")

index = DedupIndex(threshold=0.8)

dup_posts = [
    CleanedPost(content_id="1", source="reddit", country="ID", url="", title="", body="",
                clean_text="Hari ini saya pergi ke pasar membeli nasi goreng yang enak.",
                language="id", language_confidence=0.99, author_hash="x", created_at=datetime.utcnow()),
    CleanedPost(content_id="2", source="reddit", country="ID", url="", title="", body="",
                clean_text="Hari ini saya pergi ke pasar membeli nasi goreng yang enak.",  # exact dup
                language="id", language_confidence=0.99, author_hash="x", created_at=datetime.utcnow()),
    CleanedPost(content_id="3", source="reddit", country="ID", url="", title="", body="",
                clean_text="Besok saya akan ke pantai dengan keluarga besar saya.",  # different
                language="id", language_confidence=0.99, author_hash="x", created_at=datetime.utcnow()),
]

kept = index.dedup_posts(dup_posts)
print(f"   Input: {len(dup_posts)}, Kept: {len(kept)} (should be 2)")
assert len(kept) == 2, f"Expected 2 kept, got {len(kept)}"
assert dup_posts[1].is_duplicate, "Post 2 should be marked as duplicate"

# Near-duplicate test
near_dup = "Hari ini saya pergi ke pasar membeli nasi goreng yg enak."  # "yang" -> "yg"
is_dup = index.is_duplicate(near_dup)
print(f"   Near-duplicate detected: {is_dup} (should be True)")

# ── 6. Test exporter ───────────────────────────────────────────
print("\n6. Testing Parquet export...")

from config import settings as s
df = posts_to_dataframe([raw])
path = export_to_parquet([raw], s.raw_dir)
print(f"   Raw export: {path} ({path.stat().st_size} bytes)")

# Roundtrip
import pandas as pd
df_read = pd.read_parquet(path)
print(f"   Roundtrip: {len(df_read)} rows, columns={list(df_read.columns)}")

# ── 7. Test country mapping ────────────────────────────────────
print("\n7. Country/subreddit mapping:")
for code in COUNTRY_SUBREDDITS:
    subs = COUNTRY_SUBREDDITS[code]
    print(f"   {code} ({COUNTRY_NAMES[code]:15s}): {', '.join(subs)}")

# ── 8. Test Reddit connection (if credentials set) ─────────────
print("\n8. Reddit API connection...")
if settings.reddit_client_id and settings.reddit_client_id != "your_client_id":
    try:
        from crawler.reddit_spider import RedditSpider
        spider = RedditSpider(country="ID", limit=3, sort="hot")
        posts = list(spider.scrape())
        print(f"   ✓ Connected! Got {len(posts)} posts from r/indonesia")
        for p in posts[:2]:
            print(f"     - {p.title[:80]}...")
            print(f"       lang: {detect_language(p.body)[0]}, body_len: {len(p.body)}")
    except Exception as e:
        print(f"   ✗ Error: {e}")
else:
    print("   ⚠ Reddit credentials not set. Skipping live test.")
    print("   → Get credentials at https://www.reddit.com/prefs/apps")
    print("   → Then edit .env with REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT")

print("\n" + "=" * 50)
print("All non-Reddit tests passed!")
