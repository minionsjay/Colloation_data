"""LangGraph-based jury + arbiter pipeline.

Replaces the manual ThreadPoolExecutor + if/else orchestration
with a proper graph: fan-out to 3 jurors, fan-in for voting,
conditional routing to LLM arbiter on split verdict.

Usage:
    from jury.graph import run_jury_graph

    final = run_jury_graph(
        content_id="post-001",
        text="พวกมึงแม่งโง่ ไปตายซะ",
        language="th",
    )
    print(final.final_verdict)  # True/False
"""

from __future__ import annotations

import operator
import time
from typing import Annotated, Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from arbiter.llm_arbiter import call_arbiter
from arbiter.voting import majority_vote
from jury.juror_a import call_juror_a
from jury.juror_b import call_juror_b
from jury.juror_c import call_juror_c
from jury.prompt_builder import build_juror_prompt
from pipeline.schema import FinalVerdict, JurorVerdict


# ── State ──────────────────────────────────────────────────────

class JuryGraphState(TypedDict):
    # ── Inputs ──
    content_id: str
    text: str
    source: str
    country: str
    language: str
    timeout: float

    # ── Juror configs ──
    juror_a_model: str
    juror_b_provider: str
    juror_b_model: str
    juror_b_base_url: str
    juror_b_api_key: str
    juror_b_no_proxy: bool
    juror_c_provider: str
    juror_c_model: str
    juror_c_base_url: str
    juror_c_api_key: str
    juror_c_no_proxy: bool

    # ── Arbiter configs ──
    arbiter_provider: str
    arbiter_model: str
    arbiter_base_url: str
    arbiter_api_key: str
    arbiter_no_proxy: bool

    # ── Runtime state (populated by nodes) ──
    prompts: dict[str, dict[str, str]]  # {"A": {"system":...,"user":...}, ...}
    started_at: float
    verdicts: Annotated[list[JurorVerdict], operator.add]  # reducer: merge parallel branches
    final_verdict: Optional[FinalVerdict]  # None = not decided yet


# ── Nodes ──────────────────────────────────────────────────────

def _build_prompts_node(state: JuryGraphState) -> dict:
    """Build system + user prompts for all three jurors."""
    prompts = build_juror_prompt(
        content=state["text"],
        source=state.get("source", ""),
        country=state.get("country", ""),
        language=state.get("language", ""),
    )
    return {"prompts": prompts, "started_at": time.monotonic()}


def _call_juror_node(state: JuryGraphState) -> dict:
    """Single node dispatched by juror_key — called 3× in parallel via Send."""
    key = state.get("juror_key", "")
    content_id = state["content_id"]
    language = state.get("language", "")
    system_prompt = state.get("system_prompt", "")
    user_prompt = state.get("user_prompt", "")
    timeout = state.get("timeout", 30.0)

    if key == "A":
        verdict = call_juror_a(
            content_id=content_id,
            language=language,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_name=state.get("model_name", "local-specialist"),
            timeout=timeout,
        )
    elif key == "B":
        verdict = call_juror_b(
            content_id=content_id,
            language=language,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            provider=state.get("provider", "together"),
            model_name=state.get("model_name", ""),
            base_url=state.get("base_url", ""),
            api_key=state.get("api_key", ""),
            no_proxy=state.get("no_proxy", False),
            timeout=timeout,
        )
    elif key == "C":
        verdict = call_juror_c(
            content_id=content_id,
            language=language,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            provider=state.get("provider", "anthropic"),
            model_name=state.get("model_name", ""),
            base_url=state.get("base_url", ""),
            api_key=state.get("api_key", ""),
            no_proxy=state.get("no_proxy", False),
            timeout=timeout,
        )
    else:
        return {"verdicts": []}

    return {"verdicts": [verdict]}


def _check_verdicts_node(state: JuryGraphState) -> dict:
    """Convergence point: all 3 verdicts collected. Try majority vote."""
    verdicts = state.get("verdicts", [])
    result = majority_vote(verdicts)
    if result is not None:
        return {"final_verdict": result}
    return {}  # disputed — final_verdict stays None, routes to arbiter


def _llm_arbitrate_node(state: JuryGraphState) -> dict:
    """LLM judge reviews juror reasoning and makes final decision."""
    verdicts = state.get("verdicts", [])
    result = call_arbiter(
        content_id=state["content_id"],
        content=state["text"],
        verdicts=verdicts,
        source=state.get("source", ""),
        country=state.get("country", ""),
        language=state.get("language", ""),
        provider=state.get("arbiter_provider", "anthropic"),
        model=state.get("arbiter_model", ""),
        base_url=state.get("arbiter_base_url", ""),
        api_key=state.get("arbiter_api_key", ""),
        no_proxy=state.get("arbiter_no_proxy", False),
        timeout=state.get("timeout", 60.0),
    )
    return {"final_verdict": result}


# ── Routing ────────────────────────────────────────────────────

