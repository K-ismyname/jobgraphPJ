# Neo4j 그래프 DB에 공고·이력서 데이터를 저장하는 클라이언트
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from openai import OpenAI
from neo4j import GraphDatabase

from src.extraction.skill_extractor import ResumeExtraction

# ── Cypher 쿼리 ─────────────────────────────────────────────────
CREATE_CONSTRAINTS = """
CREATE CONSTRAINT skill_name IF NOT EXISTS
    FOR (s:Skill) REQUIRE s.name IS UNIQUE;

CREATE CONSTRAINT posting_id IF NOT EXISTS
    FOR (p:JobPosting) REQUIRE p.source_id IS UNIQUE;

CREATE CONSTRAINT company_name IF NOT EXISTS
    FOR (c:Company) REQUIRE c.name IS UNIQUE;

CREATE CONSTRAINT job_family_name IF NOT EXISTS
    FOR (jf:JobFamily) REQUIRE jf.name IS UNIQUE;

CREATE CONSTRAINT portfolio_item_id IF NOT EXISTS
    FOR (pi:PortfolioItem) REQUIRE pi.item_id IS UNIQUE;
"""

UPSERT_COMPANY = """
MERGE (c:Company {name: $name})
ON CREATE SET c.posting_count = 1
ON MATCH  SET c.posting_count = c.posting_count + 1
RETURN c
"""

UPSERT_JOB_FAMILY = """
MERGE (jf:JobFamily {name: $name})
ON CREATE SET jf.posting_count = 1
ON MATCH  SET jf.posting_count = jf.posting_count + 1
RETURN jf
"""

LINK_POSTING_COMPANY = """
MATCH (jp:JobPosting {source_id: $source_id})
MATCH (c:Company {name: $company_name})
MERGE (jp)-[:POSTED_BY]->(c)
"""

LINK_POSTING_JOB_FAMILY = """
MATCH (jp:JobPosting {source_id: $source_id})
MATCH (jf:JobFamily {name: $job_family_name})
MERGE (jp)-[:INSTANCE_OF]->(jf)
"""

UPSERT_SKILL = """
MERGE (s:Skill {name: $name})
ON CREATE SET
    s.frequency = 1
ON MATCH SET
    s.frequency = s.frequency + 1
RETURN s
"""

UPSERT_POSTING = """
MERGE (p:JobPosting {source_id: $source_id})
ON CREATE SET
    p.title           = $title,
    p.job_family      = $job_family,
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

# 특정 job_title 공고들이 요구하는 스킬 빈도 집계
QUERY_TOP_SKILLS = """
MATCH (jp:JobPosting)-[:REQUIRES]->(s:Skill)
WHERE toLower(jp.title) CONTAINS toLower($job_title)
RETURN s.name AS skill, count(jp) AS count
ORDER BY count DESC
LIMIT $limit
"""

QUERY_SKILL_UNLOCK_COUNT = """
// 특정 스킬을 모두 보유할 경우 지원 가능한 공고 수
MATCH (jp:JobPosting)-[:REQUIRES]->(s:Skill)
WHERE s.name IN $skill_names
WITH jp, count(DISTINCT s) AS matched, size($skill_names) AS total
WHERE matched = total
RETURN count(jp) AS posting_count
"""

QUERY_MONTHLY_TREND = """
MATCH (jp:JobPosting)-[:REQUIRES]->(s:Skill {name: $skill_name})
WHERE jp.collected_month IS NOT NULL
RETURN jp.collected_month AS month, count(jp) AS count
ORDER BY month
"""

QUERY_LOCATION_DISTRIBUTION = """
MATCH (jp:JobPosting)
WHERE toLower(jp.title) CONTAINS toLower($job_title) AND jp.location <> ""
RETURN jp.location AS location, count(jp) AS count
ORDER BY count DESC
LIMIT $limit
"""

# 특정 스킬을 REQUIRES하는 JobPosting의 source_id 목록
QUERY_POSTINGS_FOR_SKILL = """
MATCH (jp:JobPosting)-[:REQUIRES]->(s:Skill)
WHERE toLower(s.name) = toLower($skill_name)
RETURN jp.source_id AS source_id,
       CASE WHEN jp.required_section IS NOT NULL AND jp.required_section <> '' THEN 0 ELSE 1 END AS priority
