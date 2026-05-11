#!/usr/bin/env python3
"""Final retry: Uludağ + Pantip with error resilience."""

import time, random, re
from datetime import datetime
from pathlib import Path

import pandas as pd
from config import COUNTRY_NAMES

out_dir = Path("data/comments_batch")
existing = sorted(out_dir.glob("v4_batch_*.parquet"), key=lambda p: p.stat().st_mtime)
df = pd.read_parquet(existing[-1])
all_rows = df.to_dict("records")
m = re.search(r'v4_batch_(\d+)', existing[-1].name)
counter = int(m.group(1)) if m else len(existing)
print(f"Loaded {len(all_rows)} rows from {existing[-1].name}")

def save():
    global counter; counter += 1
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    df_out = pd.DataFrame(all_rows)
    p = out_dir / f"v4_batch_{counter:03d}_{ts}.parquet"
    df_out.to_parquet(p, index=False)
    df_out.to_csv(out_dir / f"v4_batch_{counter:03d}_{ts}.csv", index=False)
    print(f"\n  SAVED [{counter}] {len(df_out)} rows -> {p.name}", flush=True)

def crawl_uludag():
    """Uludağ with per-topic retry and error resilience."""
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin, unquote
    from crawler.base_spider import RawPost
    from crawler.middleware import PoliteClient

    client = PoliteClient(default_delay=4.0, http2=False)

    # Get topic URLs from home + gundem
    topic_urls = []
    for page_url in ["https://www.uludagsozluk.com", "https://www.uludagsozluk.com/gundem"]:
        try:
            resp = client.get(page_url, delay=2.0, max_retries=2)
            soup = BeautifulSoup(resp.text, "lxml")
            for a in soup.select("a[href]"):
                href = a.get("href", "")
                txt = a.get_text(strip=True)
                if href.startswith("/k/") and len(txt) > 10:
                    full = urljoin("https://www.uludagsozluk.com", href)
                    if full not in topic_urls:
                        topic_urls.append(full)
                if len(topic_urls) >= 30:
                    break
        except Exception as e:
            print(f"  Warning listing {page_url}: {e}", flush=True)
        if len(topic_urls) >= 30:
            break

    print(f"  Found {len(topic_urls)} topics", flush=True)

    entries = []
    seen_keys = set()

    for i, t_url in enumerate(topic_urls):
        if len(entries) >= 750:
            break
        try:
            # Fresh client per topic to avoid pipe issues
            tc = PoliteClient(default_delay=3.0, http2=False)
            resp = tc.get(t_url, delay=2.0, max_retries=2, timeout=20)
            soup = BeautifulSoup(resp.text, "lxml")
            tc.close()

            # Topic title
            slug = t_url.replace("https://www.uludagsozluk.com", "").rstrip("/")
            if "/k/" in slug:
                slug_part = slug.split("/k/")[-1].rstrip("/").split("&")[0]
                topic_title = unquote(slug_part).replace("-", " ").title()
            else:
                topic_title = ""

            h1 = soup.select_one("h1, h2[class*=title]")
            if h1 and len(h1.get_text(strip=True)) > 3:
                topic_title = h1.get_text(strip=True)

            # Look for entry divs
            entry_divs = soup.select("div.entry-content, div[class*=entry-text], div.entry-body, div.col-entry-main-ulu, div[id*=entry]")
            if not entry_divs:
                entry_divs = soup.select("div[class*=entry] div, div[id*=entry] div")

            for el in entry_divs:
                txt = el.get_text(strip=True)
                # Quality filters
                if not (50 < len(txt) < 3000):
                    continue
                first50 = txt.lower()[:80]
                if any(skip in first50 for skip in ["detaylı ara", "vazgeç", "başlıklar", "üyeler",
                                                      "giriş yap", "kayıt ol", "paylaş", "şikayet",
                                                      "loading", "görsel", "entry adresi", "trends",
                                                      "iyiler", "başlık içinde ara"]):
                    continue
                key = txt[:80]
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                entries.append(
                    RawPost(
                        source="uludagsozluk", country="TR", url=t_url,
                        title=topic_title,
                        body=f"{topic_title}\n\n{txt}",
                        author_hash=RawPost.hash_author("anonymous"),
                        created_at=datetime.now(timezone.utc),
                    )
                )
                if len(entries) >= 750:
                    break

            if (i+1) % 5 == 0:
                print(f"  [{i+1}/{len(topic_urls)} topics, {len(entries)} entries]", flush=True)

        except Exception as e:
            print(f"  Skip topic {i}: {type(e).__name__}", flush=True)
            time.sleep(2)
            continue

    # Save to all_rows
    for r in entries:
        all_rows.append({
            "content_id": f"uludag_{hash(r.url) & 0x7FFFFFFF:08x}",
            "source": "uludagsozluk", "country": "TR", "url": r.url,
            "title": r.title, "body": r.body, "comment_count": 1,
            "topic": r.title, "type": "entry", "created_at": str(r.created_at),
        })

    print(f"  Uludağ done: {len(entries)} total entries", flush=True)
    return len(entries)


