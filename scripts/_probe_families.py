# 직군별 공고 수와 핵심 스킬 품질을 한눈에 — "스킬을 못 잡는" 원인이 데이터 부족인지 추출 노이즈인지 진단 (일회성)
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

from src.storage.neo4j_client import Neo4jClient  # noqa: E402

COUNTS = """
MATCH (f:JobFamily)
OPTIONAL MATCH (f)<-[:INSTANCE_OF]-(jp:JobPosting)
RETURN f.name AS fam, count(DISTINCT jp) AS postings
ORDER BY postings DESC
"""
TOP = """
MATCH (:JobFamily {name: $fam})<-[:INSTANCE_OF]-(jp)-[:REQUIRES]->(s:Skill)
RETURN s.name AS skill, count(DISTINCT jp) AS w
ORDER BY w DESC LIMIT 8
"""


def main() -> None:
    neo4j = Neo4jClient()
    rows = neo4j.execute_query(COUNTS)
    print("=== 직군별 공고 수 ===")
    for r in rows:
        print(f"  {r['fam']:<22} {r['postings']:>4}")
    print("\n=== 직군별 핵심 스킬 상위 8 (공고수) ===")
    for r in rows:
        top = neo4j.execute_query(TOP, fam=r["fam"])
        s = ", ".join(f"{t['skill']}({t['w']})" for t in top)
        print(f"  {r['fam']:<22} {s}")
    neo4j.close()


if __name__ == "__main__":
    main()
