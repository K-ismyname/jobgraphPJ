# 노드 → 진행 단계 라벨 매핑
from src.api.routers.portfolio import _NODE_PHASE


def test_node_phase_groups():
    assert _NODE_PHASE["resume_eval"] == "소스 평가 중"
    assert _NODE_PHASE["github_eval"] == "소스 평가 중"
    assert _NODE_PHASE["consensus"] == "교차검증 합의 중"
    assert _NODE_PHASE["call_model"] == "적합도 분석 중"
    assert _NODE_PHASE["coach_call_model"] == "코칭 생성 중"
