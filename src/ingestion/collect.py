# 직군별 Adzuna 공고 수집 → Neo4j 적재 일괄 스크립트
from __future__ import annotations

import json
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env")

from openai import OpenAI

from src.ingestion.adzuna_client import fetch_jobs
from src.ingestion.pipeline import filter_by_job_family, step_extract_skills, step_ingest

# 직군 → Adzuna 검색 쿼리 매핑
_QUERIES: dict[str, list[str]] = {
    "ML Engineer":       ["machine learning engineer", "mlops engineer"],
    "AI/LLM Engineer":   ["llm engineer", "ai engineer"],
    "Data Scientist":    ["data scientist"],
    "Data Analyst":      ["data analyst"],
    "Data Engineer":     ["data engineer"],
    "Software Engineer": ["software engineer", "backend developer"],
    "Frontend Engineer": ["frontend developer", "react developer"],
    "DevOps/SRE":        ["devops engineer", "site reliability engineer"],
    "Security Engineer": ["security engineer", "cybersecurity engineer"],
}

_RAW_DIR = ROOT / "data" / "raw" / "by_family"
_PROCESSED_DIR = ROOT / "data" / "processed" / "by_family"


def _normalize_adzuna(j: dict) -> None:
    """Adzuna API dict 필드를 Neo4j 호환 스칼라로 in-place 변환."""
    for field, key in (("company", "display_name"), ("location", "display_name")):
        v = j.get(field)
        if isinstance(v, dict):
            j[field] = v.get(key) or v.get("name") or ""
    if isinstance(j.get("category"), dict):
        j["category"] = j["category"].get("label", "")
    j.pop("__CLASS__", None)
    j.pop("adref", None)
    # 스킬 추출기가 text_clean을 사용하므로 description을 매핑
    if not j.get("text_clean") and j.get("description"):
        j["text_clean"] = j["description"]
    # description → required/preferred 섹션 파싱 (RAGAS faithfulness 측정용)
    if j.get("description") and not j.get("required_section"):
        from src.ingestion.preprocessor import (
            extract_sections, extract_bullet_section,
            extract_requirement_sentences, strip_html,
        )
        desc = j["description"]
        req, pref = extract_sections(desc)                          # HTML 헤더 기반
        if not req:
            req = extract_bullet_section(strip_html(desc))          # 불릿 클러스터
        if not req:
            req = extract_requirement_sentences(strip_html(desc), min_sentences=1)  # 요건 문장
        j["required_section"] = req
        j["preferred_section"] = pref


def collect_family(family: str, pages: int = 5, country: str = "gb") -> Path:
    """단일 직군 공고를 수집해 raw JSON으로 저장한다. 쿼리 여러 개면 합산."""
    _RAW_DIR.mkdir(parents=True, exist_ok=True)
    out = _RAW_DIR / f"{family.replace('/', '_').replace(' ', '_')}.json"

    queries = _QUERIES[family]
    all_jobs: list[dict] = []
    seen_ids: set[str] = set()

    for query in queries:
        print(f"  query='{query}' ({pages}페이지) ...", end=" ", flush=True)
        batch = fetch_jobs(query, country=country, n=50, pages=pages)
        new = [j for j in batch if j.get("id") not in seen_ids]
        seen_ids.update(j["id"] for j in new if j.get("id"))
        all_jobs.extend(new)
        print(f"+{len(new)}개")
        time.sleep(0.5)

    print(f"[{family}] 총 {len(all_jobs)}개 수신")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(all_jobs, f, ensure_ascii=False, indent=2)
    return out


def collect_and_ingest(
    families: list[str] | None = None,
    pages: int = 5,
    country: str = "gb",
) -> None:
    """지정 직군(기본: 전체)의 공고를 수집 → 스킬 추출 → Neo4j 적재."""
    targets = families or list(_QUERIES.keys())
    openai = OpenAI()

    for family in targets:
        raw_path = collect_family(family, pages=pages, country=country)
        time.sleep(1)  # rate limit 여유

        with open(raw_path, encoding="utf-8") as f:
            raw_jobs = json.load(f)

        # Adzuna raw → Neo4j 호환 포맷 (dict 필드 평탄화)
        for j in raw_jobs:
            _normalize_adzuna(j)

        # 직군 필터 (title 기반으로 불필요한 공고 제거)
        filtered = filter_by_job_family(raw_jobs)
        if not filtered:
            print(f"  [{family}] 직군 필터 후 0개 — 건너뜀")
            continue

        processed_path = _PROCESSED_DIR / f"{family.replace('/', '_').replace(' ', '_')}_skills.json"
        _PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

        jobs_with_skills = step_extract_skills(filtered, processed_path)
        step_ingest(jobs_with_skills)
        print(f"  [{family}] 완료\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="직군별 공고 수집 + Neo4j 적재")
    parser.add_argument("--families", nargs="+", help="수집할 직군 (기본: 전체)")
    parser.add_argument("--pages", type=int, default=5, help="Adzuna 페이지 수 (50개/페이지, 기본: 5)")
    parser.add_argument("--country", default="gb", help="국가 코드 (기본: gb)")
    args = parser.parse_args()

    collect_and_ingest(families=args.families, pages=args.pages, country=args.country)
