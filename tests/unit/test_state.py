# AppState에 v3 다중 소스 평가 필드가 정의됐는지 검증
from src.agent.state import AppState


def test_v3_fields_exist():
    ann = AppState.__annotations__
    for field in (
        "resume_eval", "github_eval", "portfolio_eval", "deploy_eval",
        "consensus", "critic_report", "gap_result", "final_report",
    ):
        assert field in ann, f"'{field}' 필드 누락"


def test_v1_orphan_fields_removed():
    # v1 Plan-and-Execute/Executor 잔재 필드는 제거됨
    ann = AppState.__annotations__
    for field in ("plan", "replan_count", "profile_result",
                  "retrieved_context", "market_result", "github_result",
                  "skill_trends", "fit_result"):
        assert field not in ann, f"'{field}' 잔재 필드가 남아 있음"
