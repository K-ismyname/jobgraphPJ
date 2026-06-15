# 직군 핵심 스킬 교집합·적합도 검증
from src.analysis.capability import skill_overlap, skill_fit


def test_skill_overlap_normalizes_and_counts():
    count, matched = skill_overlap(["React.js", "Python"], ["React", "Java"])
    assert count == 1
    assert matched == ["React.js"]


def test_skill_overlap_dedup_and_empty():
    assert skill_overlap([], ["SQL"]) == (0, [])
    count, matched = skill_overlap(["SQL", "sql"], ["SQL"])
    assert count == 1
    assert matched == ["SQL"]


def test_skill_fit_counts_and_grades():
    consensus = {"React": {"verification": "Verified"}}
    r = skill_fit(["React.js", "Python"], ["React", "Vue.js", "HTML"], consensus)
    assert r["total"] == 3
    assert r["fit"] == 0.33
    assert r["met"] == [{"skill": "React.js", "verification": "Verified"}]
    assert r["unmet"] == ["Vue.js", "HTML"]


def test_skill_fit_default_grade_claimed():
    r = skill_fit(["HTML"], ["HTML", "CSS"], {})
    assert r["met"] == [{"skill": "HTML", "verification": "Claimed"}]
    assert r["unmet"] == ["CSS"]
