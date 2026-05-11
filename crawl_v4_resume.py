#!/usr/bin/env python3
"""v4 续跑: 从 Phase 2 继续（Phase 1 Reddit Split hot 已完成 43,057 条）。"""

import time
import random
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import COUNTRY_NAMES

COUNTRY_SUBS = {
    "SG": ["singapore", "SingaporeRaw"],
    "ID": ["indonesia", "indonesian"],
    "TH": ["thailand", "thaithai"],
    "TR": ["turkey", "TurkeyJerky", "KGBTR"],
    "SA": ["saudiarabia", "Arabs", "Yemen", "Palestine"],
    "BR": ["brasil", "Brazil", "futebol", "brasilivre", "riodejaneiro"],
    "MX": ["mexico", "mexicanfood", "mexicocity"],
    "ZA": ["southafrica", "capetown", "johannesburg"],
    "_global": ["worldnews", "news", "politics", "geopolitics", "syriancivilwar"],
}

POSTS_PER_PAGE = 25
COMMENTS_PER_POST = 60
PAGES_PER_SORT = 4
SORTS = ["hot", "top", "controversial"]
TOP_TIMES = ["year"]

FORUM_TOPICS = 30
FORUM_ENTRIES = 25
PANTIP_LIMIT = 30
PANTIP_COMMENTS = 80

out_dir = Path("data/comments_batch")
out_dir.mkdir(parents=True, exist_ok=True)

# 加载已有数据 (找最新的 batch)
import re
existing_files = sorted(out_dir.glob("v4_batch_*.parquet"), key=lambda p: p.stat().st_mtime)
if existing_files:
    latest = existing_files[-1]
    existing_df = pd.read_parquet(latest)
    all_rows = existing_df.to_dict("records")
    # extract batch number from filename
    m = re.search(r'v4_batch_(\d+)', latest.name)
    save_counter = int(m.group(1)) if m else len(existing_files)
    print(f"Loaded {len(all_rows)} existing rows from {latest.name}")
else:
    all_rows = []
    save_counter = 0
    print("No existing data found, starting fresh")


def save():
    global save_counter
    save_counter += 1
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    df = pd.DataFrame(all_rows)
    path = out_dir / f"v4_batch_{save_counter:03d}_{ts}.parquet"
    df.to_parquet(path, index=False)
    csv_path = out_dir / f"v4_batch_{save_counter:03d}_{ts}.csv"
    df.to_csv(csv_path, index=False)
    print(f"\n  SAVED [{save_counter}] {len(df)} rows -> {path.name}", flush=True)
    return df


def crawl_reddit_split(country, sort, top_time=None, pages=PAGES_PER_SORT):
    from crawler.spiders.reddit_split_comments import RedditSplitSpider

    subs = COUNTRY_SUBS.get(country, [])
    kw = {"sort": sort, "limit": POSTS_PER_PAGE,
          "max_comments": COMMENTS_PER_POST, "pages": pages}
    if top_time:
        kw["top_time"] = top_time

    total_posts = 0
    total_comments = 0

    for sub in subs:
        try:
            s = RedditSplitSpider(subreddits=[sub], **kw)
            rows = list(s.scrape())
            s.close()

            n_posts = sum(1 for r in rows if r.metadata.get("type") == "post")
            n_comms = sum(1 for r in rows if r.metadata.get("type") == "comment")

            for r in rows:
                meta = r.metadata
                all_rows.append({
                    "content_id": f"split_{country}_{hash(r.url) & 0x7FFFFFFF:08x}",
                    "source": "reddit_split",
                    "country": country,
                    "url": r.url,
                    "title": r.title,
                    "body": r.body,
                    "comment_count": 1,
                    "parent_id": meta.get("parent_id", ""),
                    "type": meta.get("type", "post"),
                    "subreddit": meta.get("subreddit", sub),
                    "sort": sort,
                    "top_time": top_time or "",
                    "page": meta.get("page", 1),
                    "created_at": str(r.created_at),
                })

            label = f"{sub}/{sort}"
            if top_time:
                label += f"/{top_time}"
            print(f"    {label}: {n_posts}p + {n_comms}c ({len(rows)} rows, {meta.get('page', '?')} pages)", flush=True)
            total_posts += n_posts
            total_comments += n_comms

            time.sleep(random.uniform(4, 7))
        except Exception as e:
            print(f"    {sub}/{sort}: FAILED - {e}", flush=True)

    return total_posts, total_comments


