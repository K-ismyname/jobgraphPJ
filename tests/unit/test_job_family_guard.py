# run_supervisor 직군 검증 — 유효하지 않은 직군이면 그래프 실행 없이 에러
from src.agent.supervisor import run_supervisor


class _FakeGraph:
    def __init__(self):
        self.invoked = False

    def invoke(self, *args, **kwargs):
        self.invoked = True
        return {"final_report": {"gap": {}}}

    def stream(self, *args, **kwargs):
        self.invoked = True
        return iter([{"synthesizer": {"final_report": {"gap": {}}}}])


class _FakeNeo4j:
    def list_job_families(self):
        return ["AI/LLM Engineer", "Software Engineer"]

    def execute_query(self, query: str, **kwargs):
        return []

    def recommend_job_postings(self, skills: list, job_family: str | None = None, top_n: int = 5) -> list:
        return []

    def get_common_skills(self, threshold: int = 5, n: int = 10) -> list:
        return []


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


def test_llm_capacity_error_returns_partial_report():
    class GraphWithLlmFailure:
        def stream(self, *args, **kwargs):
            yield {
                "github_eval": {
                    "github_eval": {
                        "skills": [{"skill": "Python", "source": "github", "strength": "code"}],
                        "project_contexts": [{
                            "repo": "me/app",
                            "readme_summary": "README 기반 분석 서비스",
                            "structure_summary": "FastAPI와 LangGraph 기반 서비스",
                            "skill_assessments": [{
                                "skill": "Python",
                                "current_usage": "중급 패턴",
                                "relevant_files": ["src/main.py"],
                                "used_patterns": ["FastAPI 엔드포인트"],
                            }],
                        }],
                    }
                }
            }
            yield {
                "consensus": {
                    "Python": {
                        "verification": "Verified",
                        "evidences": [{"skill": "Python", "source": "github", "strength": "code"}],
                    }
                }
            }
            raise RuntimeError("OpenAI 429 credit_balance_exhausted")

    out = run_supervisor(
        GraphWithLlmFailure(),
        job_family="AI/LLM Engineer",
        owner="X",
        github_urls=["https://github.com/me/app"],
    )
    assert out["trace"]["fallback"] == "llm_capacity_error"
    assert out["verification"]["counts"]["Verified"] == 1
    assert out["coaching"]["project_briefs"][0]["repo"] == "me/app"
    assert out["coaching"]["evidence_cards"][0]["evidence"] == "me/app: src/main.py"
