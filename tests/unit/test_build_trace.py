# _build_trace가 그래프 결과 state에서 실행 흔적을 결정적으로 조립하는지 검증 (DB·LLM 불필요)
from langchain_core.messages import ToolMessage

from src.agent.nodes import _build_trace


def test_build_trace_assembles_from_state():
    state = {
        "resume_eval": {"skills": ["Python", "SQL"]},
        "github_eval": {"skills": ["Docker"]},
        "portfolio_eval": None,
        "deploy_eval": None,
        "consensus": {
            "Python": {"verification": "Verified", "evidences": [{"source": "github"}]},
            "SQL": {"verification": "Claimed", "evidences": [{"source": "resume"}]},
        },
        "messages": [
            ToolMessage(content="{}", name="gap_analysis", tool_call_id="1"),
            ToolMessage(content="{}", name="verify_skills", tool_call_id="2"),
            ToolMessage(content="{}", name="verify_skills", tool_call_id="3"),
        ],
        "iteration": 2,
        "critic_report": {"removed_claims": ["X"], "corrections": [{"skill": "Y"}]},
        "coaching_result": {"suggestions": [1, 2, 3]},
    }
    t = _build_trace(state)

    assert [e["source"] for e in t["evaluators"]] == ["resume", "github"]
    assert t["evaluators"][0]["skill_count"] == 2
    assert t["consensus"] == {"Verified": 1, "Corroborated": 0, "Claimed": 1}
    assert set(t["gap_loop"]["tool_calls"]) == {"gap_analysis", "verify_skills"}  # 중복 제거
    assert t["gap_loop"]["iterations"] == 2
    assert t["critic"] == {"removed": 1, "corrected": 1}
    assert t["coach"]["suggestion_count"] == 3


def test_build_trace_empty_state_safe():
    t = _build_trace({})
    assert t["evaluators"] == []
    assert t["consensus"] == {"Verified": 0, "Corroborated": 0, "Claimed": 0}
    assert t["gap_loop"] == {"tool_calls": [], "iterations": 0}
    assert t["critic"] == {"removed": 0, "corrected": 0}
    assert t["coach"]["suggestion_count"] == 0