def crawl_reddit_bundle(country, sort, top_time=None, pages=2):
    from crawler.spiders.reddit_with_comments import RedditCommentsSpider

    subs = COUNTRY_SUBS.get(country, [])
    kw = {"sort": sort, "limit": POSTS_PER_PAGE,
          "max_comments": COMMENTS_PER_POST, "pages": pages}
    if top_time:
        kw["top_time"] = top_time

    total_posts = 0
    total_comments = 0

    for sub in subs:
        try:
            s = RedditCommentsSpider(subreddits=[sub], **kw)
            rows = list(s.scrape())
            s.close()

            n_comms = sum(r.metadata.get("comment_count", 0) for r in rows)
            for r in rows:
                all_rows.append({
                    "content_id": f"bundle_{country}_{hash(r.url) & 0x7FFFFFFF:08x}",
                    "source": "reddit_bundle",
                    "country": country,
                    "url": r.url,
                    "title": r.title,
                    "body": r.body,
                    "comment_count": r.metadata.get("comment_count", 0),
                    "subreddit": r.metadata.get("subreddit", sub),
                    "sort": sort,
                    "top_time": top_time or "",
                    "page": r.metadata.get("page", 1),
                    "type": "post_with_comments",
                    "created_at": str(r.created_at),
                })

            print(f"    {sub}/{sort}: {len(rows)} posts, {n_comms} comments", flush=True)
            total_posts += len(rows)
            total_comments += n_comms

            time.sleep(random.uniform(3, 6))
        except Exception as e:
            print(f"    {sub}/{sort}: FAILED - {e}", flush=True)

    return total_posts, total_comments


def crawl_eksi():
    from crawler.spiders.eksisozluk import EksiSozlukSpider
    print(f"  Ekşi: {FORUM_TOPICS} topics x {FORUM_ENTRIES} entries", flush=True)
    s = EksiSozlukSpider(limit=FORUM_TOPICS, entries_per_topic=FORUM_ENTRIES)
    rows = list(s.scrape())
    s.close()
    topics = len(set(r.title for r in rows))
    for r in rows:
        all_rows.append({
            "content_id": f"eksi_{hash(r.url) & 0x7FFFFFFF:08x}",
            "source": "eksisozluk", "country": "TR", "url": r.url,
            "title": r.title, "body": r.body, "comment_count": 1,
            "topic": r.title, "type": "entry", "created_at": str(r.created_at),
        })
    print(f"  => {len(rows)} entries ({topics} topics)", flush=True)
    return len(rows)


def crawl_uludag():
    from crawler.spiders.uludagsozluk import UludagSozlukSpider
    print(f"  Uludağ: {FORUM_TOPICS} topics x {FORUM_ENTRIES} entries", flush=True)
    s = UludagSozlukSpider(limit=FORUM_TOPICS, entries_per_topic=FORUM_ENTRIES)
    rows = list(s.scrape())
    s.close()
    topics = len(set(r.title for r in rows))
    for r in rows:
        all_rows.append({
            "content_id": f"uludag_{hash(r.url) & 0x7FFFFFFF:08x}",
            "source": "uludagsozluk", "country": "TR", "url": r.url,
            "title": r.title, "body": r.body, "comment_count": 1,
            "topic": r.title, "type": "entry", "created_at": str(r.created_at),
        })
    print(f"  => {len(rows)} entries ({topics} topics)", flush=True)
    return len(rows)


def crawl_pantip():
    from crawler.spiders.pantip_comments import PantipCommentSpider
    print(f"  Pantip: {PANTIP_LIMIT} posts x {PANTIP_COMMENTS} comments", flush=True)
    s = PantipCommentSpider(limit=PANTIP_LIMIT, max_comments=PANTIP_COMMENTS)
    rows = s.scrape()
    n_comms = sum(r.metadata.get("comment_count", 0) for r in rows)
    for r in rows:
        all_rows.append({
            "content_id": f"pantip_{hash(r.url) & 0x7FFFFFFF:08x}",
            "source": "pantip", "country": "TH", "url": r.url,
            "title": r.title, "body": r.body,
            "comment_count": r.metadata.get("comment_count", 0),
            "room": r.metadata.get("room", ""),
            "type": "post_with_comments", "created_at": str(r.created_at),
        })
    print(f"  => {len(rows)} posts, {n_comms} comments", flush=True)
    return len(rows)


