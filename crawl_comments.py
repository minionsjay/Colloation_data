#!/usr/bin/env python3
"""批量爬取评论数据：Reddit + 本地论坛，输出到 data/comments_batch/"""

import time
from pathlib import Path

import pandas as pd

from config import COUNTRY_SUBREDDITS, COUNTRY_NAMES


def main():
    out_dir = Path("data/comments_batch")
    out_dir.mkdir(parents=True, exist_ok=True)
    all_rows = []

    # ── 1. RedditCommentsSpider (8 国, sort=hot) ──
    print("=" * 60)
    print("1. RedditCommentsSpider: 8 国, sort=hot, 5 posts/国, 20 comments/post")
    print("=" * 60)
    from crawler.spiders.reddit_with_comments import RedditCommentsSpider

    for country in ["SG", "ID", "TH", "TR", "SA", "BR", "MX", "ZA"]:
        subs = COUNTRY_SUBREDDITS.get(country, [])
        try:
            s = RedditCommentsSpider(subreddits=subs, limit=5, max_comments=20, sort="hot")
            posts = list(s.scrape())
            s.close()

            n_comments = sum(p.metadata.get("comment_count", 0) for p in posts)
            print(f"  {country} ({', '.join(subs[:2])}): {len(posts)} posts, {n_comments} comments")

            for p in posts:
                all_rows.append({
                    "content_id": f"reddit_{country}_{hash(p.url) & 0x7FFFFFFF:08x}",
                    "source": "reddit_comments",
                    "country": country,
                    "url": p.url,
                    "title": p.title,
                    "body": p.body,
                    "comment_count": p.metadata.get("comment_count", 0),
                    "subreddit": p.metadata.get("subreddit", ""),
                    "sort": "hot",
                    "type": "post_with_comments",
                    "created_at": str(p.created_at),
                })
        except Exception as e:
            print(f"  {country}: FAILED - {e}")

    # ── 2. RedditCommentsSpider (8 国, sort=controversial) ──
    print()
    print("=" * 60)
    print("2. RedditCommentsSpider: 8 国, sort=controversial, 5 posts/国, 20 comments/post")
    print("=" * 60)
    time.sleep(10)  # polite pause between batches

    for country in ["SG", "ID", "TH", "TR", "SA", "BR", "MX", "ZA"]:
        subs = COUNTRY_SUBREDDITS.get(country, [])
        try:
            s = RedditCommentsSpider(subreddits=subs, limit=5, max_comments=20, sort="controversial")
            posts = list(s.scrape())
            s.close()

            n_comments = sum(p.metadata.get("comment_count", 0) for p in posts)
            print(f"  {country} ({', '.join(subs[:2])}): {len(posts)} posts, {n_comments} comments")

            for p in posts:
                all_rows.append({
                    "content_id": f"reddit_{country}_{hash(p.url) & 0x7FFFFFFF:08x}",
                    "source": "reddit_comments",
                    "country": country,
                    "url": p.url,
                    "title": p.title,
                    "body": p.body,
                    "comment_count": p.metadata.get("comment_count", 0),
                    "subreddit": p.metadata.get("subreddit", ""),
                    "sort": "controversial",
                    "type": "post_with_comments",
                    "created_at": str(p.created_at),
                })
            time.sleep(2)
        except Exception as e:
            print(f"  {country}: FAILED - {e}")

    # ── 3. Ekşi Sözlük (TR) + more entries ──
    print()
    print("=" * 60)
    print("3. Ekşi Sözlük: TR, 10 topics, 10 entries/topic")
    print("=" * 60)
    time.sleep(5)
    from crawler.spiders.eksisozluk import EksiSozlukSpider

    try:
        s = EksiSozlukSpider(limit=10, entries_per_topic=10)
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
                "comment_count": 1,  # each entry = one comment
                "topic": p.title,
                "type": "entry",
                "created_at": str(p.created_at),
            })
    except Exception as e:
        print(f"  FAILED - {e}")

    # ── 4. Uludağ Sözlük (TR) + more entries ──
    print()
    print("=" * 60)
    print("4. Uludağ Sözlük: TR, 10 topics, 10 entries/topic")
    print("=" * 60)
    time.sleep(5)
    from crawler.spiders.uludagsozluk import UludagSozlukSpider

    try:
        s = UludagSozlukSpider(limit=10, entries_per_topic=10)
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
    except Exception as e:
        print(f"  FAILED - {e}")

    # ── 5. PantipCommentSpider (TH) ──
    print()
    print("=" * 60)
    print("5. PantipCommentSpider: TH, Playwright, 10 posts, 30 comments/post")
    print("=" * 60)
    time.sleep(5)
    from crawler.spiders.pantip_comments import PantipCommentSpider

    try:
        s = PantipCommentSpider(limit=10, max_comments=30)
        posts = s.scrape()
        n_comments = sum(p.metadata.get("comment_count", 0) for p in posts)
        print(f"  {len(posts)} posts, {n_comments} comments")

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
    except Exception as e:
        print(f"  FAILED - {e}")

    # ── 导出 ──
    print()
    print("=" * 60)
    df = pd.DataFrame(all_rows)
    csv_path = out_dir / "comments_batch.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"Total: {len(df)} rows → {csv_path}")

    # 统计
    print()
    print("=== 统计 ===")
    print(f"总计: {len(df)} 条")
    print()
    print("按来源/排序:")
    stats = df.groupby(["source", df.get("sort", "N/A")]).agg(
        rows=("content_id", "count"),
        total_comments=("comment_count", "sum"),
    )
    print(stats.to_string())
    print()
    print("按国家:")
    print(df.groupby("country").agg(
        rows=("content_id", "count"),
        total_comments=("comment_count", "sum"),
    ).to_string())


if __name__ == "__main__":
    main()
