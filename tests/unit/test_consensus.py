# 합의 노드 — 검증 상태 판정(결정적)
from src.agent.consensus import build_consensus


def test_verified_when_github_code():
    # 코드 근거(strength="code")가 있어야 Verified
    out = build_consensus([
        {"skills": [{"skill": "LangGraph", "evidence": "코드", "source": "github",
                     "strength": "code", "level_hint": "실무"}]},
    ])
    assert out["LangGraph"]["verification"] == "Verified"


def test_github_readme_mention_alone_not_verified():
    # README에 스킬명이 적혀 있기만 한 것(strength="mention")은 단독으로 Verified 아님
    out = build_consensus([
        {"skills": [{"skill": "Kubernetes", "evidence": "README 언급", "source": "github",
                     "strength": "mention", "level_hint": "실무"}]},
    ])
    assert out["Kubernetes"]["verification"] == "Claimed"


def test_github_mention_plus_resume_corroborated():
    # 코드 근거는 없지만 github(언급)+resume 두 소스가 뒷받침 → Corroborated
    out = build_consensus([
        {"skills": [{"skill": "Redis", "evidence": "README", "source": "github",
                     "strength": "mention", "level_hint": "실무"}]},
        {"skills": [{"skill": "Redis", "evidence": "이력서", "source": "resume", "level_hint": None}]},
    ])
    assert out["Redis"]["verification"] == "Corroborated"


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
        {"skills": [{"skill": "LangGraph", "evidence": "코드", "source": "github",
                     "strength": "code", "level_hint": "실무"}]},
    ])
    assert "flags" not in out["LangGraph"]


def test_consensus_node_includes_portfolio():
    from src.agent.consensus import create_consensus_node
    node = create_consensus_node()
    state = {
        "resume_eval": {"skills": [{"skill": "Docker", "evidence": "a", "source": "resume", "level_hint": None}]},
        "portfolio_eval": {"skills": [{"skill": "Docker", "evidence": "b", "source": "portfolio", "level_hint": None}]},
    }
    out = node(state)["consensus"]
    # resume + portfolio 두 소스 → Corroborated
    assert out["Docker"]["verification"] == "Corroborated"


def test_consensus_node_deploy_mention_alone_claimed():
    # 배포 HTML 키워드(strength="mention")는 단독으로 Verified 아님 — 단순 언급이라 Claimed
    from src.agent.consensus import create_consensus_node
    node = create_consensus_node()
    state = {
        "deploy_eval": {"skills": [{"skill": "React", "evidence": "배포", "source": "deploy",
                                    "strength": "mention", "level_hint": "실무"}]},
    }
    out = node(state)["consensus"]
    assert out["React"]["verification"] == "Claimed"


def test_build_verification_summary():
    from src.agent.consensus import build_verification_summary
    consensus = {
        "Docker": {"verification": "Claimed", "evidences": [{"source": "resume"}]},
        "React": {"verification": "Verified", "evidences": [{"source": "github"}, {"source": "deploy"}]},
        "Python": {"verification": "Corroborated", "evidences": [{"source": "resume"}, {"source": "portfolio"}]},
    }
    out = build_verification_summary(consensus)
    assert out["counts"] == {"Verified": 1, "Corroborated": 1, "Claimed": 1}
    # 강한 검증 우선 정렬: Verified → Corroborated → Claimed
    assert out["skills"][0]["skill"] == "React"
    assert out["skills"][0]["sources"] == ["deploy", "github"]   # 정렬된 소스
    assert out["skills"][-1]["skill"] == "Docker"
