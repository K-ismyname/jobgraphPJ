# The Muse API 에서 채용공고 원본을 수집해 data/raw/jobs_raw_muse.json 에 저장
"""
사용법: python scripts/collect_muse.py

- API 키 불필요 (무료 공개 API)
- description 전체 텍스트 제공
- 중복 공고(id 기준) 자동 제거
- 기존 파일 있으면 신규 공고만 추가
- 수집 카테고리: Software Engineering / Data and Analytics / Design and UX
- 직무명 화이트리스트 + 회사당 상한으로 품질 보장
"""

from __future__ import annotations  # 옛 파이썬 버전에서도 list[dict] 같은 최신 타입 문법을 쓰게 해줌
import json                      # JSON 파일 읽기/쓰기
import time                      # API 요청 사이에 잠깐 쉬기 위해 (time.sleep)
from collections import Counter  # "회사별 개수", "카테고리별 개수" 같은 집계를 쉽게 세는 도구
from pathlib import Path         # 파일 경로를 문자열 대신 객체로 다루는 표준 라이브러리
import httpx                     # 외부 API에 HTTP 요청(GET)을 보내는 라이브러리 (requests와 비슷한 역할)

# 결과 JSON을 저장할 위치
ROOT = Path(__file__).resolve().parent.parent
# __file__ = 이 파일 자신의 경로 → .resolve()로 절대경로 변환 → .parent.parent로 2단계 위(scripts/→루트)
OUT_PATH = ROOT / "data" / "raw" / "jobs_raw_muse.json"

# The Muse API 기본 URL — 요청을 보낼 주소(엔드포인트). "저장 위치"가 아니라 "요청 목적지".
BASE_URL = "https://www.themuse.com/api/public/jobs"

# 3개의 직군만 수집 (Software Engineering / Data and Analytics / Design and UX)
CATEGORIES = ["Software Engineering", "Data and Analytics", "Design and UX"]

# 포트폴리오가 필요한 기술 직함 키워드
TITLE_KEYWORDS = [
    "engineer", "developer", "architect", "programmer",
    "devops", "sre", "ios", "android", "frontend", "backend",
    "data scientist", "data analyst", "data engineer",
    "machine learning", "ml engineer", "ai engineer",
    "analytics engineer", "analyst", "scientist", "researcher",
    "designer", "ux", "ui ",
]

MAX_PER_COMPANY = 5   # 회사당 최대 공고 수 (Walmart 스팸 방지)
MAX_PAGES = 50        # 카테고리당 최대 페이지 (API 오류 시 무한 루프 방지용 안전장치)


def is_relevant(title: str) -> bool:
    """제목을 소문자로 바꾸고 TITLE_KEYWORDS 중 하나라도 포함되는지 확인."""
    t = title.lower()
    return any(kw in t for kw in TITLE_KEYWORDS)


def fetch_page(category: str, page: int) -> list[dict]:
    """The Muse API에서 카테고리+페이지 1장 분량의 공고를 가져온다."""
    # httpx.get() : BASE_URL로 GET 요청 (?category=..&page=.. 형태로 쿼리스트링이 붙음)
    resp = httpx.get(
        BASE_URL,                                     # 요청 목적지 (API 엔드포인트)
        params={"category": category, "page": page},  # URL에 붙일 쿼리 파라미터
        timeout=15,                                    # 15초 안에 응답 없으면 예외 발생
    )
    resp.raise_for_status()  # 상태코드가 4xx/5xx(에러)면 여기서 예외를 던짐 — 에러를 조용히 넘기지 않기 위함
    # httpx.HTTPStatusError를 강제로 발생 break 로 대응 가능 
    return resp.json().get("results", [])  # 응답 JSON에서 "results" 배열만 꺼냄 (없으면 빈 리스트)