ORDER BY priority
LIMIT $limit
"""

# rel_type을 직접 포매팅. 호출부에서 항상 "REQUIRES" 또는 "PREFERS" 만 사용.
UPSERT_POSTING_SKILL_REL = """
MATCH (jp:JobPosting {{source_id: $source_id}})
MATCH (s:Skill {{name: $skill_name}})
MERGE (jp)-[r:{rel_type}]->(s)
ON CREATE SET r.weight = 1
ON MATCH  SET r.weight = r.weight + 1
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
ON CREATE SET s.frequency = 0

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

    def clear_all(self) -> None:
        """DB의 모든 노드·관계를 삭제한다."""
        with self._driver.session() as sess:
            sess.run("MATCH (n) DETACH DELETE n")
        print("DB 초기화 완료")

    def ingest_posting(self, posting: dict) -> None:
        """공고 1개를 그래프에 삽입."""
        source_id = posting["id"]
        company_name = posting.get("company", "")
        job_family_name = posting.get("job_family", "")
        skills = posting.get("skills", {})
        required_names: list[str] = skills.get("required", [])
        preferred_names: list[str] = skills.get("preferred", [])

        all_pairs: list[tuple[str, str]] = (
            [(name, "REQUIRES") for name in required_names]
            + [(name, "PREFERS") for name in preferred_names]
        )
        all_names = [name for name, _ in all_pairs]

        with self._driver.session() as sess:
            sess.run(UPSERT_POSTING,
                source_id=source_id,
                title=posting["title"],
                job_family=job_family_name,
                company=company_name,
                location=posting.get("location", ""),
                salary_min=posting.get("salary_min"),
                salary_max=posting.get("salary_max"),
                contract_type=posting.get("contract_type", ""),
                url=posting.get("url", ""),
                created=posting["created"],
                collected_month=datetime.now().strftime("%Y-%m"),
            )

            if company_name:
                sess.run(UPSERT_COMPANY, name=company_name)
                sess.run(LINK_POSTING_COMPANY, source_id=source_id, company_name=company_name)

            if job_family_name:
                sess.run(UPSERT_JOB_FAMILY, name=job_family_name)
                sess.run(LINK_POSTING_JOB_FAMILY, source_id=source_id, job_family_name=job_family_name)

            for skill_name, rel_type in all_pairs:
                sess.run(UPSERT_SKILL, name=skill_name)
                cypher = UPSERT_POSTING_SKILL_REL.format(rel_type=rel_type)
                sess.run(cypher, source_id=source_id, skill_name=skill_name)

            for i, name_a in enumerate(all_names):
                for name_b in all_names[i + 1:]:
                    try:
                        sess.run(UPSERT_CO_OCCURS, skill_a=name_a, skill_b=name_b)
                    except Exception as e:
                        print(f"[warn] CO_OCCURS 실패 ({name_a}, {name_b}): {e}")

        # 섹션 텍스트는 MERGE와 별도로 SET — 기존 공고도 업데이트 가능
        req = posting.get("required_section", "")
        pref = posting.get("preferred_section", "")
        if req or pref:
            self.set_posting_sections(source_id, req, pref)

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
                            evidence=skill.evidence,
                            confidence=skill.confidence,
                        )
                        print(f"  [{skill.confidence}] {section.title} → {skill.name}")
                    except Exception as e:
                        print(f"[warn] DEMONSTRATES 실패 ({skill.name}): {e}")

    def get_job_distribution(self) -> list[dict]:
        """타이틀 키워드별 공고 수 분포 (상위 20개)."""
        query = """
        MATCH (jp:JobPosting)
        RETURN jp.title AS title, count(*) AS count
        ORDER BY count DESC LIMIT 20
        """
        return self.execute_query(query)

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

    def get_portfolio_demonstrated_skills(self, owner: str) -> list:
        """Neo4j PortfolioItem에서 소유자의 DemonstratedSkill 목록 반환."""
        from src.extraction.skill_extractor import DemonstratedSkill
        query = """
        MATCH (:PortfolioItem {owner: $owner})-[d:DEMONSTRATES]->(s:Skill)
        RETURN s.name AS name, d.confidence AS confidence, d.evidence AS evidence
        """
        rows = self.execute_query(query, owner=owner)
        return [
            DemonstratedSkill(
                name=r["name"],
                confidence=r.get("confidence") or "low",
                evidence=r.get("evidence") or "",
            )
            for r in rows
        ]

    def list_job_families(self) -> list[str]:
        """등록된 직군명 목록 (유효성 검증·선택지 노출용)."""
        try:
            rows = self.execute_query(
                "MATCH (j:JobFamily) RETURN j.name AS name ORDER BY j.posting_count DESC"
            )
            return [r["name"] for r in rows if r.get("name")]
        except Exception as e:
            print(f"[neo4j] 직군 목록 조회 실패: {e}")
            return []

    def get_job_family_skills(
        self, job_family: str, exclude_common_threshold: int | None = 8
    ) -> list[str]:
        """직군의 상위 요구/우대 스킬명 (공고수 빈도순).

        exclude_common_threshold: 이 값 이상의 직군에 공통 등장하는 스킬은 제외.
            None이면 필터 없이 전체 반환. 기본값 8 = 9개 직군 중 8개 이상 등장한 스킬 제외.
        """
        if exclude_common_threshold is None:
            query = """
            MATCH (:JobFamily {name: $job_family})<-[:INSTANCE_OF]-(jp)-[:REQUIRES|PREFERS]->(s:Skill)
            RETURN s.name AS skill, count(jp) AS weight
            ORDER BY weight DESC
            LIMIT 30
            """
            params = {"job_family": job_family}
        else:
            query = """
            MATCH (:JobFamily {name: $job_family})<-[:INSTANCE_OF]-(jp)-[:REQUIRES|PREFERS]->(s:Skill)
            WITH s, count(DISTINCT jp) AS weight
            MATCH (jf2:JobFamily)<-[:INSTANCE_OF]-(:JobPosting)-[:REQUIRES|PREFERS]->(s)
            WITH s, weight, count(DISTINCT jf2) AS family_count
            WHERE family_count < $threshold
            RETURN s.name AS skill, weight
            ORDER BY weight DESC
            LIMIT 30
            """
            params = {"job_family": job_family, "threshold": exclude_common_threshold}
        try:
            from src.extraction.normalizer import normalize_skill, is_noise_skill
            rows = self.execute_query(query, **params)
            seen: set[str] = set()
            result: list[str] = []
            for r in rows:
                raw = r.get("skill")
                if not raw:
                    continue
                normalized = normalize_skill(raw)
                if is_noise_skill(normalized) or normalized in seen:
                    continue
                seen.add(normalized)
                result.append(normalized)
                if len(result) >= 30:
                    break
            return result
        except Exception as e:
            print(f"[neo4j] 직군 스킬 조회 실패: {e}")
            return []

    def get_common_skills(self, threshold: int = 5, n: int = 10) -> list[str]:
        """threshold개 이상 직군에 공통 등장하는 기초 스킬 (공고 수 많은 순 상위 n개)."""
        query = """
        MATCH (jp:JobPosting)-[:INSTANCE_OF]->(jf:JobFamily)
        MATCH (jp)-[:REQUIRES]->(s:Skill)
        WITH s, count(DISTINCT jf) AS family_count, count(DISTINCT jp) AS posting_count
        WHERE family_count >= $threshold
        RETURN s.name AS skill
        ORDER BY posting_count DESC
        LIMIT $n
        """
        try:
            from src.extraction.normalizer import normalize_skill, is_noise_skill
            rows = self.execute_query(query, threshold=threshold, n=n)
            seen: set[str] = set()
            result: list[str] = []
            for r in rows:
                raw = r.get("skill")
                if not raw:
                    continue
                normalized = normalize_skill(raw)
                if is_noise_skill(normalized) or normalized in seen:
                    continue
                seen.add(normalized)
                result.append(normalized)
            return result
        except Exception as e:
            print(f"[neo4j] 공통 스킬 조회 실패: {e}")
            return []

    def get_co_occurring_skills(self, skills: list[str], top_n: int = 8) -> list[str]:
        """주어진 스킬들과 CO_OCCURS로 함께 등장하는 스킬을 가중치 상위로(입력 제외)."""
        if not skills:
            return []
        query = """
        MATCH (s:Skill)-[r:CO_OCCURS]-(o:Skill)
        WHERE s.name IN $skills AND NOT o.name IN $skills
        RETURN o.name AS skill, sum(r.count) AS w
        ORDER BY w DESC
        LIMIT $n
        """
        try:
            rows = self.execute_query(query, skills=skills, n=top_n)
            return [r["skill"] for r in rows if r.get("skill")]
        except Exception as e:
            print(f"[neo4j] CO_OCCURS 조회 실패: {e}")
            return []

    def recommend_job_postings(self, skills: list[str], top_n: int = 5, min_required: int = 4) -> list[dict]:
        """보유 스킬과 매칭률이 높은 채용공고 상위 N개를 반환한다.

        min_required: 요구 스킬이 이 수 미만인 공고는 제외 (노이즈 방지).
        """
        if not skills:
            return []
        query = """
        WITH $skills AS portfolio
        MATCH (jp:JobPosting)-[:REQUIRES]->(s:Skill)
        WHERE s.name IN portfolio
        WITH jp, count(DISTINCT s) AS matched
        MATCH (jp)-[:REQUIRES]->(ts:Skill)
        WITH jp, matched, count(DISTINCT ts) AS total
        WHERE total >= $min_required
        MATCH (jp)-[:POSTED_BY]->(c:Company)
        MATCH (jp)-[:INSTANCE_OF]->(jf:JobFamily)
        RETURN jp.title AS title, c.name AS company, jp.url AS url,
               jf.name AS job_family, matched, total,
               round(toFloat(matched) / total * 100) AS match_pct
        ORDER BY match_pct DESC, matched DESC
        LIMIT $n
        """
        try:
            rows = self.execute_query(query, skills=skills, n=top_n, min_required=min_required)
            return [
                {
                    "title": r["title"],
                    "company": r["company"],
                    "job_family": r["job_family"],
                    "match_pct": r["match_pct"],
                    "matched": r["matched"],
                    "total": r["total"],
                    "url": r["url"],
                }
                for r in rows
            ]
        except Exception as e:
            print(f"[neo4j] 공고 추천 조회 실패: {e}")
            return []

    def update_portfolio_confidence(self, owner: str, changes: dict[str, str]) -> None:
        """confidence 레벨을 업데이트한다. changes: {"LangChain": "medium → high"}."""
        query = """
        MATCH (:PortfolioItem {owner: $owner})-[d:DEMONSTRATES]->(s:Skill {name: $skill})
        SET d.confidence = $new_confidence
        """
        with self._driver.session() as sess:
            for skill, change in changes.items():
                new_confidence = change.split("→")[-1].strip()
                try:
                    sess.run(query, owner=owner, skill=skill, new_confidence=new_confidence)
                except Exception as e:
                    print(f"[warn] confidence 업데이트 실패 ({skill}): {e}")

    def set_posting_sections(self, source_id: str, required: str, preferred: str) -> None:
        """공고 노드에 요건 원문(필수·우대)을 속성으로 저장한다."""
        try:
            self.execute_query(
                "MATCH (p:JobPosting {source_id: $source_id}) "
                "SET p.required_section = $required, p.preferred_section = $preferred",
                source_id=source_id, required=required or "", preferred=preferred or "",
            )
        except Exception as e:
            print(f"[neo4j] 공고 원문 저장 실패({source_id}): {e}")

    def get_posting_sections(self, source_ids: list[str]) -> list[dict]:
        """source_id 목록의 공고 요건 원문을 가져온다."""
        try:
            return self.execute_query(
                "MATCH (p:JobPosting) WHERE p.source_id IN $ids "
                "RETURN p.source_id AS source_id, p.company AS company, "
                "p.required_section AS required_section, p.preferred_section AS preferred_section",
                ids=source_ids,
            )
        except Exception as e:
            print(f"[neo4j] 공고 원문 조회 실패: {e}")
            return []

    def get_postings_requiring_skill(self, skill_name: str, limit: int = 5) -> list[str]:
        """특정 스킬을 REQUIRES하는 JobPosting의 source_id 목록을 반환한다."""
        rows = self.execute_query(QUERY_POSTINGS_FOR_SKILL, skill_name=skill_name, limit=limit)
        return [r["source_id"] for r in rows]

    def get_skill_trend(self, skill_name: str, window_days: int = 30) -> dict:
        """최근 N일 vs 이전 N일 공고 등장 횟수를 비교해 트렌드를 반환한다.

        posted_at이 없거나 비교 불가한 경우 delta_pct=0으로 반환한다.
        """
        # posted_at은 Neo4j datetime 타입이므로 cutoff 문자열도 datetime()으로 캐스팅해야 비교된다.
        query = """
        MATCH (s:Skill)<-[:REQUIRES]-(jp:JobPosting)
        WHERE toLower(s.name) = toLower($skill_name)
          AND jp.posted_at IS NOT NULL
        WITH jp.posted_at AS posted_at
        WITH
          sum(CASE WHEN posted_at >= datetime($recent_cutoff) THEN 1 ELSE 0 END) AS recent_count,
          sum(CASE WHEN posted_at >= datetime($prev_cutoff) AND posted_at < datetime($recent_cutoff) THEN 1 ELSE 0 END) AS prev_count
        RETURN recent_count, prev_count
        """
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        recent_cutoff = (now - timedelta(days=window_days)).isoformat()
        prev_cutoff = (now - timedelta(days=window_days * 2)).isoformat()

        try:
            rows = self.execute_query(
                query,
                skill_name=skill_name,
                recent_cutoff=recent_cutoff,
                prev_cutoff=prev_cutoff,
            )
            if not rows:
                return {"skill": skill_name, "recent_count": 0, "prev_count": 0, "delta_pct": 0.0}
            recent = rows[0].get("recent_count") or 0
            prev = rows[0].get("prev_count") or 0
            delta = round(((recent - prev) / prev * 100) if prev > 0 else 0.0, 1)
            return {"skill": skill_name, "recent_count": recent, "prev_count": prev, "delta_pct": delta}
        except Exception as e:
            return {"skill": skill_name, "recent_count": 0, "prev_count": 0, "delta_pct": 0.0, "error": str(e)}

    def execute_query(self, query: str, **params) -> list[dict]:
        """임의 Cypher 쿼리 실행."""
        with self._driver.session() as s:
            result = s.run(query, **params)
            return [dict(row) for row in result]
