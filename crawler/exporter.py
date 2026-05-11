"""Export crawled posts to the pipeline in Parquet format."""

from pathlib import Path

import pandas as pd

from crawler.base_spider import RawPost


def posts_to_dataframe(posts: list[RawPost]) -> pd.DataFrame:
    """Convert RawPost list to DataFrame for storage."""
    records = []
    for p in posts:
        rec = {
            "content_id": p.content_id,
            "source": p.source,
            "country": p.country,
            "url": p.url,
            "title": p.title,
            "body": p.body,
            "author_hash": p.author_hash,
            "created_at": p.created_at,
            "crawled_at": p.crawled_at,
        }
        # Flatten metadata into top-level columns with prefix
        for k, v in p.metadata.items():
            rec[f"meta_{k}"] = v
        records.append(rec)
    return pd.DataFrame(records)


def export_to_parquet(posts: list[RawPost], output_dir: Path) -> Path:
    """Save posts to a date-stamped Parquet file. Returns the file path."""
    df = posts_to_dataframe(posts)
    timestamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"raw_posts_{timestamp}.parquet"
    df.to_parquet(output_path, index=False)
    return output_path
