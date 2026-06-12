# finalize_coach가 consensus 기반 검증 요약을 final_report에 surface하는지 검증
import os

import pytest
from langchain_core.messages import AIMessage

from src.agent.nodes import create_coach_nodes

requires_key = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"), reason="create_coach_nodes가 OPENAI_API_KEY를 요구"
)


@requires_key
def test_verification_summary_surfaced_to_report():
    """consensus가 final_report.verification에 검증 요약으로 노출된다 (죽은 github 필드 대체)."""
    _, finalize = create_coach_nodes([])
    out = finalize({
        "coach_messages": [AIMessage(content='{"summary":"x","suggestions":[]}')],
        "gap_result": {"match_rate": 0.5},
        "consensus": {
            "React": {"verification": "Verified", "evidences": [{"source": "github"}]},
            "Docker": {"verification": "Claimed", "evidences": [{"source": "resume"}]},
        },
    })
    fr = out["final_report"]
    assert "github" not in fr            # 죽은 v1 필드 제거됨
    assert fr["verification"]["counts"] == {"Verified": 1, "Corroborated": 0, "Claimed": 1}
    assert fr["verification"]["skills"][0]["skill"] == "React"   # Verified 우선 정렬
    assert fr["gap"] == {"match_rate": 0.5} and "coaching" in fr


@requires_key
def test_empty_consensus_summary():
    """consensus 없으면 빈 검증 요약."""
    _, finalize = create_coach_nodes([])
    out = finalize({
        "coach_messages": [AIMessage(content="{}")],
        "gap_result": {},
    })
    summary = out["final_report"]["verification"]
    assert summary["counts"] == {"Verified": 0, "Corroborated": 0, "Claimed": 0}
    assert summary["skills"] == []
