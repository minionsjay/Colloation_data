#!/usr/bin/env python3
"""大规模爬取 8 国论坛数据，按国家分类保存。

用法:
  python bulk_crawl.py              # 默认每个源 30 条
  python bulk_crawl.py 50           # 每个源 50 条
  python bulk_crawl.py 50 --fast    # 快速模式（减少延迟）

输出:
  data/raw_bulk/{country}/
    ├── {source}_{timestamp}.parquet
    └── ...

覆盖:
  SG - HardwareZone 论坛 + Reddit r/singapore
  ID - Kompasiana + Reddit r/indonesia
  TH - Pantip + Reddit r/thailand, r/thaithai
  TR - Reddit r/turkey
  SA - Reddit r/saudiarabia
  BR - Reddit r/brasil, r/brazil
  MX - Reddit r/mexico
  ZA - Reddit r/southafrica
"""

import argparse
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pandas as pd
from bs4 import BeautifulSoup

from crawler.base_spider import RawPost
from crawler.spiders.reddit_split_comments import RedditSplitSpider


def clean_text(text: str) -> str:
    """清洗文本：去多余换行/空格/控制字符。"""
    if not isinstance(text, str):
        return ""
    # 合并连续换行（3+ → 2）
    text = re.sub(r"\n{3,}", "\n\n", text)
    # 去行首尾空白
    lines = [l.strip() for l in text.split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    text = "\n".join(lines)
    # 压缩空格
    text = re.sub(r" {3,}", "  ", text)
    text = re.sub(r"\t+", " ", text)
    # 去控制字符
    text = "".join(ch for ch in text if ch.isprintable() or ch == "\n")
    # Unicode 正规化
    text = unicodedata.normalize("NFC", text)
    return text.strip()


# ── Reddit 爬取（已有稳定爬虫）───────────────────────────────

REDDIT_SOURCES = {
    "SG": ["singapore", "SingaporeRaw"],
    "ID": ["indonesia"],
    "TH": ["thailand", "thaithai"],
    "TR": ["turkey", "TurkeyJerky"],
    "SA": ["saudiarabia"],
    "BR": ["brasil", "Brazil"],
    "MX": ["mexico"],
    "ZA": ["southafrica"],
}

REDDIT_SORTS = ["hot", "controversial", "top"]


def crawl_reddit(country: str, limit: int, pages: int, outdir: Path):
    """爬取 Reddit 帖子+分离评论，支持多页。"""
    import uuid
    from datetime import datetime, timezone
    from urllib.parse import urljoin

    subs = REDDIT_SOURCES.get(country, [])
    proxy = os.getenv("http_proxy", "") or os.getenv("https_proxy", "")

    for sub in subs:
        for sort in REDDIT_SORTS:
            total_collected = 0
            after = None

            for page in range(pages):
                url = f"https://old.reddit.com/r/{sub}/{sort}/"
                if after:
                    url += f"?count={page*25}&after={after}"

                print(f"  r/{sub}/{sort} p{page+1}...", end=" ", flush=True)
                try:
                    with httpx.Client(proxy=proxy, timeout=15,
                                      headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"}) as client:
                        r = client.get(url)
                        soup = BeautifulSoup(r.text, "lxml")

                    items = []
                    post_divs = soup.select("div.thing")
                    for post_div in post_divs:
                        title_el = post_div.select_one("a.title")
                        if not title_el:
                            continue
                        title = title_el.text.strip()
                        href = title_el.get("href", "")

                        # 获取 after token 用于分页
                        thing_id = post_div.get("data-fullname", "")
                        if thing_id:
                            after = thing_id

                        post_url = urljoin("https://old.reddit.com", href)

                        # 帖子正文
                        body_text = ""
                        body_el = post_div.select_one("div.expando, div.usertext-body")
                        if body_el:
                            body_text = body_el.text.strip()

                        pid = str(uuid.uuid4())[:12]
                        items.append(RawPost(
                            source="reddit", country=country, url=post_url,
                            title=title,
                            body=f"[POST] {title}\n\n{body_text}".strip(),
                            author_hash=RawPost.hash_author("anon"),
                            created_at=datetime.now(timezone.utc),
                            metadata={"type": "post", "parent_id": pid, "subreddit": sub, "sort": sort},
                        ))

                        # 评论
                        try:
                            tr = client.get(post_url)
                            csoup = BeautifulSoup(tr.text, "lxml")
                            for ci, cmt in enumerate(csoup.select("div.comment")[:20]):
                                if cmt.find_parent("div.comment"):
                                    continue
                                if cmt.select_one("div.deleted, div.removed"):
                                    continue
                                md = cmt.select_one("div.md")
                                if not md:
                                    continue
                                txt = md.text.strip()
                                if len(txt) >= 8:
                                    items.append(RawPost(
                                        source="reddit", country=country, url=post_url,
                                        title=f"RE: {title}",
                                        body=f"[COMMENT #{ci+1}]\n{txt}",
                                        author_hash=RawPost.hash_author("anon"),
                                        created_at=datetime.now(timezone.utc),
                                        metadata={"type": "comment", "parent_id": pid, "subreddit": sub, "sort": sort},
                                    ))
                            time.sleep(0.3)
                        except Exception:
                            pass

                    if items:
                        df = _raw_posts_to_df(items)
                        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                        path = outdir / f"reddit_{sub}_{sort}_p{page+1}_{ts}.parquet"
                        df.to_parquet(path, index=False)
                        total_collected += len(items)
                        print(f"{len(items)} items")
                    else:
                        print("0 - stopping pagination")
                        break

                    if not after:
                        break

                except Exception as e:
                    print(f"err: {type(e).__name__}")
                    break

            print(f"  → r/{sub}/{sort}: {total_collected} total")


# ── 论坛爬取（httpx 直连）─────────────────────────────────────

def crawl_hardwarezone(limit: int, outdir: Path, proxy: str):
    """新加坡 HardwareZone — 英语论坛，评论丰富。"""
    print("  HardwareZone...", end=" ", flush=True)
    items = []
    with httpx.Client(proxy=proxy, timeout=20,
                      headers={"User-Agent": "Mozilla/5.0"}) as client:
        # 热门板块
        for forum in ["eat-drink-man-woman", "current-affairs"]:
            try:
                r = client.get(f"https://forums.hardwarezone.com.sg/forums/{forum}/")
                soup = BeautifulSoup(r.text, "lxml")
                links = []
                for a in soup.select("a[href*='threads/']"):
                    href = a.get("href", "")
                    if "/threads/" in href and "/post-" not in href:
                        full = "https://forums.hardwarezone.com.sg" + href if href.startswith("/") else href
                        if full not in links:
                            links.append(full)

                for url in links[:limit]:
                    try:
                        tr = client.get(url)
                        tsoup = BeautifulSoup(tr.text, "lxml")
                        title_el = tsoup.select_one("h1.p-title-value")
                        title = title_el.text.strip() if title_el else "N/A"
                        body_el = tsoup.select_one("div.bbWrapper")
                        body = body_el.text.strip()[:3000] if body_el else ""

                        items.append(RawPost(
                            source="hardwarezone", country="SG", url=url,
                            title=title, body=f"{title}\n\n{body}",
                            author_hash=RawPost.hash_author("anon"),
                            created_at=datetime.now(timezone.utc),
                            metadata={"type": "post", "forum": forum},
                        ))

                        # 评论
                        for ci, cmt in enumerate(tsoup.select("article.message")[:15]):
                            cmt_body = cmt.select_one("div.bbWrapper")
                            if cmt_body:
                                txt = cmt_body.text.strip()
                                if len(txt) > 5:
                                    items.append(RawPost(
                                        source="hardwarezone", country="SG", url=url,
                                        title=f"RE: {title}",
                                        body=f"[COMMENT #{ci+1}]\n{txt}",
                                        author_hash=RawPost.hash_author("anon"),
                                        created_at=datetime.now(timezone.utc),
                                        metadata={"type": "comment", "forum": forum},
                                    ))
                        time.sleep(0.5)
                    except Exception:
                        continue
            except Exception as e:
                print(f"({forum}: {type(e).__name__})", end=" ")
                continue

    if items:
        df = _raw_posts_to_df(items)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = outdir / f"hardwarezone_{ts}.parquet"
        df.to_parquet(path, index=False)
        print(f"{len(items)} items → {path.name}")
    else:
        print("0 items")


def crawl_kompasiana(limit: int, outdir: Path, proxy: str):
    """印尼 Kompasiana — 印尼语博客/新闻。"""
    print("  Kompasiana...", end=" ", flush=True)
    items = []
    with httpx.Client(proxy=proxy, timeout=20,
                      headers={"User-Agent": "Mozilla/5.0"}) as client:
        # 分类页
        for cat in ["", "/politik", "/sosial-budaya", "/internasional"]:
            try:
                url = f"https://www.kompasiana.com{cat}" if cat else "https://www.kompasiana.com"
                r = client.get(url)
                soup = BeautifulSoup(r.text, "lxml")
                links = set()
                for a in soup.select("a[href*='kompasiana.com/']"):
                    href = a.get("href", "")
                    text = a.text.strip()
                    if len(text) > 30 and "/tag/" not in href and "/category/" not in href:
                        if href.startswith("/"):
                            href = "https://www.kompasiana.com" + href
                        links.add(href)

                for url in list(links)[:limit]:
                    try:
                        tr = client.get(url)
                        tsoup = BeautifulSoup(tr.text, "lxml")
                        title_el = tsoup.select_one("h1.article-title, h1")
                        title = title_el.text.strip() if title_el else "N/A"
                        body_el = tsoup.select_one("div.article-content, article, div.post-content")
                        body = body_el.text.strip()[:3000] if body_el else ""

                        items.append(RawPost(
                            source="kompasiana", country="ID", url=url,
                            title=title, body=f"{title}\n\n{body}",
                            author_hash=RawPost.hash_author("anon"),
                            created_at=datetime.now(timezone.utc),
                            metadata={"type": "post", "category": cat or "home"},
                        ))
                        time.sleep(0.5)
                    except Exception:
                        continue
            except Exception as e:
                print(f"({cat}: {type(e).__name__})", end=" ")
                continue

    if items:
        df = _raw_posts_to_df(items)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = outdir / f"kompasiana_{ts}.parquet"
        df.to_parquet(path, index=False)
        print(f"{len(items)} items → {path.name}")
    else:
        print("0 items")


def crawl_pantip(limit: int, outdir: Path, proxy: str):
    """泰国 Pantip — 泰语论坛（敏感话题房间）。"""
    print("  Pantip...", end=" ", flush=True)
    items = []
    # 敏感话题 / 热门房间
    rooms = [
        "/forum/sinthorn",       # 社会政治
        "/forum/rajdumnern",     # 时事
        "/forum/supachalasai",   # 综合
        "/forum/bluplanet",      # 生活
    ]
    with httpx.Client(proxy=proxy, timeout=20,
                      headers={"User-Agent": "Mozilla/5.0"}) as client:
        for room in rooms:
            try:
                r = client.get(f"https://pantip.com{room}")
                soup = BeautifulSoup(r.text, "lxml")
                links = set()
                for a in soup.select("a[href*='/topic/']"):
                    href = a.get("href", "")
                    if "/topic/" in href and "/tag/" not in href:
                        links.add(href if href.startswith("http") else f"https://pantip.com{href}")

                for url in list(links)[:limit]:
                    try:
                        tr = client.get(url)
                        tsoup = BeautifulSoup(tr.text, "lxml")
                        title_el = tsoup.select_one("h1.display-post-title")
                        title = title_el.text.strip() if title_el else "N/A"
                        body_el = tsoup.select_one("div.display-post-story")
                        body = body_el.text.strip()[:3000] if body_el else ""

                        items.append(RawPost(
                            source="pantip", country="TH", url=url,
                            title=title, body=f"{title}\n\n{body}",
                            author_hash=RawPost.hash_author("anon"),
                            created_at=datetime.now(timezone.utc),
                            metadata={"type": "post", "room": room},
                        ))
                        time.sleep(0.5)
                    except Exception:
                        continue
            except Exception as e:
                print(f"({room}: {type(e).__name__})", end=" ")
                continue

    if items:
        df = _raw_posts_to_df(items)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = outdir / f"pantip_{ts}.parquet"
        df.to_parquet(path, index=False)
        print(f"{len(items)} items → {path.name}")
    else:
        print("0 items")


# ── 工具函数 ──────────────────────────────────────────────────

def _raw_posts_to_df(posts: list[RawPost]) -> pd.DataFrame:
    """RawPost 列表转清洗后的 DataFrame。"""
    rows = []
    for p in posts:
        body = clean_text(p.body)
        # 过滤无效
        if not body or len(body) < 5 or body.lower() in ("loading...", "[deleted]", "[removed]"):
            continue
        rows.append({
            "content_id": p.content_id,
            "source": p.source,
            "country": p.country,
            "url": p.url,
            "title": clean_text(p.title),
            "body": body,
            "author_hash": p.author_hash,
            "created_at": p.created_at,
            "type": p.metadata.get("type", "post"),
            "parent_id": p.metadata.get("parent_id", ""),
            "comment_index": p.metadata.get("comment_index", 0),
            "subreddit": p.metadata.get("subreddit", ""),
            "forum": p.metadata.get("forum", ""),
            "room": p.metadata.get("room", ""),
            "sort": p.metadata.get("sort", ""),
        })
    return pd.DataFrame(rows)


def _dedup_dir(outdir: Path):
    """合并一个国家目录下的所有 parquet 并去重。"""
    files = list(outdir.glob("*.parquet"))
    if len(files) <= 1:
        return
    dfs = []
    for f in files:
        try:
            dfs.append(pd.read_parquet(f))
        except Exception:
            pass
    if not dfs:
        return
    combined = pd.concat(dfs, ignore_index=True)
    before = len(combined)
    # 用 title+body 去重
    combined["_key"] = combined["title"].fillna("") + combined["body"].fillna("").str[:200]
    combined = combined.drop_duplicates(subset=["_key"], keep="last")
    combined = combined.drop(columns=["_key"])
    after = len(combined)
    if before > after:
        # 覆盖第一个文件
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = outdir / f"deduped_{ts}.parquet"
        combined.to_parquet(path, index=False)
        # 删旧文件
        for f in files:
            f.unlink()
        print(f"    Dedup: {before} → {after}, saved to {path.name}")


# ── Main ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Bulk crawl 8 countries")
    parser.add_argument("limit", nargs="?", type=int, default=25,
                        help="Posts per page (default: 25)")
    parser.add_argument("--pages", type=int, default=10,
                        help="Pages per source (default: 10)")
    parser.add_argument("--fast", action="store_true",
                        help="Reduce delays between requests")
    parser.add_argument("--countries", nargs="+",
                        default=["SG", "ID", "TH", "TR", "SA", "BR", "MX", "ZA"],
                        help="Countries to crawl (default: all 8)")
    args = parser.parse_args()

    proxy = os.getenv("http_proxy", "") or os.getenv("https_proxy", "")
    outbase = Path("data/raw_bulk")

    print("=" * 60)
    print(f"Bulk Crawl — {len(args.countries)} countries, ~{args.limit} posts/source")
    print(f"Proxy: {proxy[:30]}..." if proxy else "No proxy")
    print("=" * 60)

    for country in args.countries:
        outdir = outbase / country
        outdir.mkdir(parents=True, exist_ok=True)
        print(f"\n{'='*60}")
        print(f"  {country}")
        print(f"{'='*60}")

        # Reddit（所有国家）
        if country in REDDIT_SOURCES:
            crawl_reddit(country, args.limit, args.pages, outdir)

        # 本地论坛
        if country == "SG":
            crawl_hardwarezone(args.limit, outdir, proxy)
        elif country == "ID":
            crawl_kompasiana(args.limit, outdir, proxy)
        elif country == "TH":
            crawl_pantip(args.limit, outdir, proxy)

        # 统计
        files = list(outdir.glob("*.parquet"))
        total = 0
        for f in files:
            try:
                total += len(pd.read_parquet(f))
            except Exception:
                pass
        print(f"  → {country} total: ~{total} items in {len(files)} files")

    # 最终统计
    print(f"\n{'='*60}")
    print("All done! Output:")
    print(f"{'='*60}")
    for country_dir in sorted(outbase.iterdir()):
        if country_dir.is_dir():
            files = list(country_dir.glob("*.parquet"))
            total = 0
            for f in files:
                try:
                    total += len(pd.read_parquet(f))
                except Exception:
                    pass
            print(f"  {country_dir.name}/ : {total} items in {len(files)} files")


if __name__ == "__main__":
    main()
