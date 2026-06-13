# 스킬을 역량(capability)으로 묶어 직군 핵심 역량 충족을 따지는 모듈
from __future__ import annotations

import json
from pathlib import Path

from src.extraction.normalizer import normalize_skill

# 역량 시드 사전 (수동 — 명백한 매핑은 사전이 정답). 키=역량, 값=스킬 소문자 집합.
SEED_CAPABILITIES: dict[str, set[str]] = {
    "language": {"python", "java", "javascript", "typescript", "go", "c++", "c#", "kotlin", "php", "scala", "ruby", "c", "rust"},
    "backend_fw": {"spring", "spring boot", "django", "express", "fastapi", "node.js", "flask", ".net", "rails", "nestjs"},
    "frontend": {"react", "vue.js", "angular", "next.js", "svelte", "html", "css", "tailwind css", "bootstrap", "redux"},
    "database": {"postgresql", "mysql", "mariadb", "sqlite", "mongodb", "redis", "oracle", "cassandra", "dynamodb", "mybatis", "ibatis"},
    "cloud": {"aws", "gcp", "azure", "naver cloud platform"},
    "container": {"docker", "kubernetes"},
    "cicd": {"jenkins", "github actions", "gitlab ci", "circleci", "argocd", "ci/cd"},
    "data_eng": {"spark", "hadoop", "kafka", "airflow", "snowflake", "dbt", "etl", "databricks", "bigquery"},
    "ml_ai": {"pytorch", "tensorflow", "llms", "ml", "ai", "langchain", "langgraph", "scikit-learn", "ai/ml"},
    "mobile": {"android", "ios", "swift", "react native", "flutter", "swiftui", "uikit"},
    "security": {"siem", "edr", "threat intelligence", "cissp", "penetration testing"},
}

# 백필 스크립트(Task 2)가 채우는 미매핑 스킬 분류
_JSON_PATH = Path(__file__).resolve().parents[2] / "data" / "seeds" / "skill_capabilities.json"

_skill2cap: dict[str, str] | None = None


def load_capabilities() -> dict[str, str]:
    """skill_lower → capability. 시드 + JSON 백필 병합(시드 우선)."""
    m = {s: cap for cap, ss in SEED_CAPABILITIES.items() for s in ss}
    if _JSON_PATH.exists():
        try:
            for s, cap in json.loads(_JSON_PATH.read_text(encoding="utf-8")).items():
                m.setdefault(s.lower(), cap)  # 시드가 우선
        except Exception:
            pass
    return m


def _cap_map() -> dict[str, str]:
    global _skill2cap
    if _skill2cap is None:
        _skill2cap = load_capabilities()
    return _skill2cap


def skills_to_capabilities(skills: list[str]) -> set[str]:
    """보유 스킬 목록을 역량 집합으로. 정규화·계열 흡수, 미지/other 제외."""
    m = _cap_map()
    caps: set[str] = set()
    for s in skills:
        cap = m.get(s.lower()) or m.get(normalize_skill(s).lower())
        if cap and cap != "other":
            caps.add(cap)
    return caps
