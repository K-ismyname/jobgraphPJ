# LangGraph Supervisor 그래프 통합 테스트 — 실 환경변수(OPENAI_API_KEY) 필요
import os
from unittest.mock import MagicMock

import pytest

from src.agent.supervisor import create_supervisor_graph, run_analysis
from src.agent.state import AppState, MAX_ITERATIONS, COACH_MAX_ITERATIONS

requires_api_key = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY 환경변수 필요",
)


@pytest.fixture
def mock_clients():
    neo4j = MagicMock()
    neo4j.execute_query.return_value = []
    neo4j.get_portfolio_demonstrated_skills.return_value = []
    # Market 노드가 호출하는 메서드 — 직렬화 가능한 값으로 mock (MagicMock 반환 방지)
    neo4j.get_job_distribution.return_value = []
    neo4j.get_top_skills.return_value = []
    neo4j.get_location_distribution.return_value = []
    chroma = MagicMock()
    chroma.search.return_value = []
    openai = MagicMock()
    return neo4j, chroma, openai


class TestCreateSupervisorGraph:
    @requires_api_key
    def test_graph_compiles(self, mock_clients) -> None:
        """create_supervisor_graph()가 예외 없이 컴파일된다."""
        neo4j, chroma, openai = mock_clients
        graph = create_supervisor_graph(neo4j, chroma, openai)
        assert graph is not None

    @requires_api_key
    def test_graph_has_gap_loop_nodes(self, mock_clients) -> None:
        """Gap 루프 노드(call_model, tools, synthesizer)가 모두 존재한다."""
        neo4j, chroma, openai = mock_clients
        graph = create_supervisor_graph(neo4j, chroma, openai)
        node_names = set(graph.get_graph().nodes.keys())
        assert "call_model"  in node_names
        assert "tools"       in node_names
        assert "synthesizer" in node_names

    @requires_api_key
    def test_graph_has_v3_nodes(self, mock_clients) -> None:
        """v3 단계1 노드(평가자·합의·synthesizer·critic)가 모두 존재한다."""
        neo4j, chroma, openai = mock_clients
        graph = create_supervisor_graph(neo4j, chroma, openai)
        names = set(graph.get_graph().nodes.keys())
        for n in ("resume_eval", "github_eval", "consensus", "synthesizer", "critic"):
            assert n in names, f"'{n}' 누락"

    @requires_api_key
    def test_graph_has_coach_nodes(self, mock_clients) -> None:
        """Coach 파이프라인 노드가 모두 존재한다."""
        neo4j, chroma, openai = mock_clients
        graph = create_supervisor_graph(neo4j, chroma, openai)
        node_names = set(graph.get_graph().nodes.keys())
        assert "coach_call_model" in node_names
        assert "finalize_coach"   in node_names


class TestRunAnalysis:
    @requires_api_key
    def test_returns_dict(self, mock_clients) -> None:
        """run_analysis()는 gap_result(dict)를 반환한다."""
        neo4j, chroma, openai = mock_clients
        graph = create_supervisor_graph(neo4j, chroma, openai)
        result = run_analysis(graph, job_title="AI/LLM Engineer", owner="김지원")
        assert isinstance(result, dict)


class TestCreateGraphNoKey:
    def test_raises_without_api_key(self, mock_clients, monkeypatch) -> None:
        """OPENAI_API_KEY 없으면 EnvironmentError가 발생한다."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        neo4j, chroma, openai = mock_clients
        with pytest.raises(EnvironmentError, match="OPENAI_API_KEY"):
            create_supervisor_graph(neo4j, chroma, openai)


class TestAppState:
    def test_state_fields(self) -> None:
        """AppState TypedDict에 필수 필드가 모두 정의됐다."""
        annotations = AppState.__annotations__
        for field in ("job_family", "owner", "messages", "iteration", "final_report"):
            assert field in annotations, f"'{field}' 필드 누락"

    def test_iteration_limits_positive(self) -> None:
        assert MAX_ITERATIONS > 0
        assert COACH_MAX_ITERATIONS > 0
