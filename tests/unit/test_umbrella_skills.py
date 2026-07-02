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


def test_weak_direct_claim_upgraded_by_strong_indirect():
    # 이력서에 "LLM"이 직접 적혀 Claimed로 먼저 잡혀도, LangGraph(Verified)로
    # 간접 실증되면 업그레이드된다 — 약한 직접 증거가 강한 간접 증거를 막던 버그 수정.
    neo4j = _FakeNeo4j({"LLM": ["LangGraph"]})
    cons = _consensus(LangGraph="Verified", LLM="Claimed")
    out = expand_umbrella_skills(cons, neo4j)
    assert out["LLM"]["verification"] == "Verified"
    # 기존 직접 증거(이력서 주장)는 버리지 않고 병기
    assert len(out["LLM"]["evidences"]) == 1   # 원래 Claimed 항목엔 evidences가 없었으므로 derived만 1개
    assert any("간접 실증" in f for f in out["LLM"]["flags"])


def test_strong_direct_evidence_not_downgraded():
    # LLM에 이미 Verified 직접 증거가 있으면, LangChain(Corroborated) 기반 간접 실증이
    # 더 약해도 다운그레이드하지 않는다.
    neo4j = _FakeNeo4j({"LLM": ["LangChain"]})
    cons = _consensus(LangChain="Corroborated", LLM="Verified")
    out = expand_umbrella_skills(cons, neo4j)
    assert out["LLM"]["verification"] == "Verified"


def test_resume_evidence_preserved_when_upgraded():
    # 실제 상황 재현: 이력서에 "AI"가 적혀 있어 evidences가 채워진 Claimed 항목이,
    # 업그레이드 후에도 그 이력서 근거를 잃지 않고 간접 실증과 함께 보관된다.
    neo4j = _FakeNeo4j({"AI": ["LangGraph"]})
    cons = {
        "LangGraph": {"verification": "Verified", "evidences": []},
        "AI": {"verification": "Claimed",
               "evidences": [{"skill": "AI", "evidence": "이력서: AI 프로젝트 다수 수행",
                              "source": "resume", "level_hint": None}],
               "flags": ["코드·실증 미확인 — 주장/언급만"]},
    }
    out = expand_umbrella_skills(cons, neo4j)
    assert out["AI"]["verification"] == "Verified"
    sources = {e["source"] for e in out["AI"]["evidences"]}
    assert sources == {"resume", "derived"}   # 둘 다 보존


def test_equal_grade_not_touched():
    # 기존이 이미 Corroborated면 같은 등급의 간접 실증으로 재작성하지 않는다
    neo4j = _FakeNeo4j({"LLM": ["LangChain"]})
    cons = _consensus(LangChain="Corroborated", LLM="Corroborated")
    original_evidences = cons["LLM"]["evidences"]
    out = expand_umbrella_skills(cons, neo4j)
    assert out["LLM"]["evidences"] is original_evidences   # 손 안 댐


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
