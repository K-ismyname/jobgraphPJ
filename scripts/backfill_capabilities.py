# Neo4j의 모든 Skill 중 시드에 없는 것을 11개 역량으로 LLM 일괄 분류 → JSON 저장
import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from openai import OpenAI

from src.analysis.capability import SEED_CAPABILITIES, _JSON_PATH
from src.storage.neo4j_client import Neo4jClient

CAPS = list(SEED_CAPABILITIES.keys()) + ["other"]


def main() -> None:
    neo4j = Neo4jClient()
    rows = neo4j.execute_query("MATCH (s:Skill) RETURN s.name AS name")
    seeded = {s for ss in SEED_CAPABILITIES.values() for s in ss}
    todo = sorted({r["name"] for r in rows if r["name"] and r["name"].lower() not in seeded})
    print(f"미매핑 스킬 {len(todo)}개 분류")

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    result: dict[str, str] = {}
    batch = 60
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        prompt = (
            f"다음 기술 스킬들을 아래 역량 중 하나로 분류해 JSON(스킬명:역량)으로만 답하세요.\n"
            f"역량: {', '.join(CAPS)}\n"
            f"애매하면 other. 스킬: {json.dumps(chunk, ensure_ascii=False)}"
        )
        raw = client.chat.completions.create(
            model="gpt-4o-mini", temperature=0,
            messages=[{"role": "user", "content": prompt}],
        ).choices[0].message.content
        raw = raw.replace("```json", "").replace("```", "").strip()
        try:
            for k, v in json.loads(raw).items():
                result[k.lower()] = v if v in CAPS else "other"
        except json.JSONDecodeError:
            print(f"  [skip] 배치 {i} 파싱 실패")
        print(f"  {min(i + batch, len(todo))}/{len(todo)}")

    _JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    _JSON_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장: {_JSON_PATH} ({len(result)}개)")
    neo4j.close()


if __name__ == "__main__":
    main()
