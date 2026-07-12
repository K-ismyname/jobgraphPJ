# Neo4j 그래프 DB에 공고·이력서 데이터를 저장하는 클라이언트
#
# 이 파일이 하는 일: pipeline.py의 Step 3(step_ingest)가 호출하는 실제 DB 작업자.
# 지금까지 본 preprocessor.py(텍스트 정제)·skill_extractor.py(LLM 추출)·normalizer.py(표기 통일)를
# 거쳐 완성된 공고 dict를 받아서, 실제로 Neo4j에 노드(:JobPosting, :Skill, :Company 등)와
# 관계(REQUIRES, PREFERS, POSTED_BY 등)를 만들어 저장하는 마지막 단계.
#
# 파일 앞부분(문자열 상수들)은 전부 "Cypher"라는 Neo4j 전용 쿼리 언어로 짜여 있다.
# SQL의 그래프 DB 버전이라고 생각하면 됨 — SELECT 대신 MATCH, INSERT 대신 CREATE/MERGE를 씀.
#
# 이 파일의 절반 이상(get_top_skills 이후의 "시장 인사이트" 메서드들)은 pipeline.py Step 3에서
# 쓰이지 않는다 — 아직 우리가 안 본 src/agent/, src/api/ 레이어가 나중에 이 메서드들을 호출해서
# "이 스킬을 가지면 몇 개 공고에 지원 가능한가" 같은 질문에 답하는 용도로 쓴다.

import json       # 시드 파일(skill_relations.json) 읽을 때 사용
import logging    # print() 대신 로그 레벨(warning/error)을 구분해 남기는 표준 라이브러리
import os         # 환경변수(NEO4J_URI 등) 읽기
from datetime import datetime  # 적재 시각(연-월)을 기록할 때 사용
from pathlib import Path

from openai import OpenAI  # 이 파일에서 실제로 사용되진 않지만 타입 힌트 등을 위해 남아있는 것으로 보임
from neo4j import GraphDatabase
# neo4j 공식 파이썬 드라이버 — GraphDatabase.driver(주소, 인증정보)로 DB와 연결을 맺는 객체를 만듦

logger = logging.getLogger("jobgraph.storage")
# 이 파일 전용 로거 생성. print()와 달리 나중에 "이 로그는 storage 관련이다"라고 필터링하거나
# 로그 레벨(warning/error)에 따라 다르게 처리할 수 있음

# 프로젝트 루트 — 시드 등 데이터 파일을 CWD와 무관하게 절대경로로 해석
ROOT = Path(__file__).resolve().parents[2]
# parents[2] → .parent.parent와 같은 뜻이지만 인덱스로 표현한 것. src/storage/neo4j_client.py 기준
# parents[0]=src/storage, parents[1]=src, parents[2]=프로젝트 루트

# ── Cypher 쿼리 ─────────────────────────────────────────────────
# 아래는 전부 "쿼리 문자열"을 미리 만들어 상수로 저장해두는 부분.
# 실행 코드(클래스 메서드)에서 이 문자열들을 재사용하면서 $변수명 자리에 실제 값을 끼워 넣는 방식으로 동작함.

CREATE_CONSTRAINTS = """
CREATE CONSTRAINT skill_name IF NOT EXISTS
    FOR (s:Skill) REQUIRE s.name IS UNIQUE;

CREATE CONSTRAINT posting_id IF NOT EXISTS
    FOR (p:JobPosting) REQUIRE p.source_id IS UNIQUE;

CREATE CONSTRAINT company_name IF NOT EXISTS
    FOR (c:Company) REQUIRE c.name IS UNIQUE;

CREATE CONSTRAINT job_family_name IF NOT EXISTS
    FOR (jf:JobFamily) REQUIRE jf.name IS UNIQUE;
"""
# CREATE CONSTRAINT ... IF NOT EXISTS → "이미 있으면 그냥 넘어가고, 없으면 만들어라"
# FOR (s:Skill) REQUIRE s.name IS UNIQUE → ":Skill 타입 노드는 name 속성이 절대 중복되면 안 된다"는 규칙
# 이 제약이 있어야 나중에 MERGE(있으면 찾고 없으면 생성)가 name 기준으로 정확히 동작함 —
# 제약이 없으면 같은 이름의 Skill 노드가 실수로 여러 개 생길 수 있음

UPSERT_COMPANY = """
MERGE (c:Company {name: $name})
ON CREATE SET c.posting_count = 1
ON MATCH  SET c.posting_count = c.posting_count + 1
RETURN c
"""
# MERGE (c:Company {name: $name}) → name이 $name인 Company 노드를 찾고, 없으면 새로 만듦 ("upsert"의 그래프 버전)
# ON CREATE SET → 방금 새로 만들어졌을 때만 실행 (posting_count를 1로 초기화)
# ON MATCH SET  → 이미 있던 노드를 찾았을 때만 실행 (posting_count를 1 증가)
# $name 처럼 $로 시작하는 건 "파라미터" — 실행할 때 sess.run(쿼리, name="실제값") 형태로 값을 주입함
# (문자열을 직접 이어붙이지 않고 파라미터로 분리하는 이유: SQL 인젝션과 비슷한 공격을 막고, 값에 특수문자가 있어도 안전함)

UPSERT_JOB_FAMILY = """
MERGE (jf:JobFamily {name: $name})
ON CREATE SET jf.posting_count = 1
ON MATCH  SET jf.posting_count = jf.posting_count + 1
RETURN jf
"""
# UPSERT_COMPANY와 완전히 같은 패턴, 대상만 Company → JobFamily로 바뀜

