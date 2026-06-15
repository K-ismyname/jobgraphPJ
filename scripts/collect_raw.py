# Adzuna API 에서 채용공고 원본을 수집해 data/raw/jobs_raw.json 에 저장하는 스크립트
"""
사용법: python scripts/collect_raw.py

- 가공 없이 Adzuna API 응답 그대로 저장
- 중복 공고(id 기준)는 자동 제거
- 기존 파일이 있으면 병합 (새 공고만 추가)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from src.ingestion.adzuna_client import fetch_jobs

# 부족 직군 보강용 검색어 — 직군별 특화어 포함 (SE·DE·DA는 이미 충분해 제외)
QUERIES = [
    # Frontend
    "frontend react", "frontend vue typescript", "react developer",
    # ML
    "machine learning engineer", "mlops engineer", "ml engineer pytorch",
    # Security
    "security engineer", "cybersecurity siem soc", "application security",
    # AI/LLM
    "llm engineer", "generative ai engineer", "ai engineer rag langchain",
    # Data Scientist
    "data scientist", "data scientist machine learning", "data scientist statistics",
    # DevOps
    "devops engineer", "site reliability engineer", "platform engineer kubernetes",
]

RESULTS_PER_QUERY = 15   # 쿼리당 최대 공고 수
OUT_PATH = ROOT / "data" / "raw" / "jobs_raw.json"


def main() -> None:
    # 기존 파일 로드
    existing: dict[str, dict] = {}
    if OUT_PATH.exists():
        with open(OUT_PATH, encoding="utf-8") as f:
            for job in json.load(f):
                existing[job["id"]] = job
        print(f"기존 공고 {len(existing)}개 로드")

    new_count = 0
    for query in QUERIES:
        print(f"\n검색: \"{query}\"")
        try:
            jobs = fetch_jobs(query, country="gb", n=RESULTS_PER_QUERY)
        except Exception as e:
            print(f"  오류: {e}")
            continue

        for job in jobs:
            job_id = str(job.get("id", ""))
            if job_id and job_id not in existing:
                existing[job_id] = job
                new_count += 1
                title = job.get("title", "?")
                company = job.get("company", {})
                name = company.get("display_name", "?") if isinstance(company, dict) else company
                print(f"  + [{job_id}] {title} @ {name}")
            else:
                print(f"  - 중복 skip: {job.get('title', '?')}")

        time.sleep(0.5)   # API 요청 간격

    # 저장
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(list(existing.values()), f, ensure_ascii=False, indent=2)

    print(f"\n신규 {new_count}개 추가 → 총 {len(existing)}개")
    print(f"저장: {OUT_PATH}")


if __name__ == "__main__":
    main()
