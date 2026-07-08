# 원본 공고 JSON → 전처리 → 스킬 추출 → Neo4j 적재 파이프라인
#
# 이 파일 하나가 하는 일: collect_muse.py가 모아둔 원본 공고 JSON을 받아서,
# ① 텍스트 정제 → ② LLM으로 기술스택 추출 → ③ Neo4j 그래프 DB에 저장
# 까지 3단계를 순서대로 실행시키는 "지휘자" 역할의 파일이다.
# 실제 세부 작업(HTML 파싱, LLM 호출, DB 쿼리)은 이 파일이 직접 하지 않고
# 다른 파일들(preprocessor.py, skill_extractor.py, neo4j_client.py)에 맡긴다.

from __future__ import annotations

# 파이썬 버전이 낮아도 `list[dict]`, `str | None` 같은 최신 타입 표기법을 쓸 수 있게 해주는 선언.
# 이 줄이 없으면 구버전 파이썬에서 타입 힌트 작성 시 오류가 날 수 있다.

import json  # 파이썬 dict/list ↔ JSON 텍스트 파일 서로 변환할 때 사용
import os  # 환경변수(OPENAI_API_KEY 등)를 읽을 때 사용
import time  # time.sleep()으로 코드 실행을 잠깐 멈출 때 사용
from pathlib import (
    Path,
)  # 파일 경로를 다루는 표준 도구. "폴더/파일명" 조합을 문자열 대신 객체로 다룸

from dotenv import load_dotenv

# .env 파일(키=값 형태로 저장된 비밀 설정 파일)을 읽어서
# os.getenv()로 꺼낼 수 있게 환경변수로 등록해주는 함수

ROOT = Path(__file__).resolve().parent.parent.parent
# __file__ = "지금 이 파일(pipeline.py)의 경로"
# .resolve() = 상대경로를 절대경로(전체 경로)로 바꿔줌
# .parent 를 3번 반복 = 폴더를 3단계 위로 이동
#   src/ingestion/pipeline.py → src/ingestion → src → 프로젝트 최상위 폴더
# 결과적으로 ROOT는 "이 프로젝트가 있는 최상위 폴더"를 가리키는 변수가 됨

# .env를 여기서 미리 로드해야, 아래에서 import하는 OpenAI/Neo4jClient 등이
# 모듈 로드 시점에 os.getenv()로 키를 읽어도 값이 이미 준비돼 있음
load_dotenv(ROOT / ".env")
# ROOT / ".env" → Path 객체끼리 "/"로 연결하면 경로를 이어붙일 수 있음 (문자열 슬래시 나누기 아님)
# 즉 이 줄은 "프로젝트 루트 폴더 안의 .env 파일을 읽어서 환경변수로 등록해라"라는 뜻

from openai import OpenAI

# OpenAI 사의 파이썬 SDK에서 OpenAI라는 클래스(클라이언트)를 가져옴.
# 이 클래스의 인스턴스를 만들어야 GPT 모델에 요청을 보낼 수 있음.

# 이 파이프라인이 의존하는 다른 단계들의 모듈
# "from A import B"는 "A라는 파일(모듈)에서 B라는 함수/클래스만 골라서 가져온다"는 뜻
from src.ingestion.preprocessor import preprocess_file  # Step 1: HTML 정제·섹션 분리
from src.extraction.skill_extractor import (
    extract_skills_from_posting,
)  # Step 2: LLM 스킬 추출
from src.extraction.normalizer import normalize_skill  # Step 2: 스킬명 동의어 통합
from src.storage.neo4j_client import Neo4jClient  # Step 3: 그래프 DB 적재

