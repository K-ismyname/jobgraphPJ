"""스킬 대체군/동등군 규칙.

데이터가 적은 직군에서는 빈도 상위 스킬에 같은 역할의 기술이 여러 개 올라와
"React를 쓰는데 Vue.js와 Angular도 부족" 같은 오탐이 생긴다. 여기서는 명확한 대체군만
작게 유지해 gap 계산과 capability fit에서 같은 그룹을 하나의 요구로 접는다.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from src.extraction.normalizer import normalize_skill

_ROOT = Path(__file__).resolve().parents[2]
_SEED_PATH = _ROOT / "data" / "seeds" / "skill_alternatives.json"
_DEFAULT_ALTERNATIVE_SKILL_GROUPS: tuple[tuple[str, ...], ...] = (
    ("React", "Vue.js", "Angular"),
    ("AWS", "Azure", "GCP"),
)


@lru_cache(maxsize=1)
def alternative_skill_groups() -> tuple[tuple[str, ...], ...]:
    """대체군 시드 파일을 읽는다. 실패 시 작은 기본값으로 동작한다."""
    try:
        with open(_SEED_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return _DEFAULT_ALTERNATIVE_SKILL_GROUPS

    groups: list[tuple[str, ...]] = []
    for item in data:
        group = item.get("group") if isinstance(item, dict) else item
        if not isinstance(group, list):
            continue
        normalized = tuple(normalize_skill(s) for s in group if isinstance(s, str) and s.strip())
        if len(normalized) >= 2:
            groups.append(normalized)
    return tuple(groups) or _DEFAULT_ALTERNATIVE_SKILL_GROUPS


def _group_by_skill() -> dict[str, int]:
    return {
        normalize_skill(skill).lower(): idx
        for idx, group in enumerate(alternative_skill_groups())
        for skill in group
    }


def alternative_group_id(skill: str) -> int | None:
    """스킬이 속한 대체군 id. 대체군이 아니면 None."""
    return _group_by_skill().get(normalize_skill(skill).lower())


def collapse_alternatives(skills: list[str], owned_skills: list[str] | None = None) -> list[str]:
    """대체군 스킬은 그룹당 하나로 접는다.

    같은 그룹 안에 보유 스킬이 있으면 보유 스킬을 대표로 고르고, 없으면 입력 순서상 첫 스킬
    (이미 빈도순으로 정렬된 목록에서는 가장 자주 요구된 스킬)을 대표로 둔다.
    """
    owned_norm = {normalize_skill(s).lower() for s in (owned_skills or [])}
    out: list[str] = []
    seen_groups: set[int] = set()

    for skill in skills:
        group_id = alternative_group_id(skill)
        if group_id is None:
            out.append(skill)
            continue
        if group_id in seen_groups:
            continue
        seen_groups.add(group_id)
        group = alternative_skill_groups()[group_id]
        owned_in_group = [s for s in group if normalize_skill(s).lower() in owned_norm]
        out.append(owned_in_group[0] if owned_in_group else skill)
    return out
