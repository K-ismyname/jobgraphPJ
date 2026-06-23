# Frontend 직군의 핵심 역량 6개와 그 근거 스킬을 뽑아 ml_ai/cloud가 왜 들어갔는지 확인 (일회성)
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

from src.analysis.capability import _cap_map, job_family_core_capabilities  # noqa: E402
from src.extraction.normalizer import normalize_skill  # noqa: E402
from src.storage.neo4j_client import Neo4jClient  # noqa: E402

FAM = "Frontend Engineer"
CORE = """
MATCH (:JobFamily {name: $fam})<-[:INSTANCE_OF]-(jp)-[:REQUIRES]->(s:Skill)
RETURN s.name AS skill, count(DISTINCT jp) AS w
ORDER BY w DESC
"""


def main() -> None:
    neo4j = Neo4jClient()
    m = _cap_map()
    rows = neo4j.execute_query(CORE, fam=FAM)
    print(f"=== {FAM} REQUIRES 스킬 상위 20 (스킬, 공고수, 역량) ===")
    for r in rows[:20]:
        sk = r["skill"]
        cap = m.get(sk.lower()) or m.get(normalize_skill(sk).lower()) or "(미분류)"
        print(f"  {sk:<22} {r['w']:>3}  → {cap}")

    # 역량별 가중 합산
    capw: dict[str, int] = {}
    cap_skills: dict[str, list] = {}
    for r in rows:
        sk = r["skill"]
        cap = m.get(sk.lower()) or m.get(normalize_skill(sk).lower())
        if cap and cap != "other":
            capw[cap] = capw.get(cap, 0) + int(r["w"])
            cap_skills.setdefault(cap, []).append((sk, int(r["w"])))
    print(f"\n=== 역량별 가중 합산 (공고수 기준 내림차순) ===")
    for cap, w in sorted(capw.items(), key=lambda x: -x[1]):
        top = ", ".join(f"{s}({n})" for s, n in sorted(cap_skills[cap], key=lambda x: -x[1])[:5])
        print(f"  {cap:<12} {w:>3}  ← {top}")

    print(f"\n=== 실제 핵심 역량 6개 (job_family_core_capabilities) ===")
    print("  " + ", ".join(job_family_core_capabilities(neo4j, FAM)))
    neo4j.close()


if __name__ == "__main__":
    main()
