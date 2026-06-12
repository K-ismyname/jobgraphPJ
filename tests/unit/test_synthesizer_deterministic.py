# synthesizer 결정적 수치 — confidence/match_rate는 코드로, fit_score는 제거 (LLM 환각 차단)
from src.agent.nodes import (
    _confidence_from_consensus,
    _match_rate_from_tools,
    _apply_deterministic_metrics,
)


def _consensus(*verifs):
    return {f"skill{i}": {"verification": v} for i, v in enumerate(verifs)}


def test_confidence_all_verified_high():
    assert _confidence_from_consensus(_consensus("Verified", "Verified", "Corroborated")) == "high"


def test_confidence_all_claimed_low():
    assert _confidence_from_consensus(_consensus("Claimed", "Claimed", "Claimed")) == "low"


def test_confidence_mixed_medium():
    # 3개 중 강한 근거 1개(33%) → medium (>=0.3, <0.6)
    assert _confidence_from_consensus(_consensus("Verified", "Claimed", "Claimed")) == "medium"


def test_confidence_empty_low():
    assert _confidence_from_consensus({}) == "low"


def test_match_rate_from_gap_tool():
    tools = [
        {"tool": "vector_search", "result": [{"x": 1}]},
        {"tool": "gap_analysis", "result": {"match_rate": 0.42, "required_total": 10}},
    ]
    assert _match_rate_from_tools(tools) == 0.42


def test_match_rate_none_when_absent():
    assert _match_rate_from_tools([{"tool": "vector_search", "result": []}]) is None


def test_apply_overwrites_llm_lies_and_drops_fit_score():
    # LLM이 부풀린 값을 코드 계산값으로 덮어쓰고 fit_score는 제거
    report = {
        "match_rate": 0.99,          # LLM 거짓
        "fit_score": 0.95,           # 임의값
        "confidence_level": "high",  # LLM 거짓 (실제 전부 Claimed)
        "advice": "아무 말",
        "summary": "요약 유지",
    }
    consensus = _consensus("Claimed", "Claimed")            # 전부 주장 → low
    tools = [{"tool": "gap_analysis", "result": {"match_rate": 0.3}}]
    out = _apply_deterministic_metrics(report, consensus, tools)
    assert "fit_score" not in out
    assert out["confidence_level"] == "low"
    assert out["match_rate"] == 0.3
    assert "GitHub" in out["advice"]
    assert out["summary"] == "요약 유지"   # 산문은 보존


def test_apply_keeps_match_rate_when_no_tool():
    report = {"match_rate": 0.5, "fit_score": 0.1, "confidence_level": "high"}
    out = _apply_deterministic_metrics(report, _consensus("Verified", "Verified"), [])
    assert "fit_score" not in out
    assert out["confidence_level"] == "high"
    assert out["match_rate"] == 0.5   # 도구 결과 없으면 기존 값 유지
