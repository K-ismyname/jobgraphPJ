# 원천 jobs_filtered.json의 요건 원문을 JobPosting 노드 속성으로 백필
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from src.storage.neo4j_client import Neo4jClient

SRC = Path(__file__).resolve().parents[1] / "data" / "processed" / "jobs_filtered.json"


def main() -> None:
    recs = json.loads(SRC.read_text(encoding="utf-8"))
    if isinstance(recs, dict):
        recs = recs.get("jobs") or list(recs.values())[0]
    neo4j = Neo4jClient()
    n = 0
    for r in recs:
        sid = str(r.get("id") or "")
        if not sid:
            continue
        neo4j.set_posting_sections(sid, r.get("required_section") or "", r.get("preferred_section") or "")
        n += 1
    print(f"백필 완료: {n}개 공고")
    neo4j.close()


if __name__ == "__main__":
    main()
