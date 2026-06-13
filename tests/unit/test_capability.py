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
