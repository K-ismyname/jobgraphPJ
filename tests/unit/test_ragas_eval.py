# RAGAS 평가 보조 로직 단위 테스트 — evidence 스킬 매칭, EvalReport 집계 (DB/LLM 불필요)
from src.evaluation.ragas_eval import EvalReport, RagasScore, _evidence_mentions_skill


def test_evidence_mentions_skill_alias():
    # PostgreSQL 별칭(postgres)이 텍스트에 있으면 True
    assert _evidence_mentions_skill("PostgreSQL", "Experience with Postgres and Redis required")
    # 단어 경계 — react가 reaction에 오탐되지 않음
    assert not _evidence_mentions_skill("React", "Fast reaction time is valued")
    assert _evidence_mentions_skill("React", "Built the UI with React and Redux")


def test_evidence_skips_unrelated_text():
    # PostgreSQL을 물었는데 Docker/Java만 언급 → 근거 아님
    text = "Bachelor's degree. Experience with Docker and Java Spring framework."
    assert not _evidence_mentions_skill("PostgreSQL", text)


def test_eval_report_aggregates():
    report = EvalReport(samples=[
        RagasScore("SE", ["Python"], faithfulness=0.8, answer_relevancy=0.6, n_contexts=2),
        RagasScore("SE", ["Java"], faithfulness=0.4, answer_relevancy=0.4, n_contexts=1),
    ])
    assert report.avg_faithfulness() == 0.6
    assert report.avg_answer_relevancy() == 0.5


def test_eval_report_empty_safe():
    report = EvalReport(samples=[])
    assert report.avg_faithfulness() == 0.0
    assert report.avg_answer_relevancy() == 0.0
