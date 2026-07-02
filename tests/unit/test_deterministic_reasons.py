# 학습 추천 reason 결정적 조립 — LLM 일반론을 그래프 사실로 교체하는지 검증
import json

from src.agent.nodes import (
    build_deterministic_reasons,
    build_deterministic_project_reasons,
    _excerpt_around_keyword,
)


_MISSING = [{"skill": "Machine Learning", "weight": 12}]
_VERIFY = {"Machine Learning": {
    "posting_count": 5,
    "evidence": [{"source_id": "p1", "company": "ACME",
                  "text": "ML 파이프라인 구축 및 모델 서빙 경험 필수"}],
}}
_CONSENSUS = {"Python": {"verification": "Verified", "evidences": []}}
_NEIGHBORS = {"Machine Learning": ["Python", "SQL"]}


def test_full_evidence_reason():
    out = build_deterministic_reasons(_MISSING, _VERIFY, _CONSENSUS, _NEIGHBORS)
    reason = out["Machine Learning"]
    assert "12건" in reason                       # 요구 건수
    assert "ACME" in reason                        # 실제 회사
    assert "ML 파이프라인" in reason               # 공고 원문 발췌
    assert "Python(검증됨)" in reason              # 보유 스킬 연결
    # 일반론 표현이 아니라 전부 데이터 슬롯 — 거짓말 불가


def test_no_excerpt_still_grounded():
    out = build_deterministic_reasons(_MISSING, {}, _CONSENSUS, _NEIGHBORS)
    reason = out["Machine Learning"]
    assert "12건" in reason and "Python" in reason


def test_no_data_skill_excluded():
    # 재료가 하나도 없으면 맵에서 제외 — LLM reason 유지 경로
    out = build_deterministic_reasons([{"skill": "Java"}], {}, {}, {})
    assert "Java" not in out


def test_neighbor_not_held_is_skipped():
    # CO_OCCURS 이웃이라도 consensus에 없으면(미보유) 연결 문장 없음
    out = build_deterministic_reasons(_MISSING, {}, {}, {"Machine Learning": ["Scala"]})
    assert "Scala" not in out.get("Machine Learning", "")


def test_finalize_coach_overwrites_generic_reason(monkeypatch):
    # 통합: LLM이 쓴 일반론 reason이 결정적 조립값으로 덮어써지는지
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    from langchain_core.messages import AIMessage
    from src.agent.nodes import create_coach_nodes

    _, finalize = create_coach_nodes([])
    coaching = {"learning_recommendations": [
        {"skill": "Machine Learning", "reason": "복잡한 문제 해결에 필요합니다.", "how": "학습하세요."},
    ]}
    state = {
        "coach_messages": [AIMessage(content=json.dumps(coaching, ensure_ascii=False))],
        "gap_result": {"deterministic_reasons": {
            "Machine Learning": "이 직군 공고 12건이 필수로 요구합니다. ACME 공고: \"ML 파이프라인…\"",
        }},
        "consensus": {},
        "project_contexts": [],
    }
    out = finalize(state)
    rec = out["coaching_result"]["learning_recommendations"][0]
    assert "12건" in rec["reason"]
    assert "복잡한 문제 해결" not in rec["reason"]   # 일반론 제거됨


# ── _excerpt_around_keyword: 발췌 절단이 키워드를 잘라내던 문제 ──────────
def test_excerpt_keeps_keyword_when_late_in_sentence():
    # 실제 오탐 재현: 키워드가 90자 이후에 나와도 잘리지 않아야 함
    text = ("NVIDIA's Enterprise Product Group is seeking a highly technical "
            "GenAI Product Integration engineer with strong Docker and Kubernetes experience")
    out = _excerpt_around_keyword("Docker", text, window=40)
    assert "Docker" in out


def test_excerpt_short_text_untouched():
    out = _excerpt_around_keyword("Machine Learning", "ML 파이프라인 구축 경험 필수")
    assert "ML" in out or "ml" in out.lower()
    assert not out.startswith("…")


def test_excerpt_no_keyword_match_falls_back_to_prefix():
    out = _excerpt_around_keyword("Rust", "이 공고는 Python 경험을 요구합니다" * 5, window=20)
    assert len(out) <= 25   # window + 말줄임표 정도


def test_excerpt_empty_text():
    assert _excerpt_around_keyword("Docker", "") == ""


# ── build_deterministic_project_reasons: ③ project_suggestions 근거 결정화 ──
def test_project_reason_grounded_in_relevant_files():
    contexts = [{"repo": "me/app", "skill_assessments": [
        {"skill": "AI", "current_usage": "중급 패턴",
         "used_patterns": ["OpenAI 함수 호출", "구조화 출력 파싱"],
         "relevant_files": ["src/agent/nodes.py", "src/agent/tools.py"]},
    ]}]
    out = build_deterministic_project_reasons(contexts)
    reason = out["AI"]
    assert "me/app" in reason
    assert "src/agent/nodes.py" in reason
    assert "중급 패턴" in reason
    assert "OpenAI 함수 호출" in reason


def test_project_reason_skips_no_files_skill():
    # code_anchor=false(relevant_files 없음) 스킬은 제외 — LLM why 유지 경로
    contexts = [{"repo": "me/app", "skill_assessments": [
        {"skill": "Kubernetes", "current_usage": "기본 사용", "relevant_files": []},
    ]}]
    out = build_deterministic_project_reasons(contexts)
    assert "Kubernetes" not in out


def test_finalize_coach_overwrites_project_suggestion_why(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    from langchain_core.messages import AIMessage
    from src.agent.nodes import create_coach_nodes

    _, finalize = create_coach_nodes([])
    coaching = {"project_suggestions": [
        {"repo": "me/app", "add_skill": "AI", "why": "추가하면 강화됩니다.", "how": "확장하세요."},
    ]}
    state = {
        "coach_messages": [AIMessage(content=json.dumps(coaching, ensure_ascii=False))],
        "gap_result": {},
        "consensus": {},
        "project_contexts": [{"repo": "me/app", "skill_assessments": [
            {"skill": "AI", "current_usage": "고급 패턴",
             "used_patterns": ["멀티에이전트 오케스트레이션"],
             "relevant_files": ["src/agent/supervisor.py"]},
        ]}],
    }
    out = finalize(state)
    rec = out["coaching_result"]["project_suggestions"][0]
    assert "supervisor.py" in rec["why"]
    assert "고급 패턴" in rec["why"]
    assert rec["why"] != "추가하면 강화됩니다."
