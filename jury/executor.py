"""Jury executor: runs all three jurors in parallel for one content item."""

import concurrent.futures
import time
from dataclasses import dataclass

from pipeline.schema import JurorVerdict
from jury.prompt_builder import build_juror_prompt
from jury.juror_a import call_juror_a
from jury.juror_b import call_juror_b
from jury.juror_c import call_juror_c


@dataclass
class JuryResult:
    """Verdicts from all three jurors for one piece of content."""

    content_id: str
    verdict_a: JurorVerdict
    verdict_b: JurorVerdict
    verdict_c: JurorVerdict
    total_latency_ms: float

    @property
    def all_verdicts(self) -> list[JurorVerdict]:
        return [self.verdict_a, self.verdict_b, self.verdict_c]

    @property
    def agreement(self) -> str:
        """Human-readable agreement string, e.g. 'A:violation / B:clean / C:violation'."""
        parts = []
        for v in self.all_verdicts:
            val = "null" if v.violation is None else ("violation" if v.violation else "clean")
            parts.append(f"{v.juror}:{val}")
        return " / ".join(parts)


def run_jury(
    content_id: str,
    text: str,
    source: str = "",
    country: str = "",
    language: str = "",
    juror_a_model: str = "local-specialist",
    juror_b_provider: str = "custom",
    juror_b_model: str = "",
    juror_b_base_url: str = "",
    juror_b_api_key: str = "",
    juror_b_no_proxy: bool = False,
    juror_c_provider: str = "custom",
    juror_c_model: str = "",
    juror_c_base_url: str = "",
    juror_c_api_key: str = "",
    juror_c_no_proxy: bool = False,
    timeout: float = 45.0,
) -> JuryResult:
    """Run all three jurors in parallel on a single piece of content.

    Each juror is called in a separate thread. If a juror fails or times
    out, its verdict will have violation=None with error reasoning.

    Args:
        content_id: Unique ID for the content
        text: The content text to judge
        source: Source platform name
        country: ISO country code
        language: Detected language code
        juror_a_model: Model name for local juror A
        juror_b_provider: Provider for juror B (together/groq/fireworks/custom)
        juror_b_model: Override model for juror B
        juror_b_base_url: Custom API endpoint for juror B
        juror_b_api_key: Custom API key for juror B
        juror_c_provider: Provider for juror C (anthropic/gemini/openai/custom)
        juror_c_model: Override model for juror C
        juror_c_base_url: Custom API endpoint for juror C
        juror_c_api_key: Custom API key for juror C
        timeout: Max seconds per juror

    Returns a JuryResult with all three verdicts.
    """
    prompts = build_juror_prompt(
        content=text,
        source=source,
        country=country,
        language=language,
    )

    t0 = time.monotonic()

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        future_a = pool.submit(
            call_juror_a,
            content_id=content_id,
            language=language,
            system_prompt=prompts["A"]["system"],
            user_prompt=prompts["A"]["user"],
            model_name=juror_a_model,
            timeout=timeout,
        )
        future_b = pool.submit(
            call_juror_b,
            content_id=content_id,
            language=language,
            system_prompt=prompts["B"]["system"],
            user_prompt=prompts["B"]["user"],
            provider=juror_b_provider,
            model_name=juror_b_model,
            base_url=juror_b_base_url,
            api_key=juror_b_api_key,
            no_proxy=juror_b_no_proxy,
            timeout=timeout,
        )
        future_c = pool.submit(
            call_juror_c,
            content_id=content_id,
            language=language,
            system_prompt=prompts["C"]["system"],
            user_prompt=prompts["C"]["user"],
            provider=juror_c_provider,
            model_name=juror_c_model,
            base_url=juror_c_base_url,
            api_key=juror_c_api_key,
            no_proxy=juror_c_no_proxy,
            timeout=timeout,
        )

        verdict_a = future_a.result(timeout=timeout + 5)
        verdict_b = future_b.result(timeout=timeout + 5)
        verdict_c = future_c.result(timeout=timeout + 5)

    total_ms = (time.monotonic() - t0) * 1000
    return JuryResult(
        content_id=content_id,
        verdict_a=verdict_a,
        verdict_b=verdict_b,
        verdict_c=verdict_c,
        total_latency_ms=total_ms,
    )
