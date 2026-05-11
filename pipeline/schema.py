"""Data models for the pipeline — cleaned post and final judgment record."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class ViolationCategory(str, Enum):
    hate_speech = "hate_speech"
    violence = "violence"
    adult = "adult"
    fraud = "fraud"
    illegal = "illegal"
    political = "political"
    none = "none"


@dataclass
class CleanedPost:
    """A post after cleaning, language detection, and dedup."""

    content_id: str
    source: str
    country: str
    url: str
    title: str
    body: str
    clean_text: str  # HTML removed, normalized
    language: str  # ISO 639-1 code, auto-detected
    language_confidence: float
    author_hash: str
    created_at: Optional[datetime] = None
    cleaned_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_duplicate: bool = False
    quality_flag: str = "ok"  # "ok", "too_short", "too_long", "low_conf_lang"


@dataclass
class JurorVerdict:
    """A single juror's judgment."""

    content_id: str
    juror: str  # "A", "B", "C"
    model_name: str
    violation: Optional[bool]  # None = unable to judge
    category: ViolationCategory = ViolationCategory.none
    confidence: float = 0.0
    reasoning: str = ""
    language: str = ""
    latency_ms: float = 0.0
    tokens_used: int = 0
    judged_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class FinalVerdict:
    """Arbiter's final judgment after reviewing all jurors."""

    content_id: str
    final_verdict: bool
    category: ViolationCategory
    confidence: float
    adopted_juror: str  # "A", "B", "C", "consensus", "none"
    adopted_reason: str
    juror_agreement: str  # e.g. "A:violation / B:clean / C:violation"
    reasoning: str
    judge_model: str
    judged_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    requires_human_review: bool = False
