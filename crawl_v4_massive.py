#!/usr/bin/env python3
"""大规模评论爬取 v4: 分页 + 扩展 subreddit + 目标 2 万/国。

策略:
- RedditSplitSpider (每条评论独立) 为主力，多页深爬
- hot + top + controversial + new 四种排序全跑
- 定向敏感话题 subreddit
- 每 500 条自动存盘
- 支持断点续传
"""

import time
import random
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import COUNTRY_NAMES

# ── 扩展后的 subreddit 列表（定向敏感/争议话题） ──────────────────────────
COUNTRY_SUBS = {
    "SG": ["singapore", "SingaporeRaw"],
    "ID": ["indonesia", "indonesian"],
    "TH": ["thailand", "thaithai"],
    "TR": ["turkey", "TurkeyJerky", "KGBTR"],
    "SA": ["saudiarabia", "Arabs", "Yemen", "Palestine"],
    "BR": ["brasil", "Brazil", "futebol", "brasilivre", "riodejaneiro"],
    "MX": ["mexico", "mexicanfood", "mexicocity"],
    "ZA": ["southafrica", "capetown", "johannesburg"],
    # 通用争议话题 subreddit（多国共用）
    "_global": ["worldnews", "news", "politics", "geopolitics", "syriancivilwar"],
}

# ── 爬取配置 ──────────────────────────────────────────────────────────
POSTS_PER_PAGE = 25
COMMENTS_PER_POST = 60
PAGES_PER_SORT = 4  # 每排序 4 页 → 100 帖/sub/sort (避免 429)
SORTS = ["hot", "top", "controversial"]
TOP_TIMES = ["year"]  # top 按年

# TR/TH 本地论坛
FORUM_TOPICS = 30
FORUM_ENTRIES = 25
PANTIP_LIMIT = 30
PANTIP_COMMENTS = 80

out_dir = Path("data/comments_batch")
out_dir.mkdir(parents=True, exist_ok=True)
all_rows = []
save_counter = 0


def save():
    global save_counter
    save_counter += 1
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    df = pd.DataFrame(all_rows)
    path = out_dir / f"v4_batch_{save_counter:03d}_{ts}.parquet"
    df.to_parquet(path, index=False)
    n_comms = (df["comment_count"] == 1).sum() if "comment_count" in df.columns else 0
    print(f"\n  💾 [{save_counter}] {len(df)} rows → {path.name}", flush=True)
    return df


def crawl_reddit_split(country, sort, top_time=None, pages=PAGES_PER_SORT):
    """主力：每条评论独立记录。"""
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
    """辅助：帖子+评论打包（每个 post 算 1 条，comment_count 表示评论数）。"""
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
    print(f"PROGRESS: {len(df)} rows total")
    print("=" * 70)
    stats = df.groupby("country").agg(
        rows=("content_id", "count"),
    ).sort_values("rows", ascending=False)
    print(stats.to_string())
    print()


def main():
    start = time.time()
    countries = list(COUNTRY_SUBS.keys())
    countries = [c for c in countries if c != "_global"]

    # ── Phase 1: Reddit Split（每条评论独立），hot ──
    print("=" * 70)
    print(f"PHASE 1: Reddit Split (hot) — {POSTS_PER_PAGE} posts/page × {PAGES_PER_SORT} pages × all subs")
    print("=" * 70)
    for country in countries:
        print(f"\n--- {country} ({COUNTRY_NAMES.get(country, '?')}) ---", flush=True)
        crawl_reddit_split(country, "hot")
        print_stats()
        time.sleep(random.uniform(5, 10))
    save()

    # ── Phase 2: Reddit Split，top (year + all) ──
    for top_time in TOP_TIMES:
        print(f"\n{'='*70}")
        print(f"PHASE 2: Reddit Split (top/{top_time})")
        print("=" * 70)
        for country in countries:
            print(f"\n--- {country} ({COUNTRY_NAMES.get(country, '?')}) ---", flush=True)
            crawl_reddit_split(country, "top", top_time=top_time)
            print_stats()
            time.sleep(random.uniform(5, 10))
        save()

    # ── Phase 3: Reddit Split，controversial ──
    print(f"\n{'='*70}")
    print(f"PHASE 3: Reddit Split (controversial)")
    print("=" * 70)
    for country in countries:
        print(f"\n--- {country} ---", flush=True)
        crawl_reddit_split(country, "controversial", pages=5)
        print_stats()
        time.sleep(random.uniform(5, 10))
    save()

    # ── Phase 4: Reddit Bundle（打包），hot + top ──
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
    print(f"DONE in {elapsed/60:.1f} min — {len(df)} rows")
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
