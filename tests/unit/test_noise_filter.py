# 노이즈 스킬 필터 — 개념어는 걸러내되 실재 언어는 지켜야 한다
import pytest

from src.extraction.normalizer import is_noise_skill
from src.ingestion.pipeline import _normalize_skills


@pytest.mark.parametrize("name", [
    "DevOps",               # 직무명이지 습득할 스킬이 아님
    "Distributed Systems",  # 개념
    "Data Modeling",        # 개념
    "APIS",                 # 비스킬 표현
    "communication",        # 소프트스킬
    "Agile", "Scrum", "Jira",   # 방법론·협업도구
    "CISSP",                # 자격증
    "a", "",                # 너무 짧음
])
def test_noise_is_filtered(name):
    assert is_noise_skill(name) is True


@pytest.mark.parametrize("name", [
    "R",        # 통계 언어 — 한 글자라고 걸러내면 안 된다 (Data Analyst/Scientist 핵심)
    "C",        # 언어
    "Go",
    "Python", "Docker", "Kubernetes", "PyTorch",
])
def test_real_skills_survive(name):
    assert is_noise_skill(name) is False


def test_r_survives_normalization_pipeline():
    """R이 적재 파이프라인을 통과해야 한다.

    is_noise_skill의 길이 기준(len <= 1)에 R이 걸려, 노이즈 필터를 배선하는 순간
    R이 통째로 사라질 뻔했다 (라이브 DB에 REQUIRES 21건 보유).
    """
    out = _normalize_skills({"required": ["R", "SQL", "DevOps"], "preferred": []})
    assert "R" in out["required"]
    assert "SQL" in out["required"]
    assert "DevOps" not in out["required"]   # 개념어는 제거


def test_pipeline_drops_noise_and_dedupes():
    out = _normalize_skills({
        "required": ["Python", "python", "Distributed Systems", "APIS", "k8s"],
        "preferred": ["Agile"],
    })
    assert out["required"] == ["Python", "Kubernetes"]   # 중복·노이즈 제거, 별칭 정규화
    assert out["preferred"] == []
