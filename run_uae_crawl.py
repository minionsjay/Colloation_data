#!/usr/bin/env python3
"""Dedicated UAE crawl → 30K+ cleaned posts.

Strategy (resume-friendly):
  - Phase 1: deep top posts WITH comments (content multiplier)
  - Phase 2: if still short, add hot listing pages without comments
"""

import sys

from config import COUNTRY_SUBREDDITS
from crawler.spiders.reddit_split_comments import RedditSplitSpider
from crawler.exporter import export_to_parquet
from pipeline.cleaner import clean_post, quality_check
from pipeline.language_detector import annotate_language
from pipeline.dedup import DedupIndex
from pipeline.storage import write_cleaned_posts
from config import settings

COUNTRY = "AE"
SUBREDDITS = COUNTRY_SUBREDDITS[COUNTRY]


def pipeline(all_raw: list, label: str = "") -> list:
    """Clean → lang detect → dedup → quality filter."""
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


def crawl_batch(label: str, sort: str, pages: int, max_comments: int, delay: float) -> list:
    """Run one crawl batch and return raw posts."""
    print(f"\n{'='*60}")
    print(f"[{label}] sort={sort}, pages={pages}, comments≤{max_comments}, delay={delay}s")
    print(f"{'='*60}")

    spider = RedditSplitSpider(
        subreddits=SUBREDDITS,
        limit=25,
        max_comments=max_comments,
        sort=sort,
        pages=pages,
        top_time="all",
        country=COUNTRY,
        delay=delay,
    )
    posts = list(spider.scrape())
    spider.close()

    post_count = sum(1 for p in posts if p.metadata.get("type") == "post")
    comment_count = sum(1 for p in posts if p.metadata.get("type") == "comment")
    print(f"  → {len(posts)} records ({post_count} posts + {comment_count} comments)")

    # Save intermediate raw
    raw_dir = settings.raw_dir / "uae"
    raw_dir.mkdir(parents=True, exist_ok=True)
    export_to_parquet(posts, raw_dir)

    return posts


def main():
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 30_000

    all_raw = []

    # Phase 1 — Deep comments on top (content multiplier, high delay to avoid 429)
    all_raw += crawl_batch("deep-top", "top", pages=20, max_comments=25, delay=4.0)

    # Phase 2 — Bulk hot listing (no comments, fast, only if needed)
    if len(all_raw) < target * 2:  # rough estimate before dedup/quality
        all_raw += crawl_batch("bulk-hot", "hot", pages=50, max_comments=0, delay=3.0)

    # Phase 3 — Bulk new listing (higher delay to avoid 429)
    if len(all_raw) < target * 2:
        all_raw += crawl_batch("bulk-new", "new", pages=40, max_comments=0, delay=4.0)

    print(f"\n{'='*60}")
    print(f"Total raw records: {len(all_raw)}")
    print(f"{'='*60}")

    if not all_raw:
        print("No posts crawled.")
        return

    # Pipeline
    quality = pipeline(all_raw, label="full")

    # Export
    clean_dir = settings.clean_dir / "uae"
    clean_dir.mkdir(parents=True, exist_ok=True)
    clean_path = write_cleaned_posts(quality, clean_dir / "cleaned_uae.parquet")
    print(f"\nClean export: {clean_path}")
    print(f"Done. {len(quality)} cleaned UAE posts ready for jury judgment.")

    if len(quality) < target:
        print(f"\n⚠ Only {len(quality)} posts (target: {target}). "
              f"Run again with more pages or subreddits.")
    else:
        print(f"✓ Target of {target} reached with {len(quality)} clean posts.")


if __name__ == "__main__":
    main()
