# 핵심 스킬(공통+직군별)을 6종으로 분류해 Neo4j Skill.category에 저장하는 일회성 스크립트
import os
import json
from collections import Counter

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI
from src.storage.neo4j_client import Neo4jClient

_CORE_N = 30  # 직군별 상위 N개

_CORE_SKILLS_QUERY = """
MATCH (:JobFamily {name: $fam})<-[:INSTANCE_OF]-(jp)-[r:REQUIRES|PREFERS]->(s:Skill)
RETURN s.name AS skill, count(jp) AS w
ORDER BY w DESC LIMIT $n
"""


def collect_core_skills(c: Neo4jClient) -> list[str]:
    """9개 직군 핵심 + 공통 스킬을 모아 중복 제거."""
    skills: set[str] = set()
    for fam in c.list_job_families():
        for r in c.execute_query(_CORE_SKILLS_QUERY, fam=fam, n=_CORE_N):
            if r.get("skill"):
                skills.add(r["skill"])
    skills.update(c.get_common_skills(threshold=5, n=20))
    return sorted(skills)


def classify(openai: OpenAI, skills: list[str]) -> dict[str, str]:
    """스킬을 language/framework/tool/database/concept/soft 6종으로 분류."""
    result: dict[str, str] = {}
    for i in range(0, len(skills), 150):
        batch = skills[i:i + 150]
        prompt = (
            "다음 기술 스킬들을 각각 하나의 카테고리로 분류하세요.\n"
            "- language: 프로그래밍 언어 (Python, Java, Go)\n"
            "- framework: 프레임워크·라이브러리 (React, FastAPI, Pandas, LangChain)\n"
            "- tool: 도구·인프라·클라우드 (Docker, Kubernetes, AWS, Terraform)\n"
            "- database: 데이터베이스 (PostgreSQL, Neo4j, Redis)\n"
            "- concept: 기술 개념·기법 (AI, Machine Learning, RAG, Computer Vision)\n"
            "- soft: 순수 역량·방법론 (Problem Solving, Agile, Communication, 프로젝트 관리)\n"
            f"스킬: {', '.join(batch)}\n"
            'JSON 객체로만 답하세요: {"스킬명":"카테고리", ...}'
        )
        resp = openai.chat.completions.create(
            model="gpt-4o-mini", temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            result.update(json.loads(resp.choices[0].message.content))
        except (json.JSONDecodeError, TypeError) as e:
            print(f"[warn] 배치 {i} 파싱 실패: {e}")
    return result


if __name__ == "__main__":
    c = Neo4jClient()
    openai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    skills = collect_core_skills(c)
    print(f"핵심 스킬 {len(skills)}개 수집")

    cats = classify(openai, skills)
    valid = {"language", "framework", "tool", "database", "concept", "soft"}
    pairs = [{"name": k, "cat": v} for k, v in cats.items() if v in valid]
    c.execute_query(
        "UNWIND $pairs AS p MATCH (s:Skill {name: p.name}) SET s.category = p.cat",
        pairs=pairs,
    )
    print(f"category 저장: {len(pairs)}개")
    print("분포:", dict(Counter(v for v in cats.values() if v in valid)))
    print("soft(③ 제외 대상):", sorted(k for k, v in cats.items() if v == "soft"))
    c.close()
