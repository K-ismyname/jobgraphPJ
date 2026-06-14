# gap_analysis가 핵심 필수(REQUIRES weight 상위 N개)만 적합도 분모로 쓰는지 검증
from unittest.mock import MagicMock

from src.agent.tools import _CORE_REQUIRED_N, create_tools


def _make_gap_tool(rows):
    neo4j = MagicMock()
    neo4j.execute_query.return_value = rows
    neo4j.get_portfolio_demonstrated_skills.return_value = []
    tools = create_tools(neo4j)
    return next(t for t in tools if t.name == "gap_analysis")


def test_match_rate_uses_only_core_top_n():
    # REQUIRES 15개(weight 15..1, 내림차순) + PREFERS 3개
    rows = [{"skill": f"R{i}", "importance": "REQUIRES", "weight": 15 - i} for i in range(15)]
    rows += [{"skill": f"P{i}", "importance": "PREFERS", "weight": 1} for i in range(3)]
    gap = _make_gap_tool(rows)

    # 핵심 상위 10개(R0~R9) 중 5개(R0~R4)만 보유
    have = [f"R{i}" for i in range(5)]
    res = gap.invoke({"job_family": "Software Engineer", "portfolio_skills": have, "owner": "t"})

    # 분모는 전체 15개가 아니라 핵심 10개
    assert res["required_total"] == _CORE_REQUIRED_N
    assert res["match_rate"] == 0.5  # 5/10
    # 비핵심 REQUIRES(R10~R14)는 missing에 포함되지 않음
    missing = {m["skill"] for m in res["missing_required"]}
    assert missing == {"R5", "R6", "R7", "R8", "R9"}


def test_fewer_than_n_required_uses_actual_count():
    # REQUIRES가 N개 미만이면 있는 만큼만 분모
    rows = [{"skill": f"R{i}", "importance": "REQUIRES", "weight": 4 - i} for i in range(4)]
    gap = _make_gap_tool(rows)
    res = gap.invoke({"job_family": "Software Engineer", "portfolio_skills": ["R0", "R1"], "owner": "t"})
    assert res["required_total"] == 4
    assert res["match_rate"] == 0.5  # 2/4
