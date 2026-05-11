#!/usr/bin/env python3
"""Crawl all working spiders and run through the full pipeline."""

import sys
import time
from pathlib import Path

sys.path.insert(0, ".")

from config import settings
from crawler.spiders.pantip import PantipSpider
from crawler.spiders.hardwarezone import HardwareZoneSpider
from crawler.spiders.kompasiana import KompasianaSpider
from crawler.spiders.uludagsozluk import UludagSozlukSpider
from crawler.spiders.old_reddit import OldRedditSpider
from crawler.exporter import export_to_parquet
from pipeline.cleaner import clean_post, quality_check
from pipeline.language_detector import annotate_language
from pipeline.dedup import DedupIndex
from pipeline.storage import write_cleaned_posts


def crawl_all(limit: int = 10):
    """Run all working spiders, clean, dedup, export."""
    all_raw = []

    spiders_cfg = [
        ("Pantip (TH)", lambda: PantipSpider(limit=limit)),
        ("HardwareZone (SG)", lambda: HardwareZoneSpider(limit=limit)),
        ("Kompasiana (ID)", lambda: KompasianaSpider(limit=limit)),
        ("UludagSozluk (TR)", lambda: UludagSozlukSpider(limit=limit, entries_per_topic=2)),
        ("Reddit (MX)", lambda: OldRedditSpider(country="MX", limit=limit)),
        ("Reddit (SA)", lambda: OldRedditSpider(country="SA", limit=limit)),
        ("Reddit (BR)", lambda: OldRedditSpider(country="BR", limit=limit)),
        ("Reddit (ZA)", lambda: OldRedditSpider(country="ZA", limit=limit)),
    ]

    # ── Phase 1: Crawl ─────────────────────────────────────
    print("═" * 60)
    print("PHASE 1: CRAWLING")
    print("═" * 60)

    for name, spider_factory in spiders_cfg:
        print(f"\n▸ {name} ...", end=" ", flush=True)
        try:
            spider = spider_factory()
            t0 = time.time()
            posts = list(spider.scrape())
            elapsed = time.time() - t0
            all_raw.extend(posts)
            print(f"{len(posts)} posts ({elapsed:.1f}s)")
            for p in posts[:2]:
                print(f"    - {p.title[:70]}")
            if len(posts) > 2:
                print(f"    - ... +{len(posts)-2} more")
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"FAILED: {type(e).__name__}: {e}")
        finally:
            try:
                spider.close()
            except Exception:
                pass
        time.sleep(2)  # gap between spiders

    print(f"\n{'─'*60}")
    print(f"Total raw posts: {len(all_raw)}")

    if not all_raw:
        print("No posts crawled! Check proxy and .env settings.")
        return

    # ── Phase 2: Export raw ────────────────────────────────
    print(f"\n{'═'*60}")
    print("PHASE 2: EXPORT RAW")
    raw_path = export_to_parquet(all_raw, settings.raw_dir)
    print(f"  → {raw_path} ({raw_path.stat().st_size:,} bytes)")

    # ── Phase 3: Clean + Language Detect ───────────────────
    print(f"\n{'═'*60}")
    print("PHASE 3: CLEANING & LANGUAGE DETECTION")

    cleaned = []
    lang_stats = {}
    for raw in all_raw:
        post = clean_post(raw)
        post = annotate_language(post)
        post.quality_flag = quality_check(post.clean_text, post.language_confidence)
        cleaned.append(post)
        lang_stats[post.language] = lang_stats.get(post.language, 0) + 1

    print(f"  Languages detected: {lang_stats}")
    quality_flags = {}
    for p in cleaned:
        quality_flags[p.quality_flag] = quality_flags.get(p.quality_flag, 0) + 1
    print(f"  Quality: {quality_flags}")

    # ── Phase 4: Dedup ─────────────────────────────────────
    print(f"\n{'═'*60}")
    print("PHASE 4: DEDUPLICATION")
    index = DedupIndex(threshold=0.8)
    kept = index.dedup_posts(cleaned)
    dup_count = len(cleaned) - len(kept)
    print(f"  Input: {len(cleaned)}, Kept: {len(kept)}, Duplicates: {dup_count}")

    # Filter to only good quality
    good = [p for p in kept if p.quality_flag == "ok"]
    low_quality = [p for p in kept if p.quality_flag != "ok"]
    print(f"  Good quality: {len(good)}, Low quality: {len(low_quality)}")

    # ── Phase 5: Export clean ──────────────────────────────
    print(f"\n{'═'*60}")
    print("PHASE 5: EXPORT CLEAN DATA")
    if good:
        clean_path = write_cleaned_posts(good)
        print(f"  → {clean_path} ({clean_path.stat().st_size:,} bytes)")

    # ── Summary ────────────────────────────────────────────
    print(f"\n{'═'*60}")
    print("SUMMARY")
    print(f"  Raw posts crawled: {len(all_raw)}")
    print(f"  After dedup:       {len(kept)}")
    print(f"  High quality:      {len(good)}")
    print(f"  Ready for jury:    {len(good)}")

    # Show sample by country
    print(f"\n  Sample by country:")
    seen_countries = set()
    for p in good:
        if p.country not in seen_countries:
            seen_countries.add(p.country)
            print(f"  [{p.country}/{p.language}] {p.title[:70]}")
            print(f"    {p.clean_text[:120]}...")
            print()

    print(f"\n  Data files:")
    print(f"    Raw:      {raw_path}")
    if good:
        print(f"    Clean:    {clean_path}")
    print(f"\n  Next step: python test_jury.py  (when API keys set)")


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    crawl_all(limit)
