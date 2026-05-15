#!/usr/bin/env python3
"""Flexible country crawl — given subreddits, pages, and sort, produce clean parquet.

Usage:
  python run_country_crawl.py AE 20 15 30000   # UAE, 20 pages, 15 comments, 30K target
  python run_country_crawl.py TH 15 20         # Thailand, 15 pages, 20 comments
"""

import sys
from pathlib import Path

from config import COUNTRY_SUBREDDITS, COUNTRY_NAMES
from crawler.spiders.reddit_split_comments import RedditSplitSpider
from crawler.exporter import export_to_parquet
from pipeline.cleaner import clean_post, quality_check
from pipeline.language_detector import annotate_language
from pipeline.dedup import DedupIndex
from pipeline.storage import write_cleaned_posts
from config import settings


def pipeline(all_raw: list, label: str = "") -> list:
    print(f"\n[clean:{label}] Cleaning {len(all_raw)} texts...")
    cleaned = []
    for raw in all_raw:
        post = clean_post(raw)
        post = annotate_language(post)
        post.quality_flag = quality_check(post.clean_text, post.language_confidence)
        cleaned.append(post)

    print(f"[dedup:{label}] Running MinHash LSH deduplication...")
    index = DedupIndex(threshold=0.8)
    kept = index.dedup_posts(cleaned)
    print(f"  Kept: {len(kept)}, duplicates removed: {len(cleaned) - len(kept)}")

    quality = [p for p in kept if p.quality_flag == "ok"]
    flagged = [p for p in kept if p.quality_flag != "ok"]
    flag_counts = {}
    for p in flagged:
        flag_counts[p.quality_flag] = flag_counts.get(p.quality_flag, 0) + 1
    print(f"[quality:{label}] Good: {len(quality)}, Flagged: {len(flagged)} ({flag_counts})")

    lang_counts = {}
    for p in quality:
        lang_counts[p.language] = lang_counts.get(p.language, 0) + 1
    print(f"[lang:{label}] Top: {sorted(lang_counts.items(), key=lambda x: -x[1])[:8]}")
    return quality


def crawl_country(country: str, target: int, pages: int = 20,
                  max_comments: int = 20, delay: float = 4.0) -> list:
    """Crawl a country's subreddits with deep comments on top sort,
    then bulk hot+new if needed. Returns clean posts."""

    subs = COUNTRY_SUBREDDITS.get(country, [])
    name = COUNTRY_NAMES.get(country, country)
    print(f"\n{'#'*60}")
    print(f"# {name} ({country}) — target: {target:,} | subs: {subs}")
    print(f"{'#'*60}")

    all_raw = []

    # Phase 1: top sort WITH comments (content multiplier)
    spider = RedditSplitSpider(
        subreddits=subs, limit=25, max_comments=max_comments,
        sort="top", pages=pages, top_time="all",
        country=country, delay=delay,
    )
    posts = list(spider.scrape())
    spider.close()
    pc = sum(1 for p in posts if p.metadata.get("type") == "post")
    cc = sum(1 for p in posts if p.metadata.get("type") == "comment")
    print(f"  [top] → {len(posts):,} records ({pc:,} posts + {cc:,} comments)")
    all_raw += posts

    raw_dir = settings.raw_dir / country.lower()
    raw_dir.mkdir(parents=True, exist_ok=True)
    export_to_parquet(posts, raw_dir)

    # Phase 2: hot listing (no comments, fast) if needed
    if len(all_raw) < target * 1.5:
        spider = RedditSplitSpider(
            subreddits=subs, limit=25, max_comments=0,
            sort="hot", pages=pages, country=country, delay=3.0,
        )
        posts = list(spider.scrape())
        spider.close()
        print(f"  [hot] → {len(posts):,} records")
        all_raw += posts
        export_to_parquet(posts, raw_dir)

    print(f"\n  Total raw: {len(all_raw):,}")

    # Run pipeline
    quality = pipeline(all_raw, label=country)

    # Export
    clean_dir = settings.clean_dir / country.lower()
    clean_dir.mkdir(parents=True, exist_ok=True)
    clean_path = write_cleaned_posts(quality, clean_dir / f"cleaned_{country}.parquet")
    print(f"\n  Clean export: {clean_path}")
    print(f"  {len(quality):,} cleaned posts for {name}")

    if len(quality) < target:
        print(f"  ⚠ Short of target by {target - len(quality):,}")
    else:
        print(f"  ✓ Target of {target:,} reached!")

    return quality


def main():
    if len(sys.argv) < 2:
        print("Usage: python run_country_crawl.py <COUNTRY_CODE> [pages] [max_comments] [target]")
        sys.exit(1)

    country = sys.argv[1].upper()
    if country not in COUNTRY_SUBREDDITS:
        print(f"Unknown country: {country}. Known: {list(COUNTRY_SUBREDDITS.keys())}")
        sys.exit(1)

    pages = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    max_comments = int(sys.argv[3]) if len(sys.argv) > 3 else 20
    target = int(sys.argv[4]) if len(sys.argv) > 4 else 30_000

    crawl_country(country, target=target, pages=pages, max_comments=max_comments)


if __name__ == "__main__":
    main()
