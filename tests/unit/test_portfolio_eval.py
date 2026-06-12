# 포트폴리오 평가자 — 순수 파싱·병합 + 입력 가드 (vision/LLM 미호출)
from unittest.mock import MagicMock
from src.agent.evaluators.portfolio_eval import (
    create_portfolio_evaluator,
    _skills_from_vision,
    _merge_skills,
    _partition_pages,
)


def test_no_path_empty():
    node = create_portfolio_evaluator(MagicMock())
    out = node({"portfolio_path": None})
    assert out["portfolio_eval"]["skills"] == []


def test_skills_from_vision_maps_source_and_where():
    data = {"skills": [
        {"skill": "LangGraph", "evidence": "멀티에이전트 다이어그램", "where": "diagram"},
        {"skill": "FastAPI", "evidence": "API 서버 스크린샷", "where": "screenshot"},
        {"not_skill": 1},          # skill 없는 항목은 무시
    ]}
    skills = _skills_from_vision(data)
    assert {s["skill"] for s in skills} == {"LangGraph", "FastAPI"}
    assert all(s["source"] == "portfolio" for s in skills)
    assert "diagram" in next(s["evidence"] for s in skills if s["skill"] == "LangGraph")


def test_merge_skills_dedupes_by_normalized_name():
    alls = [
        {"skill": "react.js", "evidence": "1p", "source": "portfolio", "level_hint": None},
        {"skill": "React", "evidence": "3p", "source": "portfolio", "level_hint": None},  # 정규화 시 중복
        {"skill": "Docker", "evidence": "2p", "source": "portfolio", "level_hint": None},
    ]
    merged = _merge_skills(alls)
    names = [s["skill"] for s in merged]
    assert names == ["react.js", "Docker"]   # 첫 등장(react.js) 유지, React 제거


def test_partition_pages_routes_text_and_image():
    # 텍스트가 충분한 페이지는 누적, 빈약/공백 페이지는 vision 대상 인덱스로
    page_texts = [
        "프로젝트 상세 설명이 충분히 긴 텍스트 페이지입니다. " * 3,  # 텍스트
        "",                                                      # 이미지(빈 텍스트)
        "   ",                                                   # 이미지(공백만)
        "또 다른 텍스트 페이지 내용이 길게 들어 있습니다. " * 3,      # 텍스트
    ]
    text, image_pages = _partition_pages(page_texts)
    assert image_pages == [1, 2]
    assert "프로젝트 상세" in text and "또 다른" in text
