# RAGAS 0.4.x 기반 갭 분석 에이전트 품질 평가 — faithfulness / answer_relevancy
#
# 평가 기준:
#   user_input        : "직군 X에 지원. 보유 스킬 Y. 갭 분석해줘."
#   retrieved_contexts: 에이전트가 실제로 사용한 공고 텍스트 (ToolMessage 수집)
#   response          : 에이전트가 생성한 최종 갭 분석 리포트
#
# Faithfulness     : 리포트의 각 주장이 공고 근거에 기반하는가? (환각 탐지)
# Answer Relevancy : 리포트가 "갭 분석" 질문에 실제로 답하는가?
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv
load_dotenv()


@dataclass
class RagasScore:
    job_family: str
    portfolio_skills: list[str]
    faithfulness: float
    answer_relevancy: float
    n_contexts: int       # 에이전트가 사용한 공고 텍스트 수

    def avg(self) -> float:
        return round((self.faithfulness + self.answer_relevancy) / 2, 3)


@dataclass
class EvalReport:
    samples: list[RagasScore] = field(default_factory=list)
    error: str | None = None

    def avg_faithfulness(self) -> float:
        if not self.samples:
            return 0.0
        return round(sum(s.faithfulness for s in self.samples) / len(self.samples), 3)

    def avg_answer_relevancy(self) -> float:
        if not self.samples:
            return 0.0
        return round(sum(s.answer_relevancy for s in self.samples) / len(self.samples), 3)

    def summary(self) -> str:
        return (
            f"샘플 수: {len(self.samples)}\n"
            f"Faithfulness:      {self.avg_faithfulness():.3f}\n"
            f"Answer Relevancy:  {self.avg_answer_relevancy():.3f}\n"
            f"평균:              {(self.avg_faithfulness() + self.avg_answer_relevancy()) / 2:.3f}"
        )


# ── verify_skills 근거 검색 품질 평가 (옵션 A) ───────────────────

def _build_evidence_samples(
    job_family: str,
    portfolio_skills: list[str],
    owner: str,
    graph,
) -> list[dict]:
    """verify_skills 툴 호출 결과를 RAGAS SingleTurnSample 목록으로 변환.

    평가 단위: 부족한 스킬 1개 = 샘플 1개
      user_input        : "Is {skill} required for {job_family}?"
      retrieved_contexts: verify_skills가 가져온 공고 원문 텍스트
      response          : 에이전트가 생성한 reason (스킬이 필요한 이유)

    이 방식은 RAG가 실제로 하는 일(근거 검색)을 직접 측정하므로
    갭 분석 전체를 평가하는 것보다 Faithfulness 지표에 맞다.
    """
    from src.agent.supervisor import run_analysis
    from langchain_core.messages import ToolMessage

    final_report, messages = run_analysis(
        graph,
        job_title=job_family,
        owner=owner,
        portfolio_skills=portfolio_skills,
        return_state=True,
    )
    if not final_report:
        return []

    # verify_skills 결과에서 스킬별 evidence 수집
    skill_evidence: dict[str, list[str]] = {}
    for msg in messages:
        if not isinstance(msg, ToolMessage) or getattr(msg, "name", None) != "verify_skills":
            continue
        try:
            content = json.loads(msg.content)
        except (json.JSONDecodeError, TypeError):
            continue
        for skill, skill_data in content.items():
            if not isinstance(skill_data, dict):
                continue
            texts = []
            for ev in skill_data.get("evidence", []):
                if isinstance(ev, dict) and "text" in ev and len(ev["text"]) > 30:
                    company = ev.get("company", "")
                    prefix = f"[{company}] " if company else ""
                    texts.append(f"{prefix}{ev['text'][:400]}")
            if texts:
                skill_evidence[skill] = texts

    # final_report의 missing_required에서 reason 수집 → response
    reason_by_skill: dict[str, str] = {}
    for item in final_report.get("missing_required", []):
        if isinstance(item, dict) and item.get("skill") and item.get("reason"):
            reason_by_skill[item["skill"]] = item["reason"]

    # 샘플 조립 — evidence가 있는 스킬만
    samples: list[dict] = []
    for skill, contexts in skill_evidence.items():
        response = reason_by_skill.get(skill, f"{skill} is required for the {job_family} role.")
        samples.append({
            "user_input": f"Is {skill} required for the {job_family} role?",
            "retrieved_contexts": contexts[:5],
            "response": response,
        })

    return samples


