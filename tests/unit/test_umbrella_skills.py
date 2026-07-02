# PART_OF 간접 실증 — "LangGraph 썼는데 LLM 부족" 오탐 방지 검증
from src.agent.consensus import expand_umbrella_skills


class _FakeNeo4j:
    def __init__(self, coverage):
        self._coverage = coverage
        self.asked_with = None

    def get_covered_umbrella_skills(self, skills):
        self.asked_with = list(skills)
        return self._coverage


def _consensus(**entries):
    return {k: {"verification": v, "evidences": []} for k, v in entries.items()}


def test_verified_concrete_skill_covers_umbrella():
    # LangGraph(Verified) → LLM·GenAI·AI 간접 실증
    neo4j = _FakeNeo4j({"LLM": ["LangGraph"], "GenAI": ["LangGraph"], "AI": ["LangGraph"]})
    out = expand_umbrella_skills(_consensus(LangGraph="Verified"), neo4j)
    for umbrella in ("LLM", "GenAI", "AI"):
        assert out[umbrella]["verification"] == "Verified"
        assert any("간접 실증" in f for f in out[umbrella]["flags"])
    assert neo4j.asked_with == ["LangGraph"]


def test_claimed_skill_does_not_expand():
    # 이력서 주장(Claimed)만으로는 상위 스킬을 세탁하지 않는다
    neo4j = _FakeNeo4j({"LLM": ["LangGraph"]})
    out = expand_umbrella_skills(_consensus(LangGraph="Claimed"), neo4j)
    assert "LLM" not in out
    assert neo4j.asked_with is None   # strong 스킬 없음 → 조회 자체를 안 함


def test_direct_evidence_not_overwritten():
    # LLM에 직접 증거(Claimed)가 있으면 간접 실증이 덮어쓰지 않음
    neo4j = _FakeNeo4j({"LLM": ["LangGraph"]})
    cons = _consensus(LangGraph="Verified", LLM="Claimed")
    out = expand_umbrella_skills(cons, neo4j)
    assert out["LLM"]["verification"] == "Claimed"   # 직접 증거 유지


def test_corroborated_basis_gives_corroborated():
    neo4j = _FakeNeo4j({"LLM": ["LangChain"]})
    out = expand_umbrella_skills(_consensus(LangChain="Corroborated"), neo4j)
    assert out["LLM"]["verification"] == "Corroborated"


def test_no_neo4j_is_noop():
    cons = _consensus(LangGraph="Verified")
    assert expand_umbrella_skills(dict(cons), None) == cons


def test_critic_strips_umbrella_from_missing():
    # 통합: 간접 실증된 LLM이 missing_required에서 false_missing으로 걸러지는지
    from src.agent.critic import verify_gap_against_consensus

    neo4j = _FakeNeo4j({"LLM": ["LangGraph"]})
    cons = expand_umbrella_skills(_consensus(LangGraph="Verified"), neo4j)
    gap = {"skills": [], "missing_required": [{"skill": "LLM"}, {"skill": "Java"}]}
    _, clean_missing, report = verify_gap_against_consensus(gap, cons)
    assert [m["skill"] for m in clean_missing] == ["Java"]   # 진짜 갭만 남음
    assert report["false_missing"] == ["LLM"]
