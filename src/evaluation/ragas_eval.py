# RAGAS 0.4.x 기반 갭 분석 에이전트 품질 평가 — faithfulness / answer_relevancy
#
# 한 줄 요약: gap_agent가 만든 리포트가 "진짜 근거에 기반한 건지, 아니면 지어낸 건지"를
# RAGAS라는 외부 평가 라이브러리로 점수 매기는 파일. CLAUDE.md의 "Langfuse + RAGAS 평가"에서
# RAGAS(품질 채점) 쪽입니다. 사람이 눈으로 하나하나 확인하는 대신, 이 파일이 자동으로 점수를 냄.
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
# langfuse_tracer.py에서 본 그 dataclass — 가벼운 데이터 상자를 만드는 방법

from dotenv import load_dotenv
load_dotenv()
# .env 파일의 환경변수(OPENAI_API_KEY 등)를 미리 읽어둠 — 이 파일을 단독으로 실행할 때도
# (pipeline.py를 거치지 않아도) 키를 쓸 수 있게 여기서 직접 한 번 더 로드

from src.common.text_match import keywords_for as _keywords_for, word_match as _word_match


def _evidence_mentions_skill(skill: str, text: str) -> bool:
    """근거 텍스트가 해당 스킬(별칭 포함)을 실제로 언급하는지.

    faithfulness는 response의 주장이 retrieved_contexts에서 지지되는지 측정한다.
    그 스킬을 언급조차 않는 근거를 컨텍스트로 주면 측정이 무의미해지므로 걸러낸다.
    """
    # 쉽게 말하면: "이 공고 텍스트 안에 진짜로 그 스킬 이름이 있나?"만 확인하는 필터.
    # 없는데 근거라고 우기면, 이후 채점(faithfulness) 자체가 의미 없어지니까 미리 걸러냄.
    text_l = text.lower()
    return any(_word_match(kw, text_l) for kw in _keywords_for(skill))


@dataclass
class RagasScore:
    # 평가 대상 하나(직군 + 보유 스킬 조합)에 대한 점수를 담는 상자
    job_family: str
    portfolio_skills: list[str]
    faithfulness: float       # 0~1 사이 점수. 1에 가까울수록 "근거에 충실함"(환각 적음)
    answer_relevancy: float   # 0~1 사이 점수. 1에 가까울수록 "질문에 잘 답함"
    n_contexts: int       # 에이전트가 사용한 공고 텍스트 수

    def avg(self) -> float:
        return round((self.faithfulness + self.answer_relevancy) / 2, 3)
        # 두 점수의 평균 — "이 케이스의 종합 점수"를 간단히 보고 싶을 때