# 공고 제목 → 직군(JobFamily) 매핑용 키워드 테이블
# 파이썬의 dict(딕셔너리) 자료형 — {키: 값} 쌍을 저장. 여기서는 {직군 이름: [키워드 리스트]}
# Neo4j에 저장되는 실제 Skill/기술 스택은 여기 없음 — 그건 LLM이 추출(Step 2)하고,
# 여기 정의된 건 오직 "이 공고가 어느 직군에 속하는가"를 정하는 규칙일 뿐
_JOB_FAMILIES = {
    "ML Engineer": ["ml engineer", "machine learning engineer", "ml ops", "mlops"],
    "AI/LLM Engineer": ["ai engineer", "ai/ml", "llm", "genai", "agentic ai"],
    "Data Scientist": ["data scientist", "data science"],
    "Data Analyst": ["data analyst", "data analytics", "business analyst", "bi "],
    "Data Engineer": ["data engineer", "data platform", "etl", "spark", "databricks"],
    "Software Engineer": [
        "backend engineer",
        "backend developer",
        "software engineer",
        "software developer",
        "full stack",
        "fullstack",
    ],
    "Frontend Engineer": ["frontend", "front end", "front-end"],
    "DevOps/SRE": [
        "devops",
        "sre",
        "site reliability",
        "platform engineer",
        "infrastructure engineer",
        "cloud engineer",
    ],
    "Security Engineer": [
        "security engineer",
        "appsec",
        "application security",
        "cybersecurity",
        "infosec",
        "soc analyst",
        "security analyst",
        "penetration test",
        "pentest",
        "threat detection",
        "incident response",
        "security operations",
        "vulnerability",
    ],
}
# 이름 앞의 언더스코어(_)는 "이 변수는 이 파일 안에서만 쓰는 내부용"이라는 파이썬 관례 표시
# (다른 파일에서 import해서 쓰라고 만든 게 아니라는 신호일 뿐, 강제로 막는 기능은 아님)


def _job_family(title: str) -> str | None:
    """타이틀에서 직군을 판별. 확실한 직군이 아니면 None 반환."""
    # 함수 정의: def 함수이름(매개변수: 타입) -> 반환타입: 형태
    # title: str  → title이라는 매개변수는 문자열(str) 타입이어야 한다는 힌트
    # -> str | None → 이 함수는 문자열을 반환하거나, 아무것도 못 찾으면 None(값 없음)을 반환한다는 뜻
    t = (
        title.lower()
    )  # .lower()는 문자열을 전부 소문자로 바꿔주는 메서드 — 대소문자 구분 없이 비교하기 위함
    # _JOB_FAMILIES를 위에서부터 순서대로 확인 → 딕셔너리 정의 순서가 우선순위가 됨
    # (예: "AI Engineer"는 "ML Engineer"보다 먼저 체크되지 않도록 순서 주의 필요)
    for family, keywords in _JOB_FAMILIES.items():
        # .items()는 딕셔너리를 (키, 값) 쌍으로 하나씩 꺼내주는 메서드
        # 여기서는 family = 직군 이름(예: 'ML Engineer'), keywords = 그 직군의 키워드 리스트
        if any(k in t for k in keywords):
            # any(...)는 괄호 안 조건 중 하나라도 True면 전체가 True가 되는 함수
            # "for k in keywords"로 키워드를 하나씩 꺼내며 "k in t"(키워드가 제목에 포함되는가)를 검사
            # 즉 이 줄은 "keywords 중 하나라도 제목(t)에 포함되어 있는가?"를 검사하는 것
            return family  # 조건을 만족하는 첫 번째 직군을 즉시 반환하고 함수 종료
    return None  # 어떤 키워드에도 안 걸리면 직군 미분류 (Neo4j에서 INSTANCE_OF 관계 안 생김)


