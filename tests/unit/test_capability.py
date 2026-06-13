# 스킬→역량 매핑 검증 (정규화·계열 흡수·미지 제외)
from src.analysis.capability import skills_to_capabilities


def test_maps_known_skills():
    caps = skills_to_capabilities(["MariaDB", "Spring", "React.js", "Docker", "AWS"])
    assert {"database", "backend_fw", "frontend", "container", "cloud"} <= caps


def test_alias_and_normalize():
    # MariaDB·SQLite → database (계열 흡수), React.js → React → frontend
    assert "database" in skills_to_capabilities(["SQLite"])
    assert "frontend" in skills_to_capabilities(["React.js"])


def test_unknown_excluded():
    assert skills_to_capabilities(["완전미지스킬xyz"]) == set()


from src.analysis.capability import capability_fit, capability_evidence


def test_capability_fit_ratio():
    core = ["language", "frontend", "database", "container", "cloud", "backend_fw"]
    resume = {"language", "database", "container", "cloud", "backend_fw"}  # frontend 빠짐
    r = capability_fit(resume, core)
    assert r["fit"] == 0.83
    assert r["unmet"] == ["frontend"]
    assert set(r["met"]) == resume


def test_capability_evidence_grades():
    owned = [{"skill": "Spring", "source": "github"}, {"skill": "AWS", "source": "resume"}]
    consensus = {"Spring": {"verification": "Verified"}, "AWS": {"verification": "Claimed"}}
    ev = capability_evidence(owned, consensus, met_caps={"backend_fw", "cloud"})
    by_cap = {e["capability"]: e["tools"] for e in ev}
    assert by_cap["backend_fw"][0] == {"skill": "Spring", "verification": "Verified"}
    assert by_cap["cloud"][0] == {"skill": "AWS", "verification": "Claimed"}
