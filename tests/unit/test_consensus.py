# 합의 노드 — 검증 상태 판정(결정적)
from src.agent.consensus import build_consensus


def test_verified_when_github():
    out = build_consensus([
        {"skills": [{"skill": "LangGraph", "evidence": "코드", "source": "github", "level_hint": "실무"}]},
    ])
    assert out["LangGraph"]["verification"] == "Verified"


def test_corroborated_when_two_sources():
    out = build_consensus([
        {"skills": [{"skill": "Docker", "evidence": "a", "source": "resume", "level_hint": None}]},
        {"skills": [{"skill": "Docker", "evidence": "b", "source": "portfolio", "level_hint": None}]},
    ])
    assert out["Docker"]["verification"] == "Corroborated"


def test_claimed_single_source_has_flag():
    out = build_consensus([
        {"skills": [{"skill": "AWS", "evidence": "a", "source": "resume", "level_hint": None}]},
    ])
    assert out["AWS"]["verification"] == "Claimed"
    assert "flags" in out["AWS"]


def test_normalize_merges_aliases():
    out = build_consensus([
        {"skills": [{"skill": "react.js", "evidence": "a", "source": "resume", "level_hint": None}]},
        {"skills": [{"skill": "React", "evidence": "b", "source": "portfolio", "level_hint": None}]},
    ])
    assert "React" in out
    assert out["React"]["verification"] == "Corroborated"


def test_evidences_accumulate_from_all_sources():
    # 여러 소스의 증거가 evidences에 빠짐없이 모이는지 검증
    out = build_consensus([
        {"skills": [{"skill": "Docker", "evidence": "이력서 근거", "source": "resume", "level_hint": None}]},
        {"skills": [{"skill": "Docker", "evidence": "포폴 근거", "source": "portfolio", "level_hint": None}]},
    ])
    evidences = out["Docker"]["evidences"]
    assert len(evidences) == 2
    assert {e["evidence"] for e in evidences} == {"이력서 근거", "포폴 근거"}
    assert {e["source"] for e in evidences} == {"resume", "portfolio"}


def test_no_flag_when_not_claimed():
    # Verified/Corroborated에는 flags가 붙지 않아야 함
    out = build_consensus([
        {"skills": [{"skill": "LangGraph", "evidence": "코드", "source": "github", "level_hint": "실무"}]},
    ])
    assert "flags" not in out["LangGraph"]
