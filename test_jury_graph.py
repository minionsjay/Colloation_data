#!/usr/bin/env python3
"""Test the LangGraph jury + arbiter pipeline with mocked jurors.

No API keys needed — all LLM calls are mocked.
"""

import sys
from unittest.mock import patch

sys.path.insert(0, ".")

from pipeline.schema import FinalVerdict, JurorVerdict, ViolationCategory
from jury.graph import run_jury_graph

# ── Shared mock verdicts ───────────────────────────────────────

VERDICT_VIOLATION_A = JurorVerdict(
    content_id="t", juror="A", model_name="local",
    violation=True, category=ViolationCategory.hate_speech,
    confidence=0.95, reasoning="A found hate speech.", language="th",
)
VERDICT_VIOLATION_B = JurorVerdict(
    content_id="t", juror="B", model_name="qwen",
    violation=True, category=ViolationCategory.hate_speech,
    confidence=0.90, reasoning="B found hate speech.", language="th",
)
VERDICT_VIOLATION_C = JurorVerdict(
    content_id="t", juror="C", model_name="claude",
    violation=True, category=ViolationCategory.hate_speech,
    confidence=0.92, reasoning="C found hate speech.", language="th",
)

VERDICT_CLEAN_A = JurorVerdict(
    content_id="t", juror="A", model_name="local",
    violation=False, category=ViolationCategory.none,
    confidence=0.90, reasoning="A says clean.", language="id",
)
VERDICT_CLEAN_B = JurorVerdict(
    content_id="t", juror="B", model_name="qwen",
    violation=False, category=ViolationCategory.none,
    confidence=0.85, reasoning="B says clean.", language="id",
)
VERDICT_CLEAN_C = JurorVerdict(
    content_id="t", juror="C", model_name="claude",
    violation=False, category=ViolationCategory.none,
    confidence=0.88, reasoning="C says clean.", language="id",
)

VERDICT_NULL_A = JurorVerdict(
    content_id="t", juror="A", model_name="local",
    violation=None, reasoning="A could not judge.", language="tr",
)
VERDICT_NULL_B = JurorVerdict(
    content_id="t", juror="B", model_name="qwen",
    violation=None, reasoning="B API error.", language="tr",
)
VERDICT_NULL_C = JurorVerdict(
    content_id="t", juror="C", model_name="claude",
    violation=None, reasoning="C could not judge.", language="tr",
)

MOCK_ARBITER_RESULT = FinalVerdict(
    content_id="t", final_verdict=True,
    category=ViolationCategory.hate_speech, confidence=0.85,
    adopted_juror="A", adopted_reason="A had best reasoning.",
    juror_agreement="A:violation / B:clean / C:null",
    reasoning="Arbiter determined violation.", judge_model="claude",
    requires_human_review=False,
)

MOCK_ARBITER_FALLBACK = FinalVerdict(
    content_id="t", final_verdict=False,
    category=ViolationCategory.none, confidence=0.0,
    adopted_juror="none", adopted_reason="All jurors failed.",
    juror_agreement="A:null / B:null / C:null",
    reasoning="Arbiter could not determine.", judge_model="fallback",
    requires_human_review=True,
)


# ── Test cases ─────────────────────────────────────────────────

def test_all_agree_violation():
    """3-0 unanimous violation → consensus, no arbiter called."""
    with (
        patch("jury.graph.call_juror_a", return_value=VERDICT_VIOLATION_A),
        patch("jury.graph.call_juror_b", return_value=VERDICT_VIOLATION_B),
        patch("jury.graph.call_juror_c", return_value=VERDICT_VIOLATION_C),
        patch("jury.graph.call_arbiter") as mock_arb,
    ):
        result = run_jury_graph(content_id="t1", text="x", language="th")

    assert isinstance(result, FinalVerdict)
    assert result.final_verdict is True
    assert result.adopted_juror == "consensus"
    mock_arb.assert_not_called()  # no arbiter needed
    print("✓ All agree (violation)")