def print_stats():
    if not all_rows:
        return
    df = pd.DataFrame(all_rows)
    print("\n" + "=" * 70)
    print(f"TOTAL: {len(df)} rows")
    print("=" * 70)
    stats = df.groupby("country").agg(
        rows=("content_id", "count"),
    ).sort_values("rows", ascending=False)
    print(stats.to_string())
    print()


def main():
    start = time.time()
    countries = [c for c in COUNTRY_SUBS.keys() if c != "_global"]

    # Phase 1 & 2 already completed in previous runs - skipping

    # ── Phase 3: Reddit Split，controversial ──
    print(f"\n{'='*70}")
    print("PHASE 3: Reddit Split (controversial)")
    print("=" * 70)
    for country in countries:
        print(f"\n--- {country} ---", flush=True)
        crawl_reddit_split(country, "controversial", pages=5)
        print_stats()
        time.sleep(random.uniform(5, 10))
    save()

    # ── Phase 4: Reddit Bundle，hot + top ──
    for sort in ["hot", "top"]:
        top_time = "year" if sort == "top" else None
        print(f"\n{'='*70}")
        print(f"PHASE 4: Reddit Bundle ({sort}) — 3 pages")
        print("=" * 70)
        for country in countries:
            print(f"\n--- {country} ---", flush=True)
            crawl_reddit_bundle(country, sort, top_time=top_time)
            print_stats()
            time.sleep(random.uniform(5, 10))
        save()

    # ── Phase 5: Global controversial subreddits ──
    print(f"\n{'='*70}")
    print("PHASE 5: Global controversial subreddits")
    print("=" * 70)
    for sub in COUNTRY_SUBS.get("_global", []):
        print(f"\n--- global/{sub} ---", flush=True)
        try:
            from crawler.spiders.reddit_split_comments import RedditSplitSpider
            s = RedditSplitSpider(subreddits=[sub], limit=POSTS_PER_PAGE,
                                  max_comments=COMMENTS_PER_POST, sort="hot", pages=2)
            rows = list(s.scrape())
            s.close()
            n_comms = sum(1 for r in rows if r.metadata.get("type") == "comment")
            for r in rows:
                meta = r.metadata
                all_rows.append({
                    "content_id": f"global_{hash(r.url) & 0x7FFFFFFF:08x}",
                    "source": "reddit_split",
                    "country": "GLOBAL",
                    "url": r.url, "title": r.title, "body": r.body,
                    "comment_count": 1,
                    "parent_id": meta.get("parent_id", ""),
                    "type": meta.get("type", "post"),
                    "subreddit": sub, "sort": "hot",
                    "page": meta.get("page", 1),
                    "created_at": str(r.created_at),
                })
            print(f"  {sub}: {len(rows)} rows, ~{n_comms} comments", flush=True)
            time.sleep(random.uniform(5, 10))
        except Exception as e:
            print(f"  {sub}: FAILED - {e}", flush=True)
    save()

    # ── Phase 6: TR 本地论坛 ──
    print(f"\n{'='*70}")
    print("PHASE 6: TR local forums")
    print("=" * 70)
    crawl_eksi()
    time.sleep(5)
    crawl_uludag()
    save()

    # ── Phase 7: TH Pantip ──
    print(f"\n{'='*70}")
    print("PHASE 7: TH Pantip (Playwright)")
    print("=" * 70)
    try:
        crawl_pantip()
    except Exception as e:
        print(f"  Pantip FAILED: {e}", flush=True)
    save()

    # ── 最终统计 ──
    df = pd.DataFrame(all_rows)
    elapsed = time.time() - start
    print("\n" + "=" * 70)
    print(f"DONE in {elapsed/60:.1f} min — {len(df)} rows total")
    print("=" * 70)
    print("\n按国家:")
    stats = df.groupby("country").agg(
        rows=("content_id", "count"),
        unique_posts=("parent_id", "nunique"),
    ).sort_values("rows", ascending=False)
    print(stats.to_string())
    save()


if __name__ == "__main__":
    main()
