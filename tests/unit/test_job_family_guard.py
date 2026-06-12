# run_supervisor 직군 검증 — 유효하지 않은 직군이면 그래프 실행 없이 에러
from src.agent.supervisor import run_supervisor


class _FakeGraph:
    def __init__(self):
        self.invoked = False

    def invoke(self, *args, **kwargs):
        self.invoked = True
        return {"final_report": {"gap": {}}}


class _FakeNeo4j:
    def list_job_families(self):
        return ["AI/LLM Engineer", "Software Engineer"]


def test_invalid_job_family_blocks():
    g = _FakeGraph()
    out = run_supervisor(g, job_family="AI Engineer", owner="X",
                         resume_skills=["Python"], neo4j=_FakeNeo4j())
    assert out["error"] == "invalid_job_family"
    assert "Software Engineer" in out["message"]
    assert g.invoked is False


def test_valid_job_family_runs():
    g = _FakeGraph()
    run_supervisor(g, job_family="Software Engineer", owner="X",
                   resume_skills=["Python"], neo4j=_FakeNeo4j())
    assert g.invoked is True


def test_no_neo4j_skips_validation():
    # neo4j 미제공 시 검증 스킵 (gap_analysis 백스톱에 위임)
    g = _FakeGraph()
    run_supervisor(g, job_family="아무직군", owner="X", resume_skills=["Python"])
    assert g.invoked is True
