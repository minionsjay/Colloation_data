#!/usr/bin/env python3
"""Retry failed crawls + add local forums for extra coverage."""

import time, random, re
from datetime import datetime
from pathlib import Path

import pandas as pd
from config import COUNTRY_NAMES

out_dir = Path("data/comments_batch")
existing = sorted(out_dir.glob("v4_batch_*.parquet"), key=lambda p: p.stat().st_mtime)
if existing:
    df = pd.read_parquet(existing[-1])
    all_rows = df.to_dict("records")
    m = re.search(r'v4_batch_(\d+)', existing[-1].name)
    counter = int(m.group(1)) if m else len(existing)
    print(f"Loaded {len(all_rows)} rows from {existing[-1].name}")
else:
    all_rows = []; counter = 0

def save():
    global counter; counter += 1
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    df = pd.DataFrame(all_rows)
    p = out_dir / f"v4_batch_{counter:03d}_{ts}.parquet"
    df.to_parquet(p, index=False)
    df.to_csv(out_dir / f"v4_batch_{counter:03d}_{ts}.csv", index=False)
    print(f"\n  SAVED [{counter}] {len(df)} rows -> {p.name}", flush=True)

def stats():
    if not all_rows: return
    df = pd.DataFrame(all_rows)
    print(f"\n  TOTAL: {len(df)} rows")

def main():
    pre_count = len(all_rows)
    start = time.time()

    # ── 1. Uludağ Sözlük (TR) ──
    print("=" * 60)
    print("RETRY: Uludağ Sözlük (TR)")
    print("=" * 60)
    try:
        from crawler.spiders.uludagsozluk import UludagSozlukSpider
        s = UludagSozlukSpider(limit=30, entries_per_topic=25)
        rows = list(s.scrape()); s.close()
        for r in rows:
            all_rows.append({
                "content_id": f"uludag_{hash(r.url) & 0x7FFFFFFF:08x}",
                "source": "uludagsozluk", "country": "TR", "url": r.url,
                "title": r.title, "body": r.body, "comment_count": 1,
                "topic": r.title, "type": "entry", "created_at": str(r.created_at),
            })
        print(f"  Uludağ: {len(rows)} entries", flush=True)
        save()
    except Exception as e:
        print(f"  Uludağ FAILED: {e}", flush=True)
    stats()

    # ── 2. Pantip (TH) ──
    print("\n" + "=" * 60)
    print("RETRY: TH Pantip (Playwright, 60s timeout)")
    print("=" * 60)
    try:
        from crawler.spiders.pantip_comments import PantipCommentSpider
        s = PantipCommentSpider(limit=30, max_comments=80)
        rows = s.scrape()
        for r in rows:
            all_rows.append({
                "content_id": f"pantip_{hash(r.url) & 0x7FFFFFFF:08x}",
                "source": "pantip", "country": "TH", "url": r.url,
                "title": r.title, "body": r.body,
                "comment_count": r.metadata.get("comment_count", 0),
                "room": r.metadata.get("room", ""),
                "type": "post_with_comments", "created_at": str(r.created_at),
            })
        print(f"  Pantip: {len(rows)} posts", flush=True)
        save()
    except Exception as e:
        print(f"  Pantip FAILED: {e}", flush=True)
    stats()

    # ── 3. HardwareZone (SG) ──
    print("\n" + "=" * 60)
    print("EXTRA: HardwareZone (SG)")
    print("=" * 60)
    try:
        from crawler.spiders.hardwarezone import HardwareZoneSpider
        s = HardwareZoneSpider(limit=30)
        rows = list(s.scrape()); s.close()
        for r in rows:
            all_rows.append({
                "content_id": f"hwz_{hash(r.url) & 0x7FFFFFFF:08x}",
                "source": "hardwarezone", "country": "SG", "url": r.url,
                "title": r.title, "body": r.body, "comment_count": 1,
                "type": "post", "created_at": str(r.created_at),
            })
        print(f"  HardwareZone: {len(rows)} posts", flush=True)
        save()
    except Exception as e:
        print(f"  HardwareZone FAILED: {e}", flush=True)
    stats()

    # ── 4. Kompasiana (ID) ──
    print("\n" + "=" * 60)
    print("EXTRA: Kompasiana (ID)")
    print("=" * 60)
    try:
        from crawler.spiders.kompasiana import KompasianaSpider
        s = KompasianaSpider(limit=30)
        rows = list(s.scrape()); s.close()
        for r in rows:
            all_rows.append({
                "content_id": f"komp_{hash(r.url) & 0x7FFFFFFF:08x}",
                "source": "kompasiana", "country": "ID", "url": r.url,
                "title": r.title, "body": r.body, "comment_count": 1,
                "type": "post", "created_at": str(r.created_at),
            })
        print(f"  Kompasiana: {len(rows)} posts", flush=True)
        save()
    except Exception as e:
        print(f"  Kompasiana FAILED: {e}", flush=True)
    stats()

    # Done
    elapsed = time.time() - start
    gained = len(all_rows) - pre_count
    print(f"\n{'='*60}")
    print(f"DONE in {elapsed/60:.1f} min — gained {gained} new rows")
    print(f"{'='*60}")
    df = pd.DataFrame(all_rows)
    print(df.groupby("country").agg(rows=("content_id","count")).sort_values("rows",ascending=False).to_string())
    save()

if __name__ == "__main__":
    main()
