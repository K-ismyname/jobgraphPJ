# 직군 핵심 스킬 대비 이력서 충족(적합도)과 역방향 직군 추천을 따지는 모듈
from __future__ import annotations

from typing import TYPE_CHECKING

from src.extraction.normalizer import normalize_skill

if TYPE_CHECKING:
    from src.storage.neo4j_client import Neo4jClient


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


_FAMILY_SKILLS_QUERY = """
MATCH (:JobFamily {name: $job_family})<-[:INSTANCE_OF]-(jp)-[:REQUIRES]->(s:Skill)
RETURN s.name AS skill, count(DISTINCT jp) AS w
ORDER BY w DESC
LIMIT $n
"""


def job_family_core_skills(neo4j: "Neo4jClient", job_family: str, n: int = 10) -> list[str]:
    """직군 REQUIRES 스킬을 공고 수 가중 상위 n개로."""
    rows = neo4j.execute_query(_FAMILY_SKILLS_QUERY, job_family=job_family, n=n)
    return [r["skill"] for r in rows]


def skill_fit(resume_skills: list[str], core_skills: list[str], consensus: dict) -> dict:
    """직군 핵심 스킬 중 이력서 충족 비율 + 충족(검증등급)/미충족."""
    count, met = skill_overlap(resume_skills, core_skills)
    met_norm = {normalize_skill(s).lower() for s in met}
    unmet = [s for s in core_skills if normalize_skill(s).lower() not in met_norm]
    met_graded = [
        {"skill": s, "verification": (consensus.get(normalize_skill(s)) or {}).get("verification", "Claimed")}
        for s in met
    ]
    return {"fit": round(count / len(core_skills), 2) if core_skills else 0.0,
            "total": len(core_skills), "met": met_graded, "unmet": unmet}


def recommend_families(neo4j: "Neo4jClient", resume_skills: list[str], families: list[str], n: int = 25) -> list[dict]:
    """직군별 빈도 상위 n개 스킬 풀과 이력서 스킬의 교집합 개수로 추천 — 내림차순."""
    out = []
    for fam in families:
        count, matched = skill_overlap(resume_skills, job_family_core_skills(neo4j, fam, n))
        out.append({"job_family": fam, "matched_count": count, "matched_skills": matched})
    return sorted(out, key=lambda x: -x["matched_count"])
