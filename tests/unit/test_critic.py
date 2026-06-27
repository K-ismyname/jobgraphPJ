# Critic — gap_result 보유/부족 스킬을 consensus와 대조해 환각 제거·검증 라벨 교정 (결정적)
from src.agent.critic import verify_gap_against_consensus, create_critic_node


def test_removes_skill_not_in_consensus():
    gap = {"skills": [
        {"skill": "Java", "verification": "Verified"},
        {"skill": "Rust", "verification": "Verified"},   # consensus에 없음 → 환각
    ]}
    consensus = {"Java": {"verification": "Verified"}}
    kept, clean_missing, report = verify_gap_against_consensus(gap, consensus)
    assert [s["skill"] for s in kept] == ["Java"]
    assert report["removed_claims"] == ["Rust"]


def test_corrects_inflated_verification():
    gap = {"skills": [{"skill": "Docker", "verification": "Verified"}]}   # LLM 부풀림
    consensus = {"Docker": {"verification": "Claimed"}}                    # 실제는 주장
    kept, _, report = verify_gap_against_consensus(gap, consensus)
    assert kept[0]["verification"] == "Claimed"
    assert report["corrections"] == [{"skill": "Docker", "from": "Verified", "to": "Claimed"}]


def test_keeps_matching_skill_unchanged():
    gap = {"skills": [{"skill": "Python", "verification": "Verified", "gap": ""}]}
    consensus = {"Python": {"verification": "Verified"}}
    kept, _, report = verify_gap_against_consensus(gap, consensus)
    assert kept == [{"skill": "Python", "verification": "Verified", "gap": ""}]
    assert report["corrections"] == [] and report["removed_claims"] == []


def test_normalizes_skill_name_before_match():
    gap = {"skills": [{"skill": "react.js", "verification": "Verified"}]}
    consensus = {"React": {"verification": "Corroborated"}}   # 정규화하면 매칭
    kept, _, report = verify_gap_against_consensus(gap, consensus)
    assert kept[0]["verification"] == "Corroborated"   # 교정됨 (제거 아님)
    assert report["removed_claims"] == []


def test_empty_skills_ok():
    kept, clean_missing, report = verify_gap_against_consensus({"error": "파싱 실패"}, {})
    assert kept == [] and clean_missing == []
    assert report["removed_claims"] == [] and report["corrections"] == []


def test_removes_false_missing():
    """consensus에 있는 스킬이 missing_required에 있으면 제거한다."""
    gap = {
        "skills": [],
        "missing_required": [
            {"skill": "Python", "reason": "필수"},   # 이미 보유 → 환각
            {"skill": "Rust",   "reason": "권장"},   # 미보유 → 유지
        ],
    }
    consensus = {"Python": {"verification": "Verified"}}
    _, clean_missing, report = verify_gap_against_consensus(gap, consensus)
    assert [m["skill"] for m in clean_missing] == ["Rust"]
    assert report["false_missing"] == ["Python"]


def test_node_writes_corrected_gap_and_report():
    node = create_critic_node()
    state = {
        "gap_result": {
            "match_rate": 0.3,
            "skills": [
                {"skill": "Java", "verification": "Verified"},
                {"skill": "Go",   "verification": "Verified"},  # consensus 없음
            ],
            "missing_required": [
                {"skill": "Python", "reason": "필수"},  # 이미 보유 → 제거
                {"skill": "Kotlin", "reason": "권장"},  # 미보유 → 유지
            ],
        },
        "consensus": {
            "Java":   {"verification": "Verified"},
            "Python": {"verification": "Verified"},
        },
    }
    out = node(state)
    assert [s["skill"] for s in out["gap_result"]["skills"]] == ["Java"]
    assert [m["skill"] for m in out["gap_result"]["missing_required"]] == ["Kotlin"]
    assert out["gap_result"]["match_rate"] == 0.3
    assert out["critic_report"]["removed_claims"] == ["Go"]
    assert out["critic_report"]["false_missing"] == ["Python"]
