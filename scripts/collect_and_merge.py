# Adzuna 원본을 중간 포맷으로 변환해 스킬 추출하고, 기존 jobs_filtered.json에 병합·재필터하는 스크립트
from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.ingestion.preprocessor import preprocess_job, is_tech_job
from src.ingestion.pipeline import step_extract_skills, _job_family

RAW = ROOT / "data" / "raw" / "jobs_raw.json"
WITH_SKILLS = ROOT / "data" / "processed" / "jobs_raw_with_skills.json"
FILTERED = ROOT / "data" / "processed" / "jobs_filtered.json"


def adzuna_to_muse(j: dict) -> dict:
    """Adzuna 원본 → preprocess_job(Muse 포맷)이 기대하는 키 구조로 변환."""
    comp = j.get("company", {})
    loc = j.get("location", {})
    return {
        "id": str(j.get("id", "")),
        "name": j.get("title", ""),
        "contents": j.get("description", ""),
        "company": {"name": comp.get("display_name", "") if isinstance(comp, dict) else str(comp)},
        "locations": [{"name": loc.get("display_name", "")}] if isinstance(loc, dict) and loc.get("display_name") else [],
        "refs": {"landing_page": j.get("redirect_url", "")},
        "publication_date": j.get("created", ""),
        "type": j.get("contract_type", ""),
    }


def main() -> None:
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    processed = [preprocess_job(adzuna_to_muse(j)) for j in raw]
    processed = [j for j in processed if is_tech_job(j["title"])]

    # (title+company) 중복 제거 — 빈 타이틀 제외
    seen: set[tuple[str, str]] = set()
    deduped: list[dict] = []
    for j in processed:
        key = (j["title"].strip().lower(), j["company"].lower())
        if j["title"].strip() and key not in seen:
            seen.add(key)
            deduped.append(j)
    print(f"Adzuna 변환·전처리: {len(raw)} → 기술·중복 필터 후 {len(deduped)}개")

    jobs = step_extract_skills(deduped, WITH_SKILLS)

    existing = {j["id"]: j for j in json.loads(FILTERED.read_text(encoding="utf-8"))}
    added = 0
    for j in jobs:
        if "skills" in j:
            if j["id"] not in existing:
                added += 1
            existing[j["id"]] = j

    # 직군 판별 후 job_family 필드 설정 (ingest_posting이 이 필드로 INSTANCE_OF 연결), 미분류 제거
    merged: list[dict] = []
    for j in existing.values():
        fam = _job_family(j["title"])
        if fam:
            j["job_family"] = fam
            merged.append(j)
    FILTERED.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"신규 {added}개 추가, 필터 후 총 {len(merged)}개 → {FILTERED}")


if __name__ == "__main__":
    main()
