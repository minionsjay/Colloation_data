"""Simple scheduler for periodic crawling.

Tracks last crawl time per source+country and triggers new crawls
when the configured interval has elapsed.
"""

import json
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

from config import settings


@dataclass
class CrawlJob:
    source: str  # "reddit", "kaskus", etc.
    country: str  # "ID", "TH", etc.
    interval_hours: int = 6
    last_crawl: str = ""  # ISO timestamp


class CrawlScheduler:
    """File-backed crawl scheduler. State persists across restarts."""

    def __init__(self, state_path: Path | None = None):
        self.state_path = state_path or settings.data_dir / "crawl_state.json"
        self.jobs: dict[str, CrawlJob] = {}
        self._load()

    def _load(self):
        if self.state_path.exists():
            data = json.loads(self.state_path.read_text())
            for key, v in data.items():
                self.jobs[key] = CrawlJob(**v)

    def _save(self):
        self.state_path.write_text(
            json.dumps({k: asdict(v) for k, v in self.jobs.items()}, indent=2)
        )

    def add_job(self, source: str, country: str, interval_hours: int = 6):
        key = f"{source}_{country}"
        if key not in self.jobs:
            self.jobs[key] = CrawlJob(
                source=source, country=country, interval_hours=interval_hours
            )
            self._save()

    def should_crawl(self, source: str, country: str) -> bool:
        key = f"{source}_{country}"
        job = self.jobs.get(key)
        if job is None:
            return True  # never crawled
        if not job.last_crawl:
            return True
        last = datetime.fromisoformat(job.last_crawl)
        elapsed = (datetime.now(timezone.utc) - last).total_seconds() / 3600
        return elapsed >= job.interval_hours

    def mark_crawled(self, source: str, country: str):
        key = f"{source}_{country}"
        if key not in self.jobs:
            return
        self.jobs[key].last_crawl = datetime.now(timezone.utc).isoformat()
        self._save()

    def due_jobs(self) -> list[str]:
        """Return keys of all jobs due for crawling."""
        return [k for k, j in self.jobs.items() if self.should_crawl(j.source, j.country)]
