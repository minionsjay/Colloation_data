#!/usr/bin/env python3
"""大规模评论爬取 v2：每国 100+ 条带评论数据，输出 Parquet + CSV。"""

import sys
import time
import random
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from config import COUNTRY_SUBREDDITS, COUNTRY_NAMES


# ── 配置 ──────────────────────────────────────────────────────────────
REDDIT_LIMIT = 15          # 每个 subreddit 的帖子数
REDDIT_COMMENTS = 50       # 每帖最多评论数
REDDIT_SORTS = ["hot", "top"]  # hot 和 top 评论更多
FORUM_TOPICS = 20          # Ekşi/Uludağ 话题数
FORUM_ENTRIES = 15         # 每个话题的 entry 数
PANTIP_LIMIT = 20          # Pantip 帖子数
PANTIP_COMMENTS = 50       # 每帖评论数

out_dir = Path("data/comments_batch")
out_dir.mkdir(parents=True, exist_ok=True)
all_rows = []


def save_intermediate(df, label=""):
    """保存中间结果，防止丢失。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"comments_{label}_{ts}.parquet"
    df.to_parquet(path, index=False)
    path2 = out_dir / f"comments_{label}_{ts}.csv"
    df.to_csv(path2, index=False, encoding="utf-8-sig")
    print(f"  Saved {len(df)} rows to {path}")
    return path


def crawl_reddit_comments(country: str, sort: str):
    """抓取 Reddit 评论（post + comments 合并模式）。"""
    from crawler.spiders.reddit_with_comments import RedditCommentsSpider

    subs = COUNTRY_SUBREDDITS.get(country, [])
    posts_out = []
    for sub in subs:
        try:
            s = RedditCommentsSpider(
                subreddits=[sub], limit=REDDIT_LIMIT,
                max_comments=REDDIT_COMMENTS, sort=sort,
            )
            posts = list(s.scrape())
            s.close()
            n_comms = sum(p.metadata.get("comment_count", 0) for p in posts)
            posts_out.extend(posts)
            print(f"    {sub}: {len(posts)} posts, {n_comms} comments")
            if len(posts_out) >= REDDIT_LIMIT:
                break
            time.sleep(random.uniform(3, 6))
        except Exception as e:
            print(f"    {sub}: FAILED - {e}")

    for p in posts_out:
        all_rows.append({
            "content_id": f"reddit_{country}_{hash(p.url) & 0x7FFFFFFF:08x}",
            "source": "reddit",
            "country": country,
            "url": p.url,
            "title": p.title,
            "body": p.body,
            "comment_count": p.metadata.get("comment_count", 0),
            "subreddit": p.metadata.get("subreddit", ""),
            "sort": sort,
            "type": "post_with_comments",
            "created_at": str(p.created_at),
        })

    n_comms = sum(p.metadata.get("comment_count", 0) for p in posts_out)
    print(f"  {country} {sort}: {len(posts_out)} total posts, {n_comms} total comments")


def crawl_eksi_sozluk():
    """Ekşi Sözlük: 每个 entry 相当于一条评论。"""
    from crawler.spiders.eksisozluk import EksiSozlukSpider

    print(f"\n  Ekşi Sözlük: {FORUM_TOPICS} topics, {FORUM_ENTRIES} entries/topic")
    s = EksiSozlukSpider(limit=FORUM_TOPICS, entries_per_topic=FORUM_ENTRIES)
    posts = list(s.scrape())
    s.close()

    topics = len(set(p.title for p in posts))
    print(f"  {len(posts)} entries from {topics} topics")
    for p in posts:
        all_rows.append({
            "content_id": f"eksi_{hash(p.url) & 0x7FFFFFFF:08x}",
            "source": "eksisozluk",
            "country": "TR",
            "url": p.url,
            "title": p.title,
            "body": p.body,
            "comment_count": 1,
            "topic": p.title,
            "type": "entry",
            "created_at": str(p.created_at),
        })


def crawl_uludag_sozluk():
    """Uludağ Sözlük: 每个 entry 相当于一条评论。"""
    from crawler.spiders.uludagsozluk import UludagSozlukSpider

    print(f"\n  Uludağ Sözlük: {FORUM_TOPICS} topics, {FORUM_ENTRIES} entries/topic")
    s = UludagSozlukSpider(limit=FORUM_TOPICS, entries_per_topic=FORUM_ENTRIES)
    posts = list(s.scrape())
    s.close()

    topics = len(set(p.title for p in posts))
    print(f"  {len(posts)} entries from {topics} topics")
    for p in posts:
        all_rows.append({
            "content_id": f"uludag_{hash(p.url) & 0x7FFFFFFF:08x}",
            "source": "uludagsozluk",
            "country": "TR",
            "url": p.url,
            "title": p.title,
            "body": p.body,
            "comment_count": 1,
            "topic": p.title,
            "type": "entry",
            "created_at": str(p.created_at),
        })


def crawl_pantip():
    """Pantip + 评论 via Playwright。"""
    from crawler.spiders.pantip_comments import PantipCommentSpider

    print(f"\n  Pantip: {PANTIP_LIMIT} posts, {PANTIP_COMMENTS} comments/post")
    s = PantipCommentSpider(limit=PANTIP_LIMIT, max_comments=PANTIP_COMMENTS)
    posts = s.scrape()

    n_comms = sum(p.metadata.get("comment_count", 0) for p in posts)
    print(f"  {len(posts)} posts, {n_comms} comments")
    for p in posts:
        all_rows.append({
            "content_id": f"pantip_{hash(p.url) & 0x7FFFFFFF:08x}",
            "source": "pantip",
            "country": "TH",
            "url": p.url,
            "title": p.title,
            "body": p.body,
            "comment_count": p.metadata.get("comment_count", 0),
            "room": p.metadata.get("room", ""),
            "type": "post_with_comments",
            "created_at": str(p.created_at),
        })


def main():
    start_time = time.time()

    # ── Phase 1: Reddit hot (8 国) ──
    print("=" * 60)
    print(f"PHASE 1: Reddit hot — {REDDIT_LIMIT} posts/国, {REDDIT_COMMENTS} comments/post")
    print("=" * 60)
    for country in COUNTRY_SUBREDDITS:
        print(f"\n  --- {country} ({COUNTRY_NAMES.get(country, country)}) ---", flush=True)
        crawl_reddit_comments(country, "hot")
        time.sleep(random.uniform(4, 7))  # 国间延迟

    # 中间保存
    save_intermediate(pd.DataFrame(all_rows), "phase1_hot")

    # ── Phase 2: Reddit top (8 国) ──
    print()
    print("=" * 60)
    print(f"PHASE 2: Reddit top — {REDDIT_LIMIT} posts/国, {REDDIT_COMMENTS} comments/post")
    print("=" * 60)
    for country in COUNTRY_SUBREDDITS:
        print(f"\n  --- {country} ({COUNTRY_NAMES.get(country, country)}) ---", flush=True)
        crawl_reddit_comments(country, "top")
        time.sleep(random.uniform(4, 7))

    save_intermediate(pd.DataFrame(all_rows), "phase2_top")

    # ── Phase 3: TR 本地论坛 ──
    print()
    print("=" * 60)
    print("PHASE 3: TR 本地论坛 (Ekşi + Uludağ)")
    print("=" * 60)
    crawl_eksi_sozluk()
    time.sleep(5)
    crawl_uludag_sozluk()

    save_intermediate(pd.DataFrame(all_rows), "phase3_tr")

    # ── Phase 4: TH 本地论坛 ──
    print()
    print("=" * 60)
    print("PHASE 4: TH Pantip (Playwright)")
    print("=" * 60)
    try:
        crawl_pantip()
    except Exception as e:
        print(f"  Pantip FAILED: {e}")

    # ── 最终导出 ──
    df = pd.DataFrame(all_rows)
    save_intermediate(df, "final")

    elapsed = time.time() - start_time
    print()
    print("=" * 60)
    print(f"FINISHED in {elapsed/60:.1f} min")
    print(f"Total: {len(df)} rows, {df['comment_count'].sum()} comments")
    print()
    print("=== 按国家统计 ===")
    stats = df.groupby("country").agg(
        rows=("content_id", "count"),
        comments=("comment_count", "sum"),
    )
    print(stats.to_string())
    print()
    print("=== 按来源统计 ===")
    stats2 = df.groupby(["country", "source"]).agg(
        rows=("content_id", "count"),
        comments=("comment_count", "sum"),
    )
    print(stats2.to_string())


if __name__ == "__main__":
    main()
