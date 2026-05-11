#!/usr/bin/env python3
"""Main entry point: crawl Reddit for all 8 countries, clean, dedup, export."""

import sys
from pathlib import Path

from config import settings, COUNTRY_SUBREDDITS, COUNTRY_NAMES
from crawler.reddit_spider import RedditSpider
from crawler.exporter import export_to_parquet
from pipeline.cleaner import clean_post, quality_check
from pipeline.language_detector import annotate_language
from pipeline.dedup import DedupIndex
from pipeline.storage import write_cleaned_posts


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 50

    # ── 1. Crawl ────────────────────────────────────────────────
    all_raw = []
    for code in COUNTRY_SUBREDDITS:
        name = COUNTRY_NAMES.get(code, code)
        print(f"[crawl] {name} ({code})")
        spider = RedditSpider(country=code, limit=limit, sort="hot")
        posts = list(spider.scrape())
        print(f"  -> {len(posts)} posts")
        all_raw.extend(posts)

    if not all_raw:
        print("No posts crawled. Check your Reddit API credentials in .env")
        return

    print(f"\nTotal raw posts: {len(all_raw)}")

    # ── 2. Export raw ──────────────────────────────────────────
    raw_path = export_to_parquet(all_raw, settings.raw_dir)
    print(f"Raw export: {raw_path}")

    # ── 3. Clean ───────────────────────────────────────────────
    print("\n[clean] Cleaning text...")
    cleaned = []
    for raw in all_raw:
        post = clean_post(raw)
        post = annotate_language(post)
        post.quality_flag = quality_check(post.clean_text, post.language_confidence)
        cleaned.append(post)

    # ── 4. Dedup ───────────────────────────────────────────────
    print("[dedup] Running MinHash LSH deduplication...")
    index = DedupIndex(threshold=0.8)
    kept = index.dedup_posts(cleaned)
    duped = len(cleaned) - len(kept)
    print(f"  Kept: {len(kept)}, duplicates removed: {duped}")

    # ── 5. Filter low quality ──────────────────────────────────
    quality = [p for p in kept if p.quality_flag == "ok"]
    flagged = [p for p in kept if p.quality_flag != "ok"]
    print(
        f"[quality] Good: {len(quality)}, Flagged: {len(flagged)} "
        f"({', '.join(f'{p.quality_flag}={sum(1 for x in flagged if x.quality_flag == p.quality_flag)}' for p in flagged[:1]) or 'none'})"
    )

    # ── 6. Export clean ────────────────────────────────────────
    clean_path = write_cleaned_posts(quality)
    print(f"\nClean export: {clean_path}")
    print("Done. Data ready for jury judgment.")


if __name__ == "__main__":
    main()
