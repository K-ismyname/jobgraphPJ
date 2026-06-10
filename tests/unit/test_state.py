# AppState에 Plan-and-Execute 필드가 정의됐는지 검증
from src.agent.state import AppState


def test_plan_execute_fields_exist():
    ann = AppState.__annotations__
    for field in (
        "plan", "replan_count",
        "profile_result", "retrieved_context", "market_result",
        "critic_report",
    ):
        assert field in ann, f"'{field}' 필드 누락"
