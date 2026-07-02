# create_supervisor_graph가 실제로 컴파일되는지 검증 — langgraph API 레벨 회귀 가드.
#
# AppState 필드명(resume_eval 등)과 노드명이 동일한 설계라, langgraph 0.x 전 버전대는
# StateGraph.add_node에서 "노드명이 State 필드명과 같으면 안 된다"는 검증으로
# ValueError를 던진다(1.x부터 통과). 다른 단위 테스트는 그래프 빌드를 mock으로
# 우회하므로 이 문제를 못 잡는다 — 실제로 HF Spaces 배포에서 런타임 크래시로
# 드러났던 버그. 이 테스트는 mock 클라이언트로 실제 StateGraph.compile()까지 실행해
# langgraph 버전 호환성을 매 테스트 실행마다 보증한다.
from unittest.mock import MagicMock


def test_supervisor_graph_compiles_with_expected_nodes(monkeypatch):
    # create_nodes가 OPENAI_API_KEY 존재만 확인(실 API 호출 없음) — 가짜 키로 충분
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")

    from src.agent.supervisor import create_supervisor_graph

    neo4j = MagicMock()
    openai_client = MagicMock()

    graph = create_supervisor_graph(neo4j, openai_client)
    nodes = set(graph.get_graph().nodes.keys())

    expected = {
        "resume_eval", "github_eval", "portfolio_eval", "deploy_eval",
        "consensus", "seed_gap", "gap_agent", "synthesizer", "critic", "coach_agent",
    }
    assert expected <= nodes
