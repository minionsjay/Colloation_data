#!/usr/bin/env python3
"""大规模评论爬取 v3: 修复 data-permalink bug，加大爬取量，覆盖所有评论来源。"""

import time, random
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import COUNTRY_SUBREDDITS, COUNTRY_NAMES

# ── 配置 ──────────────────────────────────────────────────────────────
REDDIT_LIMIT = 20
REDDIT_COMMENTS = 60
REDDIT_SORTS = ["hot", "top"]
FORUM_TOPICS = 25
FORUM_ENTRIES = 20
PANTIP_LIMIT = 25
PANTIP_COMMENTS = 60
COMMENT_SORTS_EXTRA = True  # SG 额外抓 controversial

out_dir = Path("data/comments_batch")
out_dir.mkdir(parents=True, exist_ok=True)
all_rows = []


def save(label=""):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    df = pd.DataFrame(all_rows)
    df.to_parquet(out_dir / f"comments_{label}_{ts}.parquet", index=False)
    df.to_csv(out_dir / f"comments_{label}_{ts}.csv", index=False, encoding="utf-8-sig")
    print(f"  [saved {len(df)} rows]", flush=True)
    return df


def crawl_reddit(country, sort):
    """Reddit 评论 (post + comments 合并模式)."""
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
            print(f"    {sub}/{sort}: {len(posts)} posts, {n_comms} comments", flush=True)
            time.sleep(random.uniform(3, 6))
        except Exception as e:
            print(f"    {sub}/{sort}: FAILED - {e}", flush=True)

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

    return len(posts_out), sum(p.metadata.get("comment_count", 0) for p in posts_out)


def crawl_split_reddit(country, sort):
    """Reddit 评论 (每条评论独立记录)."""
    from crawler.spiders.reddit_split_comments import RedditSplitSpider

    subs = COUNTRY_SUBREDDITS.get(country, [])
    posts_out = []
    for sub in subs:
        try:
            s = RedditSplitSpider(
                subreddits=[sub], limit=10, max_comments=60, sort=sort,
            )
            posts = list(s.scrape())
            s.close()
            posts_out.extend(posts)
            n_posts = sum(1 for p in posts if p.metadata.get("type") == "post")
            n_comms = sum(1 for p in posts if p.metadata.get("type") == "comment")
            print(f"    {sub}/{sort} split: {n_posts} posts + {n_comms} comments", flush=True)
            time.sleep(random.uniform(3, 6))
        except Exception as e:
            print(f"    {sub}/{sort} split: FAILED - {e}", flush=True)

    for p in posts_out:
        all_rows.append({
            "content_id": f"split_{country}_{hash(p.url) & 0x7FFFFFFF:08x}",
            "source": "reddit_split",
            "country": country,
            "url": p.url,
            "title": p.title,
            "body": p.body,
            "comment_count": 1,
            "parent_id": p.metadata.get("parent_id", ""),
            "type": p.metadata.get("type", "post"),
            "subreddit": p.metadata.get("subreddit", ""),
            "sort": sort,
            "created_at": str(p.created_at),
        })

    return len(posts_out), sum(1 for p in posts_out if p.metadata.get("type") == "comment")


def crawl_eksi():
    from crawler.spiders.eksisozluk import EksiSozlukSpider
    print(f"  Ekşi Sözlük: {FORUM_TOPICS} topics x {FORUM_ENTRIES} entries", flush=True)
    s = EksiSozlukSpider(limit=FORUM_TOPICS, entries_per_topic=FORUM_ENTRIES)
    posts = list(s.scrape())
    s.close()
    topics = len(set(p.title for p in posts))
    print(f"  {len(posts)} entries from {topics} topics", flush=True)
    for p in posts:
        all_rows.append({
            "content_id": f"eksi_{hash(p.url) & 0x7FFFFFFF:08x}",
            "source": "eksisozluk", "country": "TR", "url": p.url,
            "title": p.title, "body": p.body, "comment_count": 1,
            "topic": p.title, "type": "entry", "created_at": str(p.created_at),
        })
    return len(posts)


