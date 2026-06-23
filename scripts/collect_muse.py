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
from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data" / "raw" / "jobs_raw_muse.json"

BASE_URL = "https://www.themuse.com/api/public/jobs"

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
MAX_PAGES = 50        # 카테고리당 최대 페이지


def is_relevant(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in TITLE_KEYWORDS)


def fetch_page(category: str, page: int) -> list[dict]:
    resp = httpx.get(
        BASE_URL,
        params={"category": category, "page": page},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("results", [])


def main() -> None:
    existing: dict[str, dict] = {}
    if OUT_PATH.exists():
        with open(OUT_PATH, encoding="utf-8") as f:
            for job in json.load(f):
                existing[str(job["id"])] = job
        print(f"기존 공고 {len(existing)}개 로드")

    company_count: Counter = Counter(
        j.get("company", {}).get("name", "?")
        for j in existing.values()
    )

    new_count = 0

    for category in CATEGORIES:
        print(f"\n카테고리: \"{category}\"")
        cat_new = 0

        for page in range(1, MAX_PAGES + 1):
            try:
                results = fetch_page(category, page)
            except Exception as e:
                print(f"  페이지 {page} 오류: {e}")
                break

            if not results:
                print(f"  페이지 {page}: 결과 없음 — 중단")
                break

            added = 0
            for job in results:
                job_id = str(job.get("id", ""))
                title = job.get("name", "")
                company = job.get("company", {}).get("name", "?")

                if not is_relevant(title):
                    continue
                if company_count[company] >= MAX_PER_COMPANY:
                    continue
                if job_id in existing:
                    continue

                job["_collected_category"] = category
                existing[job_id] = job
                company_count[company] += 1
                new_count += 1
                added += 1
                cat_new += 1

            print(f"  페이지 {page:2d}: {len(results)}개 조회 / {added}개 추가 (카테고리 누적 {cat_new}개)")
            time.sleep(0.4)

        print(f"  → \"{category}\" 소계: {cat_new}개")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(list(existing.values()), f, ensure_ascii=False, indent=2)

    print(f"\n신규 {new_count}개 추가 → 총 {len(existing)}개")
    print(f"저장: {OUT_PATH}")

    jobs = list(existing.values())

    cat_stat = Counter(j.get("_collected_category", "?") for j in jobs)
    print("\n카테고리별:")
    for cat, cnt in cat_stat.most_common():
        print(f"  {cat}: {cnt}개")

    level_stat = Counter(
        lv["name"] for j in jobs for lv in j.get("levels", [])
    )
    print("\n레벨별:")
    for lv, cnt in level_stat.most_common():
        print(f"  {lv}: {cnt}개")

    desc_lens = [len(j.get("contents", "")) for j in jobs]
    if desc_lens:
        print(f"\ndescription 평균 길이: {sum(desc_lens)//len(desc_lens)}자")


if __name__ == "__main__":
    main()