LINK_POSTING_COMPANY = """
MATCH (jp:JobPosting {source_id: $source_id})
MATCH (c:Company {name: $company_name})
MERGE (jp)-[:POSTED_BY]->(c)
"""
# MATCH는 "이미 존재하는 걸 찾기만" 함 (MERGE와 달리 없으면 안 만들고 그냥 결과가 없음)
# 이미 만들어진 JobPosting 노드와 Company 노드를 각각 찾아서, 그 사이에 POSTED_BY 관계를 만듦(없으면 생성, 있으면 유지)

LINK_POSTING_JOB_FAMILY = """
MATCH (jp:JobPosting {source_id: $source_id})
MATCH (jf:JobFamily {name: $job_family_name})
MERGE (jp)-[:INSTANCE_OF]->(jf)
"""
# 공고와 직군 사이에 INSTANCE_OF 관계 연결 — pipeline.py의 _job_family()가 판별한 직군명이 여기로 들어옴

UPSERT_SKILL = """
MERGE (s:Skill {name: $name})
ON CREATE SET
    s.frequency = 1
ON MATCH SET
    s.frequency = s.frequency + 1
RETURN s
"""
# 스킬 노드도 Company/JobFamily와 동일 패턴 — 처음 보는 스킬이면 frequency=1로 시작, 이미 있으면 +1

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
# 다른 UPSERT들과 다르게 ON MATCH SET이 없음 — 즉 이미 있는 공고를 재적재할 때는
# title/company/location 등 속성을 다시 덮어쓰지 않고 그대로 둠 (최초 생성 시점 값을 유지)
# datetime($created) → Cypher의 datetime() 함수로 문자열을 Neo4j 전용 날짜 타입으로 변환해서 저장
# (문자열로 그냥 저장하면 나중에 "최근 N일" 같은 날짜 비교 쿼리를 할 수 없어서 타입 변환이 필요)

# ── 시장 인사이트 쿼리 ──────────────────────────────────────────
# 여기부터의 쿼리들은 pipeline.py의 적재(Step 3) 과정에서 쓰이는 게 아니라,
# 데이터가 다 쌓인 뒤 "이 그래프에게 질문을 던지는" 조회 전용 쿼리들이다.
# 아래쪽 클래스 메서드 중 get_top_skills, get_skill_unlock_count 등에서 사용됨.

# 특정 job_title 공고들이 요구하는 스킬 빈도 집계
QUERY_TOP_SKILLS = """
MATCH (jp:JobPosting)-[:REQUIRES]->(s:Skill)
WHERE toLower(jp.title) CONTAINS toLower($job_title)
RETURN s.name AS skill, count(jp) AS count
ORDER BY count DESC
LIMIT $limit
"""
# toLower(...)로 대소문자 무시 비교, CONTAINS는 부분 문자열 포함 여부 (SQL의 LIKE '%...%'와 비슷)
# "이 제목 키워드를 포함하는 공고들이 요구하는 스킬을, 등장 횟수 많은 순으로" 뽑는 쿼리

QUERY_SKILL_UNLOCK_COUNT = """
// 특정 스킬을 모두 보유할 경우 지원 가능한 공고 수
// INSTANCE_OF 필수 — 미분류 공고를 세면 수치가 부풀려진다(실측 97% 오염)
MATCH (jp:JobPosting)-[:REQUIRES]->(s:Skill)
WHERE s.name IN $skill_names
  AND (jp)-[:INSTANCE_OF]->(:JobFamily)
WITH jp, count(DISTINCT s) AS matched, size($skill_names) AS total
WHERE matched = total
RETURN count(jp) AS posting_count
"""
# Cypher에서 //는 한 줄 주석
# WITH는 SQL의 서브쿼리 같은 역할 — 앞 단계 결과를 다음 단계로 넘기며 새 컬럼(matched, total)을 계산
# "matched = total"(요구 스킬 전부를 갖고 있다) 조건을 만족하는 공고 개수만 셈
# → "이 스킬 조합을 다 갖추면 지원 가능한 공고가 몇 개나 늘어나는가"를 계산하는 용도 (agent의 skill_unlock 툴에서 씀)

QUERY_MONTHLY_TREND = """
MATCH (jp:JobPosting)-[:REQUIRES]->(s:Skill {name: $skill_name})
WHERE jp.collected_month IS NOT NULL
RETURN jp.collected_month AS month, count(jp) AS count
ORDER BY month
"""
# 특정 스킬이 요구된 공고 개수를, 수집된 월(collected_month) 기준으로 집계 — 트렌드 그래프용 데이터

QUERY_LOCATION_DISTRIBUTION = """
MATCH (jp:JobPosting)
WHERE toLower(jp.title) CONTAINS toLower($job_title) AND jp.location <> ""
RETURN jp.location AS location, count(jp) AS count
ORDER BY count DESC
LIMIT $limit
"""
# 특정 직무 제목의 공고들이 어느 지역에 많은지 집계 (location이 빈 문자열인 건 제외)

