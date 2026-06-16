# 원본 공고 JSON → 전처리 → 스킬 추출 → Neo4j 적재 파이프라인
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT / ".env")

from openai import OpenAI

from src.ingestion.preprocessor import preprocess_file, preprocess_remoteok_file
from src.extraction.skill_extractor import extract_skills_from_posting
from src.extraction.normalizer import normalize_skill

def filter_by_job_family(jobs: list[dict]) -> list[dict]:
    """확실한 직군이 아닌 공고를 제거한다."""
    kept = [j for j in jobs if _job_family(j["title"]) is not None]
    removed = len(jobs) - len(kept)
    if removed:
        print(f"직군 필터: {len(jobs)}개 → {len(kept)}개 ({removed}개 제거)")
    return kept
from src.storage.neo4j_client import Neo4jClient


_JOB_FAMILIES = {
    'ML Engineer':       ['ml engineer','machine learning engineer','ml ops','mlops'],
    'AI/LLM Engineer':   ['ai engineer','ai/ml','llm','genai','agentic ai'],
    'Data Scientist':    ['data scientist','data science'],
    'Data Analyst':      ['data analyst','data analytics','business analyst','bi '],
    'Data Engineer':     ['data engineer','data platform','etl','spark','databricks'],
    'Software Engineer': ['backend engineer','backend developer','software engineer','software developer','full stack','fullstack'],
    'Frontend Engineer': ['frontend','front end','front-end'],
    'DevOps/SRE':        ['devops','sre','site reliability','platform engineer','infrastructure engineer','cloud engineer'],
    'Security Engineer': ['security engineer','appsec','application security','cybersecurity',
                          'infosec','soc analyst','security analyst','penetration test','pentest',
                          'threat detection','incident response','security operations','vulnerability'],
}

def _job_family(title: str) -> str | None:
    """타이틀에서 직군을 판별. 확실한 직군이 아니면 None 반환."""
    t = title.lower()
    for family, keywords in _JOB_FAMILIES.items():
        if any(k in t for k in keywords):
            return family
    return None


def _normalize_skills(skills: dict) -> dict:
    """추출된 스킬 목록에서 normalize_skill() 적용 + 중복 제거."""
    for group in ("required", "preferred"):
        seen: set[str] = set()
        deduped: list[str] = []
        for name in skills.get(group, []):
            normalized = normalize_skill(name) if isinstance(name, str) else normalize_skill(name.get("name", ""))
            if normalized and normalized not in seen:
                seen.add(normalized)
                deduped.append(normalized)
        skills[group] = deduped
    return skills

_DEFAULT_RAW = ROOT / "data" / "raw" / "jobs_data_analytics.json"
_DEFAULT_PROCESSED = ROOT / "data" / "processed" / "jobs_da_processed.json"
_DEFAULT_WITH_SKILLS = ROOT / "data" / "processed" / "jobs_da_with_skills.json"

# RemoteOK 경로
_REMOTEOK_RAW = ROOT / "data" / "raw" / "jobs_remoteok.json"
_REMOTEOK_PROCESSED = ROOT / "data" / "processed" / "jobs_remoteok_processed.json"
_REMOTEOK_WITH_SKILLS = ROOT / "data" / "processed" / "jobs_remoteok_with_skills.json"


def _get_openai() -> OpenAI:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise EnvironmentError("OPENAI_API_KEY 환경변수가 필요합니다.")
    return OpenAI(api_key=key)


