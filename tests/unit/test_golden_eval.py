# 골든셋 기반 end-task 정확도 — 정답 도출·채점 로직 (LLM 없이 검증 가능한 순수 부분)
import pytest

from src.evaluation.golden_eval import CaseScore, expected_missing, load_golden, run_golden_eval

_GOLDEN = {
    "AI/LLM Engineer": {"core": ["Python", "LLM", "PyTorch", "RAG"], "excluded": {}},
}


def test_expected_missing_is_core_minus_held():
    out = expected_missing("AI/LLM Engineer", ["Python", "Docker"], _GOLDEN)
    assert out == {"LLM", "PyTorch", "RAG"}   # Docker는 core에 없으므로 무관


def test_expected_missing_normalizes_aliases():
    # 이력서에 "파이토치"/"torch" 같은 표기로 있어도 보유로 인정돼야 한다
    out = expected_missing("AI/LLM Engineer", ["python", "torch"], _GOLDEN)
    assert "PyTorch" not in out
    assert "Python" not in out


def test_expected_missing_unknown_family_raises():
    with pytest.raises(KeyError):
        expected_missing("Astronaut", [], _GOLDEN)


# ── 채점 로직 ────────────────────────────────────────────────────
def _case(expected, predicted):
    return CaseScore("c1", "AI/LLM Engineer", [], set(expected), set(predicted))


def test_perfect_prediction():
    c = _case({"LLM", "RAG"}, {"LLM", "RAG"})
    assert c.precision == 1.0 and c.recall == 1.0 and c.f1 == 1.0
    assert not c.false_alarm and not c.missed


def test_false_alarm_lowers_precision():
    # 필요 없는 Java를 부족하다고 지목 → 사용자가 헛공부하게 된다
    c = _case({"LLM"}, {"LLM", "Java"})
    assert c.precision == 0.5
    assert c.recall == 1.0
    assert c.false_alarm == {"Java"}


def test_miss_lowers_recall():
    # 정작 필요한 RAG를 놓침
    c = _case({"LLM", "RAG"}, {"LLM"})
    assert c.precision == 1.0
    assert c.recall == 0.5
    assert c.missed == {"RAG"}


def test_empty_prediction_misses_everything():
    # 아무것도 지목 안 했으면 오탐은 없지만(precision=1) 전부 놓친 것(recall=0)
    c = _case({"LLM"}, set())
    assert c.precision == 1.0
    assert c.recall == 0.0
    assert c.f1 == 0.0


def test_perfect_candidate_recall_is_undefined():
    """핵심 스킬을 전부 보유해 부족한 게 없는 지원자 — recall은 정의되지 않는다.

    0.0으로 세면 "다 갖춘 사람"이 평균 recall을 끌어내려 지표가 왜곡된다.
    놓칠 것이 애초에 없었으므로 누락률을 논할 수 없다.
    """
    c = _case(set(), {"Java"})   # 정답 없음인데 Java를 부족하다고 지목
    assert c.recall is None      # 평균에서 제외됨
    assert c.f1 is None
    assert c.precision == 0.0    # 오탐 1개 → precision은 0
    assert c.false_alarm == {"Java"}


def test_perfect_candidate_with_no_prediction_is_correct():
    # 부족한 게 없는데 아무것도 안 짚었다 — 이게 정답이다
    c = _case(set(), set())
    assert c.precision == 1.0
    assert c.recall is None
    assert not c.false_alarm


# ── 실제 골든셋 파일 ─────────────────────────────────────────────
def test_shipped_golden_file_is_valid():
    golden = load_golden()
    assert golden, "골든셋이 비어 있다"
    for family, entry in golden.items():
        assert entry.get("core"), f"{family}: core가 비어 있음"
        # core와 excluded가 겹치면 라벨이 모순이다
        overlap = set(entry["core"]) & set(entry.get("excluded", {}))
        assert not overlap, f"{family}: core와 excluded가 겹침 — {overlap}"


def test_run_golden_eval_fails_fast_when_neo4j_unavailable(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    class NoDataNeo4j:
        def list_job_families(self):
            return []

    report = run_golden_eval([], graph=object(), neo4j=NoDataNeo4j())
    assert report.error == "Neo4j 직군 데이터 없음 또는 연결 실패"


def test_run_golden_eval_fails_fast_when_family_missing(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    class Neo4j:
        def list_job_families(self):
            return ["Software Engineer"]

    report = run_golden_eval(
        [{"case_id": "c", "job_family": "AI/LLM Engineer", "resume_skills": []}],
        graph=object(),
        neo4j=Neo4j(),
    )
    assert report.error == "Neo4j에 없는 직군: AI/LLM Engineer"