def _normalize_skills(skills: dict) -> dict:
    """추출된 스킬 목록에서 normalize_skill() 적용 + 중복 제거."""
    # required, preferred 두 그룹을 동일한 방식으로 각각 처리
    for group in ("required", "preferred"):
        # ("required", "preferred")는 튜플(tuple) — 리스트와 비슷하지만 내용을 바꿀 수 없는 자료형
        # 여기서는 그냥 "이 두 개를 순서대로 처리하겠다"는 반복 대상으로 쓰임
        seen: set[str] = set()  # 이미 나온 정규화된 스킬명 추적 (중복 방지)
        # set(집합)은 리스트와 달리 "같은 값이 두 번 안 들어가는" 자료형.
        # "어떤 값이 이미 있었는지"를 빠르게 확인하려고 씀 (예: "React"가 seen에 이미 있는지 in으로 즉시 확인)
        deduped: list[str] = []  # 중복 제거된 최종 스킬 리스트
        for name in skills.get(group, []):
            # skills.get(group, [])는 "skills 딕셔너리에서 group이라는 키를 찾되,
            # 없으면 에러 내지 말고 빈 리스트([])를 대신 써라"는 안전한 조회 방법
            # LLM 응답이 문자열("React")일 수도, dict({"name": "React"})일 수도 있어서 분기 처리
            normalized = (
                normalize_skill(name)
                if isinstance(name, str)
                else normalize_skill(name.get("name", ""))
            )
            # 이 줄은 파이썬의 "삼항 표현식": 값A if 조건 else 값B
            # isinstance(name, str) = "name이 문자열 타입인가?"를 확인
            # 문자열이면 name 그대로 normalize_skill()에 넣고,
            # 아니면(=dict라고 가정) name.get("name", "")로 안의 "name" 키 값을 꺼내서 넣음
            if normalized and normalized not in seen:
                # normalized가 빈 문자열이 아니고(and), 아직 seen에 없는 새로운 값이면
                seen.add(normalized)  # seen 집합에 추가해서 "이제 나왔다"고 기록
                deduped.append(normalized)  # 최종 리스트에도 추가
        skills[group] = (
            deduped  # 원래 skills 딕셔너리의 이 그룹을 중복 제거된 리스트로 덮어씀
        )
    return skills


# 파이프라인 각 단계의 입출력 파일 기본 경로
# 원본 -> 전처리 → 스킬 추출 → Neo4j 적재 순서로 진행되므로, 각 단계의 출력 파일이 다음 단계의 입력 파일이 됨
_DEFAULT_RAW = ROOT / "data" / "raw" / "jobs_data_analytics.json"
_DEFAULT_PROCESSED = ROOT / "data" / "processed" / "jobs_da_processed.json"
_DEFAULT_WITH_SKILLS = ROOT / "data" / "processed" / "jobs_da_with_skills.json"
# 세 변수 모두 Path 객체. 예: _DEFAULT_RAW는 "프로젝트루트/data/raw/jobs_data_analytics.json"을 가리킴


def _get_openai() -> OpenAI:
    """OpenAI 클라이언트 생성. 키가 없으면 즉시 에러 (mock으로 대체하지 않음 — 스킬 추출은 LLM이 필수라서)."""
    key = os.getenv("OPENAI_API_KEY")
    # os.getenv("이름")은 환경변수 값을 문자열로 가져옴. 없으면 None을 반환 (에러를 내지 않음)
    if not key:
        # key가 None이거나 빈 문자열이면 (파이썬에서 둘 다 "거짓"으로 취급됨) 이 블록 실행
        raise EnvironmentError("OPENAI_API_KEY 환경변수가 필요합니다.")
        # raise = 의도적으로 에러를 발생시켜서 프로그램 실행을 여기서 멈추게 함
    return OpenAI(
        api_key=key
    )  # 키가 있으면 그 키로 OpenAI 클라이언트 객체를 만들어 반환


