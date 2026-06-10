# gap_analyzer.py 단위 테스트 — mock Neo4j/Chroma 사용
from unittest.mock import MagicMock, patch

import pytest

from src.analysis.gap_analyzer import GapAnalysisResult, SkillGap, run_gap_analysis


def _make_skill_gap(skill: str, have_it: bool, demand: int = 10) -> SkillGap:
    return SkillGap(
        skill=skill,
        category="framework",
        have_it=have_it,
        confidence="high" if have_it else None,
        evidence="사용 근거" if have_it else None,
        related_skills=[],
        difficulty="학습 장벽 낮음" if have_it else "신규 학습 필요",
        job_demand=demand,
    )


# ── match_rate 계산 ───────────────────────────────────────────────
class TestMatchRate:
    def test_all_have(self) -> None:
        result = GapAnalysisResult(
            job_title="AI Engineer",
            owner="김지원",
            match_rate=0.0,  # 아직 계산 전
            have=[_make_skill_gap("Python", True), _make_skill_gap("LangChain", True)],
            missing=[],
            top_missing=[],
        )
        total = len(result.have) + len(result.missing)
        actual_rate = len(result.have) / total if total > 0 else 0.0
        assert actual_rate == 1.0

    def test_partial_match(self) -> None:
        have    = [_make_skill_gap(s, True) for s in ["Python", "Docker"]]
        missing = [_make_skill_gap(s, False) for s in ["LangGraph", "Neo4j", "Chroma"]]
        total = len(have) + len(missing)
        rate = len(have) / total
        assert rate == pytest.approx(2 / 5)

    def test_zero_match(self) -> None:
        missing = [_make_skill_gap(s, False) for s in ["A", "B", "C"]]
        total = len(missing)
        rate = 0 / total
        assert rate == 0.0


# ── top_missing 정렬 ─────────────────────────────────────────────
class TestTopMissing:
    def test_sorted_by_demand(self) -> None:
        missing = [
            _make_skill_gap("LangGraph", False, demand=9),
            _make_skill_gap("Neo4j",     False, demand=5),
            _make_skill_gap("Chroma",    False, demand=7),
        ]
        # job_demand 내림차순 정렬
        sorted_missing = sorted(missing, key=lambda s: s.job_demand, reverse=True)
        assert sorted_missing[0].skill == "LangGraph"
        assert sorted_missing[1].skill == "Chroma"
        assert sorted_missing[2].skill == "Neo4j"


# ── run_gap_analysis mock 테스트 ─────────────────────────────────
class TestRunGapAnalysis:
    def test_mock_mode_returns_result(self) -> None:
        """Neo4j mock 모드에서 run_gap_analysis가 GapAnalysisResult를 반환한다."""
        mock_neo4j = MagicMock()
        mock_neo4j.execute_query.return_value = []  # 공고 없음

        mock_chroma = MagicMock()
        mock_chroma.search_evidence.return_value = []

        result = run_gap_analysis(mock_neo4j, mock_chroma, "AI Engineer", "김지원")

        assert isinstance(result, GapAnalysisResult)
        assert result.job_title == "AI Engineer"
        assert result.owner == "김지원"
        assert 0.0 <= result.match_rate <= 1.0

    def test_result_fields_populated(self) -> None:
        """반환된 결과에 필수 필드가 모두 존재한다."""
        mock_neo4j = MagicMock()
        mock_neo4j.execute_query.return_value = []
        mock_chroma = MagicMock()
        mock_chroma.search_evidence.return_value = []

        result = run_gap_analysis(mock_neo4j, mock_chroma, "ML Engineer", "이지원")

        assert hasattr(result, "have")
        assert hasattr(result, "missing")
        assert hasattr(result, "top_missing")
        assert isinstance(result.have, list)
        assert isinstance(result.missing, list)
