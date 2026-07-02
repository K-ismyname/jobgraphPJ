# 스킬명 단어경계 매칭·별칭 키워드 확장 — 여러 평가자·툴·평가 모듈이 공유
from __future__ import annotations

import re

from src.extraction.normalizer import SKILL_ALIASES


def word_match(keyword: str, text: str) -> bool:
    """단어 경계 매칭. 'react'가 'reaction'에, 'aws'가 'draws'에 오탐되지 않게 한다."""
    pattern = rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])"
    return re.search(pattern, text) is not None


def keywords_for(skill: str) -> list[str]:
    """스킬명 + 같은 정규화명을 갖는 별칭들을 매칭 키워드로."""
    canon = skill.lower()
    kws = {canon}
    for alias, mapped in SKILL_ALIASES.items():
        if mapped.lower() == canon:
            kws.add(alias.lower())
    return list(kws)
