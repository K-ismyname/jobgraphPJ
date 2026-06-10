# Planner의 결정적 골격(입력 조합별 step 포함 규칙)을 검증
from src.agent.planner import build_skeleton_plan


def _state(**kw):
    base = {
        "job_family": "AI/LLM Engineer", "owner": "김지원",
        "pdf_path": None, "resume_text": None, "github_url": None,
        "resume_skills": [], "critic_report": None,
    }
    base.update(kw)
    return base


def test_pdf_only_includes_profile():
    steps = build_skeleton_plan(_state(pdf_path="resume.pdf"))
    agents = [s["agent"] for s in steps]
    assert "profile" in agents
    assert "retrieval" in agents and "market" in agents and "gap" in agents


def test_injected_skills_skip_profile():
    steps = build_skeleton_plan(_state(resume_skills=["Python", "LangGraph"]))
    agents = [s["agent"] for s in steps]
    assert "profile" not in agents          # 스킬 주입 시 Profile 생략
    assert "retrieval" in agents and "gap" in agents


def test_replan_narrows_to_retrieval():
    # Critic이 재계획을 요구하면 근거 보강(retrieval)에 집중하는 계획
    state = _state(
        pdf_path="resume.pdf",
        critic_report={"needs_replan": True, "unsupported_claims": ["LangGraph 근거 약함"]},
    )
    steps = build_skeleton_plan(state)
    agents = [s["agent"] for s in steps]
    assert "retrieval" in agents and "gap" in agents
    assert "market" not in agents           # 재계획은 시장 재조사 생략
