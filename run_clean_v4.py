"""Run the full cleaning pipeline across all v4 batch files."""

import glob
import os
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline.clean_v4 import clean_batch, DedupIndex

INPUT_DIR = "data/comments_batch"
OUTPUT_DIR = "data/cleaned_v4"
V4_PATTERN = "v4_batch_*.parquet"


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    files = sorted(glob.glob(os.path.join(INPUT_DIR, V4_PATTERN)))
    print(f"Found {len(files)} batch files")

    dedup = DedupIndex()
    all_results = []
    total_raw = 0
    total_kept = 0
    total_skipped = {"too_short": 0, "too_long": 0, "mostly_urls": 0, "duplicate": 0}

    t_start = time.time()

    for fi, fpath in enumerate(files):
        fname = os.path.basename(fpath)
        print(f"\n[{fi+1}/{len(files)}] {fname} ...", flush=True)

        df = pd.read_parquet(fpath)
        total_raw += len(df)
        print(f"  input: {len(df):,}", flush=True)

        t0 = time.time()
        result, skipped = clean_batch(df, dedup=dedup)
        dt = time.time() - t0

        for k in total_skipped:
            total_skipped[k] += skipped[k]
        total_kept += len(result)

        print(f"  kept: {len(result):,} | skipped: {skipped} | time: {dt:.1f}s | dedup index: {len(dedup):,}", flush=True)

        if len(result) > 0:
            all_results.append(result)

        # Save intermediate per-batch output
        out_path = os.path.join(OUTPUT_DIR, fname)
        result.to_parquet(out_path, index=False)

    elapsed = time.time() - t_start
    print(f"\n{'='*60}")
    print(f"TOTAL raw:     {total_raw:>10,}")
    print(f"TOTAL kept:    {total_kept:>10,}")
    print(f"  too_short:   {total_skipped['too_short']:>10,}")
    print(f"  too_long:    {total_skipped['too_long']:>10,}")
    print(f"  mostly_urls: {total_skipped['mostly_urls']:>10,}")
    print(f"  duplicate:   {total_skipped['duplicate']:>10,}")
    print(f"  dedup index: {len(dedup):>10,}")
    print(f"Elapsed: {elapsed/60:.1f} min")

    # Merge and save per-country
    print(f"\nSaving per-country files...")
    all_df = pd.concat(all_results, ignore_index=True)
    for country in sorted(all_df["country"].unique()):
        country_df = all_df[all_df["country"] == country]
        out_path = os.path.join(OUTPUT_DIR, f"{country}.parquet")
        country_df.to_parquet(out_path, index=False)
        print(f"  {country}: {len(country_df):,}")

    # Full merged
    full_path = os.path.join(OUTPUT_DIR, "all_cleaned.parquet")
    all_df.to_parquet(full_path, index=False)
    print(f"  all: {len(all_df):,} → {full_path}")


if __name__ == "__main__":
    main()
