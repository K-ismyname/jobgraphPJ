# finalize_coach가 GitHub 보강 결과(profile_result.github_changes)를 final_report에 surface하는지 검증
import os

import pytest
from langchain_core.messages import AIMessage

from src.agent.nodes import create_coach_nodes

requires_key = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"), reason="create_coach_nodes가 OPENAI_API_KEY를 요구"
)


@requires_key
def test_github_changes_surfaced_to_report():
    """profile_result.github_changes가 있으면 final_report.github에 노출된다."""
    _, finalize = create_coach_nodes([])
    out = finalize({
        "coach_messages": [AIMessage(content='{"summary":"x","suggestions":[]}')],
        "gap_result": {"match_rate": 0.5},
        "profile_result": {"github_changes": {"LangChain": "medium→high"}},
    })
    assert out["final_report"]["github"] == {"changes": {"LangChain": "medium→high"}}


@requires_key
def test_no_github_changes_is_none():
    """GitHub 변경이 없으면 final_report.github는 None이다."""
    _, finalize = create_coach_nodes([])
    out = finalize({
        "coach_messages": [AIMessage(content="{}")],
        "gap_result": {},
        "profile_result": {"github_changes": {}},
    })
    assert out["final_report"]["github"] is None
