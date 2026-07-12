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


def test_self_reported_sources_do_not_corroborate():
    """resume + portfolio는 둘 다 본인이 쓴 자기 서술이라 서로를 검증하지 못한다.

    이력서에 쓴 스킬을 포트폴리오에도 쓰는 건 당연하므로, 이 둘이 일치하는 것은
    교차 검증이 아니라 같은 주장의 자기 복제다. 예전에는 이것만으로 Corroborated가
    되어, 아무 외부 근거 없이도 "2개 소스가 뒷받침함" 라벨이 붙었다.
    """
    out = build_consensus([
        {"skills": [{"skill": "Docker", "evidence": "a", "source": "resume", "level_hint": None}]},
        {"skills": [{"skill": "Docker", "evidence": "b", "source": "portfolio", "level_hint": None}]},
    ])
    assert out["Docker"]["verification"] == "Claimed"
    assert out["Docker"]["flags"] == ["본인 서술만 일치 — 외부 근거 없음"]


def test_two_observable_sources_corroborate():
    # github(언급) + deploy(언급) — 코드 근거는 없지만 둘 다 외부에서 관측된 흔적
    out = build_consensus([
        {"skills": [{"skill": "React", "evidence": "README", "source": "github",
                     "strength": "mention", "level_hint": None}]},
        {"skills": [{"skill": "React", "evidence": "배포 HTML", "source": "deploy",
                     "strength": "mention", "level_hint": None}]},
    ])
    assert out["React"]["verification"] == "Corroborated"


def test_claimed_single_source_has_flag():
    out = build_consensus([
        {"skills": [{"skill": "AWS", "evidence": "a", "source": "resume", "level_hint": None}]},
    ])
    assert out["AWS"]["verification"] == "Claimed"
    assert "flags" in out["AWS"]


def test_normalize_merges_aliases():
    # 표기가 다른 스킬명("react.js" / "React")이 하나의 노드로 병합되는지 (등급과 무관한 정규화 검증)
    out = build_consensus([
        {"skills": [{"skill": "react.js", "evidence": "a", "source": "resume", "level_hint": None}]},
        {"skills": [{"skill": "React", "evidence": "b", "source": "github",
                     "strength": "mention", "level_hint": None}]},
    ])
    assert "React" in out
    assert len(out) == 1                       # 두 표기가 하나로 합쳐짐
    assert out["React"]["verification"] == "Corroborated"   # resume + github(외부 관측)


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
    # portfolio_eval 결과가 합의에 실제로 반영되는지 (증거가 두 소스에서 모임)
    assert {e["source"] for e in out["Docker"]["evidences"]} == {"resume", "portfolio"}
    # 다만 둘 다 자기 서술이므로 등급은 Claimed에 머문다
    assert out["Docker"]["verification"] == "Claimed"


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
