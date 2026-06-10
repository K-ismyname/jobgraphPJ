# Neo4j 그래프 DB에 공고·이력서 데이터를 저장하는 클라이언트
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from openai import OpenAI
from neo4j import GraphDatabase

from src.extraction.normalizer import normalize_job_title
from src.extraction.skill_extractor import ResumeExtraction

# ── Cypher 쿼리 ─────────────────────────────────────────────────
CREATE_CONSTRAINTS = """
CREATE CONSTRAINT job_title IF NOT EXISTS
    FOR (j:Job) REQUIRE j.normalized_title IS UNIQUE;

CREATE CONSTRAINT skill_name IF NOT EXISTS
    FOR (s:Skill) REQUIRE s.name IS UNIQUE;

CREATE CONSTRAINT posting_id IF NOT EXISTS
    FOR (p:JobPosting) REQUIRE p.source_id IS UNIQUE;

CREATE CONSTRAINT portfolio_item_id IF NOT EXISTS
    FOR (pi:PortfolioItem) REQUIRE pi.item_id IS UNIQUE;
"""

UPSERT_JOB = """
MERGE (j:Job {normalized_title: $normalized_title})
ON CREATE SET
    j.aliases       = [$raw_title],
    j.posting_count = 1,
    j.updated_at    = datetime()
ON MATCH SET
    j.aliases = CASE
        WHEN NOT $raw_title IN j.aliases
        THEN j.aliases + [$raw_title]
        ELSE j.aliases
    END,
    j.posting_count = coalesce(j.posting_count, 0) + 1,
    j.updated_at    = datetime()
RETURN j
"""

UPSERT_SKILL = """
MERGE (s:Skill {name: $name})
ON CREATE SET
    s.category  = $category,
    s.frequency = 1,
    s.aliases   = [$raw]
ON MATCH SET
    s.frequency = s.frequency + 1,
    s.aliases   = CASE
        WHEN NOT $raw IN s.aliases
        THEN s.aliases + [$raw]
        ELSE s.aliases
    END
RETURN s
"""

UPSERT_POSTING = """
MERGE (p:JobPosting {source_id: $source_id})
ON CREATE SET
    p.title           = $title,
    p.company         = $company,
    p.location        = $location,
    p.salary_min      = $salary_min,
    p.salary_max      = $salary_max,
    p.contract_type   = $contract_type,
    p.url             = $url,
    p.posted_at       = datetime($created),
    p.collected_month = $collected_month,
    p.is_active       = true
RETURN p
"""

# ── 시장 인사이트 쿼리 ──────────────────────────────────────────

QUERY_JOB_DISTRIBUTION = """
MATCH (j:Job)
RETURN j.normalized_title AS job, j.posting_count AS count
ORDER BY count DESC
"""

QUERY_TOP_SKILLS = """
MATCH (j:Job {normalized_title: $job_title})-[r:REQUIRES]->(s:Skill)
RETURN s.name AS skill, s.category AS category, r.weight AS count
ORDER BY count DESC
LIMIT $limit
"""

QUERY_SKILL_UNLOCK_COUNT = """
// 특정 스킬을 보유할 경우 지원 가능한 공고 수
MATCH (j:Job)-[:REQUIRES]->(s:Skill)
WHERE s.name IN $skill_names
WITH j, count(DISTINCT s) AS matched, size($skill_names) AS total
WHERE matched = total
MATCH (jp:JobPosting)-[:INSTANCE_OF]->(j)
RETURN count(jp) AS posting_count
"""

QUERY_MONTHLY_TREND = """
// 월별 특정 스킬 등장 공고 수 (지원 타이밍 분석용)
MATCH (jp:JobPosting)-[:INSTANCE_OF]->(j:Job)-[:REQUIRES]->(s:Skill {name: $skill_name})
WHERE jp.collected_month IS NOT NULL
RETURN jp.collected_month AS month, count(jp) AS count
ORDER BY month
"""

QUERY_LOCATION_DISTRIBUTION = """
MATCH (jp:JobPosting)-[:INSTANCE_OF]->(j:Job {normalized_title: $job_title})
WHERE jp.location <> ""
RETURN jp.location AS location, count(jp) AS count
ORDER BY count DESC
LIMIT $limit
"""

# 특정 스킬을 REQUIRES하는 JobPosting의 source_id 목록
QUERY_POSTINGS_FOR_SKILL = """
MATCH (jp:JobPosting)-[:INSTANCE_OF]->(j:Job)-[:REQUIRES]->(s:Skill)
WHERE toLower(s.name) = toLower($skill_name)
RETURN jp.source_id AS source_id
LIMIT $limit
"""