def main() -> None:
    # ── 1단계: 기존 결과 파일 로드 (재실행 대비) ──────────────
    existing: dict[str, dict] = {}  # id를 key로 하는 dict — "이미 수집했는지" O(1)로 빠르게 확인하기 위함
    if OUT_PATH.exists():
        with open(OUT_PATH, encoding="utf-8") as f:
            for job in json.load(f):
                existing[str(job["id"])] = job
        print(f"기존 공고 {len(existing)}개 로드")

    # ── 2단계: 기존 데이터 기준으로 회사별 개수 미리 집계 ──────
    # 재실행 시 이미 5개 있는 회사에 5개를 더 추가해버리는 걸 막기 위해,
    # 새로 수집을 시작하기 전에 "현재 회사별 개수"를 먼저 복원해둔다.
    company_count: Counter = Counter(
        j.get("company", {}).get("name", "?")
        for j in existing.values()
    )

    new_count = 0  # 이번 실행에서 새로 추가된 공고 총 개수

    # ── 3단계: 카테고리 3개 × 페이지 순회하며 수집 ─────────────
    for category in CATEGORIES:
        print(f"\n카테고리: \"{category}\"")
        cat_new = 0  # 이 카테고리에서 새로 추가된 개수

        for page in range(1, MAX_PAGES + 1):  # 1페이지부터 최대 50페이지까지
            # 3-1. API 호출 (실패하면 이 카테고리만 포기하고 다음 카테고리로 넘어감)
            try:
                results = fetch_page(category, page)
            except Exception as e:
                print(f"  페이지 {page} 오류: {e}")
                break

            # 3-2. 더 이상 결과가 없으면 (마지막 페이지 지남) 이 카테고리 수집 중단
            if not results:
                print(f"  페이지 {page}: 결과 없음 — 중단")
                break

            added = 0
            for job in results:
                job_id = str(job.get("id", ""))
                title = job.get("name", "")
                company = job.get("company", {}).get("name", "?")

                # 3-3. 필터링: 셋 중 하나라도 걸리면 이 공고는 건너뜀
                if not is_relevant(title):                     # ① 관련 없는 제목
                    continue
                if company_count[company] >= MAX_PER_COMPANY:  # ② 회사당 상한 초과
                    continue
                if job_id in existing:                          # ③ 이미 수집된 공고
                    continue

                # 3-4. 필터를 통과한 공고 저장
                job["_collected_category"] = category  # 나중 단계(전처리)에서 쓰려고 카테고리 태깅
                existing[job_id] = job
                company_count[company] += 1
                new_count += 1
                added += 1
                cat_new += 1

            print(f"  페이지 {page:2d}: {len(results)}개 조회 / {added}개 추가 (카테고리 누적 {cat_new}개)")
            time.sleep(0.4)  # 3-5. API에 과도한 요청을 보내지 않도록 페이지마다 잠깐 대기

        print(f"  → \"{category}\" 소계: {cat_new}개")

    # ── 4단계: 최종 결과를 JSON 파일로 저장 ─────────────────
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)  # 저장 폴더가 없으면 생성
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(list(existing.values()), f, ensure_ascii=False, indent=2)
        # ensure_ascii=False → 한글이 유니코드 이스케이프(\uXXXX)로 안 깨지고 그대로 저장됨

    print(f"\n신규 {new_count}개 추가 → 총 {len(existing)}개")
    print(f"저장: {OUT_PATH}")

    # ── 5단계: 수집 품질을 눈으로 바로 확인하기 위한 통계 출력 ──
    jobs = list(existing.values())

    # 5-1. 카테고리별 개수
    cat_stat = Counter(j.get("_collected_category", "?") for j in jobs)
    print("\n카테고리별:")
    for cat, cnt in cat_stat.most_common():  # most_common() = 개수 많은 순 정렬
        print(f"  {cat}: {cnt}개")

    # 5-2. 레벨별(신입/시니어 등) 개수 — 공고 하나가 레벨을 여러 개 가질 수 있어 이중 for문
    level_stat = Counter(
        lv["name"] for j in jobs for lv in j.get("levels", [])
    )
    print("\n레벨별:")
    for lv, cnt in level_stat.most_common():
        print(f"  {lv}: {cnt}개")

    # 5-3. 공고 본문 평균 길이 — 너무 짧으면 다음 단계(스킬 추출)에서 정보 부족 문제 생김
    desc_lens = [len(j.get("contents", "")) for j in jobs]
    if desc_lens:  # 전량 필터링돼 0개면 나누기 오류(ZeroDivisionError) 나므로 방어
        print(f"\ndescription 평균 길이: {sum(desc_lens)//len(desc_lens)}자")


if __name__ == "__main__":
    # 이 파일을 직접 실행했을 때만 main() 호출 (다른 파일에서 import할 땐 실행 안 됨)
    main()