def _save_json(data: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def step_preprocess(
    raw_path: Path = _DEFAULT_RAW,
    processed_path: Path = _DEFAULT_PROCESSED,
    *,
    force: bool = False,
) -> list[dict]:
    """Step 1: raw JSON → 텍스트 정제 + 섹션 분리."""
    if not force and processed_path.exists():
        print(f"[skip] 전처리 파일 존재: {processed_path}")
        with open(processed_path, encoding="utf-8") as f:
            return json.load(f)
    print("=== Step 1: 전처리 ===")
    return preprocess_file(raw_path, processed_path)


def step_extract_skills(
    jobs: list[dict],
    output_path: Path = _DEFAULT_WITH_SKILLS,
) -> list[dict]:
    """Step 2: 전처리 공고 → LLM 스킬 추출. 기추출 공고는 스킵."""
    openai = _get_openai()

    already: dict[str, dict] = {}
    if output_path.exists():
        with open(output_path, encoding="utf-8") as f:
            for j in json.load(f):
                already[j["id"]] = j

    pending = [j for j in jobs if j["id"] not in already]
    print(f"\n=== Step 2: 스킬 추출 (신규 {len(pending)}개 / 전체 {len(jobs)}개) ===")

    for i, job in enumerate(pending):
        try:
            skills = _normalize_skills(extract_skills_from_posting(job, openai))
            job["skills"] = skills
            already[job["id"]] = job
            req_n = len(skills.get("required", []))
            pref_n = len(skills.get("preferred", []))
            print(f"  [{i+1}/{len(pending)}] {job['title'][:45]:<45} req={req_n} pref={pref_n}")
        except Exception as e:
            print(f"  [{i+1}/{len(pending)}] {job['title'][:45]:<45} 오류: {e}")

        if (i + 1) % 10 == 0:
            _save_json(list(already.values()), output_path)

        time.sleep(0.3)

    _save_json(list(already.values()), output_path)
    extracted = [j for j in already.values() if "skills" in j]
    print(f"스킬 추출 완료: {len(extracted)}/{len(already)}개 → {output_path}")
    return list(already.values())


def step_ingest(jobs: list[dict]) -> None:
    """Step 3: Neo4j에 공고·스킬·관계 적재."""
    neo4j = Neo4jClient()

    try:
        neo4j.setup_constraints()
        neo4j.load_skill_seeds()

        ingestible = [j for j in jobs if "skills" in j]
        print(f"\n=== Step 3: Neo4j 적재 ({len(ingestible)}개) ===")

        success = 0
        for job in ingestible:
            try:
                neo4j.ingest_posting(job)
                success += 1
            except Exception as e:
                print(f"  [오류] {job.get('title', '?')}: {e}")

        print(f"적재 완료: {success}/{len(ingestible)}개")
    finally:
        neo4j.close()


def step_preprocess_remoteok(
    raw_path: Path = _REMOTEOK_RAW,
    processed_path: Path = _REMOTEOK_PROCESSED,
    *,
    force: bool = False,
) -> list[dict]:
    """Step 1 (RemoteOK): raw JSON → 개발자 필터 + 텍스트 정제 + 섹션 분리."""
    if not force and processed_path.exists():
        print(f"[skip] 전처리 파일 존재: {processed_path}")
        with open(processed_path, encoding="utf-8") as f:
            return json.load(f)
    print("=== Step 1: RemoteOK 전처리 ===")
    return preprocess_remoteok_file(raw_path, processed_path)


def run_remoteok_pipeline(
    raw_path: str | Path = _REMOTEOK_RAW,
    processed_path: str | Path = _REMOTEOK_PROCESSED,
    with_skills_path: str | Path = _REMOTEOK_WITH_SKILLS,
    *,
    limit: int | None = None,
    force_preprocess: bool = False,
    skip_ingest: bool = False,
) -> None:
    """RemoteOK 전체 파이프라인 실행."""
    jobs = step_preprocess_remoteok(
        Path(raw_path), Path(processed_path), force=force_preprocess
    )

    if limit:
        jobs = jobs[:limit]
        print(f"(limit={limit})")

    jobs = step_extract_skills(jobs, Path(with_skills_path))

    if not skip_ingest:
        step_ingest(jobs)


def run_pipeline(
    raw_path: str | Path = _DEFAULT_RAW,
    processed_path: str | Path = _DEFAULT_PROCESSED,
    with_skills_path: str | Path = _DEFAULT_WITH_SKILLS,
    *,
    limit: int | None = None,
    force_preprocess: bool = False,
    skip_ingest: bool = False,
) -> None:
    """전체 파이프라인 실행.

    Args:
        limit: 처리할 공고 수 상한 (테스트용)
        force_preprocess: 기존 전처리 파일이 있어도 재생성
        skip_ingest: Step 3(Neo4j 적재) 건너뜀 (스킬 추출만 실행할 때)
    """
    jobs = step_preprocess(Path(raw_path), Path(processed_path), force=force_preprocess)

    if limit:
        jobs = jobs[:limit]
        print(f"(limit={limit})")

    jobs = step_extract_skills(jobs, Path(with_skills_path))

    if not skip_ingest:
        step_ingest(jobs)


_FILTERED = ROOT / "data" / "processed" / "jobs_filtered.json"


def run_ingest_all(
    filtered_path: str | Path = _FILTERED,
    *,
    clear: bool = False,
) -> None:
    """jobs_filtered.json → Neo4j 전체 적재."""
    with open(filtered_path, encoding="utf-8") as f:
        jobs = json.load(f)

    neo4j = Neo4jClient()
    try:
        if clear:
            neo4j.clear_all()

        neo4j.setup_constraints()
        neo4j.load_skill_seeds()

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
    import argparse

    parser = argparse.ArgumentParser(description="DA 채용공고 수집 파이프라인")
    parser.add_argument("--limit", type=int, default=None, help="처리할 공고 수 상한 (테스트용)")
    parser.add_argument("--force-preprocess", action="store_true", help="전처리 재실행")
    parser.add_argument("--skip-ingest", action="store_true", help="Neo4j 적재 건너뜀")
    args = parser.parse_args()

    run_pipeline(
        limit=args.limit,
        force_preprocess=args.force_preprocess,
        skip_ingest=args.skip_ingest,
    )