@dataclass
class EvalReport:
    # 여러 개의 RagasScore를 모아서 "전체 평가 결과"를 담는 더 큰 상자
    samples: list[RagasScore] = field(default_factory=list)
    error: str | None = None
    # error가 채워져 있으면 "평가 자체가 실패했다"는 뜻 (예: API 키 없음)

    def avg_faithfulness(self) -> float:
        if not self.samples:
            return 0.0
            # 샘플이 하나도 없으면 나눗셈(sum/len)에서 에러 나니까 미리 0.0으로 방어
        return round(sum(s.faithfulness for s in self.samples) / len(self.samples), 3)

    def avg_answer_relevancy(self) -> float:
        if not self.samples:
            return 0.0
        return round(sum(s.answer_relevancy for s in self.samples) / len(self.samples), 3)

    def summary(self) -> str:
        # 사람이 콘솔에서 바로 읽기 좋은 요약 문자열을 만들어주는 함수
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
    # 쉽게 말하면: 실제로 gap_agent 그래프를 한 번 돌려보고, 그 안에서 verify_skills 도구가
    # 가져온 "진짜 공고 근거"들을 모아서, RAGAS가 채점할 수 있는 형태로 포장하는 함수.
    from src.agent.supervisor import run_analysis
    from langchain_core.messages import ToolMessage

    final_report, messages = run_analysis(
        graph,
        job_title=job_family,
        owner=owner,
        portfolio_skills=portfolio_skills,
        return_state=True,
        # return_state=True → gap_result뿐 아니라 대화 기록(messages)까지 같이 받음.
        # 지난번 supervisor.py에서 "RAGAS eval이 이걸 쓸 것"이라고 예상했던 게 여기서 확인됨
    )
    if not final_report:
        return []

    # verify_skills 결과에서 스킬별 evidence 수집
    skill_evidence: dict[str, list[str]] = {}
    for msg in messages:
        if not isinstance(msg, ToolMessage) or getattr(msg, "name", None) != "verify_skills":
            continue
            # 대화 기록 중에서 "verify_skills 도구의 실행 결과"인 메시지만 골라냄
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
                    # 30자보다 짧은 근거는 너무 빈약해서 평가 재료로 부적합하다고 보고 제외
                    # 그 스킬을 실제 언급하는 근거만 — 무관한 공고 텍스트는 faithfulness를 왜곡
                    if not _evidence_mentions_skill(skill, ev["text"]):
                        continue
                    company = ev.get("company", "")
                    prefix = f"[{company}] " if company else ""
                    texts.append(f"{prefix}{ev['text'][:400]}")
            if texts:
                skill_evidence[skill] = texts

    # 샘플 조립 — evidence가 있는 스킬만.
    # response는 에이전트의 핵심 판정(이 스킬이 부족한 '필수' 스킬이다)을 영어 사실 진술로
    # 표현한다. faithfulness는 이 판정이 공고 근거(영어)에서 지지되는지 = 환각 여부를 측정한다.
    # 한국어 reason(일반 지식 서술)은 영어 근거와 언어·형식이 어긋나 측정을 왜곡하므로 쓰지 않는다.
    samples: list[dict] = []
    for skill, contexts in skill_evidence.items():
        samples.append({
            "user_input": f"Is {skill} required for the {job_family} role?",
            "retrieved_contexts": contexts[:5],
            "response": f"{skill} is a required skill for the {job_family} role.",
            # 여기서 흥미로운 점: response가 실제 gap_agent의 한국어 reason 문장이 아니라,
            # "이 스킬은 필수다"라는 단순한 영어 문장으로 다시 만들어짐. 왜 그런지는 위 주석에 설명돼 있음 —
            # RAGAS가 영어 근거와 한국어 문장을 비교하면 언어가 달라서 채점이 왜곡되기 때문
        })

    return samples


# ── RAGAS 평가 실행 ──────────────────────────────────────────────

