# normalizer.py 단위 테스트
import pytest

from src.extraction.normalizer import normalize_skill


@pytest.mark.parametrize("raw, expected", [
    # 대소문자·점·JS 변형 — ALIASES에 정의된 케이스
    ("React.js",   "React"),
    ("react.js",   "React"),
    ("reactjs",    "React"),
    ("langgraph",  "LangGraph"),
    ("LangGraph",  "LangGraph"),
    ("fastapi",    "FastAPI"),
    # 이미 정규화된 이름은 그대로
    ("Python",     "Python"),
    ("LangChain",  "LangChain"),
])
def test_normalize_skill(raw: str, expected: str) -> None:
    assert normalize_skill(raw) == expected