# rel_type을 직접 포매팅. 호출부에서 항상 "REQUIRES" 또는 "PREFERS" 만 사용.
UPSERT_JOB_SKILL_REL = """
MATCH (j:Job {{normalized_title: $normalized_title}})
MATCH (s:Skill {{name: $skill_name}})
MERGE (j)-[r:{rel_type}]->(s)
ON CREATE SET r.weight = 1
ON MATCH  SET r.weight = r.weight + 1
"""

LINK_POSTING_JOB = """
MATCH (p:JobPosting {source_id: $source_id})
MATCH (j:Job {normalized_title: $normalized_title})
MERGE (p)-[:INSTANCE_OF]->(j)
"""

UPSERT_CO_OCCURS = """
MATCH (a:Skill {name: $skill_a})
MATCH (b:Skill {name: $skill_b})
MERGE (a)-[r:CO_OCCURS]-(b)
ON CREATE SET r.count = 1
ON MATCH  SET r.count = r.count + 1
"""

UPSERT_PORTFOLIO_ITEM = """
MERGE (pi:PortfolioItem {item_id: $item_id})
ON CREATE SET
    pi.title       = $title,
    pi.type        = $section_type,
    pi.owner       = $owner,
    pi.created_at  = datetime()
ON MATCH SET
    pi.updated_at  = datetime()
RETURN pi
"""

UPSERT_DEMONSTRATES = """
MERGE (s:Skill {name: $skill_name})
ON CREATE SET s.category = $category, s.frequency = 0

MERGE (pi:PortfolioItem {item_id: $item_id})

MERGE (pi)-[r:DEMONSTRATES]->(s)
ON CREATE SET
    r.evidence   = $evidence,
    r.confidence = $confidence
ON MATCH SET
    r.evidence   = $evidence,
    r.confidence = $confidence
"""

UPSERT_PART_OF = """
MERGE (a:Skill {name: $from_skill})
MERGE (b:Skill {name: $to_skill})
MERGE (a)-[r:PART_OF]->(b)
ON CREATE SET r.relation = $relation
"""


