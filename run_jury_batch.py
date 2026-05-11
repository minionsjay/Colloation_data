"""Batch jury runner — processes multiple items through the jury pipeline."""

import sys
import os
import time
import json
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from jury.executor import run_jury
from arbiter.voting import majority_vote
from arbiter.llm_arbiter import call_arbiter


def process_one(row, idx, total):
    """Process a single item: jury → vote → (arbiter if needed). Returns result dict."""
    content_id = row["content_id"]
    text = str(row["clean_text"] or "")
    source = str(row.get("source", "") or "")
    country = str(row.get("country", "") or "")
    language = str(row.get("language", "") or "")

    t0 = time.monotonic()

    # Step 1: Run 3 jurors in parallel
    jury_result = run_jury(
        content_id=content_id,
        text=text,
        source=source,
        country=country,
        language=language,
        juror_b_provider="custom",
        juror_c_provider="custom",
        timeout=60.0,
    )
    jury_latency = jury_result.total_latency_ms

    # Step 2: Try majority vote
    final = majority_vote(jury_result.all_verdicts)

    # Step 3: If disputed, call LLM arbiter
    arbiter_used = False
    if final is None:
        final = call_arbiter(
            content_id=content_id,
            content=text,
            verdicts=jury_result.all_verdicts,
            source=source,
            country=country,
            language=language,
            provider="custom",
            timeout=60.0,
        )
        arbiter_used = True

    total_latency = (time.monotonic() - t0) * 1000

    # Build output row
    return {
        "content_id": content_id,
        "country": country,
        "language": language,
        "source": source,
        "type": row.get("type", ""),
        "clean_text": text[:500],
        "juror_agreement": jury_result.agreement,
        "juror_a_violation": jury_result.verdict_a.violation,
        "juror_a_category": str(jury_result.verdict_a.category),
        "juror_a_confidence": jury_result.verdict_a.confidence,
        "juror_a_reasoning": jury_result.verdict_a.reasoning[:500],
        "juror_a_model": jury_result.verdict_a.model_name,
        "juror_b_violation": jury_result.verdict_b.violation,
        "juror_b_category": str(jury_result.verdict_b.category),
        "juror_b_confidence": jury_result.verdict_b.confidence,
        "juror_b_reasoning": jury_result.verdict_b.reasoning[:500],
        "juror_b_model": jury_result.verdict_b.model_name,
        "juror_c_violation": jury_result.verdict_c.violation,
        "juror_c_category": str(jury_result.verdict_c.category),
        "juror_c_confidence": jury_result.verdict_c.confidence,
        "juror_c_reasoning": jury_result.verdict_c.reasoning[:500],
        "juror_c_model": jury_result.verdict_c.model_name,
        "arbiter_used": arbiter_used,
        "final_verdict": final.final_verdict if final else None,
        "final_category": str(final.category) if final else "none",
        "final_confidence": final.confidence if final else 0.0,
        "adopted_juror": final.adopted_juror if final else "none",
        "judge_model": final.judge_model if final else "error",
        "requires_human_review": final.requires_human_review if final else True,
        "judge_reasoning": final.reasoning[:500] if final else "",
        "jury_latency_ms": round(jury_latency, 0),
        "total_latency_ms": round(total_latency, 0),
        "judged_at": datetime.now(timezone.utc).isoformat(),
    }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-country", type=int, default=50)
    parser.add_argument("--max-workers", type=int, default=3)
    parser.add_argument("--output", default="data/results/jury_batch.parquet")
    parser.add_argument("--input", default="data/cleaned_v4/all_cleaned.parquet")
    args = parser.parse_args()

    # Load cleaned data
    df = pd.read_parquet(args.input)
    print(f"Loaded {len(df):,} records from {args.input}")

    # Sample per country
    samples = []
    for country in sorted(df["country"].unique()):
        country_df = df[df["country"] == country]
        samp = country_df.sample(n=min(args.per_country, len(country_df)), random_state=42)
        samples.append(samp)
        print(f"  {country}: sampling {len(samp)} / {len(country_df)}")

    batch = pd.concat(samples).reset_index(drop=True)
    total = len(batch)
    print(f"Total: {total} items")
    print(f"Estimated time: ~{total * 10 / 60:.0f} min (sequential), ~{total * 10 / args.max_workers / 60:.0f} min (with {args.max_workers} workers)")

    # Process
    results = []
    t_start = time.time()
    completed = 0

    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        futures = {}
        for i, row in batch.iterrows():
            fut = pool.submit(process_one, row, completed, total)
            futures[fut] = (i, row["country"])

        for fut in as_completed(futures):
            idx = futures[fut][0]
            country = futures[fut][1]
            try:
                result = fut.result()
                results.append(result)
                completed += 1
                elapsed = time.time() - t_start
                rate = completed / elapsed if elapsed > 0 else 0
                eta = (total - completed) / rate if rate > 0 else 0
                print(f"  [{completed}/{total}] {country} | final={result['final_verdict']} conf={result['final_confidence']:.2f} | {result['juror_agreement']} | {result['total_latency_ms']:.0f}ms | ETA {eta/60:.0f}m")
            except Exception as e:
                idx = futures[fut][0]
                country = futures[fut][1]
                completed += 1
                print(f"  [{completed}/{total}] {country} | ERROR: {e}")

    elapsed = time.time() - t_start
    print(f"\nDone! {completed}/{total} in {elapsed/60:.1f} min ({completed/elapsed*60:.1f} items/min)")

    # Save results
    result_df = pd.DataFrame(results)
    result_df.to_parquet(args.output, index=False)
    print(f"Saved to {args.output}")

    # Summary stats
    if len(result_df) > 0:
        print(f"\n=== Summary ===")
        print(f"Total: {len(result_df)}")
        print(f"Violations: {result_df['final_verdict'].value_counts().to_dict()}")
        print(f"By country:")
        for country in sorted(result_df["country"].unique()):
            sub = result_df[result_df["country"] == country]
            viol = sub["final_verdict"].value_counts().to_dict()
            print(f"  {country}: {len(sub)} items | violations: {viol}")
        print(f"Arbiter used: {result_df['arbiter_used'].sum()} / {len(result_df)}")
        print(f"Requires human review: {result_df['requires_human_review'].sum()} / {len(result_df)}")


if __name__ == "__main__":
    main()
