#!/usr/bin/env python3
"""Targeted crawl to boost local-language content in countries with low ratios.

Crawls only the most local-language-heavy subreddits with deep comments.
Merges into existing country data.
"""

import sys
import pandas as pd
from pathlib import Path
from datasketch import MinHash, MinHashLSH

from crawler.spiders.reddit_split_comments import RedditSplitSpider
from pipeline.cleaner import clean_post, quality_check
from pipeline.language_detector import annotate_language
from pipeline.storage import write_cleaned_posts

# Subreddits known to have high local-language content
LANG_BOOST_SUBS = {
    "ZA": ["afrikaans"],                    # Afrikaans
    "MX": ["espanolmexico"],                # Mexican Spanish
    "ID": ["indonesian"],                   # Bahasa Indonesia
    "TH": ["thaithai"],                     # Thai language
    "VN": ["TroChuyenLinhTinh"],            # Vietnamese
    "PH": ["ChikaPH"],                      # Tagalog-heavy
    "SA": ["Arabs"],                        # Arabic
    "AE": ["Emiratis"],                     # Emirati Arabic
    "TR": ["turkey"],                       # Turkish
}

EXISTING_FILES = {
    "ZA": "data/cleaned_v4/ZA.parquet",
    "MX": "data/cleaned_v4/MX.parquet",
    "ID": "data/cleaned_v4/ID.parquet",
    "TH": "data/cleaned_v4/TH.parquet",
    "VN": "data/cleaned_v4/VN.parquet",
    "PH": "data/cleaned_v4/PH.parquet",
    "SA": "data/cleaned_v4/SA.parquet",
    "AE": "data/clean/uae/cleaned_uae.parquet",
    "TR": "data/cleaned_v4/TR.parquet",
}


def boost_country(code: str, subs: list[str], pages: int = 15,
                  max_comments: int = 25, delay: float = 4.0):
    """Crawl language-specific subs and merge into existing data."""
    print(f"\n{'='*60}")
    print(f"Boosting {code}: {subs} — pages={pages}, comments≤{max_comments}")
    print(f"{'='*60}")

    # Crawl with top sort + deep comments
    spider = RedditSplitSpider(
        subreddits=subs, limit=25, max_comments=max_comments,
        sort="top", pages=pages, top_time="all",
        country=code, delay=delay,
    )
    raw = list(spider.scrape())
    spider.close()

    pc = sum(1 for p in raw if p.metadata.get("type") == "post")
    cc = sum(1 for p in raw if p.metadata.get("type") == "comment")
    print(f"  Raw: {len(raw):,} ({pc:,} posts + {cc:,} comments)")

    if len(raw) < 100:
        print(f"  ⚠ Too few results, trying hot sort...")
        spider2 = RedditSplitSpider(
            subreddits=subs, limit=25, max_comments=max_comments,
            sort="hot", pages=pages, country=code, delay=delay,
        )
        raw2 = list(spider2.scrape())
        spider2.close()
        raw += raw2
        print(f"  Raw (combined): {len(raw):,}")

    if not raw:
        print(f"  No data for {code}")
        return

    # Clean new posts
    cleaned_new = []
    for r in raw:
        post = clean_post(r)
        post = annotate_language(post)
        post.quality_flag = quality_check(post.clean_text, post.language_confidence)
        cleaned_new.append(post)

    # Load existing
    existing_path = EXISTING_FILES[code]
    existing = pd.read_parquet(existing_path)
    print(f"  Existing: {len(existing):,}")

    # Show existing language distribution
    old_langs = existing['language'].value_counts()
    old_local = sum(v for k, v in old_langs.items() if k != 'en')
    old_pct = old_local / len(existing) * 100
    print(f"  Old local lang ratio: {old_pct:.1f}%")

    # Dedup against existing
    lsh = MinHashLSH(threshold=0.8, num_perm=128)
    kept = []
    dupes = 0

    for idx, row in existing.iterrows():
        text = str(row.get('clean_text', ''))
        if len(text) >= 20:
            m = MinHash(num_perm=128)
            for i in range(len(text) - 2):
                m.update(text[i:i+3].encode('utf-8'))
            lsh.insert(f'e_{idx}', m)

    for idx, post in enumerate(cleaned_new):
        text = post.clean_text
        if len(text) >= 20:
            m = MinHash(num_perm=128)
            for i in range(len(text) - 2):
                m.update(text[i:i+3].encode('utf-8'))
            if lsh.query(m):
                dupes += 1
                continue
            lsh.insert(f'n_{idx}', m)
        if post.quality_flag == 'ok':
            kept.append(post)

    print(f"  New unique: {len(kept):,} (dupes: {dupes:,})")

    if not kept:
        print(f"  No new unique data for {code}")
        return

    # Language breakdown of new data
    new_langs = {}
    for p in kept:
        new_langs[p.language] = new_langs.get(p.language, 0) + 1
    new_local = sum(v for k, v in new_langs.items() if k != 'en')
    new_pct = new_local / len(kept) * 100 if kept else 0
    print(f"  New languages: {sorted(new_langs.items(), key=lambda x: -x[1])[:6]}")
    print(f"  New local lang ratio: {new_pct:.1f}%")

    # Merge
    clean_dir = Path(f'data/clean/{code.lower()}')
    clean_dir.mkdir(parents=True, exist_ok=True)
    new_path = write_cleaned_posts(kept, clean_dir / f'lang_boost.parquet')
    new_df = pd.read_parquet(new_path)
    # Fix type mismatches
    for col in existing.columns:
        if col in new_df.columns and existing[col].dtype != new_df[col].dtype:
            existing[col] = existing[col].astype(str)
            new_df[col] = new_df[col].astype(str)
    combined = pd.concat([existing, new_df], ignore_index=True)

    # Save
    out = Path(existing_path)
    combined.to_parquet(out, index=False)

    # New totals
    final_langs = combined['language'].value_counts()
    final_local = sum(v for k, v in final_langs.items() if k != 'en')
    final_pct = final_local / len(combined) * 100
    print(f"  FINAL: {len(combined):,} total, local lang ratio: {final_pct:.1f}% "
          f"(was {old_pct:.1f}%, +{final_pct - old_pct:.1f}%)")


def main():
    codes = sys.argv[1:] if len(sys.argv) > 1 else sorted(LANG_BOOST_SUBS.keys())
    for code in codes:
        if code not in LANG_BOOST_SUBS:
            print(f"Unknown: {code}")
            continue
        boost_country(code, LANG_BOOST_SUBS[code])


if __name__ == "__main__":
    main()
