# RAGAS 기반 갭 분석 품질 평가 — faithfulness / answer_relevancy / context_recall
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.analysis.gap_analyzer import GapAnalysisResult
    from src.storage.chroma_client import ChromaClient


# ── 결과 모델 ────────────────────────────────────────────────────
@dataclass
class MetricScore:
    name: str
    score: float    # 0.0 ~ 1.0
    description: str = ""


@dataclass
class ExperimentResult:
    experiment_name: str
    job_title: str
    owner: str
    metrics: list[MetricScore] = field(default_factory=list)
    error: str | None = None

    def avg_score(self) -> float:
        if not self.metrics:
            return 0.0
        return sum(m.score for m in self.metrics) / len(self.metrics)


@dataclass
class ComparisonReport:
    strategy_a: ExperimentResult
    strategy_b: ExperimentResult

    def winner(self) -> str:
        if self.strategy_a.avg_score() >= self.strategy_b.avg_score():
            return self.strategy_a.experiment_name
        return self.strategy_b.experiment_name


# ── RAGAS 데이터셋 변환 ──────────────────────────────────────────
def gap_result_to_ragas_sample(
    gap_result: "GapAnalysisResult",
    chroma: "ChromaClient",
) -> dict:
    """GapAnalysisResult → RAGAS SingleTurnSample 생성용 dict.

    - user_input : 분석 질문
    - response   : LLM이 생성한 갭 분석 요약 (있는 기술 + 없는 기술)
    - retrieved_contexts : Chroma에서 가져온 근거 문장 목록
    - reference  : 정답 — 공고에서 요구하는 기술명 목록 (쉼표 구분)
    """
    # 질문
    user_input = (
        f"What skills does {gap_result.owner} have for the {gap_result.job_title} role, "
        f"and what is missing?"
    )

    # 응답 — 갭 분석 결과 텍스트 요약
    have_names    = [s.skill for s in gap_result.have]
    missing_names = [s.skill for s in gap_result.missing]
    response = (
        f"{gap_result.owner} has: {', '.join(have_names) or 'none'}. "
        f"Missing for {gap_result.job_title}: {', '.join(missing_names) or 'none'}. "
        f"Match rate: {gap_result.match_rate:.0%}."
    )

    # 컨텍스트 — 보유 기술의 Chroma 근거 문장
    contexts: list[str] = []
    for skill in gap_result.have[:5]:  # 상위 5개만 (비용 절감)
        evidence = skill.evidence or ""
        if not evidence:
            try:
                hits = chroma.search_evidence(skill.skill, n=1)
                evidence = hits[0] if hits else ""
            except Exception:
                pass
        if evidence:
            contexts.append(evidence)

    if not contexts:
        contexts = [f"No evidence found in portfolio for {gap_result.job_title}."]

    # 정답 — 전체 기술 목록 (보유 + 부족)
    all_skills = have_names + missing_names
    reference = ", ".join(all_skills) if all_skills else "No skills data available."

    return {
        "user_input": user_input,
        "response": response,
        "retrieved_contexts": contexts,
        "reference": reference,
    }


# ── 단일 실험 평가 ────────────────────────────────────────────────
def evaluate_strategy(
    experiment_name: str,
    gap_result: "GapAnalysisResult",
    chroma: "ChromaClient",
    llm=None,
    embeddings=None,
) -> ExperimentResult:
    """단일 GapAnalysisResult에 대해 RAGAS 지표를 측정한다.

    ANTHROPIC_API_KEY 없으면 점수를 산출할 수 없어 스킵한다.
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("[skip] ANTHROPIC_API_KEY 없음 — RAGAS 평가 건너뜀")
        return ExperimentResult(
            experiment_name=experiment_name,
            job_title=gap_result.job_title,
            owner=gap_result.owner,
            error="ANTHROPIC_API_KEY 미설정",
        )

    try:
        from ragas import EvaluationDataset, SingleTurnSample, evaluate
        from ragas.metrics.collections import (
            answer_relevancy,
            context_recall,
            faithfulness,
        )

        sample_dict = gap_result_to_ragas_sample(gap_result, chroma)
        sample = SingleTurnSample(**sample_dict)
        dataset = EvaluationDataset(samples=[sample])

        metrics = [faithfulness, answer_relevancy, context_recall]
        eval_result = evaluate(
            dataset=dataset,
            metrics=metrics,
            llm=llm,
            embeddings=embeddings,
            show_progress=False,
            raise_exceptions=False,
        )

        scores = []
        result_dict = eval_result.to_pandas().iloc[0].to_dict()
        metric_meta = {
            "faithfulness":      "LLM 응답이 컨텍스트에 근거하는 비율",
            "answer_relevancy":  "응답이 질문에 관련된 정도",
            "context_recall":    "정답 내용이 컨텍스트에 포함된 비율",
        }
        for metric_name, description in metric_meta.items():
            raw = result_dict.get(metric_name)
            score = float(raw) if raw is not None and str(raw) != "nan" else 0.0
            scores.append(MetricScore(
                name=metric_name,
                score=round(score, 4),
                description=description,
            ))

        return ExperimentResult(
            experiment_name=experiment_name,
            job_title=gap_result.job_title,
            owner=gap_result.owner,
            metrics=scores,
        )

    except Exception as e:
        return ExperimentResult(
            experiment_name=experiment_name,
            job_title=gap_result.job_title,
            owner=gap_result.owner,
            error=str(e),
        )


# ── 두 전략 비교 ─────────────────────────────────────────────────
def run_comparison(
    result_a: "GapAnalysisResult",
    result_b: "GapAnalysisResult",
    chroma: "ChromaClient",
    name_a: str = "전략 A",
    name_b: str = "전략 B",
) -> ComparisonReport:
    """두 GapAnalysisResult를 같은 RAGAS 지표로 비교한다.
    예: Claude Haiku 기반 추출 vs 파인튜닝 모델 기반 추출.
    """
    exp_a = evaluate_strategy(name_a, result_a, chroma)
    exp_b = evaluate_strategy(name_b, result_b, chroma)
    return ComparisonReport(strategy_a=exp_a, strategy_b=exp_b)


# ── 결과 포맷팅 ──────────────────────────────────────────────────
def to_markdown_table(results: list[ExperimentResult]) -> str:
    """ExperimentResult 목록을 마크다운 테이블로 변환한다 (README·모델카드용)."""
    if not results:
        return "(결과 없음)"

    metric_names = [m.name for m in results[0].metrics] if results[0].metrics else []

    header = "| 실험 | " + " | ".join(metric_names) + " | 평균 |"
    sep    = "|" + "|".join(["---"] * (len(metric_names) + 2)) + "|"

    rows = [header, sep]
    for r in results:
        if r.error:
            row = f"| {r.experiment_name} | " + " | ".join(["N/A"] * len(metric_names)) + f" | Error: {r.error} |"
        else:
            score_cells = " | ".join(f"{m.score:.3f}" for m in r.metrics)
            row = f"| {r.experiment_name} | {score_cells} | {r.avg_score():.3f} |"
        rows.append(row)

    return "\n".join(rows)