# 특정 스킬을 REQUIRES하는 JobPosting의 source_id 목록
# INSTANCE_OF 필수 — 직군 미분류 공고(대부분 Adzuna)는 본문이 빈약해 스킬 추출이 환각이므로
# 근거로 쓸 수 없다. 실측: 이 필터 없이 Docker를 조회하면 2,528건 중 2,463건(97%)이 미분류 공고였다.
QUERY_POSTINGS_FOR_SKILL = """
MATCH (jp:JobPosting)-[:REQUIRES]->(s:Skill)
WHERE toLower(s.name) = toLower($skill_name)
  AND (jp)-[:INSTANCE_OF]->(:JobFamily)
RETURN jp.source_id AS source_id,
       CASE WHEN jp.required_section IS NOT NULL AND jp.required_section <> '' THEN 0 ELSE 1 END AS priority
ORDER BY priority
LIMIT $limit
"""
# CASE WHEN ... THEN ... ELSE ... END → SQL의 CASE WHEN과 동일한 조건 분기 표현식
# required_section이 채워진 공고(priority=0)를 우선으로 정렬해서 반환 — 텍스트 원문이 있는 공고가 더 유용하기 때문

# rel_type을 직접 포매팅. 호출부에서 항상 "REQUIRES" 또는 "PREFERS" 만 사용.
UPSERT_POSTING_SKILL_REL = """
MATCH (jp:JobPosting {{source_id: $source_id}})
MATCH (s:Skill {{name: $skill_name}})
MERGE (jp)-[r:{rel_type}]->(s)
ON CREATE SET r.weight = 1
ON MATCH  SET r.weight = r.weight + 1
"""
# 이 쿼리만 특이하게 {{ }}(이중 중괄호)와 {rel_type}(단일 중괄호)이 섞여 있음.
# 이건 Cypher의 $파라미터 문법과 파이썬의 .format() 문자열 치환 문법이 한 문자열 안에 공존하기 때문:
#   - {{source_id: ...}} → 실제 Cypher에서 쓸 { } 문자를 .format()이 건드리지 않도록 이스케이프
#   - {rel_type}          → 파이썬 쪽에서 .format(rel_type="REQUIRES")로 실제 관계 타입 문자열을 끼워 넣는 자리
# 관계 타입(REQUIRES/PREFERS)은 Cypher에서 $파라미터로 못 넘기고 쿼리 문자열 자체에 박아 넣어야 해서 이런 방식을 씀
# (관계 타입은 코드에서 "REQUIRES"/"PREFERS" 둘로 고정돼 있어 안전 — 사용자 입력이 그대로 들어가는 게 아님)

# 트렌드 증감률을 계산하기에 최소한 필요한 표본 수 (recent + prev 합계).
# 활성 공고가 직군당 수십 건 규모라, 이보다 적으면 1건 차이가 ±100%로 튀어 수치가 무의미하다.
_MIN_TREND_SAMPLE = 10

UPSERT_CO_OCCURS = """
MATCH (a:Skill {name: $skill_a})
MATCH (b:Skill {name: $skill_b})
MERGE (a)-[r:CO_OCCURS]-(b)
ON CREATE SET r.count = 1
ON MATCH  SET r.count = r.count + 1
"""
# -[r:CO_OCCURS]- (화살표 없음) → 방향이 없는 관계. "같이 등장했다"는 사실엔 방향이 없기 때문
# 같은 공고 안에 스킬 A와 B가 동시에 등장할 때마다 이 관계의 count를 올림 (스킬 간 연관성 데이터)

UPSERT_PART_OF = """
MERGE (a:Skill {name: $from_skill})
MERGE (b:Skill {name: $to_skill})
MERGE (a)-[r:PART_OF]->(b)
ON CREATE SET r.relation = $relation
"""
# 시드 데이터(skill_relations.json)를 로드할 때 쓰는 쿼리 — 예: (LangGraph)-[:PART_OF]->(LangChain)
# CLAUDE.md에서 말한 "생태계 관계"(구체 기술 → 상위 개념)를 만드는 부분


