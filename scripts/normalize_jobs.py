# jobs.json 의 skill name 을 정규화하고 대소문자 중복을 제거하는 스크립트
"""
사용법: python scripts/normalize_jobs.py

jobs.json 을 읽어 각 skill name 에 대해:
1. normalize_skill() — SKILL_ALIASES 사전 매핑
2. smart_title() — 사전 미등록 기술은 단어 첫글자 대문자 통일
3. 정규화 후 같은 이름이 된 스킬은 dedup (required 우선)
4. 결과를 jobs.json 에 덮어씀
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path 에 추가
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.extraction.normalizer import normalize_skill

# 소문자로 통일했을 때 의미없는 스킬 (concept 카테고리에서 걸러낼 항목)
NON_SKILL_CONCEPTS = {
    "ai", "platforms", "data & ai practice", "development strategy",
    "team management", "stem", "leadership", "communication",
    "llm-specific risks",  # 너무 구체적인 보안 개념
}

_TITLE_STOP = {"and", "or", "the", "of", "in", "for", "a", "an", "with", "to"}
# 대문자 유지가 필요한 약어/브랜드
_KEEP_UPPER = {
    "llm", "llms", "rag", "ai", "ml", "api", "apis", "sql", "nosql",
    "nlp", "cv", "gpu", "cpu", "iam", "sdk", "ci", "cd", "aws", "gcp",
    "etl", "sre", "ui", "ux", "url", "rest", "grpc", "mlops",
}


def smart_title(name: str) -> str:
    """단어별 첫글자 대문자. 전치사/관사 소문자, 약어는 ALL CAPS 유지."""
    words = name.split()
    result = []
    for i, w in enumerate(words):
        if w.lower() in _KEEP_UPPER:
            result.append(w.upper())
        elif i == 0 or w.lower() not in _TITLE_STOP:
            result.append(w.capitalize())
        else:
            result.append(w.lower())
    return " ".join(result)


def normalize_name(raw_name: str) -> str:
    """normalize_skill 후 smart_title 적용."""
    mapped = normalize_skill(raw_name)
    # SKILL_ALIASES 에 없으면 smart_title 로 대소문자 통일
    if mapped == raw_name:
        return smart_title(raw_name)
    return mapped


def dedup_skills(skills: list[dict]) -> list[dict]:
    """같은 정규화 이름을 가진 스킬 중 required 우선으로 dedup."""
    seen: dict[str, dict] = {}
    for s in skills:
        key = s["name"]
        if key not in seen:
            seen[key] = s
        elif s["importance"] == "required" and seen[key]["importance"] == "preferred":
            # required 가 나중에 나왔으면 교체
            seen[key] = s
    return list(seen.values())


def process_jobs(jobs: list[dict]) -> tuple[list[dict], dict]:
    stats: dict[str, int] = {"normalized": 0, "removed": 0}
    processed = []

    for job in jobs:
        new_skills: dict[str, list[dict]] = {"required": [], "preferred": []}
        for kind in ("required", "preferred"):
            for s in job.get("skills", {}).get(kind, []):
                norm = normalize_name(s["name"])

                # 비기술 concept 제거
                if s.get("category") == "concept" and norm.lower() in NON_SKILL_CONCEPTS:
                    stats["removed"] += 1
                    continue

                if norm != s["name"]:
                    stats["normalized"] += 1

                new_skills[kind].append({**s, "name": norm})

        # required + preferred 합쳐서 dedup 후 다시 분리
        all_skills = [
            {**s, "importance": "required"} for s in new_skills["required"]
        ] + [
            {**s, "importance": "preferred"} for s in new_skills["preferred"]
        ]
        deduped = dedup_skills(all_skills)
        job["skills"] = {
            "required": [s for s in deduped if s["importance"] == "required"],
            "preferred": [s for s in deduped if s["importance"] == "preferred"],
        }
        processed.append(job)

    return processed, stats


def main() -> None:
    path = ROOT / "jobs.json"
    with open(path, encoding="utf-8") as f:
        jobs = json.load(f)

    print(f"처리 전: {len(jobs)}개 공고")

    processed, stats = process_jobs(jobs)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(processed, f, ensure_ascii=False, indent=2)

    print(f"정규화: {stats['normalized']}개 스킬명 변경")
    print(f"제거  : {stats['removed']}개 비기술 concept 제거")
    print(f"저장  : {path}")

    # 결과 미리보기
    from collections import Counter
    all_skills: Counter = Counter()
    for j in processed:
        for s in j["skills"]["required"] + j["skills"]["preferred"]:
            all_skills[s["name"]] += 1

    print("\n=== 정규화 후 상위 15개 기술 ===")
    for skill, cnt in all_skills.most_common(15):
        print(f"  {skill}: {cnt}")


if __name__ == "__main__":
    main()
