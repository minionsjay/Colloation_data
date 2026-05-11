"""Read/write cleaned posts and judgments to/from Parquet files."""

from pathlib import Path

import pandas as pd

from pipeline.schema import CleanedPost, JurorVerdict, FinalVerdict
from config import settings


def _df_to_records(df: pd.DataFrame) -> list[dict]:
    """DataFrame rows to list of dicts, handling NaN → None."""
    return df.where(pd.notna(df), None).to_dict(orient="records")


# ── CleanedPost ──────────────────────────────────────────────────────

def write_cleaned_posts(posts: list[CleanedPost], path: Path | None = None):
    path = path or settings.clean_dir / f"cleaned_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.parquet"
    df = pd.DataFrame([p.__dict__ for p in posts])
    df.to_parquet(path, index=False)
    return path


def read_cleaned_posts(path: Path) -> list[CleanedPost]:
    df = pd.read_parquet(path)
    return [CleanedPost(**r) for r in _df_to_records(df)]


# ── JurorVerdict ─────────────────────────────────────────────────────

def write_juror_verdicts(verdicts: list[JurorVerdict], path: Path | None = None):
    path = path or settings.results_dir / f"juror_verdicts_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.parquet"
    df = pd.DataFrame([v.__dict__ for v in verdicts])
    df.to_parquet(path, index=False)
    return path


def read_juror_verdicts(path: Path) -> list[JurorVerdict]:
    df = pd.read_parquet(path)
    return [JurorVerdict(**r) for r in _df_to_records(df)]


# ── FinalVerdict ─────────────────────────────────────────────────────

def write_final_verdicts(verdicts: list[FinalVerdict], path: Path | None = None):
    path = path or settings.results_dir / f"final_verdicts_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.parquet"
    df = pd.DataFrame([v.__dict__ for v in verdicts])
    df.to_parquet(path, index=False)
    return path


def read_final_verdicts(path: Path) -> list[FinalVerdict]:
    df = pd.read_parquet(path)
    return [FinalVerdict(**r) for r in _df_to_records(df)]
