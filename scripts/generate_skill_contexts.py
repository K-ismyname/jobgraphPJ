# 직군별 공고 데이터 + 공통 스킬 기반으로 면접 코칭 문서를 LLM으로 생성
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, ".")

from openai import OpenAI

from src.storage.neo4j_client import Neo4jClient

_GENERATE_PROMPT = """아래 스킬 목록에 대해 면접 코칭용 문서를 JSON으로 생성하세요.

각 스킬마다:
- purpose: 이 스킬이 해결하는 핵심 문제 (1-2문장)
- why_asked: 면접관이 이 스킬로 무엇을 확인하려 하는가 (1문장)
- core_concept: 이 스킬의 핵심 개념 키워드 3-5개 (쉼표 구분)
- adjacent_bridge: 이 스킬을 직접 써본 적 없는 사람이 Python·Docker·SQL·REST API 같은
  기초 기술 경험에서 핵심 개념을 어떻게 연결할 수 있는가 (1-2문장)

adjacent_bridge 규칙 (위반 금지):
- 이 스킬과 유사한 다른 전문 기술(예: Kafka → Flink, Spark)을 나열하지 말 것
  → 그 기술들도 못 써본 사람이면 연결이 안 됨
- 반드시 더 기초적인 경험(비동기 처리, 컨테이너화, SQL 쿼리 최적화, REST API 설계 등)에서
  "이 개념의 핵심 목적을 이미 경험해봤다"는 형태로 연결할 것
- "학습 계획"이나 "공부하면 된다" 같은 표현 금지

adjacent_bridge 예시:
- Kubernetes: "Docker로 컨테이너화 경험이 있다면 단일 컨테이너 → 다중 서비스 오케스트레이션의
  필요성을 이해한다고 연결 가능"
- Kafka: "FastAPI 비동기 엔드포인트나 Redis 큐를 써봤다면 이벤트 기반 비동기 패턴의
  목적은 이미 이해하고 있다고 연결 가능"

스킬 목록:
{skills}

출력 형식 (코드 펜스 없이):
{{
  "SkillName": {{
    "purpose": "...",
    "why_asked": "...",
    "core_concept": "...",
    "adjacent_bridge": "..."
  }}
}}"""


# 공고 수가 적어도 면접에 자주 나오는 중요 스킬
_EXTRA_SKILLS = {"MLflow", "Airflow", "Ray", "Triton", "RLHF", "LangChain", "LangGraph"}


def fetch_skills(neo4j: Neo4jClient) -> set[str]:
    rows = neo4j.execute_query("""
        MATCH (jf:JobFamily)<-[:INSTANCE_OF]-(jp:JobPosting)-[:REQUIRES]->(s:Skill)
        WITH jf.name AS family, s.name AS skill, count(DISTINCT jp) AS cnt
        ORDER BY family, cnt DESC
        WITH family, collect({skill: skill})[..15] AS top_skills
        RETURN top_skills
    """)
    skills: set[str] = set()
    for r in rows:
        for x in r["top_skills"]:
            skills.add(x["skill"])
    skills.update(neo4j.get_common_skills(threshold=5, n=15))
    skills.update(_EXTRA_SKILLS)
    return skills


def generate(skills: set[str]) -> dict:
    client = OpenAI()
    skill_list = "\n".join(f"- {s}" for s in sorted(skills))
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": _GENERATE_PROMPT.format(skills=skill_list)}],
        temperature=0,
    )
    raw = resp.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


def main() -> None:
    neo4j = Neo4jClient()
    skills = fetch_skills(neo4j)
    neo4j.close()
    print(f"스킬 {len(skills)}개 수집 완료. LLM 생성 중...")

    data = generate(skills)
    print(f"문서 {len(data)}개 생성 완료.")

    out_path = "data/seeds/skill_interview_context.json"
    os.makedirs("data/seeds", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"저장 완료: {out_path}")


if __name__ == "__main__":
    main()
