# run_supervisor 입력 가드 — 소스 0개면 그래프 실행 없이 안내 반환
from src.agent.supervisor import run_supervisor


class _FakeGraph:
    """invoke 호출 여부를 기록하는 가짜 그래프."""

    def __init__(self) -> None:
        self.invoked = False

    def invoke(self, *args, **kwargs) -> dict:
        self.invoked = True
        return {"final_report": {"gap": {}}}


def test_no_input_returns_error_without_invoking():
    g = _FakeGraph()
    out = run_supervisor(g, job_family="AI Engineer", owner="김지원")
    assert out["error"] == "no_input"
    assert "message" in out
    assert g.invoked is False  # 그래프를 실행하지 않아야 함


def test_resume_skills_passes_guard():
    g = _FakeGraph()
    run_supervisor(g, job_family="AI Engineer", owner="김지원", resume_skills=["Python"])
    assert g.invoked is True


def test_github_only_passes_guard():
    g = _FakeGraph()
    run_supervisor(g, job_family="AI Engineer", owner="김지원", github_urls=["https://github.com/x"])
    assert g.invoked is True
