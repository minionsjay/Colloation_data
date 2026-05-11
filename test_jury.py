#!/usr/bin/env python3
"""Test the jury + arbiter pipeline with mock or real LLM calls.

Tests with sample content from each target language.
"""

import sys
sys.path.insert(0, ".")

from jury.prompt_builder import build_juror_prompt
from jury.executor import run_jury, JuryResult
from arbiter.voting import majority_vote, weighted_vote
from arbiter.llm_arbiter import call_arbiter
from pipeline.schema import JurorVerdict, ViolationCategory


# ── Sample content for each target language ───────────────────

SAMPLES = [
    {
        "country": "TH",
        "source": "pantip",
        "language": "th",
        "text": "พวกมึงแม่งโคตรงมงาย ไปตายซะไป พวกสันดานขี้ข้า",  # Toxic Thai: "You idiots are so stupid, go die, slave mentality"
    },
    {
        "country": "ID",
        "source": "kompasiana",
        "language": "id",
        "text": "Selamat pagi semuanya, hari ini saya akan berbagi resep nasi goreng yang enak dan mudah dibuat di rumah.",  # Benign Indonesian recipe
    },
    {
        "country": "TR",
        "source": "uludagsozluk",
        "language": "tr",
        "text": "Bugün hava gerçekten çok güzel, dışarı çıkıp yürüyüş yapmak istiyorum. Herkese iyi günler.",  # Benign Turkish
    },
    {
        "country": "BR",
        "source": "reddit",
        "language": "pt",
        "text": "Seu macaco, volta pra senzala seu preto nojento!",  # Racist Portuguese
    },
    {
        "country": "MX",
        "source": "reddit",
        "language": "es",
        "text": "Pinche indio de mierda, regrésate a tu pueblo, aquí no te queremos.",  # Racist Spanish
    },
    {
        "country": "SA",
        "source": "reddit",
        "language": "ar",
        "text": "مرحبا بالجميع، أريد أن أشارككم تجربتي في تعلم اللغة العربية، لقد كانت رحلة ممتعة ومفيدة.",  # Benign Arabic
    },
]


def test_prompts():
    """Verify prompt building works for all languages."""
    print("=" * 60)
    print("1. Prompt Building Test\n")

    for s in SAMPLES:
        prompts = build_juror_prompt(
            content=s["text"],
            source=s["source"],
            country=s["country"],
            language=s["language"],
        )
        for juror in ["A", "B", "C"]:
            sys_len = len(prompts[juror]["system"])
            user_len = len(prompts[juror]["user"])
            assert s["language"] in prompts[juror]["user"], f"Language not in prompt for {juror}"
        print(f"  ✓ {s['country']}/{s['language']}: all 3 prompts OK (A:{sys_len}c B:{prompts['B']['system'].count(' ')})")

    print("  ✓ All prompts built successfully")


