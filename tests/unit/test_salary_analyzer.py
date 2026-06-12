# analyze_salary 계산 로직 검증 — execute_query를 쿼리별로 mock (DB 불필요)
from src.analysis.salary_analyzer import analyze_salary


class FakeNeo4j:
    """쿼리 문자열로 분기해 고정 행을 돌려주는 가짜 Neo4j 클라이언트."""

    def execute_query(self, query: str, **params) -> list[dict]:
        if "baseline_avg" in query:
            return [{"baseline_avg": 100000.0, "posting_count": 10}]
        if "combo_avg_salary" in query:
            return [{"combo_avg_salary": 130000.0, "posting_count": 2}]
        if "co_count" in query:
            return [{"skill_a": "Python", "skill_b": "SQL", "co_count": 4}]
        # SKILL_SALARY_QUERY
        return [
            {"skill": "Python", "avg_salary": 120000.0, "posting_count": 5},
            {"skill": "SQL", "avg_salary": 90000.0, "posting_count": 3},
        ]


def test_vs_baseline_pct_and_ordering():
    result = analyze_salary(FakeNeo4j(), job_family="Data Engineer")

    assert result.job_family == "Data Engineer"
    assert result.baseline_avg_salary == 100000
    assert result.total_postings_with_salary == 10

    by_skill = {s.skill: s for s in result.skill_impacts}
    # (120000-100000)/100000*100 = +20.0
    assert by_skill["Python"].vs_baseline_pct == 20.0
    # (90000-100000)/100000*100 = -10.0
    assert by_skill["SQL"].vs_baseline_pct == -10.0

    # top_salary_skills는 vs_baseline_pct 상위 → Python이 먼저
    assert result.top_salary_skills[0] == "Python"


def test_combo_insight_vs_single_avg():
    result = analyze_salary(FakeNeo4j(), job_family="Data Engineer")

    assert len(result.combo_insights) == 1
    combo = result.combo_insights[0]
    assert combo.skills == ["Python", "SQL"]
    assert combo.avg_salary == 130000
    # single_avg = (120000+90000)/2 = 105000 → (130000-105000)/105000*100 = +23.8
    assert combo.vs_single_avg_pct == 23.8


def test_empty_db_no_crash():
    class EmptyNeo4j:
        def execute_query(self, query: str, **params) -> list[dict]:
            return []

    result = analyze_salary(EmptyNeo4j(), job_family="Data Engineer")
    assert result.baseline_avg_salary == 0
    assert result.skill_impacts == []
    assert result.combo_insights == []