class Neo4jClient:
    def __init__(self) -> None:
        uri = os.getenv("NEO4J_URI")
        if not uri:
            raise EnvironmentError(
                "NEO4J_URI 환경변수가 필요합니다. "
                "Neo4j Aura 무료 티어에서 발급 후 .env에 추가하세요.\n"
                "  NEO4J_URI=neo4j+s://xxxx.databases.neo4j.io\n"
                "  NEO4J_USER=neo4j\n"
                "  NEO4J_PASSWORD=your_password"
            )
        user = os.getenv("NEO4J_USERNAME") or os.getenv("NEO4J_USER", "neo4j")
        pwd = os.getenv("NEO4J_PASSWORD", "")
        self._driver = GraphDatabase.driver(uri, auth=(user, pwd))

    def close(self) -> None:
        self._driver.close()

    def setup_constraints(self) -> None:
        """유니크 제약조건 설정. 최초 1회 실행."""
        with self._driver.session() as s:
            for stmt in CREATE_CONSTRAINTS.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    try:
                        s.run(stmt)
                    except Exception as e:
                        print(f"  제약조건 (이미 있으면 무시): {e}")
        print("제약조건 설정 완료")

    def load_skill_seeds(self, seeds_path: str = "data/seeds/skill_relations.json") -> None:
        """PART_OF 관계 시드 데이터를 Neo4j에 로드."""
        path = Path(seeds_path)
        if not path.exists():
            raise FileNotFoundError(f"시드 파일 없음: {seeds_path}")

        with open(path, encoding="utf-8") as f:
            seeds: list[dict] = json.load(f)

        with self._driver.session() as sess:
            for seed in seeds:
                sess.run(UPSERT_PART_OF,
                    from_skill=seed["from"],
                    to_skill=seed["to"],
                    relation=seed["relation"],
                )
        print(f"PART_OF 시드 {len(seeds)}개 로드 완료")

    def ingest_posting(
        self, posting: dict, openai_client: OpenAI | None = None
    ) -> None:
        """공고 1개를 그래프에 삽입. Job·Skill·CO_OCCURS 노드/관계 생성."""
        raw_title = posting["title"]
        normalized_title = normalize_job_title(raw_title, openai_client)
        print(f"\n처리 중: '{raw_title}' → '{normalized_title}'")

        all_skills: list[tuple[dict, str]] = (
            [(s, "REQUIRES") for s in posting["skills"]["required"]]
            + [(s, "PREFERS") for s in posting["skills"]["preferred"]]
        )
        all_skill_names = [s["name"] for s, _ in all_skills]

        company = posting.get("company", "")
        if isinstance(company, dict):
            company = company.get("display_name", "")

        location = posting.get("location", "")
        if isinstance(location, dict):
            location = location.get("display_name", "")

        with self._driver.session() as sess:
            sess.run(UPSERT_JOB, normalized_title=normalized_title, raw_title=raw_title)
            sess.run(UPSERT_POSTING,
                source_id=posting["id"],
                title=raw_title,
                company=company,
                location=location,
                salary_min=posting.get("salary_min"),
                salary_max=posting.get("salary_max"),
                contract_type=posting.get("contract_type", ""),
                url=posting.get("url", ""),
                created=posting["created"],
                collected_month=datetime.now().strftime("%Y-%m"),
            )
            sess.run(LINK_POSTING_JOB,
                source_id=posting["id"], normalized_title=normalized_title)

            for skill, rel_type in all_skills:
                sess.run(UPSERT_SKILL,
                    name=skill["name"], category=skill["category"], raw=skill["raw"])
                cypher = UPSERT_JOB_SKILL_REL.format(rel_type=rel_type)
                sess.run(cypher, normalized_title=normalized_title, skill_name=skill["name"])
                print(f"  [{rel_type}] {normalized_title} → {skill['name']}")

            for i, name_a in enumerate(all_skill_names):
                for name_b in all_skill_names[i + 1:]:
                    try:
                        sess.run(UPSERT_CO_OCCURS, skill_a=name_a, skill_b=name_b)
                    except Exception as e:
                        print(f"[warn] CO_OCCURS 실패 ({name_a}, {name_b}): {e}")

        print(f"  CO_OCCURS {len(all_skill_names) * (len(all_skill_names) - 1) // 2}개 생성")

    def save_portfolio(self, extraction: ResumeExtraction) -> None:
        """이력서 추출 결과를 PortfolioItem + DEMONSTRATES 관계로 Neo4j에 저장."""
        with self._driver.session() as sess:
            for section in extraction.sections:
                item_id = hashlib.md5(
                    f"{extraction.candidate_name}_{section.title}".encode()
                ).hexdigest()[:12]

                sess.run(UPSERT_PORTFOLIO_ITEM,
                    item_id=item_id,
                    title=section.title,
                    section_type=section.section_type,
                    owner=extraction.candidate_name,
                )

                for skill in section.skills:
                    try:
                        sess.run(UPSERT_DEMONSTRATES,
                            item_id=item_id,
                            skill_name=skill.name,
                            category=skill.category,
                            evidence=skill.evidence,
                            confidence=skill.confidence,
                        )
                        print(f"  [{skill.confidence}] {section.title} → {skill.name}")
                    except Exception as e:
                        print(f"[warn] DEMONSTRATES 실패 ({skill.name}): {e}")

    def get_job_distribution(self) -> list[dict]:
        """직무별 공고 수 분포."""
        return self.execute_query(QUERY_JOB_DISTRIBUTION)

    def get_top_skills(self, job_title: str, limit: int = 15) -> list[dict]:
        """특정 직무에서 가장 많이 요구되는 스킬 순위."""
        return self.execute_query(QUERY_TOP_SKILLS, job_title=job_title, limit=limit)

    def get_skill_unlock_count(self, skill_names: list[str]) -> int:
        """주어진 스킬 목록을 모두 보유할 때 지원 가능한 공고 수."""
        result = self.execute_query(QUERY_SKILL_UNLOCK_COUNT, skill_names=skill_names)
        return result[0]["posting_count"] if result else 0

    def get_monthly_trend(self, skill_name: str) -> list[dict]:
        """월별 특정 스킬 등장 공고 수 (지원 타이밍 분석)."""
        return self.execute_query(QUERY_MONTHLY_TREND, skill_name=skill_name)

    def get_location_distribution(self, job_title: str, limit: int = 10) -> list[dict]:
        """직무별 지역 분포."""
        return self.execute_query(QUERY_LOCATION_DISTRIBUTION, job_title=job_title, limit=limit)

    def get_postings_requiring_skill(self, skill_name: str, limit: int = 5) -> list[str]:
        """특정 스킬을 REQUIRES하는 JobPosting의 source_id 목록을 반환한다."""
        rows = self.execute_query(QUERY_POSTINGS_FOR_SKILL, skill_name=skill_name, limit=limit)
        return [r["source_id"] for r in rows]

    def execute_query(self, query: str, **params) -> list[dict]:
        """임의 Cypher 쿼리 실행."""
        with self._driver.session() as s:
            result = s.run(query, **params)
            return [dict(row) for row in result]
