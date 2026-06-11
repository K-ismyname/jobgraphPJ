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
