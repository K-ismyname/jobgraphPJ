# 스킬명 단어경계 매칭·별칭 키워드 확장 — 여러 평가자·툴·평가 모듈이 공유
#
# 이 파일이 하는 일: "텍스트 안에 이 스킬 이름이 실제로 등장하는가"를 정확히 판단하는
# 아주 작지만 여러 곳(github_eval.py, tools.py, nodes.py, ragas_eval.py)에서 재사용되는
# 공통 유틸리티. 스킬 감지 로직이 파일마다 제각각이면 정확도가 들쭉날쭉해지므로,
# "단어 경계로 정확히 매칭"이라는 규칙을 여기 한 곳에 모아두고 다들 가져다 쓴다.

from __future__ import annotations

import re

from src.extraction.normalizer import SKILL_ALIASES
# 지난번 본 normalizer.py의 그 사전 — {"react.js": "React", "reactjs": "React", ...} —
# 을 "정규화 방향"이 아니라 "역방향 검색"에 재사용한다 (아래 keywords_for 참고)


def word_match(keyword: str, text: str) -> bool:
    """단어 경계 매칭. 'react'가 'reaction'에, 'aws'가 'draws'에 오탐되지 않게 한다."""
    # 왜 이 함수가 필요한가: 단순히 "keyword in text"(부분 문자열 포함 검사)를 쓰면
    # "react"라는 키워드가 "reaction"이라는 단어 안에도 포함돼 있어서 오탐(false positive)이 생김.
    # "aws"도 "draws"라는 단어 안에 들어있어서 마찬가지. word_match는 이런 오탐을 막기 위해
    # "그 키워드가 독립된 단어로 등장했는지"만 확인하도록 정규식을 짬.
    pattern = rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])"
    # rf"..." → f-string이면서 동시에 raw string(r) — 정규식 특수문자(\ 등)를 파이썬이 이스케이프로
    # 해석하지 않고 그대로 정규식 엔진에 넘기기 위함
    # re.escape(keyword) → keyword 안에 정규식에서 특별한 의미를 갖는 문자(., +, * 등)가 있어도
    # 그걸 "그냥 문자 그대로"로 취급하게 이스케이프 처리 (예: "C++"의 +가 정규식 문법으로 오해되지 않게)
    # (?<![a-z0-9]) → "부정 lookbehind" — 이 위치 바로 앞에 영문자/숫자가 오면 안 된다는 조건
    # (?![a-z0-9])  → "부정 lookahead"  — 이 위치 바로 뒤에 영문자/숫자가 오면 안 된다는 조건
    # 즉 "keyword 앞뒤로 영문자/숫자가 붙어있지 않아야만 매칭 인정" → "react"가 "reaction"의 일부로
    # 매칭되려면 뒤에 "ion"이 붙어있으니(뒤에 알파벳 존재) 조건을 못 만족해서 매칭 실패 처리됨
    return re.search(pattern, text) is not None
    # re.search()는 패턴에 맞는 부분이 어디든 있으면 매치 객체를, 없으면 None을 반환
    # "... is not None" → 매치 객체가 있으면 True, 없으면 False로 변환해서 bool 값으로 깔끔하게 반환


def keywords_for(skill: str) -> list[str]:
    """스킬명 + 같은 정규화명을 갖는 별칭들을 매칭 키워드로."""
    # 왜 이 함수가 필요한가: 텍스트에서 "React"라는 정규화된 표준 이름만 찾으면,
    # 실제 원문에 "react.js"나 "ReactJS"라고 쓰여 있는 경우를 놓친다.
    # 그래서 "React"의 모든 변형 표기(별칭)를 역으로 찾아내 검색 키워드 목록으로 만든다.
    canon = skill.lower()   # 입력값(보통 정규화된 표준 스킬명)을 소문자로 통일
    kws = {canon}           # 표준 이름 자체도 검색 키워드 목록에 포함 (집합으로 시작 — 중복 자동 방지)
    for alias, mapped in SKILL_ALIASES.items():
        # SKILL_ALIASES는 {"react.js": "React", "reactjs": "React", "react": "React", ...} 형태.
        # 여기서는 반대로 "값(mapped)이 지금 찾는 canon과 같은 모든 키(alias)"를 역으로 탐색
        if mapped.lower() == canon:
            kws.add(alias.lower())
            # 예: skill="React"로 호출하면 canon="react" → SKILL_ALIASES를 순회하다가
            # "react.js"→"React", "reactjs"→"React", "react"→"React", "리액트"→"React"를 전부 찾아내
            # kws에 "react.js", "reactjs", "react", "리액트"까지 다 추가됨
    return list(kws)
    # 집합(set)을 리스트로 변환해서 반환 — 호출부(word_match 등)가 for문으로 순회하기 편하게