def test_all_agree_clean():
    """3-0 unanimous clean → consensus."""
    with (
        patch("jury.graph.call_juror_a", return_value=VERDICT_CLEAN_A),
        patch("jury.graph.call_juror_b", return_value=VERDICT_CLEAN_B),
        patch("jury.graph.call_juror_c", return_value=VERDICT_CLEAN_C),
    ):
        result = run_jury_graph(content_id="t2", text="x", language="id")

    assert isinstance(result, FinalVerdict)
    assert result.final_verdict is False
    assert result.adopted_juror == "consensus"
    print("✓ All agree (clean)")


def test_majority_2_1():
    """2:1 split (A+C=violation, B=clean) → majority resolves."""
    with (
        patch("jury.graph.call_juror_a", return_value=VERDICT_VIOLATION_A),
        patch("jury.graph.call_juror_b", return_value=VERDICT_CLEAN_B),
        patch("jury.graph.call_juror_c", return_value=VERDICT_VIOLATION_C),
        patch("jury.graph.call_arbiter") as mock_arb,
    ):
        result = run_jury_graph(content_id="t3", text="x", language="th")

    assert isinstance(result, FinalVerdict)
    assert result.final_verdict is True
    mock_arb.assert_not_called()
    print("✓ Majority 2:1")


def test_three_way_split_calls_arbiter():
    """A=violation, B=clean, C=null → no consensus → arbiter called."""
    with (
        patch("jury.graph.call_juror_a", return_value=VERDICT_VIOLATION_A),
        patch("jury.graph.call_juror_b", return_value=VERDICT_CLEAN_B),
        patch("jury.graph.call_juror_c", return_value=VERDICT_NULL_C),
        patch("jury.graph.call_arbiter", return_value=MOCK_ARBITER_RESULT) as mock_arb,
    ):
        result = run_jury_graph(content_id="t4", text="x", language="th")

    assert isinstance(result, FinalVerdict)
    assert result.final_verdict is True
    assert result.adopted_juror == "A"
    mock_arb.assert_called_once()
    print("✓ Three-way split → arbiter")


def test_all_fail_requires_human_review():
    """All 3 verdicts null → arbiter fallback → human review."""
    with (
        patch("jury.graph.call_juror_a", return_value=VERDICT_NULL_A),
        patch("jury.graph.call_juror_b", return_value=VERDICT_NULL_B),
        patch("jury.graph.call_juror_c", return_value=VERDICT_NULL_C),
        patch("jury.graph.call_arbiter", return_value=MOCK_ARBITER_FALLBACK) as mock_arb,
    ):
        result = run_jury_graph(content_id="t5", text="x", language="ar")

    assert isinstance(result, FinalVerdict)
    assert result.requires_human_review is True
    mock_arb.assert_called_once()
    print("✓ All fail → human review")


def test_with_real_prompts():
    """Verify prompt building works with real text through the graph."""
    with (
        patch("jury.graph.call_juror_a", return_value=VERDICT_CLEAN_A),
        patch("jury.graph.call_juror_b", return_value=VERDICT_CLEAN_B),
        patch("jury.graph.call_juror_c", return_value=VERDICT_CLEAN_C),
        patch("jury.graph.call_arbiter") as mock_arb,
    ):
        result = run_jury_graph(
            content_id="t6",
            text="วันนี้อากาศดีมากเลยครับ",
            source="pantip",
            country="TH",
            language="th",
        )

    assert isinstance(result, FinalVerdict)
    assert result.final_verdict is False  # clean
    mock_arb.assert_not_called()
    print("✓ Real Thai text → clean consensus")


# ── Main ───────────────────────────────────────────────────────

if __name__ == "__main__":
    print("LangGraph Jury + Arbiter Tests")
    print("=" * 50)
    test_all_agree_violation()
    test_all_agree_clean()
    test_majority_2_1()
    test_three_way_split_calls_arbiter()
    test_all_fail_requires_human_review()
    test_with_real_prompts()
    print("=" * 50)
    print("All 6 tests passed!")
