# 스킬을 역량(capability)으로 묶어 직군 핵심 역량 충족을 따지는 모듈
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from src.extraction.normalizer import normalize_skill

if TYPE_CHECKING:
    from src.storage.neo4j_client import Neo4jClient

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


def skill_overlap(resume_skills: list[str], family_skills: list[str]) -> tuple[int, list[str]]:
    """이력서 스킬과 직군 스킬 풀의 교집합(정규화 후). (개수, 일치한 이력서 원형 목록)."""
    fam_norm = {normalize_skill(s).lower() for s in family_skills}
    matched: list[str] = []
    seen: set[str] = set()
    for s in resume_skills:
        key = normalize_skill(s).lower()
        if key in fam_norm and key not in seen:
            seen.add(key)
            matched.append(s)
    return len(matched), matched


_CORE_QUERY = """
MATCH (:JobFamily {name: $job_family})<-[:INSTANCE_OF]-(jp)-[:REQUIRES]->(s:Skill)
RETURN s.name AS skill, count(DISTINCT jp) AS w
"""


def job_family_core_capabilities(neo4j: "Neo4jClient", job_family: str, n: int = 6) -> list[str]:
    """직군 REQUIRES 스킬을 역량으로 환산, 요구 공고 가중 상위 n개."""
    rows = neo4j.execute_query(_CORE_QUERY, job_family=job_family)
    m = _cap_map()
    capw: dict[str, int] = {}
    for r in rows:
        cap = m.get((r["skill"] or "").lower()) or m.get(normalize_skill(r["skill"] or "").lower())
        if cap and cap != "other":
            capw[cap] = capw.get(cap, 0) + int(r["w"] or 0)
    return [c for c, _ in sorted(capw.items(), key=lambda x: -x[1])[:n]]


def capability_fit(resume_caps: set[str], core_caps: list[str]) -> dict:
    """핵심 역량 충족률 + 충족/미충족 목록."""
    met = [c for c in core_caps if c in resume_caps]
    unmet = [c for c in core_caps if c not in resume_caps]
    return {
        "fit": round(len(met) / len(core_caps), 2) if core_caps else 0.0,
        "met": met,
        "unmet": unmet,
    }


_FAMILY_SKILLS_QUERY = """
MATCH (:JobFamily {name: $job_family})<-[:INSTANCE_OF]-(jp)-[:REQUIRES]->(s:Skill)
RETURN s.name AS skill, count(DISTINCT jp) AS w
ORDER BY w DESC
LIMIT $n
"""


def recommend_families(neo4j: "Neo4jClient", resume_skills: list[str], families: list[str], n: int = 25) -> list[dict]:
    """직군별 빈도 상위 n개 스킬 풀과 이력서 스킬의 교집합 개수로 추천 — 내림차순."""
    out = []
    for fam in families:
        rows = neo4j.execute_query(_FAMILY_SKILLS_QUERY, job_family=fam, n=n)
        pool = [r["skill"] for r in rows]
        count, matched = skill_overlap(resume_skills, pool)
        out.append({"job_family": fam, "matched_count": count, "matched_skills": matched})
    return sorted(out, key=lambda x: -x["matched_count"])


def capability_evidence(owned: list[dict], consensus: dict, met_caps: set[str]) -> list[dict]:
    """충족된 역량별로, 그 역량을 충족시킨 보유 도구 + 검증 등급(consensus)."""
    m = _cap_map()
    by_cap: dict[str, list[dict]] = {}
    for item in owned:
        sk = item.get("skill") if isinstance(item, dict) else None
        if not sk:
            continue
        cap = m.get(sk.lower()) or m.get(normalize_skill(sk).lower())
        if cap in met_caps:
            grade = (consensus.get(normalize_skill(sk)) or {}).get("verification", "Claimed")
            by_cap.setdefault(cap, []).append({"skill": sk, "verification": grade})
    return [{"capability": c, "tools": ts} for c, ts in by_cap.items()]