def _fan_out_to_jurors(state: JuryGraphState) -> list[Send]:
    """Build 3 Send commands for parallel juror execution."""
    prompts = state["prompts"]
    lid = state["content_id"]
    lang = state.get("language", "")
    timeout = state.get("timeout", 45.0)

    return [
        Send("call_juror", {
            "juror_key": "A",
            "content_id": lid,
            "language": lang,
            "system_prompt": prompts["A"]["system"],
            "user_prompt": prompts["A"]["user"],
            "model_name": state.get("juror_a_model", "local-specialist"),
            "timeout": timeout,
        }),
        Send("call_juror", {
            "juror_key": "B",
            "content_id": lid,
            "language": lang,
            "system_prompt": prompts["B"]["system"],
            "user_prompt": prompts["B"]["user"],
            "provider": state.get("juror_b_provider", "together"),
            "model_name": state.get("juror_b_model", ""),
            "base_url": state.get("juror_b_base_url", ""),
            "api_key": state.get("juror_b_api_key", ""),
            "no_proxy": state.get("juror_b_no_proxy", False),
            "timeout": timeout,
        }),
        Send("call_juror", {
            "juror_key": "C",
            "content_id": lid,
            "language": lang,
            "system_prompt": prompts["C"]["system"],
            "user_prompt": prompts["C"]["user"],
            "provider": state.get("juror_c_provider", "anthropic"),
            "model_name": state.get("juror_c_model", ""),
            "base_url": state.get("juror_c_base_url", ""),
            "api_key": state.get("juror_c_api_key", ""),
            "no_proxy": state.get("juror_c_no_proxy", False),
            "timeout": timeout,
        }),
    ]


def _route_after_vote(state: JuryGraphState) -> str:
    """Decide: consensus → END, disputed → LLM arbiter."""
    if state.get("final_verdict") is not None:
        return "done"
    return "arbitrate"


# ── Graph builder ──────────────────────────────────────────────

def _build_graph() -> StateGraph:
    """Construct and compile the jury + arbiter StateGraph."""
    graph = StateGraph(JuryGraphState)

    graph.add_node("build_prompts", _build_prompts_node)
    graph.add_node("call_juror", _call_juror_node)
    graph.add_node("check_verdicts", _check_verdicts_node)
    graph.add_node("llm_arbitrate", _llm_arbitrate_node)

    graph.add_edge(START, "build_prompts")
    # build_prompts → fan-out to 3 parallel juror calls
    graph.add_conditional_edges("build_prompts", _fan_out_to_jurors)
    # All 3 converge here
    graph.add_edge("call_juror", "check_verdicts")
    # check_verdicts → END (consensus) or llm_arbitrate (disputed)
    graph.add_conditional_edges("check_verdicts", _route_after_vote, {
        "done": END,
        "arbitrate": "llm_arbitrate",
    })
    graph.add_edge("llm_arbitrate", END)

    return graph.compile()


# Lazy-compiled singleton — built on first invocation so that
# @patch in tests captures function references correctly.
_graph: Optional[Any] = None


# ── Public API ─────────────────────────────────────────────────

def run_jury_graph(
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
    juror_c_provider: str = "anthropic",
    juror_c_model: str = "",
    juror_c_base_url: str = "",
    juror_c_api_key: str = "",
    juror_c_no_proxy: bool = False,
    arbiter_provider: str = "custom",
    arbiter_model: str = "",
    arbiter_base_url: str = "",
    arbiter_api_key: str = "",
    arbiter_no_proxy: bool = False,
    timeout: float = 45.0,
) -> FinalVerdict:
    """Run the full jury + arbiter pipeline as a LangGraph graph.

    Three jurors (A: local, B: open-source, C: premium) are called
    in parallel, then majority voting decides. If the vote is split
    (no consensus), the LLM arbiter makes the final call.

    Returns a FinalVerdict — either from the voting stage (consensus
    case) or from the LLM arbiter (disputed case). On failure, the
    verdict will have requires_human_review=True.
    """
    global _graph
    if _graph is None:
        _graph = _build_graph()

    initial_state: JuryGraphState = {
        "content_id": content_id,
        "text": text,
        "source": source,
        "country": country,
        "language": language,
        "timeout": timeout,
        "juror_a_model": juror_a_model,
        "juror_b_provider": juror_b_provider,
        "juror_b_model": juror_b_model,
        "juror_b_base_url": juror_b_base_url,
        "juror_b_api_key": juror_b_api_key,
        "juror_b_no_proxy": juror_b_no_proxy,
        "juror_c_provider": juror_c_provider,
        "juror_c_model": juror_c_model,
        "juror_c_base_url": juror_c_base_url,
        "juror_c_api_key": juror_c_api_key,
        "juror_c_no_proxy": juror_c_no_proxy,
        "arbiter_provider": arbiter_provider,
        "arbiter_model": arbiter_model,
        "arbiter_base_url": arbiter_base_url,
        "arbiter_api_key": arbiter_api_key,
        "arbiter_no_proxy": arbiter_no_proxy,
        "prompts": {},
        "started_at": 0.0,
        "verdicts": [],
        "final_verdict": None,
    }

    result = _graph.invoke(initial_state)
    return result["final_verdict"]
