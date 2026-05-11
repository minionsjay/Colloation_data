"""Base spider interface. All spiders (Reddit, forum-specific) inherit from this."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Iterator
import uuid
import hashlib


@dataclass
class RawPost:
    """Unified data model for a crawled post, regardless of source."""

    source: str  # e.g. "reddit", "kaskus", "pantip"
    country: str  # ISO 3166-1 alpha-2
    url: str
    title: str
    body: str
    author_hash: str  # SHA256 of author name (privacy)
    created_at: datetime | None = None
    crawled_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    content_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    metadata: dict = field(default_factory=dict)  # source-specific extras

    @classmethod
    def hash_author(cls, author_name: str) -> str:
        return hashlib.sha256(author_name.encode()).hexdigest()[:16]


class BaseSpider(ABC):
    """Abstract spider. Subclass and implement scrape()."""

    def __init__(self, source: str, country: str, limit: int = 100):
        self.source = source
        self.country = country
        self.limit = limit

    @abstractmethod
    def scrape(self) -> Iterator[RawPost]:
        """Yield RawPost objects. Callers iterate to consume."""
        ...

    @property
    def name(self) -> str:
        return f"{self.source}_{self.country}"
