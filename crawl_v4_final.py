#!/usr/bin/env python3
"""v4 final: 补充 Phase 4 top bundle + Phase 5 Global + Phase 6 TR + Phase 7 Pantip"""

import time, random, re
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
PAGES = 3  # bundle pages
GLOBAL_PAGES = 2
FORUM_TOPICS = 30
FORUM_ENTRIES = 25
PANTIP_LIMIT = 30
PANTIP_COMMENTS = 80

out_dir = Path("data/comments_batch")

# Load latest saved data
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
    print(f"\n{'='*60}\nTOTAL: {len(df)} rows\n{'='*60}")
    print(df.groupby("country").agg(rows=("content_id","count")).sort_values("rows",ascending=False).to_string())

def crawl_bundle(country, sort, top_time=None):
    from crawler.spiders.reddit_with_comments import RedditCommentsSpider
    subs = COUNTRY_SUBS.get(country, [])
    kw = {"sort": sort, "limit": POSTS_PER_PAGE, "max_comments": COMMENTS_PER_POST, "pages": PAGES}
    if top_time: kw["top_time"] = top_time
    tp = tc = 0
    for sub in subs:
        try:
            s = RedditCommentsSpider(subreddits=[sub], **kw)
            rows = list(s.scrape()); s.close()
            nc = sum(r.metadata.get("comment_count", 0) for r in rows)
            for r in rows:
                meta = r.metadata
                all_rows.append({
                    "content_id": f"bundle_{country}_{hash(r.url) & 0x7FFFFFFF:08x}",
                    "source": "reddit_bundle", "country": country, "url": r.url,
                    "title": r.title, "body": r.body,
                    "comment_count": meta.get("comment_count", 0),
                    "subreddit": meta.get("subreddit", sub), "sort": sort,
                    "top_time": top_time or "", "page": meta.get("page", 1),
                    "type": "post_with_comments", "created_at": str(r.created_at),
                })
            print(f"    {sub}/{sort}: {len(rows)} posts, {nc} comments", flush=True)
            tp += len(rows); tc += nc
            time.sleep(random.uniform(4, 7))
        except Exception as e:
            print(f"    {sub}/{sort}: FAILED - {e}", flush=True)
    return tp, tc

def main():
    start = time.time()
    countries = [c for c in COUNTRY_SUBS if c != "_global"]

    # ── Phase 4 top bundle ──
    print("=" * 60 + "\nPHASE 4: Reddit Bundle (top/year) — 3 pages\n" + "=" * 60)
    for country in countries:
        print(f"\n--- {country} ({COUNTRY_NAMES.get(country, '?')}) ---", flush=True)
        crawl_bundle(country, "top", top_time="year")
        stats()
        time.sleep(random.uniform(5, 10))
    save()

    # ── Phase 5: Global ──
    print("\n" + "=" * 60 + "\nPHASE 5: Global controversial subreddits\n" + "=" * 60)
    for sub in COUNTRY_SUBS.get("_global", []):
        print(f"\n--- global/{sub} ---", flush=True)
        try:
            from crawler.spiders.reddit_split_comments import RedditSplitSpider
            s = RedditSplitSpider(subreddits=[sub], limit=POSTS_PER_PAGE,
                                  max_comments=COMMENTS_PER_POST, sort="controversial",
                                  top_time="year", pages=GLOBAL_PAGES)
            rows = list(s.scrape()); s.close()
            for r in rows:
                meta = r.metadata
                all_rows.append({
                    "content_id": f"global_{hash(r.url) & 0x7FFFFFFF:08x}",
                    "source": "reddit_split", "country": "GLOBAL", "url": r.url,
                    "title": r.title, "body": r.body, "comment_count": 1,
                    "parent_id": meta.get("parent_id",""), "type": meta.get("type","post"),
                    "subreddit": sub, "sort": "controversial", "page": meta.get("page",1),
                    "created_at": str(r.created_at),
                })
            print(f"  {sub}: {len(rows)} rows", flush=True)
            time.sleep(random.uniform(5, 10))
        except Exception as e:
            print(f"  {sub}: FAILED - {e}", flush=True)
    save()

    # ── Phase 6: TR forums ──
    print("\n" + "=" * 60 + "\nPHASE 6: TR local forums\n" + "=" * 60)
    for forum, spider_cls_name in [("eksi", "EksiSozlukSpider"), ("uludag", "UludagSozlukSpider")]:
        try:
            mod = __import__(f"crawler.spiders.eksisozluk" if forum == "eksi" else f"crawler.spiders.uludagsozluk",
                             fromlist=[spider_cls_name])
            cls = getattr(mod, spider_cls_name)
            s = cls(limit=FORUM_TOPICS, entries_per_topic=FORUM_ENTRIES)
            rows = list(s.scrape()); s.close()
            source = "eksisozluk" if forum == "eksi" else "uludagsozluk"
            for r in rows:
                all_rows.append({
                    "content_id": f"{forum}_{hash(r.url) & 0x7FFFFFFF:08x}",
                    "source": source, "country": "TR", "url": r.url,
                    "title": r.title, "body": r.body, "comment_count": 1,
                    "topic": r.title, "type": "entry", "created_at": str(r.created_at),
                })
            print(f"  {forum}: {len(rows)} entries", flush=True)
            time.sleep(5)
        except Exception as e:
            print(f"  {forum}: FAILED - {e}", flush=True)
    save()

    # ── Phase 7: TH Pantip ──
    print("\n" + "=" * 60 + "\nPHASE 7: TH Pantip (Playwright)\n" + "=" * 60)
    try:
        from crawler.spiders.pantip_comments import PantipCommentSpider
        s = PantipCommentSpider(limit=PANTIP_LIMIT, max_comments=PANTIP_COMMENTS)
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
    except Exception as e:
        print(f"  Pantip FAILED: {e}", flush=True)
    save()

    # Done
    elapsed = time.time() - start
    df = pd.DataFrame(all_rows)
    print(f"\n{'='*60}\nALL DONE in {elapsed/60:.1f} min — {len(df)} rows\n{'='*60}")
    print(df.groupby("country").agg(rows=("content_id","count")).sort_values("rows",ascending=False).to_string())
    save()

if __name__ == "__main__":
    main()