class Neo4jClient:
    def __init__(self) -> None:
        # 클래스가 인스턴스화될 때(Neo4jClient() 호출 시) 자동으로 실행되는 생성자 메서드
        uri = os.getenv("NEO4J_URI")
        if not uri:
            raise EnvironmentError(
                "NEO4J_URI 환경변수가 필요합니다. "
                "Neo4j Aura 무료 티어에서 발급 후 .env에 추가하세요.\n"
                "  NEO4J_URI=neo4j+s://xxxx.databases.neo4j.io\n"
                "  NEO4J_USER=neo4j\n"
                "  NEO4J_PASSWORD=your_password"
            )
            # CLAUDE.md에도 명시된 대로 Neo4j는 이 프로젝트에서 유일하게 "없으면 mock 대신 즉시 기동 실패"하는 필수 환경변수
        user = os.getenv("NEO4J_USERNAME") or os.getenv("NEO4J_USER", "neo4j")
        # 두 가지 환경변수 이름(NEO4J_USERNAME, NEO4J_USER) 중 어느 쪽을 써도 되게 하고,
        # 둘 다 없으면 Neo4j의 기본 사용자명인 "neo4j"를 사용
        pwd = os.getenv("NEO4J_PASSWORD", "")
        self._driver = GraphDatabase.driver(uri, auth=(user, pwd))
        # self._driver → 이 인스턴스(self)에 driver 객체를 저장. 앞에 언더스코어(_)는 "이 클래스 내부에서만 쓰라"는 관례 표시
        # 이 시점에는 아직 실제로 연결을 확인하지 않고, "연결 정보를 가진 객체"만 만들어짐 (지연 연결)

    def close(self) -> None:
        """DB 연결 종료. pipeline.py의 step_ingest()가 finally 블록에서 항상 호출."""
        self._driver.close()

    def setup_constraints(self) -> None:
        """유니크 제약조건 설정. 최초 1회 실행."""
        with self._driver.session() as s:
            # self._driver.session() → 실제 쿼리를 실행할 "세션"(작업 단위)을 염. with문으로 끝나면 자동으로 세션 닫힘
            for stmt in CREATE_CONSTRAINTS.strip().split(";"):
                # CREATE_CONSTRAINTS 문자열 안에 세미콜론(;)으로 구분된 5개의 CREATE CONSTRAINT 문이 들어있는데,
                # Neo4j 드라이버는 한 번에 문장 하나만 실행할 수 있어서 세미콜론 기준으로 잘라 하나씩 실행
                stmt = stmt.strip()
                if stmt:  # 마지막에 잘렸을 때 생기는 빈 문자열은 건너뜀
                    try:
                        s.run(stmt)
                    except Exception as e:
                        logger.warning(f"제약조건 설정 경고(이미 있으면 무시 가능): {e}")
                        # IF NOT EXISTS가 있어서 보통은 에러가 안 나지만, 혹시 모를 상황에 대비해 warning으로 로그만 남기고 계속 진행
        print("제약조건 설정 완료")

    def load_skill_seeds(self, seeds_path: str | Path | None = None) -> None:
        """PART_OF 관계 시드 데이터를 Neo4j에 로드."""
        # 기본 경로는 CWD와 무관하게 ROOT 기준 절대경로 — 다른 디렉토리에서 실행해도 안전
        path = Path(seeds_path) if seeds_path else ROOT / "data" / "seeds" / "skill_relations.json"
        # 삼항 표현식: 매개변수로 경로가 주어지면 그걸 쓰고, 안 주어지면(None) 기본 시드 파일 경로를 사용
        if not path.exists():
            raise FileNotFoundError(f"시드 파일 없음: {path}")

        with open(path, encoding="utf-8") as f:
            seeds: list[dict] = json.load(f)
            # skill_relations.json은 [{"from": "LangGraph", "to": "LangChain", "relation": "..."}, ...] 형태로 추정

        with self._driver.session() as sess:
            for seed in seeds:
                sess.run(UPSERT_PART_OF,
                    from_skill=seed["from"],
                    to_skill=seed["to"],
                    relation=seed["relation"],
                )
                # sess.run(쿼리문자열, 키워드인자들...) → 쿼리 안의 $from_skill, $to_skill, $relation 자리에
                # 여기서 넘긴 값들이 실제로 채워져서 실행됨
        print(f"PART_OF 시드 {len(seeds)}개 로드 완료")

    def clear_all(self, confirm: bool = False) -> None:
        """DB의 모든 노드·관계를 삭제한다 (파괴적).

        실수 방지를 위해 confirm=True를 명시해야 실행된다. 삭제 전 노드 수를 출력한다.
        """
        with self._driver.session() as sess:
            count = sess.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            # MATCH (n) → 어떤 라벨이든 상관없이 모든 노드를 매칭. .single()은 결과가 딱 한 줄일 때 그 줄만 꺼내는 메서드
            if not confirm:
                raise ValueError(
                    f"clear_all은 노드 {count}개를 전부 삭제합니다. "
                    "실행하려면 clear_all(confirm=True)로 호출하세요."
                )
                # confirm 매개변수를 기본값 False로 둬서, 실수로 clear_all()만 호출하면 즉시 에러가 나고
                # 실제 삭제 전에 "지금 몇 개가 지워지는지" 개수까지 에러 메시지로 미리 보여줌 — 안전장치
            print(f"[clear_all] 노드 {count}개 삭제 중...")
            sess.run("MATCH (n) DETACH DELETE n")
            # DETACH DELETE → 노드를 지우기 전에 그 노드에 연결된 관계까지 함께 끊고 삭제 (관계가 남아있으면 삭제 자체가 안 됨)
        print("DB 초기화 완료")

    def ingest_posting(self, posting: dict) -> None:
        """공고 1개를 그래프에 삽입.

        멱등성: 동일 source_id를 재적재해도 집계 카운터(Company/JobFamily.posting_count,
        Skill.frequency, REQUIRES/PREFERS.weight, CO_OCCURS.count)를 다시 올리지 않는다.
        신규 공고일 때만 카운터를 증가시킨다 — 파이프라인 재실행이 데이터를 부풀리지 않도록.
        (섹션 텍스트는 재적재 시에도 갱신 — 전처리 개선 반영용.)
        """
        # "멱등성(idempotent)"이란: 같은 작업을 여러 번 반복해도 결과가 한 번 한 것과 똑같이 유지되는 성질.
        # 이 함수가 멱등적이지 않다면, pipeline.py를 두 번 실행했을 때 같은 공고의 Skill.frequency가
        # 실제로는 1번만 등장했는데 2, 3, 4...로 계속 부풀어 오르는 버그가 생김 (메모리 1282에서 실제로 고쳤던 문제)

        source_id = str(posting["id"])   # muse=str / adzuna=int 혼재 방지 — source_id는 항상 str
        # posting["id"] (get이 아니라 대괄호) → id가 없으면 일부러 에러를 내겠다는 뜻 (id는 반드시 있어야 하는 필수값)
        company_name = posting.get("company", "")
        job_family_name = posting.get("job_family", "")
        skills = posting.get("skills", {})
        required_names: list[str] = skills.get("required", [])
        preferred_names: list[str] = skills.get("preferred", [])

        all_pairs: list[tuple[str, str]] = (
            [(name, "REQUIRES") for name in required_names]
            + [(name, "PREFERS") for name in preferred_names]
        )
        # 리스트 컴프리헨션 두 개를 +로 이어붙임:
        # required_names의 각 스킬을 (스킬명, "REQUIRES") 튜플로, preferred_names는 (스킬명, "PREFERS") 튜플로 만들고
        # 두 리스트를 합쳐 all_pairs 하나로 만듦 — "이 스킬이 필수인지 우대인지"를 잃지 않고 하나의 리스트로 순회하기 위함
        all_names = [name for name, _ in all_pairs]
        # all_pairs의 각 튜플에서 이름만 뽑음. "_"는 "이 값은 안 쓸 거라서 이름 안 붙임"이라는 관례적 표기 (여기선 rel_type 부분)

        with self._driver.session() as sess:
            # 신규 여부를 MERGE 전에 판정 — 단일 스레드 적재라 경합 없음
            already = sess.run(
                "MATCH (p:JobPosting {source_id: $sid}) RETURN count(p) AS c",
                sid=source_id,
            ).single()["c"] > 0
            # 이 공고가 이미 DB에 있는지 먼저 확인. count(p)가 0보다 크면 True(이미 있음), 0이면 False(신규)
            # 이 판정 결과(already)가 아래에서 "카운터를 올릴지 말지" 분기의 기준이 됨

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
                # datetime.now().strftime("%Y-%m") → 현재 날짜를 "2026-07" 형식의 문자열로 변환
                # (이 필드는 "이 공고를 언제 수집했는지"를 나타내는 용도이지, 공고 게시일이 아님)
            )

            # 재적재면 카운터 증가를 전부 건너뛴다 (섹션 텍스트는 아래에서 갱신)
            if not already:
                # already가 False(신규 공고)일 때만 아래 블록 전체를 실행
                if company_name:
                    sess.run(UPSERT_COMPANY, name=company_name)
                    sess.run(LINK_POSTING_COMPANY, source_id=source_id, company_name=company_name)

                if job_family_name:
                    sess.run(UPSERT_JOB_FAMILY, name=job_family_name)
                    sess.run(LINK_POSTING_JOB_FAMILY, source_id=source_id, job_family_name=job_family_name)

                for skill_name, rel_type in all_pairs:
                    sess.run(UPSERT_SKILL, name=skill_name)
                    # 관계 타입은 Cypher의 $파라미터로 넘길 수 없어 문자열에 직접 박아야 한다.
                    # 지금은 호출부가 "REQUIRES"/"PREFERS"만 넘기지만, 미래에 사용자 입력이나
                    # LLM 출력이 이 자리에 흘러들면 곧바로 Cypher 인젝션이 된다. 화이트리스트로 못 박는다.
                    if rel_type not in ("REQUIRES", "PREFERS"):
                        raise ValueError(f"허용되지 않은 관계 타입: {rel_type!r}")
                    cypher = UPSERT_POSTING_SKILL_REL.format(rel_type=rel_type)
                    # .format(rel_type=rel_type) → 쿼리 문자열 안의 {rel_type} 자리를 실제로 "REQUIRES" 또는 "PREFERS"로 치환
                    sess.run(cypher, source_id=source_id, skill_name=skill_name)

                for i, name_a in enumerate(all_names):
                    for name_b in all_names[i + 1:]:
                        # all_names[i+1:] → name_a 바로 다음 항목부터 끝까지. 이렇게 하면 같은 쌍을 두 번 세거나
                        # 자기 자신과 짝짓는 걸 방지하면서, 모든 스킬 쌍의 조합을 한 번씩만 순회하게 됨
                        # (예: [A,B,C]면 (A,B),(A,C),(B,C)만 나오고 (B,A) 같은 중복은 안 나옴)
                        try:
                            sess.run(UPSERT_CO_OCCURS, skill_a=name_a, skill_b=name_b)
                        except Exception as e:
                            logger.warning(f"[warn] CO_OCCURS 실패 ({name_a}, {name_b}): {e}")
                            # 스킬 쌍 하나 실패해도 나머지 쌍들은 계속 처리 (전체를 막지 않음)

        # 섹션 텍스트는 MERGE와 별도로 SET — 기존 공고도 업데이트 가능
        req = posting.get("required_section", "")
        pref = posting.get("preferred_section", "")
        if req or pref:
            self.set_posting_sections(source_id, req, pref)
            # 위의 "with self._driver.session()" 블록 밖에서 실행됨 — already 여부와 무관하게 항상 실행
            # 즉 재적재(already=True)일 때도 원문 텍스트만큼은 최신 내용으로 덮어씀
            # (전처리 로직이 개선되면, 재실행 시 더 나은 텍스트로 갱신되게 하려는 의도)

    # ── 아래부터는 "시장 인사이트" 조회 메서드들 ──────────────────
    # pipeline.py의 적재 흐름에서는 전혀 호출되지 않는다.
    # 데이터가 이미 다 쌓인 뒤, 나중에 src/agent/(에이전트 툴)나 src/api/(API 응답)가
    # "이 데이터로 무엇을 물어볼 수 있는가"를 실제로 구현한 조회 함수들이다.
    # 각 함수는 execute_query()에 미리 정의된 쿼리 상수(또는 즉석에서 쓴 쿼리)를 넘겨 결과를 받아온다.

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
        # execute_query는 항상 리스트를 반환하므로, 결과가 있으면 첫 번째 행의 값을, 없으면 0을 반환

    def get_monthly_trend(self, skill_name: str) -> list[dict]:
        """월별 특정 스킬 등장 공고 수 (지원 타이밍 분석)."""
        return self.execute_query(QUERY_MONTHLY_TREND, skill_name=skill_name)

    def get_location_distribution(self, job_title: str, limit: int = 10) -> list[dict]:
        """직무별 지역 분포."""
        return self.execute_query(QUERY_LOCATION_DISTRIBUTION, job_title=job_title, limit=limit)

    def list_job_families(self) -> list[str]:
        """등록된 직군명 목록 (유효성 검증·선택지 노출용)."""
        try:
            rows = self.execute_query(
                "MATCH (j:JobFamily) RETURN j.name AS name ORDER BY j.posting_count DESC"
            )
            return [r["name"] for r in rows if r.get("name")]
        except Exception as e:
            logger.error(f"[neo4j] 직군 목록 조회 실패: {e}")
            return []
            # 이 메서드부터는 DB 조회가 실패해도(예: 연결 문제) 예외를 그대로 던지지 않고
            # 빈 리스트를 반환해서 호출한 쪽(API·에이전트)이 죽지 않고 "결과 없음"으로 처리할 수 있게 함

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
            # [:REQUIRES|PREFERS] → REQUIRES 또는 PREFERS 둘 중 아무 관계나 매칭 (관계 타입에 |로 or 조건)
            # 이 쿼리는 "이 직군에서 흔한 스킬인데, 다른 직군에서도 너무 흔하면(예: Git처럼 어디서나 쓰는 기술) 제외"하는 로직
            # family_count < threshold → 이 스킬이 등장하는 서로 다른 직군 수가 threshold보다 적어야(=이 직군에 특화됨) 통과
            params = {"job_family": job_family, "threshold": exclude_common_threshold}
        try:
            from src.extraction.normalizer import normalize_skill, is_noise_skill
            # 지난번 봤던 normalizer.py의 is_noise_skill()이 실제로 여기서 쓰이는 걸 확인할 수 있음!
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
            logger.error(f"[neo4j] 직군 스킬 조회 실패: {e}")
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
            logger.error(f"[neo4j] 공통 스킬 조회 실패: {e}")
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
        # NOT o.name IN $skills → 이미 갖고 있는 스킬 자기 자신은 추천 결과에서 제외
        try:
            rows = self.execute_query(query, skills=skills, n=top_n)
            return [r["skill"] for r in rows if r.get("skill")]
        except Exception as e:
            logger.error(f"[neo4j] CO_OCCURS 조회 실패: {e}")
            return []

    def get_skill_neighbors(self, skills: list[str], top_n: int = 6) -> dict[str, list[str]]:
        """각 스킬의 CO_OCCURS 이웃을 배치로 조회 → {skill: [neighbor,...]}.

        코칭 환각 방어용 — 보강 방향을 '함께 쓰이는 스킬'로 제약해
        관계에 없는 도약(예: AI→강화학습)을 막는다.
        """
        if not skills:
            return {}
        query = """
        MATCH (s:Skill)-[r:CO_OCCURS]-(o:Skill)
        WHERE s.name IN $skills
        WITH s.name AS skill, o.name AS neighbor, sum(r.count) AS w
        ORDER BY w DESC
        WITH skill, collect(neighbor)[0..$n] AS neighbors
        RETURN skill, neighbors
        """
        # collect(neighbor) → 여러 행의 값을 하나의 리스트로 모으는 집계 함수 (SQL엔 없는, 그래프 쿼리 특유의 기능)
        # [0..$n] → 그 리스트에서 앞 n개만 슬라이싱
        # 이 메서드는 코칭 에이전트가 "이 스킬을 배웠으면 뭘 더 배우면 좋을지" 추천할 때, 전혀 무관한 것을 억지로
        # 추천하지 않도록 "실제로 공고에서 함께 요구되는 스킬"로만 후보를 제한하는 데 쓰임 (CLAUDE.md의 환각 방지 원칙과 연결)
        try:
            rows = self.execute_query(query, skills=skills, n=top_n)
            return {r["skill"]: r["neighbors"] for r in rows if r.get("skill")}
        except Exception as e:
            logger.error(f"[neo4j] 스킬 이웃 조회 실패: {e}")
            return {}

    def get_skill_categories(self, skills: list[str]) -> dict[str, str]:
        """스킬별 category(language/framework/tool/database/concept/soft)를 배치 조회.

        코칭 환각 방어용 — category='soft'(자격증·방법론·순수역량)는 코드 보강
        대상이 아니므로 ③에서 제외하는 데 쓴다.
        """
        if not skills:
            return {}
        try:
            rows = self.execute_query(
                "MATCH (s:Skill) WHERE s.name IN $skills AND s.category IS NOT NULL "
                "RETURN s.name AS name, s.category AS category",
                skills=skills,
            )
            return {r["name"]: r["category"] for r in rows if r.get("name")}
        except Exception as e:
            logger.error(f"[neo4j] 스킬 category 조회 실패: {e}")
            return {}

    def get_covered_umbrella_skills(self, skills: list[str]) -> dict[str, list[str]]:
        """보유 스킬이 PART_OF로 실증하는 상위 카테고리 스킬을 배치 조회.

        {상위스킬: [근거가 된 보유 스킬,...]} — 예: LangGraph 보유 시
        LangGraph→LangChain→LLM→GenAI→AI 체인을 타고 {"LLM": ["LangGraph"], ...}.
        구체 프레임워크로 쌓은 실력이 상위 개념(LLM 등) 스킬명과 리터럴 매칭이
        안 돼 '부족'으로 오탐되는 문제를 막는 데 쓴다 (consensus 간접 실증).
        """
        if not skills:
            return {}
        query = """
        MATCH (s:Skill)-[:PART_OF*1..4]->(u:Skill)
        WHERE toLower(s.name) IN $names
        RETURN u.name AS umbrella, collect(DISTINCT s.name) AS via
        """
        # [:PART_OF*1..4] → "PART_OF 관계를 1번에서 4번까지 연속으로 타고 간 모든 경로"를 매칭
        # (그래프 DB만의 강력한 기능 — SQL로는 이런 가변 길이 경로 탐색이 훨씬 번거로움)
        # 예: LangGraph -PART_OF-> LangChain -PART_OF-> LLM 이렇게 2단계를 거쳐도 한 번에 찾아냄
        try:
            rows = self.execute_query(query, names=[s.lower() for s in skills])
            return {r["umbrella"]: r["via"] for r in rows if r.get("umbrella")}
        except Exception as e:
            logger.error(f"[neo4j] 상위 스킬 커버리지 조회 실패: {e}")
            return {}

    def recommend_job_postings(self, skills: list[str], top_n: int = 5, min_required: int = 4,
                               job_family: str | None = None) -> list[dict]:
        """보유 스킬과 매칭률이 높은, 지원 가능한 채용공고 상위 N개를 반환한다.

        min_required: 요구 스킬이 이 수 미만인 공고는 제외 (노이즈 방지).
        url 있는 공고만 (지원 링크 보장), job_family 지정 시 해당 직군만.
        """
        if not skills:
            return []
        query = """
        WITH $skills AS portfolio
        MATCH (jp:JobPosting)-[:REQUIRES]->(s:Skill)
        WHERE s.name IN portfolio AND jp.url IS NOT NULL AND jp.url <> ""
        WITH jp, count(DISTINCT s) AS matched
        MATCH (jp)-[:REQUIRES]->(ts:Skill)
        WITH jp, matched, count(DISTINCT ts) AS total
        WHERE total >= $min_required
        MATCH (jp)-[:POSTED_BY]->(c:Company)
        MATCH (jp)-[:INSTANCE_OF]->(jf:JobFamily)
        WHERE $job_family IS NULL OR jf.name = $job_family
        RETURN jp.title AS title, c.name AS company, jp.url AS url,
               jf.name AS job_family, matched, total,
               round(toFloat(matched) / total * 100) AS match_pct
        ORDER BY match_pct DESC, matched DESC
        LIMIT $n
        """
        # 이 쿼리는 여러 WITH로 단계를 나눠 계산: ① 매칭된 스킬 수(matched) → ② 전체 요구 스킬 수(total)
        # → ③ 매칭률(match_pct = matched/total*100)까지 계산해서, 매칭률 높은 순으로 공고를 정렬
        # round(toFloat(matched) / total * 100) → 정수 나눗셈 문제 방지를 위해 toFloat()으로 실수 변환 후 반올림
        try:
            rows = self.execute_query(query, skills=skills, n=top_n, min_required=min_required,
                                      job_family=job_family)
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
            logger.error(f"[neo4j] 공고 추천 조회 실패: {e}")
            return []

    def set_posting_sections(self, source_id: str, required: str, preferred: str) -> None:
        """공고 노드에 요건 원문(필수·우대)을 속성으로 저장한다."""
        # ingest_posting()의 마지막 부분에서 실제로 호출되는 헬퍼 — Step 3 흐름에 포함됨
        try:
            self.execute_query(
                "MATCH (p:JobPosting {source_id: $source_id}) "
                "SET p.required_section = $required, p.preferred_section = $preferred",
                source_id=source_id, required=required or "", preferred=preferred or "",
            )
        except Exception as e:
            logger.error(f"[neo4j] 공고 원문 저장 실패({source_id}): {e}")

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
            logger.error(f"[neo4j] 공고 원문 조회 실패: {e}")
            return []

    def get_postings_requiring_skill(self, skill_name: str, limit: int = 5) -> list[str]:
        """특정 스킬을 REQUIRES하는 JobPosting의 source_id 목록을 반환한다."""
        rows = self.execute_query(QUERY_POSTINGS_FOR_SKILL, skill_name=skill_name, limit=limit)
        return [r["source_id"] for r in rows]

    def get_skill_trend(self, skill_name: str, window_days: int = 30) -> dict:
        """최근 N일 vs 이전 N일 공고 등장 횟수를 비교해 트렌드를 반환한다.

        posted_at이 없거나 비교 불가한 경우 delta_pct=0으로 반환한다.
        표본이 _MIN_TREND_SAMPLE 미만이면 delta_pct 대신 low_sample=True를 반환한다 —
        활성 공고가 직군당 수십 건 규모라 1건 차이가 ±100%로 튀어 무의미하기 때문.
        """
        # posted_at은 Neo4j datetime 타입이므로 cutoff 문자열도 datetime()으로 캐스팅해야 비교된다.
        # INSTANCE_OF 필수 — 미분류(환각) 공고가 트렌드 수치를 오염시키지 않도록.
        query = """
        MATCH (s:Skill)<-[:REQUIRES]-(jp:JobPosting)
        WHERE toLower(s.name) = toLower($skill_name)
          AND jp.posted_at IS NOT NULL
          AND (jp)-[:INSTANCE_OF]->(:JobFamily)
        WITH jp.posted_at AS posted_at
        WITH
          sum(CASE WHEN posted_at >= datetime($recent_cutoff) THEN 1 ELSE 0 END) AS recent_count,
          sum(CASE WHEN posted_at >= datetime($prev_cutoff) AND posted_at < datetime($recent_cutoff) THEN 1 ELSE 0 END) AS prev_count
        RETURN recent_count, prev_count
        """
        # sum(CASE WHEN 조건 THEN 1 ELSE 0 END) → "조건을 만족하는 행의 개수 세기"를 표현하는 SQL/Cypher 공통 관용구
        from datetime import datetime, timedelta, timezone
        # 이미 파일 위에서 datetime을 import했는데 여기서 timedelta, timezone과 함께 다시 import함
        # (파이썬은 함수 안에서 다시 import해도 문제없이 동작 — 이미 import된 모듈은 캐시돼 있어서 추가 비용도 거의 없음)
        now = datetime.now(timezone.utc)
        # timezone.utc를 명시해서 시간대(UTC) 기준을 확실히 함 — 서버 로컬 시간에 의존하면 지역마다 결과가 달라질 위험
        recent_cutoff = (now - timedelta(days=window_days)).isoformat()
        # timedelta(days=30) → "30일"이라는 시간 간격 객체. now에서 그만큼 빼면 "30일 전 시각"이 나옴
        # .isoformat()으로 "2026-06-07T12:00:00+00:00" 같은 표준 문자열로 변환 (Cypher의 datetime()이 이 형식을 인식함)
        prev_cutoff = (now - timedelta(days=window_days * 2)).isoformat()
        # "이전 기간"의 시작점 — 최근 30일과 비교할 "그 이전 30일"의 시작을 60일 전으로 계산

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
            # 표본이 너무 적으면 증감률 자체가 무의미하다 — 1건이 늘어도 ±100%가 되어
            # 리포트가 "수요 100% 급증" 같은 근거 없는 숫자를 사용자에게 제시하게 된다.
            # 근거 기반을 표방하는 시스템은 신뢰할 수 없는 숫자를 내보내지 않는 편이 정직하다.
            # is_new(신규 등장)는 표본 수와 무관한 '사실'이므로 그대로 전달하고,
            # 신뢰할 수 없는 '증감률'만 None으로 막는다.
            if recent + prev < _MIN_TREND_SAMPLE:
                return {"skill": skill_name, "recent_count": recent, "prev_count": prev,
                        "delta_pct": None, "low_sample": True,
                        "is_new": prev == 0 and recent > 0}

            # prev=0, recent>0은 '신규 급증'이지 '변화 없음'이 아니다 — delta 0.0으로 묻히지 않게 처리
            if prev > 0:
                delta = round((recent - prev) / prev * 100, 1)
                # 일반적인 증감률 계산: (최근-이전)/이전*100, 소수 첫째자리까지 반올림
            elif recent > 0:
                delta = 100.0   # 이전 0 → 최근 등장: 신규 수요
                # prev가 0이면 나눗셈(ZeroDivisionError)이 안 되므로, "이전엔 0이었는데 지금은 있다"를
                # 그냥 0%가 아니라 "100% 증가"에 준하는 의미로 명시적으로 표현 (신규 수요를 놓치지 않기 위한 처리)
            else:
                delta = 0.0  # 이전도 0, 최근도 0이면 정말 변화가 없는 것
            return {"skill": skill_name, "recent_count": recent, "prev_count": prev,
                    "delta_pct": delta, "is_new": prev == 0 and recent > 0}
        except Exception as e:
            logger.error("get_skill_trend 실패 (skill=%s): %s", skill_name, e)
            # 여기서만 f-string이 아니라 %s 스타일 포맷을 씀 — logging 모듈의 관용적인 방식(둘 다 동작은 하지만 스타일이 섞여 있음)
            return {"skill": skill_name, "recent_count": 0, "prev_count": 0, "delta_pct": 0.0, "error": str(e)}

    def execute_query(self, query: str, **params) -> list[dict]:
        """임의 Cypher 쿼리 실행."""
        # **params → 호출할 때 넘긴 모든 키워드 인자(job_title=..., limit=... 등)를 딕셔너리로 모아 받음
        # 이 메서드 하나가 위의 get_top_skills, get_monthly_trend 등 거의 모든 조회 메서드의 공통 실행 엔진
        with self._driver.session() as s:
            result = s.run(query, **params)
            # **params → 이번엔 반대로, 모아뒀던 딕셔너리를 다시 개별 키워드 인자로 풀어서 s.run()에 전달
            return [dict(row) for row in result]
            # Neo4j가 반환하는 각 행(row)은 자체 객체 타입인데, dict(row)로 감싸면 일반 파이썬 딕셔너리로 변환됨
            # → 호출한 쪽이 Neo4j 전용 타입을 몰라도 그냥 평범한 dict처럼 다룰 수 있게 해주는 변환
