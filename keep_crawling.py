#!/usr/bin/env python3
"""持续爬取直到每个国家达到目标条数。

用法:
  python keep_crawling.py              # 目标 10000/国
  python keep_crawling.py --target 5000  # 目标 5000/国
  python keep_crawling.py --countries SG TH SA  # 只爬指定国家
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

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
REDDIT_UA = UA  # Reddit needs a full UA

# ── Reddit 子版块（扩充）──
REDDIT_SUBS = {
    "SG": ["singapore", "SingaporeRaw"],
    "ID": ["indonesia", "indonesian", "Jakarta"],
    "TH": ["thailand", "thaithai"],
    "TR": ["turkey", "TurkeyJerky", "Turkey"],
    "SA": ["saudiarabia", "Arabs", "saudiarabia", "arabs"],
    "BR": ["brasil", "Brazil", "futebol", "brasilivre", "brasildob"],
    "MX": ["mexico", "mexicanfood", "MexicoCity"],
    "ZA": ["southafrica", "RSA", "CapeTown"],
}

# ── 论坛源 ──
FORUMS = {
    "SG": [("hardwarezone", "https://forums.hardwarezone.com.sg",
            "/threads/", "h1.p-title-value", "div.bbWrapper", "proxy")],
    "TH": [
        ("pantip-sinthorn", "https://pantip.com/forum/sinthorn",  # 社会政治
         "/topic/", "h1.display-post-title", "div.display-post-story", "direct"),
        ("pantip-rajdumnern", "https://pantip.com/forum/rajdumnern",  # 时事
         "/topic/", "h1.display-post-title", "div.display-post-story", "direct"),
    ],
    "ID": [("kompasiana", "https://www.kompasiana.com",
            "/kompasiana.com/", "h1", "div.article-content, article", "proxy")],
    "SA": [("adslgate", "https://www.adslgate.com",
            "/thread/", "h1", "div.bbWrapper, article", "direct")],
    "BR": [("hardmob", "https://www.hardmob.com.br/content/1-home",
            "/content/", "h1", "article, div[class*=\"content\"]", "direct")],
    "TR": [("donanimhaber", "https://forum.donanimhaber.com",
            "/mesaj/yonlen/", "h2 strong, h1", "div.message", "direct")],
}


def clean_text(text):
    if not isinstance(text, str):
        return ""
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [l.strip() for l in text.split("\n")]
    while lines and not lines[0]: lines.pop(0)
    while lines and not lines[-1]: lines.pop()
    text = "\n".join(lines)
    text = re.sub(r" {3,}", "  ", text)
    text = "".join(ch for ch in text if ch.isprintable() or ch == "\n")
    return unicodedata.normalize("NFC", text).strip()


def is_valid(text):
    if not text or len(text) < 5:
        return False
    return text.lower() not in ("loading...", "[deleted]", "[removed]", ".")


def count_existing(outdir):
    """统计已爬数据量。"""
    total = 0
    for pq in outdir.glob("*.parquet"):
        try:
            total += len(pd.read_parquet(pq))
        except Exception:
            pass
    return total


def crawl_reddit(country, outdir, proxy, pages=10):
    """爬 Reddit 帖子 + 每条评论独立保存（使用 JSON API）。"""
    import json as json_mod
    subs = REDDIT_SUBS.get(country, [])
    items = []
    for sub in subs:
        for sort in ["controversial", "hot", "top"]:
            after = None
            for page in range(pages):
                listing_url = f"https://www.reddit.com/r/{sub}/{sort}/.json?limit=25"
                if after:
                    listing_url += f"&after={after}"

                try:
                    client_kw = {"timeout": 15, "headers": {"User-Agent": REDDIT_UA}}
                    if proxy:
                        client_kw["proxy"] = proxy
                    else:
                        client_kw["trust_env"] = False

                    with httpx.Client(**client_kw) as c:
                        r = c.get(listing_url)
                        if r.status_code != 200:
                            break
                        data = r.json()

                    posts = data["data"]["children"]
                    if not posts:
                        break

                    for post_wrapper in posts:
                        if post_wrapper["kind"] != "t3":
                            continue
                        post = post_wrapper["data"]
                        title = post.get("title", "")
                        post_id = post.get("id", "")
                        permalink = post.get("permalink", "")
                        selftext = post.get("selftext", "")
                        after = post.get("name", "")

                        if not title or not permalink:
                            continue

                        # 帖子正文
                        op_body = clean_text(selftext) if selftext else ""
                        body_text = clean_text(f"OP:\n{title}\n\n{op_body}" if op_body else f"OP:\n{title}")
                        if is_valid(body_text):
                            items.append({
                                "source": "reddit", "country": country,
                                "url": f"https://www.reddit.com{permalink}",
                                "title": clean_text(title),
                                "body": body_text, "type": "post",
                                "subreddit": sub, "sort": sort,
                                "created_at": datetime.now(timezone.utc).isoformat(),
                            })

                        # === JSON API 拿评论：一个请求全拿 ===
                        comments_url = f"https://www.reddit.com{permalink}.json"
                        try:
                            cr = c.get(comments_url)
                            if cr.status_code != 200:
                                continue
                            cdata = cr.json()
                            if len(cdata) < 2:
                                continue

                            for cmt_wrapper in cdata[1]["data"]["children"]:
                                if cmt_wrapper["kind"] != "t1":
                                    continue
                                cmt = cmt_wrapper["data"]
                                cmt_body = cmt.get("body", "")
                                if not cmt_body or cmt_body in ("[deleted]", "[removed]"):
                                    continue

                                items.append({
                                    "source": "reddit", "country": country,
                                    "url": f"https://www.reddit.com{permalink}",
                                    "title": f"RE: {title[:80]}",
                                    "body": clean_text(cmt_body[:2000]),
                                    "type": "comment",
                                    "subreddit": sub, "sort": sort,
                                    "created_at": datetime.now(timezone.utc).isoformat(),
                                })
                        except Exception:
                            continue  # 评论请求失败不影响继续

                except Exception:
                    break
                time.sleep(0.5)

    return items


def crawl_forum(cfg, outdir, proxy, limit=30):
    """爬论坛帖子 + 评论。"""
    name, url, link_pattern, title_sel, body_sel, method = cfg
    items = []

    client_kw = {"timeout": 20, "headers": {"User-Agent": UA, "Accept-Language": "*"}}
    if method == "direct":
        client_kw["trust_env"] = False
    elif proxy:
        client_kw["proxy"] = proxy

    try:
        with httpx.Client(**client_kw) as client:
            r = client.get(url, follow_redirects=True)
            soup = BeautifulSoup(r.text, "lxml")

            # 找帖子链接
            links = []
            for a in soup.select(f"a[href*=\"{link_pattern}\"]"):
                h = a.get("href", "")
                t = a.text.strip()
                if len(t) > 10 and "/create" not in h.lower():
                    if h.startswith("/"):
                        base = "/".join(url.split("/")[:3])
                        h = base + h
                    if h.startswith("http") and h not in [l[0] for l in links]:
                        links.append((h, t))

            for thread_url, _ in links[:limit]:
                try:
                    tr = client.get(thread_url, follow_redirects=True)
                    tsoup = BeautifulSoup(tr.text, "lxml")

                    title_el = tsoup.select_one(title_sel)
                    title = title_el.text.strip() if title_el else ""

                    body = ""
                    for bs in body_sel.split(", "):
                        el = tsoup.select_one(bs)
                        if el:
                            body = el.text.strip()[:3000]
                            if len(body) > 30:
                                break
                    if not body:
                        body = tsoup.text.strip()[:2000]

                    if title and is_valid(body):
                        items.append({
                            "source": name,
                            "country": country_from_name(name),
                            "url": thread_url,
                            "title": clean_text(title),
                            "body": clean_text(f"[POST]\n{title}\n\n{body}"),
                            "type": "post",
                            "forum": name,
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        })

                    # 评论
                    for cmt_sel in ["article.message", "div.message", "div.post",
                                    "div[class*=\"comment\"]", "div.entry"]:
                        for cmt in tsoup.select(cmt_sel)[:20]:
                            ct = cmt.text.strip()
                            if len(ct) > 10:
                                items.append({
                                    "source": name,
                                    "country": country_from_name(name),
                                    "url": thread_url,
                                    "title": f"RE: {title[:80]}",
                                    "body": clean_text(ct[:2000]),
                                    "type": "comment",
                                    "forum": name,
                                    "created_at": datetime.now(timezone.utc).isoformat(),
                                })
                        if any(i["type"] == "comment" for i in items[-10:]):
                            break
                    time.sleep(0.3)
                except Exception:
                    continue
    except Exception:
        pass

    return items


def country_from_name(name):
    mapping = {"hardwarezone": "SG", "pantip": "TH", "kompasiana": "ID",
               "adslgate": "SA", "hardmob": "BR", "donanimhaber": "TR"}
    return mapping.get(name, "??")


def save_items(items, outdir):
    if not items:
        return 0
    df = pd.DataFrame(items)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    df.to_parquet(outdir / f"crawl_{ts}.parquet", index=False)
    return len(df)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=10000)
    parser.add_argument("--countries", nargs="+",
                        default=["SG", "TH", "ID", "SA", "TR", "BR"])
    parser.add_argument("--reddit-pages", type=int, default=15)
    parser.add_argument("--forum-limit", type=int, default=30)
    args = parser.parse_args()

    proxy = os.getenv("http_proxy", "") or os.getenv("https_proxy", "")
    base = Path("data/raw_bulk")
    base.mkdir(parents=True, exist_ok=True)

    print(f"持续爬取 — 目标: {args.target}/国")
    print(f"代理: {proxy[:30] if proxy else '无'}...")
    print(f"=" * 50)

    round_num = 0
    while True:
        round_num += 1
        print(f"\n{'='*50}")
        print(f"第 {round_num} 轮")
        print(f"{'='*50}")

        all_done = True
        for country in args.countries:
            outdir = base / country
            outdir.mkdir(parents=True, exist_ok=True)
            current = count_existing(outdir)
            if current >= args.target:
                print(f"  [{country}] {current}/{args.target} ✓ 已达标, 跳过")
                continue
            all_done = False

            print(f"  [{country}] {current}/{args.target} (需+{args.target - current})...",
                  end=" ", flush=True)

            items = []

            # Reddit
            if country in REDDIT_SUBS:
                try:
                    reddit_items = crawl_reddit(country, outdir, proxy, args.reddit_pages)
                    items.extend(reddit_items)
                except Exception as e:
                    pass

            # Forum
            for cfg in FORUMS.get(country, []):
                try:
                    forum_items = crawl_forum(cfg, outdir, proxy, args.forum_limit)
                    items.extend(forum_items)
                except Exception as e:
                    pass

            if items:
                n = save_items(items, outdir)
                print(f"+{n} → {current + n}/{args.target}")
            else:
                print("+0")

        if all_done:
            break
        time.sleep(3)

    # 最终统计
    print(f"\n{'='*50}")
    print("全部达标!")
    for country in args.countries:
        print(f"  {country}: {count_existing(base / country)}")


if __name__ == "__main__":
    main()