def crawl_uludag():
    from crawler.spiders.uludagsozluk import UludagSozlukSpider
    print(f"  Uludağ Sözlük: {FORUM_TOPICS} topics x {FORUM_ENTRIES} entries", flush=True)
    s = UludagSozlukSpider(limit=FORUM_TOPICS, entries_per_topic=FORUM_ENTRIES)
    posts = list(s.scrape())
    s.close()
    topics = len(set(p.title for p in posts))
    print(f"  {len(posts)} entries from {topics} topics", flush=True)
    for p in posts:
        all_rows.append({
            "content_id": f"uludag_{hash(p.url) & 0x7FFFFFFF:08x}",
            "source": "uludagsozluk", "country": "TR", "url": p.url,
            "title": p.title, "body": p.body, "comment_count": 1,
            "topic": p.title, "type": "entry", "created_at": str(p.created_at),
        })
    return len(posts)


def crawl_pantip():
    from crawler.spiders.pantip_comments import PantipCommentSpider
    print(f"  Pantip: {PANTIP_LIMIT} posts x {PANTIP_COMMENTS} comments", flush=True)
    s = PantipCommentSpider(limit=PANTIP_LIMIT, max_comments=PANTIP_COMMENTS)
    posts = s.scrape()
    n_comms = sum(p.metadata.get("comment_count", 0) for p in posts)
    print(f"  {len(posts)} posts, {n_comms} comments", flush=True)
    for p in posts:
        all_rows.append({
            "content_id": f"pantip_{hash(p.url) & 0x7FFFFFFF:08x}",
            "source": "pantip", "country": "TH", "url": p.url,
            "title": p.title, "body": p.body,
            "comment_count": p.metadata.get("comment_count", 0),
            "room": p.metadata.get("room", ""),
            "type": "post_with_comments", "created_at": str(p.created_at),
        })
    return len(posts), n_comms


def main():
    start = time.time()

    # ── Phase 1: Reddit (评论合并模式) 8 国 x hot+top ──
    for sort in REDDIT_SORTS:
        print(f"\n{'='*60}")
        print(f"PHASE: Reddit comments ({sort}) — {REDDIT_LIMIT} posts/国", flush=True)
        print(f"{'='*60}")
        for country in COUNTRY_SUBREDDITS:
            print(f"  {country} ({COUNTRY_NAMES.get(country, '?')}):", flush=True)
            n_posts, n_comms = crawl_reddit(country, sort)
            print(f"  => {n_posts} posts, {n_comms} comments", flush=True)
            time.sleep(random.uniform(5, 8))
        save(f"phase_reddit_{sort}")

    # ── Phase 2: Reddit Split (每条评论独立) 8 国 x hot ──
    print(f"\n{'='*60}")
    print("PHASE: Reddit split comments (hot) — 10 posts/国", flush=True)
    print(f"{'='*60}")
    for country in COUNTRY_SUBREDDITS:
        print(f"  {country} ({COUNTRY_NAMES.get(country, '?')}):", flush=True)
        n_total, n_comms = crawl_split_reddit(country, "hot")
        print(f"  => {n_total} total rows, {n_comms} comments", flush=True)
        time.sleep(random.uniform(5, 8))
    save("phase_reddit_split")

    # ── Phase 3: TR 本地论坛 ──
    print(f"\n{'='*60}")
    print("PHASE: TR 论坛", flush=True)
    print(f"{'='*60}")
    n_eksi = crawl_eksi()
    time.sleep(5)
    n_uludag = crawl_uludag()
    print(f"  TR forums total: {n_eksi + n_uludag} entries", flush=True)
    save("phase_tr_forums")

    # ── Phase 4: TH Pantip ──
    print(f"\n{'='*60}")
    print("PHASE: TH Pantip (Playwright)", flush=True)
    print(f"{'='*60}")
    try:
        n_posts, n_comms = crawl_pantip()
        print(f"  Pantip: {n_posts} posts, {n_comms} comments", flush=True)
    except Exception as e:
        print(f"  Pantip FAILED: {e}", flush=True)
    save("phase_pantip")

    # ── 最终统计 ──
    df = pd.DataFrame(all_rows)
    save("final")

    elapsed = time.time() - start
    print(f"\n{'='*60}")
    print(f"DONE in {elapsed/60:.1f} min — {len(df)} rows, {df['comment_count'].sum()} comments", flush=True)
    print(f"{'='*60}")
    print("\n按国家:", flush=True)
    print(df.groupby("country").agg(rows=("content_id", "count"), comments=("comment_count", "sum")).to_string(), flush=True)
    print("\n按来源 x 排序:", flush=True)
    stats = df.groupby(["country", "source", df.get("sort", "N/A")]).agg(
        rows=("content_id", "count"), comments=("comment_count", "sum")
    )
    print(stats.to_string(), flush=True)


if __name__ == "__main__":
    main()