def run_ragas_eval(
    test_cases: list[dict],
    graph,
) -> EvalReport:
    """에이전트 갭 분석 품질을 RAGAS로 측정.

    test_cases 형식:
        [{"job_family": "AI/LLM Engineer", "skills": ["Python", "LangChain"], "owner": "테스트"}]
    """
    # 이 함수가 실제로 "여러 테스트 케이스를 돌려서 RAGAS 점수를 매기는" 진짜 실행부
    if not os.getenv("OPENAI_API_KEY"):
        return EvalReport(error="OPENAI_API_KEY 미설정")
        # RAGAS 평가 자체도 내부적으로 LLM을 써서 채점하기 때문에 API 키가 필수

    try:
        from ragas import evaluate
        from ragas.dataset_schema import EvaluationDataset, SingleTurnSample
        from ragas.metrics import answer_relevancy, faithfulness
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings
        # RAGAS는 CLAUDE.md 확정 스택에 있는 외부 평가 전용 라이브러리.
        # faithfulness, answer_relevancy는 RAGAS가 미리 만들어둔 "채점 기준" 객체.

        raw_samples: list[dict] = []
        meta: list[dict] = []
        # raw_samples = RAGAS에 넘길 실제 평가 재료들
        # meta = 나중에 "이 점수가 어느 테스트 케이스 것이었는지" 되짚어보기 위한 부가 정보

        for tc in test_cases:
            job_family = tc["job_family"]
            skills = tc["skills"]
            owner = tc.get("owner", "평가용")

            print(f"  에이전트 실행: {job_family} (보유 스킬: {', '.join(skills)})")
            # 스킬별 evidence 품질 평가 방식 (옵션 A)
            # 각 부족 스킬에 대해 "Is X required?" → evidence → reason 구조로 평가
            skill_samples = _build_evidence_samples(job_family, skills, owner, graph)
            # 테스트 케이스 하나당 실제로 gap_agent 그래프를 한 번 실행함 — 즉 이 평가는
            # "가짜 데이터"가 아니라 진짜 에이전트를 돌려서 나온 결과로 채점하는 것
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
        # SingleTurnSample(**s) → 딕셔너리를 RAGAS가 원하는 전용 객체로 변환 (skill_extractor.py에서
        # 본 ResumeExtraction(**dict) 패턴과 같은 방식)
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
        # RAGAS가 채점할 때 쓸 LLM과 임베딩 모델 — "이 답변이 근거에 충실한지"를 사람 대신 LLM이 판단함

        result = evaluate(
            dataset=dataset,
            metrics=[faithfulness, answer_relevancy],
            llm=llm,
            embeddings=embeddings,
            show_progress=False,
            raise_exceptions=False,
            # raise_exceptions=False → 샘플 하나 채점 중 에러가 나도 전체가 멈추지 않고,
            # 그 샘플만 실패 처리하고 나머지는 계속 진행
        )

        df = result.to_pandas()
        # RAGAS 결과를 pandas 표(DataFrame) 형태로 변환 — 행 하나가 샘플 하나의 점수
        scores = []
        for i, row in df.iterrows():
            # iterrows() → 표를 (행 번호, 그 행의 내용) 쌍으로 하나씩 순회
            scores.append(RagasScore(
                job_family=meta[i]["job_family"],
                portfolio_skills=meta[i]["skills"],
                faithfulness=round(float(row.get("faithfulness") or 0), 3),
                answer_relevancy=round(float(row.get("answer_relevancy") or 0), 3),
                n_contexts=meta[i]["n_ctx"],
            ))
            # meta[i] → 아까 raw_samples에 넣을 때 같은 순서로 저장해둔 meta를 인덱스로 다시 짝지음

        return EvalReport(samples=scores)

    except Exception as e:
        return EvalReport(error=str(e))
        # RAGAS 라이브러리 자체 문제든 뭐든, 평가 전체가 실패하면 에러 메시지를 담아 반환
        # (프로그램이 죽지 않고, "평가가 실패했다"는 결과를 정상적으로 돌려줌)


# ── CLI 실행 ─────────────────────────────────────────────────────
if __name__ == "__main__":
    from src.storage.neo4j_client import Neo4jClient
    from src.agent.supervisor import create_supervisor_graph

    from openai import OpenAI
    neo4j = Neo4jClient()
    openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) if os.getenv("OPENAI_API_KEY") else None
    graph = create_supervisor_graph(neo4j, openai_client)

    test_cases = [
        {
            "job_family": "AI/LLM Engineer",
            "skills": ["Python", "LangChain", "Docker"],
            "owner": "평가_LLM1",
        },
        {
            "job_family": "AI/LLM Engineer",
            "skills": ["Python", "FastAPI", "PostgreSQL", "Docker"],
            "owner": "평가_LLM2",
        },
        {
            "job_family": "Data Engineer",
            "skills": ["Python", "SQL", "PostgreSQL", "Docker", "AWS"],
            "owner": "평가_DE",
        },
    ]
    # 이 파일을 직접 실행하면(python -m src.evaluation.ragas_eval), 미리 정해둔 3가지 케이스로
    # 실제 그래프를 돌려서 품질 점수를 콘솔에 출력함 — CLAUDE.md에 적힌
    # "Faithfulness=0.250, AnswerRelevancy=0.876" 같은 수치가 바로 이 실행 결과였을 것

    print("=== 갭 분석 에이전트 RAGAS 평가 (AI/LLM Engineer 중심) ===\n")
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
