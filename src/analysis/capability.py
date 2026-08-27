# 직군 핵심 스킬 대비 이력서 충족(적합도)과 역방향 직군 추천을 따지는 모듈
#
# 이 파일이 하는 일을 한 줄로: "이 사람 스킬이 이 직군 핵심 스킬 몇 개랑 겹치는지" 세는 것.
# supervisor.py가 최종 리포트에 "적합도 몇 %" 같은 숫자를 넣을 때 이 파일의 함수들을 씁니다.

from __future__ import annotations

from typing import TYPE_CHECKING

from src.common.skill_groups import collapse_alternatives
from src.extraction.normalizer import normalize_skill
# 예전에 본 그 함수. "React"랑 "react.js"를 같은 스킬로 보게 표기를 통일해줌.

if TYPE_CHECKING:
    from src.storage.neo4j_client import Neo4jClient


def skill_overlap(resume_skills: list[str], family_skills: list[str]) -> tuple[int, list[str]]:
    """이력서 스킬과 직군 스킬 풀의 교집합(정규화 후). (개수, 일치한 이력서 원형 목록)."""
    # 쉽게 말하면: 이력서 스킬 목록이랑 직군 스킬 목록, 이 두 리스트에 둘 다 있는 것만 골라내는 함수.

    fam_norm = {normalize_skill(s).lower() for s in family_skills}
    # 직군 스킬들을 전부 표기 통일 + 소문자로 바꿔서 집합(set)에 담아둠.
    # 왜 set인가: "이 안에 있나?" 확인하는 속도가 리스트보다 훨씬 빠르기 때문.

    matched: list[str] = []   # 겹치는 스킬을 담을 빈 리스트
    seen: set[str] = set()    # 중복으로 안 넣으려고 이미 넣은 것 기록해두는 곳

    for s in resume_skills:
        # 이력서 스킬을 하나씩 꺼내서 확인
        key = normalize_skill(s).lower()
        if key in fam_norm and key not in seen:
            # "직군 스킬 목록에도 있고" + "아직 안 넣었으면" → 통과
            seen.add(key)
            matched.append(s)
            # 여기서 s(이력서에 적힌 원래 표기)를 저장 — key(정규화된 표기)가 아님을 주의.
            # 예: 이력서에 "리액트"라고 써있었으면, "React"가 아니라 "리액트" 그대로 저장됨.

    return len(matched), matched
    # 개수랑 실제 목록을 같이 반환 — 개수만 필요한 곳도 있고, 목록이 필요한 곳도 있어서 둘 다 줌


_FAMILY_SKILLS_QUERY = """
MATCH (:JobFamily {name: $job_family})<-[:INSTANCE_OF]-(jp)-[:REQUIRES]->(s:Skill)
RETURN s.name AS skill, count(DISTINCT jp) AS w
ORDER BY w DESC
LIMIT $n
"""
# 이 쿼리가 하는 일 (Cypher 문법): "이 직군의 공고들이 필수(REQUIRES)로 요구하는 스킬을,
# 그 스킬을 요구하는 공고 개수(w)가 많은 순서로 정렬해서 상위 n개만 가져와라."
# 즉 "이 직군에서 제일 자주 나오는 필수 스킬 Top N"을 뽑는 쿼리.


def job_family_core_skills(neo4j: "Neo4jClient", job_family: str, n: int = 10) -> list[str]:
    """직군 REQUIRES 스킬을 공고 수 가중 상위 n개로."""
    # 위 쿼리를 실제로 실행하는 함수. "이 직군의 핵심 스킬 Top n개 이름만 리스트로 줘"
    rows = neo4j.execute_query(_FAMILY_SKILLS_QUERY, job_family=job_family, n=n)
    return [r["skill"] for r in rows]
    # 쿼리 결과는 [{"skill": "Python", "w": 42}, {"skill": "Docker", "w": 30}, ...] 형태인데,
    # 여기선 개수(w)는 버리고 스킬 이름만 뽑아서 리스트로 만듦


def skill_fit(resume_skills: list[str], core_skills: list[str], consensus: dict) -> dict:
    """직군 핵심 스킬 중 이력서 충족 비율 + 충족(검증등급)/미충족."""
    # 이 함수가 실제로 "적합도 몇 %"를 계산하는 핵심 함수.

    core_skills = collapse_alternatives(core_skills, resume_skills)
    count, met = skill_overlap(resume_skills, core_skills)
    # 위에서 만든 함수로 "핵심 스킬 중 몇 개를 갖고 있는지" 구함
    # count = 겹치는 개수, met = 겹치는 스킬 이름 리스트

    met_norm = {normalize_skill(s).lower() for s in met}
    unmet = [s for s in core_skills if normalize_skill(s).lower() not in met_norm]
    # core_skills(직군 핵심 스킬 전체) 중에서, met(갖고 있는 것)에 없는 것만 골라 "부족한 스킬" 리스트로 만듦

    met_graded = [
        {"skill": s, "verification": (consensus.get(normalize_skill(s)) or {}).get("verification", "Claimed")}
        for s in met
    ]
    # 그냥 "갖고 있다"고만 하지 않고, consensus.py가 매긴 검증 등급(Verified/Corroborated/Claimed)도
    # 같이 붙여서 보여줌. consensus에 그 스킬 정보가 없으면 기본값 "Claimed"(가장 낮은 신뢰도)로 처리.

    return {"fit": round(count / len(core_skills), 2) if core_skills else 0.0,
            "total": len(core_skills), "met": met_graded, "unmet": unmet}
    # fit = 적합도 비율 (예: 10개 중 7개 있으면 0.7). core_skills가 비어있으면 나누기 에러 나니까
    # 그럴 땐 그냥 0.0으로 처리.
    # total = 이 직군 핵심 스킬이 몇 개였는지, met = 갖고 있는 것(등급 포함), unmet = 부족한 것


def recommend_families(neo4j: "Neo4jClient", resume_skills: list[str], families: list[str], n: int = 25) -> list[dict]:
    """직군별 빈도 상위 n개 스킬 풀과 이력서 스킬의 교집합 개수로 추천 — 내림차순."""
    # 이 함수가 하는 일: "당신 스킬로는 다른 직군에도 지원할 수 있을까?"에 답하는 함수.
    # 지원한 직군 하나만 보는 게 아니라, 존재하는 모든 직군을 하나씩 다 확인함.

    out = []
    for fam in families:
        # 직군 목록(예: ["AI/LLM Engineer", "Data Analyst", "DevOps/SRE", ...])을 하나씩 순회
        count, matched = skill_overlap(resume_skills, job_family_core_skills(neo4j, fam, n))
        # 이 직군의 핵심 스킬 Top n개를 구하고, 내 이력서 스킬이랑 몇 개 겹치는지 계산
        out.append({"job_family": fam, "matched_count": count, "matched_skills": matched})
    return sorted(out, key=lambda x: -x["matched_count"])
    # 겹치는 개수가 많은 직군부터 순서대로 정렬해서 반환.
    # key=lambda x: -x["matched_count"] → 마이너스 부호를 붙이는 이유: sort는 기본이 "작은 것부터"인데,
    # "큰 것부터"(내림차순) 정렬하고 싶어서 값에 마이너스를 붙여 크고 작음을 뒤집는 흔한 트릭