def _report_to_natural_text(report_json: str) -> str:
    """final_report JSON을 RAGAS claim 추출에 적합한 자연어 문장으로 변환.

    수치(match_rate 등)는 제외한다 — 컨텍스트에서 직접 지지되지 않아 faithfulness를
    왜곡한다. 대신 스킬별 이유(reason)와 요약(summary)만 포함한다.
    """
    try:
        report = json.loads(report_json)
    except (json.JSONDecodeError, TypeError):
        return report_json[:1500]

    lines: list[str] = []
    job_title = report.get("job_title", "")
    summary = report.get("summary", "")
    if summary:
        lines.append(f"{job_title} 직무 갭 분석: {summary}")

    have = report.get("have_required", [])
    if have:
        lines.append(f"보유 필수 기술: {', '.join(have)}")

    for item in report.get("missing_required", []):
        if isinstance(item, dict):
            skill = item.get("skill", "")
            reason = item.get("reason", "")
            priority = item.get("priority", "")
            if skill and reason:
                # "출처: X, Y" 형태를 "(required by X, Y)" 형태로 변환해 영문 컨텍스트와 매칭
                import re
                source_match = re.search(r"출처:\s*([^)]+)", reason)
                source_note = f" (required by {source_match.group(1).strip()})" if source_match else ""
                lines.append(f"The {skill} skill is required for this role and is missing from the portfolio.{source_note} {reason}")

    coaching = report.get("coaching", [])
    if coaching:
        lines.append("권장 학습 방향: " + " ".join(str(c) for c in coaching[:3]))

    return "\n".join(lines) if lines else report_json[:1000]


# ── RAGAS 평가 실행 ──────────────────────────────────────────────

def run_ragas_eval(
    test_cases: list[dict],
    graph,
) -> EvalReport:
    """에이전트 갭 분석 품질을 RAGAS로 측정.

    test_cases 형식:
        [{"job_family": "AI/LLM Engineer", "skills": ["Python", "LangChain"], "owner": "테스트"}]
    """
    if not os.getenv("OPENAI_API_KEY"):
        return EvalReport(error="OPENAI_API_KEY 미설정")

    try:
        from ragas import evaluate
        from ragas.dataset_schema import EvaluationDataset, SingleTurnSample
        from ragas.metrics import answer_relevancy, faithfulness
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings

        raw_samples: list[dict] = []
        meta: list[dict] = []

        for tc in test_cases:
            job_family = tc["job_family"]
            skills = tc["skills"]
            owner = tc.get("owner", "평가용")

            print(f"  에이전트 실행: {job_family} (보유 스킬: {', '.join(skills)})")
            # 스킬별 evidence 품질 평가 방식 (옵션 A)
            # 각 부족 스킬에 대해 "Is X required?" → evidence → reason 구조로 평가
            skill_samples = _build_evidence_samples(job_family, skills, owner, graph)
            if not skill_samples:
                print(f"  [skip] {job_family} — evidence 없음")
                continue

            print(f"    → 스킬 샘플 {len(skill_samples)}개")
            for s in skill_samples:
                raw_samples.append(s)
                meta.append({
                    "job_family": job_family,
                    "skills": skills,
                    "n_ctx": len(s["retrieved_contexts"]),
                })

        if not raw_samples:
            return EvalReport(error="유효한 샘플 없음")

        print(f"\nRAGAS 평가 실행 ({len(raw_samples)}개 샘플)...")
        dataset = EvaluationDataset(samples=[SingleTurnSample(**s) for s in raw_samples])
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

        result = evaluate(
            dataset=dataset,
            metrics=[faithfulness, answer_relevancy],
            llm=llm,
            embeddings=embeddings,
            show_progress=False,
            raise_exceptions=False,
        )

        df = result.to_pandas()
        scores = []
        for i, row in df.iterrows():
            scores.append(RagasScore(
                job_family=meta[i]["job_family"],
                portfolio_skills=meta[i]["skills"],
                faithfulness=round(float(row.get("faithfulness") or 0), 3),
                answer_relevancy=round(float(row.get("answer_relevancy") or 0), 3),
                n_contexts=meta[i]["n_ctx"],
            ))

        return EvalReport(samples=scores)

    except Exception as e:
        return EvalReport(error=str(e))


# ── CLI 실행 ─────────────────────────────────────────────────────
if __name__ == "__main__":
    from src.storage.chroma_client import ChromaClient
    from src.storage.neo4j_client import Neo4jClient
    from src.agent.supervisor import create_supervisor_graph

    from openai import OpenAI
    neo4j = Neo4jClient()
    chroma = ChromaClient()
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) if os.getenv("OPENAI_API_KEY") else None
    graph = create_supervisor_graph(neo4j, chroma, openai_client)

    # Software Engineer: 127개로 가장 많은 데이터 보유 → 신뢰도 높음
    test_cases = [
        {
            "job_family": "Software Engineer",
            "skills": ["Python", "Java", "SQL", "Git", "Docker"],
            "owner": "평가_SE",
        },
        {
            "job_family": "Software Engineer",
            "skills": ["Python", "React", "TypeScript", "AWS", "PostgreSQL", "Redis"],
            "owner": "평가_SE2",
        },
        {
            "job_family": "Data Engineer",
            "skills": ["Python", "SQL", "PostgreSQL", "Docker", "AWS"],
            "owner": "평가_DE",
        },
    ]

    print("=== 갭 분석 에이전트 RAGAS 평가 (Software Engineer 중심) ===\n")
    report = run_ragas_eval(test_cases, graph)

    if report.error:
        print(f"오류: {report.error}")
    else:
        print("\n=== 결과 ===")
        print(report.summary())
        print("\n[케이스별]")
        for s in report.samples:
            print(f"  {s.job_family} (보유: {', '.join(s.portfolio_skills[:3])}...)")
            print(f"    Faithfulness={s.faithfulness:.3f} | AnswerRelevancy={s.answer_relevancy:.3f} | 컨텍스트={s.n_contexts}개")

    neo4j.close()