def crawl_pantip():
    """Pantip with per-room retry."""
    import asyncio
    import os
    from playwright.async_api import async_playwright

    ROOMS = [
        ("https://pantip.com/forum/sinthorn", "social & political"),
        ("https://pantip.com/forum/rajdumnern", "current affairs"),
    ]
    MAX_TOPICS = 30
    MAX_COMMENTS = 80

    all_posts = []

    async def _scrape():
        proxy_url = os.getenv("http_proxy", "") or os.getenv("https_proxy", "")
        launch_args = {"headless": True}
        if proxy_url:
            launch_args["proxy"] = {"server": proxy_url}

        async with async_playwright() as p:
            browser = await p.chromium.launch(**launch_args)

            for room_url, room_name in ROOMS:
                try:
                    context = await browser.new_context(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        locale="th-TH",
                    )
                    page = await context.new_page()

                    print(f"  Navigating to {room_name}...", flush=True)
                    try:
                        await page.goto(room_url, wait_until="domcontentloaded", timeout=60000)
                        await page.wait_for_timeout(5000)
                    except Exception as e:
                        print(f"  Room nav failed: {e}", flush=True)
                        await context.close()
                        continue

                    # Get topic URLs
                    hrefs = await page.eval_on_selector_all(
                        'a[href*="/topic/"]',
                        "els => els.map(e => e.getAttribute('href')).filter(h => h && h.includes('/topic/'))"
                    )
                    seen = set()
                    topic_urls = []
                    for h in hrefs:
                        if h not in seen and "/tag/" not in h:
                            seen.add(h)
                            url = h if h.startswith("http") else "https://pantip.com" + h
                            topic_urls.append(url)
                    topic_urls = topic_urls[:MAX_TOPICS // 2]  # half per room

                    print(f"  [{room_name}] {len(topic_urls)} topics found", flush=True)

                    for j, t_url in enumerate(topic_urls):
                        if len(all_posts) >= MAX_TOPICS:
                            break
                        try:
                            await page.goto(t_url, wait_until="domcontentloaded", timeout=45000)
                            await page.wait_for_timeout(4000)

                            title = ""
                            try:
                                title_el = await page.text_content("h1.display-post-title")
                                title = title_el.strip() if title_el else ""
                            except Exception:
                                pass

                            body = ""
                            try:
                                body_el = await page.text_content("div.display-post-story")
                                body = body_el.strip() if body_el else ""
                            except Exception:
                                pass

                            # Comments
                            comments = []
                            try:
                                comment_els = await page.query_selector_all(".display-post-story-wrapper .display-post-story, .comment-text")
                                for el in comment_els[:MAX_COMMENTS]:
                                    text = await el.text_content()
                                    text = text.strip()
                                    if len(text) >= 10:
                                        comments.append(text)
                            except Exception:
                                pass

                            if not comments:
                                try:
                                    all_text = await page.evaluate("""
                                        () => {
                                            const comments = document.querySelectorAll('.comment-box-remark, .display-post-story');
                                            return Array.from(comments).map(c => c.textContent.trim()).filter(t => t.length > 10);
                                        }
                                    """)
                                    comments = all_text[:MAX_COMMENTS]
                                except Exception:
                                    pass

                            full_body = f"[POST]\n{title}\n\n{body}"
                            if comments:
                                full_body += "\n\n[COMMENTS]\n" + "\n---\n".join(comments)

                            if title or body:
                                from crawler.base_spider import RawPost
                                all_posts.append(RawPost(
                                    source="pantip", country="TH", url=t_url,
                                    title=title, body=full_body.strip(),
                                    author_hash=RawPost.hash_author("anonymous"),
                                    created_at=datetime.now(timezone.utc),
                                    metadata={"comment_count": len(comments), "room": room_name},
                                ))

                            if (j+1) % 5 == 0:
                                print(f"    [{room_name}] {j+1}/{len(topic_urls)} topics, {len(all_posts)} posts so far", flush=True)

                        except Exception as e:
                            print(f"    Skip topic: {type(e).__name__}", flush=True)
                            continue

                    await context.close()
                    time.sleep(3)

                except Exception as e:
                    print(f"  Room {room_name} FAILED: {type(e).__name__}: {e}", flush=True)

            await browser.close()

    asyncio.get_event_loop().run_until_complete(_scrape())

    for r in all_posts:
        all_rows.append({
            "content_id": f"pantip_{hash(r.url) & 0x7FFFFFFF:08x}",
            "source": "pantip", "country": "TH", "url": r.url,
            "title": r.title, "body": r.body,
            "comment_count": r.metadata.get("comment_count", 0),
            "room": r.metadata.get("room", ""),
            "type": "post_with_comments", "created_at": str(r.created_at),
        })

    print(f"  Pantip done: {len(all_posts)} posts", flush=True)
    return len(all_posts)


def main():
    pre = len(all_rows)

    # 1. Uludağ
    print("=" * 60 + "\nUludağ Sözlük (TR) - resilient retry\n" + "=" * 60)
    try:
        n = crawl_uludag()
        print(f"  Gained {n} new entries", flush=True)
        save()
    except Exception as e:
        print(f"  Uludağ crashed: {e}", flush=True)
        import traceback; traceback.print_exc()

    # 2. Pantip
    print("\n" + "=" * 60 + "\nPantip (TH) - per-room retry\n" + "=" * 60)
    try:
        n = crawl_pantip()
        print(f"  Gained {n} new posts", flush=True)
        save()
    except Exception as e:
        print(f"  Pantip crashed: {e}", flush=True)
        import traceback; traceback.print_exc()

    gained = len(all_rows) - pre
    print(f"\n{'='*60}\nDONE - gained {gained} new rows\n{'='*60}")
    df_out = pd.DataFrame(all_rows)
    print(df_out.groupby("country").agg(rows=("content_id","count")).sort_values("rows",ascending=False).to_string())
    save()

if __name__ == "__main__":
    from datetime import timezone
    main()
