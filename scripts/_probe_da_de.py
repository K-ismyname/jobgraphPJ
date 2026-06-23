# DA·DE 직군의 빈도 상위 핵심 스킬셋을 뽑아 교집합/차집합으로 구분 가능성 확인 (일회성 조사)
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

from src.storage.neo4j_client import Neo4jClient  # noqa: E402

TOP_N = 12

CORE = """
MATCH (:JobFamily {name: $fam})<-[:INSTANCE_OF]-(jp)-[:REQUIRES]->(s:Skill)
RETURN s.name AS skill, count(DISTINCT jp) AS w
ORDER BY w DESC
LIMIT $n
"""

FAMS = ["Data Analyst", "Data Engineer"]


def main() -> None:
    neo4j = Neo4jClient()
    sets: dict[str, list[tuple[str, int]]] = {}
    for fam in FAMS:
        rows = neo4j.execute_query(CORE, fam=fam, n=TOP_N)
        sets[fam] = [(r["skill"], int(r["w"] or 0)) for r in rows]
        print(f"\n=== {fam} 핵심 스킬 상위 {TOP_N} (스킬, 요구공고수) ===")
        for sk, w in sets[fam]:
            print(f"  {sk:<28} {w}")

    da = {s for s, _ in sets["Data Analyst"]}
    de = {s for s, _ in sets["Data Engineer"]}
    print(f"\n=== 교집합 (DA ∩ DE) {len(da & de)}개 ===")
    print("  " + ", ".join(sorted(da & de)) or "  (없음)")
    print(f"\n=== DA에만 {len(da - de)}개 ===")
    print("  " + (", ".join(sorted(da - de)) or "(없음)"))
    print(f"\n=== DE에만 {len(de - da)}개 ===")
    print("  " + (", ".join(sorted(de - da)) or "(없음)"))
    j = len(da & de) / len(da | de) if (da | de) else 0
    print(f"\n자카드 유사도(겹침 정도): {j:.2f}  (1=완전동일, 0=완전다름)")
    neo4j.close()


if __name__ == "__main__":
    main()