def _save_json(data: list[dict], path: Path) -> None:
    """공통 저장 헬퍼 — 폴더가 없으면 만들고 JSON으로 씀. Step 2에서 중간 저장·최종 저장에 재사용."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # path.parent = 이 파일이 들어갈 폴더 경로
    # .mkdir(parents=True, exist_ok=True) = 그 폴더를 만드는데,
    #   parents=True: 중간에 없는 폴더까지 전부 만들어줌 (예: data/processed 둘 다 없어도 한번에 생성)
    #   exist_ok=True: 이미 폴더가 있어도 에러 내지 말고 그냥 넘어가라
    with open(path, "w", encoding="utf-8") as f:
        # open(경로, "w", ...) = 이 경로의 파일을 "쓰기 모드"로 염 (기존 내용은 덮어씌워짐)
        # with ... as f: 는 파이썬의 "이 블록이 끝나면 자동으로 파일을 닫아준다"는 안전장치 문법
        json.dump(data, f, ensure_ascii=False, indent=2)
        # json.dump(데이터, 파일객체, ...) = 파이썬 데이터(리스트/딕셔너리)를 JSON 텍스트로 바꿔서 파일에 씀
        # ensure_ascii=False = 한글 등 비-ASCII 문자를 유니코드 이스케이프(\uXXXX)로 안 바꾸고 그대로 저장
        # indent=2 = 사람이 읽기 좋게 2칸 들여쓰기로 예쁘게 저장


def step_preprocess(
    raw_path: Path = _DEFAULT_RAW,
    processed_path: Path = _DEFAULT_PROCESSED,
    *,
    force: bool = False,
) -> list[dict]:
    # 함수 매개변수에 "= 값"이 붙은 건 "기본값" — 호출할 때 안 넘기면 이 값을 자동으로 씀
    # 매개변수 목록 중간의 "*"는 "이 뒤에 오는 매개변수는 반드시 이름을 붙여서 호출해야 한다"는 강제 표시
    #   예: step_preprocess(force=True) (O)   step_preprocess(True) (X, 에러남)
    #   실수로 순서를 헷갈려 잘못된 값을 넘기는 걸 방지하는 안전장치
    """Step 1: raw JSON → 텍스트 정제 + 섹션 분리.

    역할: preprocessor.preprocess_file()을 호출하는 얇은 래퍼(wrapper).
    이 함수 자체는 전처리 로직이 없고, "이미 처리된 파일이 있으면 재작업하지 않는다"는
    캐싱 판단만 담당한다.
    """
    # 1. force=True가 아니고 이미 processed_path 파일이 있으면 → 재작업 없이 그대로 읽어서 반환
    if not force and processed_path.exists():
        # "not force"는 "force가 False일 때 True"가 됨 (참/거짓을 뒤집는 연산자)
        # processed_path.exists()는 그 경로에 실제로 파일이 있는지 확인하는 메서드 (있으면 True)
        print(f"[skip] 전처리 파일 존재: {processed_path}")
        # f"..." 는 f-string — 문자열 안에 {변수}를 넣으면 그 변수의 값이 자동으로 채워짐
        with open(processed_path, encoding="utf-8") as f:
            return json.load(
                f
            )  # json.load(파일객체) = JSON 파일 내용을 파이썬 리스트/딕셔너리로 읽어옴
    # 2. 파일이 없거나 force=True면 → 실제 전처리 실행 (preprocessor.py에 위임)
    print("=== Step 1: 전처리 ===")
    return preprocess_file(raw_path, processed_path)
    # 이 함수(step_preprocess) 자체는 HTML을 어떻게 정제하는지 전혀 모름 — 그건 preprocessor.py의 일


def step_extract_skills(
    jobs: list[dict],
    output_path: Path = _DEFAULT_WITH_SKILLS,
) -> list[dict]:
    """Step 2: 전처리 공고 → LLM 스킬 추출. 기추출 공고는 스킵."""
    openai = _get_openai()  # 이 단계부터 LLM이 필수이므로 여기서 키 검증

    # 1. 기존 결과 파일을 id 기준 dict로 로드 — 이미 스킬 추출된 공고는 재호출(=비용 재발생) 방지
    already: dict[str, dict] = {}  # 처음엔 빈 딕셔너리로 시작
    if output_path.exists():
        with open(output_path, encoding="utf-8") as f:
            for j in json.load(f):
                # json.load(f)는 리스트를 반환 → 그 리스트를 for로 하나씩(j) 꺼냄
                already[j["id"]] = j
                # already[j["id"]] = j → "id 값을 키로, 공고 전체를 값으로" 딕셔너리에 저장
                # 이렇게 해야 나중에 "이 id 이미 처리했나?" 를 already 딕셔너리에서 빠르게 찾을 수 있음

    # 2. 입력 jobs 중 아직 추출 안 된 것만 골라 pending으로
    pending = [j for j in jobs if j["id"] not in already]
    # [표현식 for 항목 in 리스트 if 조건] 형태는 "리스트 컴프리헨션"
    # 풀어 쓰면: 새 리스트를 만드는데, jobs 안의 j를 하나씩 보면서 "j의 id가 already에 없으면" 그 j를 담아라
    print(f"\n=== Step 2: 스킬 추출 (신규 {len(pending)}개 / 전체 {len(jobs)}개) ===")
    # len(리스트) = 그 리스트에 항목이 몇 개 들어있는지 세는 함수

    # 3. pending 공고를 하나씩 순회하며 LLM 호출
    for i, job in enumerate(pending):
        # enumerate(리스트)는 "(순번, 항목)"을 함께 꺼내줌 — i는 0부터 시작하는 순번, job은 그 공고
        try:
            # try 블록: 이 안에서 에러가 나더라도 프로그램이 죽지 않고 아래 except로 넘어가게 함
            # 3-1. LLM으로 필수/우대 스킬 구조화 추출 후 동의어 정규화·중복 제거
            skills = _normalize_skills(extract_skills_from_posting(job, openai))
            # 안쪽부터 실행됨: extract_skills_from_posting(job, openai)로 LLM에게 스킬을 물어보고,
            # 그 결과를 바로 _normalize_skills()에 넣어 동의어 통합 + 중복 제거까지 한 번에 처리
            job["skills"] = (
                skills  # 이 공고 dict에 "skills"라는 새 키를 추가해서 결과를 저장
            )
            already[job["id"]] = job  # 캐시(already)에도 반영해둬야 중간 저장에 포함됨
            req_n = len(skills.get("required", []))  # 필수 스킬 개수
            pref_n = len(skills.get("preferred", []))  # 우대 스킬 개수
            print(
                f"  [{i+1}/{len(pending)}] {job['title'][:45]:<45} req={req_n} pref={pref_n}"
            )
            # job['title'][:45] = 제목 문자열의 앞 45글자만 자르기 (너무 길면 출력이 지저분해지므로)
            # :<45 는 f-string 포맷 문법 — 문자열을 왼쪽 정렬하고 전체 폭을 45칸으로 맞춤(빈 칸은 공백으로 채움)
        except Exception as e:
            # try 블록 안에서 어떤 종류든 에러(Exception)가 발생하면 이 블록이 대신 실행됨
            # e라는 이름에 에러 정보가 담김
            # 3-2. 공고 하나가 실패해도 전체를 중단하지 않고 다음 공고로 계속 진행
            print(f"  [{i+1}/{len(pending)}] {job['title'][:45]:<45} 오류: {e}")

        # 3-3. 10건마다 중간 저장 — 다수의 LLM 호출 도중 중단돼도 이미 처리한 만큼은 보존
        if (i + 1) % 10 == 0:
            # % 는 나머지 연산자. (i+1)이 10, 20, 30...일 때 나머지가 0이 되어 이 조건이 참이 됨
            _save_json(list(already.values()), output_path)
            # already.values() = 딕셔너리의 값들만 뽑아냄 (여기서는 공고 dict들) → list()로 리스트화해서 저장

        time.sleep(
            0.3
        )  # 3-4. OpenAI API 레이트리밋 방지용 딜레이 (0.3초 동안 코드 실행을 멈춤)

    # 4. 루프가 끝나면(10의 배수가 아니어도) 마지막으로 한 번 더 저장 — 누락 방지
    _save_json(list(already.values()), output_path)

    # 5. 반환은 입력 jobs 범위로 제한 — 캐시 파일 전체를 돌려주면 limit·필터가 무력화되고
    # 필터 기준이 바뀐 과거 공고가 계속 되살아난다. 캐시 파일은 캐시로만 사용.
    result = [already[j["id"]] for j in jobs if j["id"] in already]
    # 이번에도 리스트 컴프리헨션: jobs(원래 입력받은 리스트)를 기준으로 순서를 유지하면서,
    # 그 id에 해당하는 최신 데이터를 already에서 찾아 옴
    extracted = [j for j in result if "skills" in j]
    # "skills" in j → j라는 딕셔너리 안에 "skills"라는 키가 있는지 확인
    print(
        f"스킬 추출 완료: {len(extracted)}/{len(result)}개 (입력 {len(jobs)}개) → {output_path}"
    )
    return result


def step_ingest(jobs: list[dict]) -> None:
    """Step 3: Neo4j에 공고·스킬·관계 적재."""
    neo4j = (
        Neo4jClient()
    )  # Neo4j 데이터베이스에 접속하는 클라이언트 객체 생성 (연결 시작)

    try:
        # 1. 적재 전 준비: 제약조건(unique 등) 설정 + 스킬 생태계 시드 데이터 로드
        # (data/seeds/skill_relations.json의 PART_OF 관계, 예: LangChain → LangGraph)
        neo4j.setup_constraints()
        neo4j.load_skill_seeds()

        # 2. "skills" 키가 있는(=Step 2를 통과한) 공고만 적재 대상으로 필터링
        ingestible = [j for j in jobs if "skills" in j]
        print(f"\n=== Step 3: Neo4j 적재 ({len(ingestible)}개) ===")

        # 3. 공고 하나씩 MERGE — 실패해도 전체를 중단하지 않고 다음 공고로 계속
        success = 0  # 성공한 개수를 세는 카운터, 0부터 시작
        for job in ingestible:
            try:
                neo4j.ingest_posting(
                    job
                )  # 실제로 Neo4j에 이 공고를 저장하는 부분 (내부 로직은 neo4j_client.py)
                success += 1  # 성공했으면 카운터를 1 늘림
            except Exception as e:
                print(f"  [오류] {job.get('title', '?')}: {e}")
                # job.get('title', '?') = title 키가 없으면 '?'를 대신 씀 (안전한 조회)

        print(f"적재 완료: {success}/{len(ingestible)}개")
    finally:
        # try 블록이 성공하든 예외로 중간에 빠져나가든, finally 블록은 반드시 실행됨
        # 4. 성공하든 실패하든 커넥션은 반드시 닫음
        neo4j.close()
        # DB 연결을 안 닫으면 "커넥션 누수"가 생겨 나중에 연결이 고갈될 수 있어서, 무조건 닫아주는 것


def run_pipeline(
    raw_path: str | Path = _DEFAULT_RAW,
    processed_path: str | Path = _DEFAULT_PROCESSED,
    with_skills_path: str | Path = _DEFAULT_WITH_SKILLS,
    *,
    limit: int | None = None,
    force_preprocess: bool = False,
    skip_ingest: bool = False,
) -> None:
    """전체 파이프라인 실행 — Step 1 → 2 → 3을 순서대로 호출하는 최상위 오케스트레이터.

    Args:
        limit: 처리할 공고 수 상한 (테스트용)
        force_preprocess: 기존 전처리 파일이 있어도 재생성
        skip_ingest: Step 3(Neo4j 적재) 건너뜀 (스킬 추출만 실행할 때)
    """
    # 1단계: 전처리 (raw_path와 processed_path는 문자열로 들어와도 Path로 변환)
    jobs = step_preprocess(Path(raw_path), Path(processed_path), force=force_preprocess)
    # Path(문자열)은 문자열을 Path 객체로 바꿔주는 변환 — 이미 Path여도 다시 Path()로 감싸면 그대로 유지됨

    # 2단계: limit이 지정됐으면 여기서 자름 — 테스트 시 LLM 호출 비용을 줄이기 위함
    if limit:
        # limit이 None이거나 0이면 이 블록은 실행 안 됨 (파이썬에서 None과 0은 "거짓"으로 취급)
        jobs = jobs[:limit]
        # jobs[:limit] = 리스트 슬라이싱 — 처음부터 limit개까지만 잘라서 새 리스트로 만듦
        print(f"(limit={limit})")

    # 3단계: LLM 스킬 추출
    jobs = step_extract_skills(jobs, Path(with_skills_path))

    # 4단계: Neo4j 적재 (skip_ingest=True면 건너뜀 — 스킬 추출 결과만 확인하고 싶을 때 사용)
    if not skip_ingest:
        step_ingest(jobs)


_FILTERED = ROOT / "data" / "processed" / "jobs_filtered.json"


def run_ingest_all(
    filtered_path: str | Path = _FILTERED,
    *,
    clear: bool = False,
) -> None:
    """jobs_filtered.json → Neo4j 전체 적재.

    run_pipeline()과 별개의 진입점 — Step 1·2(전처리·스킬 추출)를 건너뛰고,
    이미 필터링·스킬 추출까지 끝난 파일을 통째로 다시 적재만 하고 싶을 때 사용.
    (예: Neo4j 스키마를 바꿔서 전체를 재적재해야 할 때)
    """
    # 1. 이미 완성된 필터링 결과 파일을 그대로 로드
    with open(filtered_path, encoding="utf-8") as f:
        jobs = json.load(f)

    neo4j = Neo4jClient()
    try:
        # 2. clear=True면 기존 그래프 데이터를 전부 지우고 새로 시작
        if clear:
            neo4j.clear_all(confirm=True)  # --clear 플래그가 명시적 의사표시
            # confirm=True를 명시적으로 넘겨야 실행되게 만들어서, 실수로 전체 삭제되는 걸 방지하는 안전장치로 보임

        # 3. step_ingest()와 동일하게 제약조건·시드 먼저 설정
        neo4j.setup_constraints()
        neo4j.load_skill_seeds()

        # 4. 공고 전체를 MERGE — 실패해도 계속 진행
        print(f"\n=== Neo4j 적재 ({len(jobs)}개) ===")
        success = 0
        for job in jobs:
            try:
                neo4j.ingest_posting(job)
                success += 1
            except Exception as e:
                print(f"  [오류] {job.get('title', '?')}: {e}")
        print(f"Neo4j 완료: {success}/{len(jobs)}개")
    finally:
        neo4j.close()


if __name__ == "__main__":
    # 파이썬의 관용적인 패턴: 이 파일을 "직접 실행"했을 때만(__name__이 "__main__"이 됨) 아래 블록이 동작.
    # 다른 파일이 이 파일을 import만 했을 때는 __name__이 "__main__"이 아니라서 이 블록이 실행되지 않음
    # → 즉 "이 파일을 라이브러리로 가져다 쓸 때"와 "터미널에서 직접 실행할 때"를 구분하는 표준적인 방법
    import argparse

    # argparse는 터미널에서 실행할 때 --limit 5 같은 옵션(인자)을 쉽게 받을 수 있게 해주는 표준 라이브러리

    # 커맨드라인에서 --limit, --force-preprocess, --skip-ingest 옵션을 받을 수 있게 설정
    parser = argparse.ArgumentParser(description="DA 채용공고 수집 파이프라인")
    parser.add_argument(
        "--limit", type=int, default=None, help="처리할 공고 수 상한 (테스트용)"
    )
    # --limit은 정수(type=int)로 받고, 안 주면 기본값 None, --help에 표시될 설명(help)도 지정
    parser.add_argument("--force-preprocess", action="store_true", help="전처리 재실행")
    # action="store_true" = 이 옵션이 있으면(--force-preprocess만 써도) True, 안 쓰면 False가 되는 스위치형 옵션
    parser.add_argument("--skip-ingest", action="store_true", help="Neo4j 적재 건너뜀")
    args = parser.parse_args()
    # 실제로 터미널에서 입력한 옵션들을 읽어서 args라는 객체에 담음 (args.limit, args.force_preprocess 식으로 접근)

    # 파싱된 옵션 그대로 run_pipeline()에 전달해 전체 파이프라인 실행
    run_pipeline(
        limit=args.limit,
        force_preprocess=args.force_preprocess,
        skip_ingest=args.skip_ingest,
    )