def test_mock_verdicts():
    """Test voting and arbitration with mock verdicts."""
    print("\n" + "=" * 60)
    print("2. Voting & Arbitration Test\n")

    # Scenario 1: All three agree on violation
    print("  Scenario: All agree (violation)")
    verdicts_agree = [
        JurorVerdict(content_id="test1", juror="A", model_name="local", violation=True,
                     category=ViolationCategory.hate_speech, confidence=0.95,
                     reasoning="Clear hate speech with racial slurs.", language="pt"),
        JurorVerdict(content_id="test1", juror="B", model_name="qwen", violation=True,
                     category=ViolationCategory.hate_speech, confidence=0.90,
                     reasoning="Contains explicit racist language.", language="pt"),
        JurorVerdict(content_id="test1", juror="C", model_name="claude", violation=True,
                     category=ViolationCategory.hate_speech, confidence=0.92,
                     reasoning="Racist derogatory terms used against Black people.", language="pt"),
    ]
    result = majority_vote(verdicts_agree)
    assert result is not None, "Should reach consensus"
    assert result.final_verdict is True
    assert result.adopted_juror == "consensus"
    print(f"  ✓ Consensus: verdict={result.final_verdict}, adopted={result.adopted_juror}")

    # Scenario 2: Split 2:1
    print("  Scenario: Split 2:1")
    verdicts_split = [
        JurorVerdict(content_id="test2", juror="A", model_name="local", violation=True,
                     category=ViolationCategory.hate_speech, confidence=0.90,
                     reasoning="Local slur detected.", language="th"),
        JurorVerdict(content_id="test2", juror="B", model_name="qwen", violation=False,
                     category=ViolationCategory.none, confidence=0.60,
                     reasoning="Seems like casual speech, no violation.", language="th"),
        JurorVerdict(content_id="test2", juror="C", model_name="claude", violation=True,
                     category=ViolationCategory.hate_speech, confidence=0.85,
                     reasoning="Contains violent instructions and insults.", language="th"),
    ]
    result = majority_vote(verdicts_split)
    assert result is not None, "Should reach majority"
    assert result.final_verdict is True
    assert result.adopted_juror in ("A", "C", "majority")
    print(f"  ✓ Majority: verdict={result.final_verdict}, adopted={result.adopted_juror}")

    # Scenario 3: All disagree (three-way split)
    print("  Scenario: Three-way split")
    verdicts_split3 = [
        JurorVerdict(content_id="test3", juror="A", model_name="local", violation=True,
                     category=ViolationCategory.hate_speech, confidence=0.80,
                     reasoning="A thinks violation.", language="tr"),
        JurorVerdict(content_id="test3", juror="B", model_name="qwen", violation=False,
                     category=ViolationCategory.none, confidence=0.70,
                     reasoning="B thinks clean.", language="tr"),
        JurorVerdict(content_id="test3", juror="C", model_name="claude", violation=None,
                     category=ViolationCategory.none, confidence=0.0,
                     reasoning="C is uncertain.", language="tr"),
    ]
    result = majority_vote(verdicts_split3)
    assert result is None, "Three-way split should escalate to arbiter"
    print(f"  ✓ No consensus (escalate to LLM arbiter)")

    # Scenario 4: Weighted vote resolves a split
    print("  Scenario: Weighted vote")
    result = weighted_vote(verdicts_split, weights={"A": 1.5, "B": 1.0, "C": 1.2})
    assert result is not None
    assert result.final_verdict is True
    print(f"  ✓ Weighted: verdict={result.final_verdict}, confidence={result.confidence:.3f}")

    print("\n  ✓ All voting scenarios passed")


def test_jury_pipeline_dry_run():
    """Test the full pipeline with real jury calls if API keys are present."""
    print("\n" + "=" * 60)
    print("3. Full Jury Pipeline Dry-Run\n")

    import os
    has_api = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("TOGETHER_API_KEY"))

    if has_api:
        sample = SAMPLES[0]  # Thai toxic sample
        print(f"  Testing with: {sample['country']}/{sample['language']}")
        print(f"  Text: {sample['text'][:80]}...")

        result = run_jury(
            content_id="live-test-1",
            text=sample["text"],
            source=sample["source"],
            country=sample["country"],
            language=sample["language"],
            timeout=30.0,
        )
        print(f"  ✓ Jury completed in {result.total_latency_ms:.0f}ms")
        print(f"  Agreement: {result.agreement}")

        # Try voting
        vote = majority_vote(result.all_verdicts)
        if vote:
            print(f"  Vote: {vote.final_verdict} (adopted: {vote.adopted_juror})")
        else:
            print(f"  No consensus — needs arbiter")

        # Try LLM arbiter
        if os.getenv("ANTHROPIC_API_KEY"):
            print("  Calling LLM arbiter...")
            arb = call_arbiter(
                content_id="live-test-1",
                content=sample["text"],
                verdicts=result.all_verdicts,
                source=sample["source"],
                country=sample["country"],
                language=sample["language"],
            )
            print(f"  Arbiter: {arb.final_verdict} (adopted: {arb.adopted_juror})")
    else:
        print("  ⚠ No LLM API keys set. Skipping live test.")
        print("  Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or TOGETHER_API_KEY in .env")
        print("  to test with real LLM calls.")

        # Test that jury degrades gracefully without API keys
        sample = SAMPLES[0]
        result = run_jury(
            content_id="dry-run",
            text=sample["text"],
            source=sample["source"],
            country=sample["country"],
            language=sample["language"],
            timeout=5.0,
        )
        print(f"\n  Dry-run result: {result.agreement}")
        for v in result.all_verdicts:
            print(f"    Juror {v.juror}: violation={v.violation} — {v.reasoning[:100]}")

    print("\n  ✓ Pipeline test complete")


if __name__ == "__main__":
    test_prompts()
    test_mock_verdicts()
    test_jury_pipeline_dry_run()
    print("\n" + "=" * 60)
    print("All jury tests passed!")
