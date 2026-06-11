# v3 평가자/합의/적합도 필드 검증
from src.agent.state import AppState


def test_v3_fields_exist():
    ann = AppState.__annotations__
    for f in ("resume_eval", "github_eval", "consensus", "fit_result"):
        assert f in ann, f"'{f}' 누락"
