# _build_trace가 그래프 결과 state에서 실행 흔적을 결정적으로 조립하는지 검증 (DB·LLM 불필요)
from langchain_core.messages import ToolMessage

from src.agent.nodes import _build_trace


def test_build_trace_assembles_from_state():
    state = {
        "resume_eval": {"skills": [{"skill": "Python", "evidence": "ev1", "source": "resume", "level_hint": "high"}]},
        "github_eval": {"skills": [{"skill": "Docker", "evidence": "ev2", "source": "github", "level_hint": None}]},
        "portfolio_eval": None,
        "deploy_eval": None,
        "consensus": {
            "Python": {"verification": "Verified", "evidences": [{"source": "github"}]},
            "SQL": {"verification": "Claimed", "evidences": [{"source": "resume"}]},
        },
        "messages": [
            ToolMessage(content="{}", name="gap_analysis", tool_call_id="1"),
            ToolMessage(content="{}", name="verify_skills", tool_call_id="2"),
        ],
        "iteration": 2,
        "critic_report": {"removed_claims": ["X"], "corrections": [{"skill": "Y"}]},
        "coaching_result": {"suggestions": [1, 2, 3]},
    }
    t = _build_trace(state)

    # 평가자: 스킬 목록까지
    assert t["evaluators"][0]["source"] == "resume"
    assert t["evaluators"][0]["skills"][0]["skill"] == "Python"
    assert t["evaluators"][0]["skills"][0]["evidence"] == "ev1"
    # 합의: counts + skills
    assert t["consensus"]["counts"] == {"Verified": 1, "Corroborated": 0, "Claimed": 1}
    assert any(s["skill"] == "Python" and s["verification"] == "Verified" for s in t["consensus"]["skills"])
    # gap 루프
    assert set(t["gap_loop"]["tool_calls"]) == {"gap_analysis", "verify_skills"}
    # critic: 항목까지
    assert t["critic"]["removed_skills"] == ["X"]
    assert t["critic"]["corrected"] == 1
    # 실행 노드
    assert "resume_eval" in t["executed_nodes"] and "github_eval" in t["executed_nodes"]
    assert "consensus" in t["executed_nodes"] and "critic" in t["executed_nodes"]
    assert t["coach"]["suggestion_count"] == 3


def test_build_trace_empty_state_safe():
    t = _build_trace({})
    assert t["evaluators"] == []
    assert t["consensus"]["counts"] == {"Verified": 0, "Corroborated": 0, "Claimed": 0}
    assert t["gap_loop"] == {"tool_calls": [], "iterations": 0}
    assert t["critic"]["removed_skills"] == []
    assert t["executed_nodes"] == ["synthesizer"]
    assert t["coach"]["suggestion_count"] == 0


def test_build_trace_prefers_passed_coaching():
    # finalize_coach는 막 만든 coaching을 직접 넘긴다 — state엔 아직 머지 전이라 비어 있음
    state = {"coaching_result": None}
    t = _build_trace(state, coaching={"suggestions": [1, 2]})
    assert t["coach"]["suggestion_count"] == 2
