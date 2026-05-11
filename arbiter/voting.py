"""Stage 1 arbiter: rule-based voting over three juror verdicts.

Phase 1 of the arbitration strategy — no LLM required.
Used before we have enough labeled data for LLM arbitration.
"""

from pipeline.schema import JurorVerdict, FinalVerdict, ViolationCategory


def majority_vote(verdicts: list[JurorVerdict]) -> FinalVerdict | None:
    """Simple majority vote over 3 jurors.

    Returns None if no consensus can be reached (all 3 disagree or
    too many nulls).
    """
    if len(verdicts) != 3:
        return None

    violations = [v.violation for v in verdicts]

    yes = sum(1 for v in violations if v is True)
    no = sum(1 for v in violations if v is False)
    nulls = sum(1 for v in violations if v is None)

    # Too many nulls — can't decide
    if nulls >= 2:
        return None

    # 3-0 unanimous — high confidence
    if yes == 3:
        return _make_verdict(verdicts, True, "consensus", "All three jurors agree: violation.")
    if no == 3:
        return _make_verdict(verdicts, False, "consensus", "All three jurors agree: clean.")

    # 2-1 majority
    if yes == 2:
        # Find the dissenter
        winner = [v for v in verdicts if v.violation is True]
        return _make_verdict(
            verdicts,
            True,
            winner[0].juror if len(winner) == 1 else "majority",
            f"Majority (2:1) found violation. Adopting {' & '.join(v.juror for v in winner)}.",
        )
    if no == 2:
        winner = [v for v in verdicts if v.violation is False]
        return _make_verdict(
            verdicts,
            False,
            winner[0].juror if len(winner) == 1 else "majority",
            f"Majority (2:1) found no violation. Adopting {' & '.join(v.juror for v in winner)}.",
        )

    # 1-1-1 split (one yes, one no, one null or three-way)
    return None  # Requires LLM arbitration or human review


def weighted_vote(
    verdicts: list[JurorVerdict],
    weights: dict[str, float] | None = None,
) -> FinalVerdict | None:
    """Weighted vote with per-juror weights.

    Default weights if not specified:
        A (local specialist): 1.5 (high weight for local language)
        B (generalist): 1.0
        C (premium): 1.2
    """
    if weights is None:
        weights = {"A": 1.5, "B": 1.0, "C": 1.2}

    score = 0.0
    total_weight = 0.0
    max_score = 0.0
    voting_details: list[str] = []

    for v in verdicts:
        w = weights.get(v.juror, 1.0)
        if v.violation is True:
            score += w * v.confidence
            max_score += w * v.confidence
            voting_details.append(f"{v.juror}:violation({v.confidence:.2f}*{w})")
        elif v.violation is False:
            score -= w * v.confidence
            max_score += w * v.confidence
            voting_details.append(f"{v.juror}:clean({v.confidence:.2f}*{w})")
        else:
            voting_details.append(f"{v.juror}:null")

    if max_score == 0:
        return None

    # Confidence = ratio of net score to max possible score
    confidence = min(abs(score) / max_score, 1.0)

    if confidence < 0.5:
        return None  # Too uncertain, escalate

    final_violation = score > 0

    # Find best juror
    best = max(verdicts, key=lambda v: v.confidence if v.violation is not None else -1)

    return FinalVerdict(
        content_id=verdicts[0].content_id,
        final_verdict=final_violation,
        category=best.category if best.violation is not None else ViolationCategory.none,
        confidence=confidence,
        adopted_juror=best.juror,
        adopted_reason=f"Weighted vote: {', '.join(voting_details)}. Score={score:.3f}",
        juror_agreement=_agreement_str(verdicts),
        reasoning="Weighted voting (Stage 1).",
        judge_model="voting",
        requires_human_review=confidence < 0.7,
    )


def _make_verdict(
    verdicts: list[JurorVerdict],
    final_violation: bool,
    adopted: str,
    reason: str,
) -> FinalVerdict:
    # 从多数方选最高置信度的陪审员，取其类别
    majority = [v for v in verdicts if v.violation == final_violation]
    best = max(majority or [v for v in verdicts if v.violation is not None], key=lambda v: v.confidence)
    return FinalVerdict(
        content_id=verdicts[0].content_id,
        final_verdict=final_violation,
        category=best.category,
        confidence=best.confidence,
        adopted_juror=adopted,
        adopted_reason=reason,
        juror_agreement=_agreement_str(verdicts),
        reasoning="Majority voting (Stage 1).",
        judge_model="voting",
    )


def _agreement_str(verdicts: list[JurorVerdict]) -> str:
    parts = []
    for v in verdicts:
        val = "null" if v.violation is None else ("violation" if v.violation else "clean")
        parts.append(f"{v.juror}:{val}")
    return " / ".join(parts)
