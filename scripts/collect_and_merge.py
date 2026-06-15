# 신규 수집분을 추출해 기존 jobs_filtered.json에 병합·재필터하는 일회성 스크립트
from __future__ import annotations

import json
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

from src.ingestion.pipeline import step_preprocess, step_extract_skills, filter_by_job_family

RAW = ROOT / "data" / "raw" / "jobs_raw.json"
PROCESSED = ROOT / "data" / "processed" / "jobs_raw_processed.json"
WITH_SKILLS = ROOT / "data" / "processed" / "jobs_raw_with_skills.json"
FILTERED = ROOT / "data" / "processed" / "jobs_filtered.json"


def main() -> None:
    # 1. 신규 raw 전처리 + 스킬 추출 (id 캐시로 기추출은 스킵)
    jobs = step_preprocess(RAW, PROCESSED, force=True)
    jobs = step_extract_skills(jobs, WITH_SKILLS)

    # 2. 기존 filtered + 신규(스킬 포함) 병합
    existing = {j["id"]: j for j in json.loads(FILTERED.read_text(encoding="utf-8"))}
    added = 0
    for j in jobs:
        if "skills" in j and j["id"] not in existing:
            added += 1
        if "skills" in j:
            existing[j["id"]] = j

    # 3. 직군 재필터 (Architect 제거 반영)
    merged = filter_by_job_family(list(existing.values()))
    FILTERED.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"신규 {added}개 추가, 필터 후 총 {len(merged)}개 → {FILTERED}")


if __name__ == "__main__":
    main()
