# 학습 추천 reason 결정적 조립 — LLM 일반론을 그래프 사실로 교체하는지 검증
import json

from src.agent.nodes import build_deterministic_reasons


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
