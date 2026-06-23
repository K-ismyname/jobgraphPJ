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


def test_normalize_skill_unifies_case_for_unmapped():
    # 사전 미등록 스킬도 표기 통일 — 대소문자만 다른 중복 방지
    a = normalize_skill("machine learning")
    b = normalize_skill("Machine Learning")
    c = normalize_skill("MACHINE LEARNING")
    assert a == b == c == "Machine Learning"


def test_normalize_skill_keeps_acronym_case():
    # 약어는 대문자 유지 (smart_title)
    assert normalize_skill("mlops") == "MLOps" or normalize_skill("mlops") == "MLOPS"


def test_normalize_skill_ai_ml_synonyms():
    assert normalize_skill("ML") == "Machine Learning"
    assert normalize_skill("machine learning") == "Machine Learning"
    assert normalize_skill("Artificial Intelligence") == "AI"
    assert normalize_skill("AI") == "AI"
    assert normalize_skill("LLMs") == "LLM"
    assert normalize_skill("LLM") == "LLM"
    assert normalize_skill("GenAI") == "GenAI"
    assert normalize_skill("generative ai") == "GenAI"
    assert normalize_skill("Retrieval Augmented Generation") == "RAG"


def test_normalize_skill_brand_casing():
    # 약어·브랜드 표기가 깔끔하게 (smart_title가 틀리던 것들)
    assert normalize_skill("mlops") == "MLOps"
    assert normalize_skill("DEVOPS") == "DevOps"
    assert normalize_skill("siem") == "SIEM"
    assert normalize_skill("github") == "GitHub"
    assert normalize_skill("power bi") == "Power BI"
    assert normalize_skill("dbt") == "dbt"
    assert normalize_skill("css") == "CSS"
    assert normalize_skill("html") == "HTML"
