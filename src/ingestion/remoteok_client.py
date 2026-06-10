# RemoteOK API에서 개발자 채용공고를 수집하는 클라이언트
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# 개발자 직무 관련 태그
_DEV_TAGS = [
    "backend", "devops", "python", "javascript", "typescript",
    "react", "node", "java", "golang", "aws", "kubernetes", "data",
]

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; job-skill-analyzer/1.0)"}


def fetch_by_tag(tag: str) -> list[dict]:
    """태그 하나로 공고 목록 수집."""
    url = f"https://remoteok.com/api?tags={tag}"
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
        jobs = [d for d in data if isinstance(d, dict) and "slug" in d]
        for job in jobs:
            job["_collected_tag"] = tag
        return jobs
    except Exception as e:
        print(f"  [오류] tag={tag}: {e}")
        return []


def fetch_all(
    tags: list[str] = _DEV_TAGS,
    delay: float = 1.0,
) -> list[dict]:
    """여러 태그로 수집 후 중복(slug 기준) 제거."""
    seen: set[str] = set()
    all_jobs: list[dict] = []

    for tag in tags:
        jobs = fetch_by_tag(tag)
        fresh = [j for j in jobs if j["slug"] not in seen]
        seen.update(j["slug"] for j in fresh)
        all_jobs.extend(fresh)
        print(f"  {tag}: {len(jobs)}개 수집, 신규 {len(fresh)}개 (누적 {len(all_jobs)}개)")
        time.sleep(delay)

    return all_jobs


def save(jobs: list[dict], output_path: str | Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)
    print(f"저장 완료: {len(jobs)}개 → {output_path}")


if __name__ == "__main__":
    print("=== RemoteOK 개발자 공고 수집 ===")
    jobs = fetch_all()
    save(jobs, ROOT / "data" / "raw" / "jobs_remoteok.json")
