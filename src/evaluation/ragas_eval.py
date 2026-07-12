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
import re
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
    kind: str = "reason(A)"  # "reason(A)"=gap_agent 자유생성, "proficiency(B)"=그래프에 없는 텍스트 정보

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
    """gap_agent가 생성한 부족 스킬 reason을 RAGAS SingleTurnSample 목록으로 변환.

    평가 단위: 부족한 스킬 1개 = 샘플 1개
      user_input        : "이 직군에서 {skill}이 부족한 이유는 무엇인가?"
      retrieved_contexts: verify_skills가 가져온 공고 원문 텍스트
      response          : gap_result["missing_required"][].reason — LLM이 실제로 생성한 설명

    "Is {skill} required?" 방식은 Neo4j REQUIRES 관계로 이미 알 수 있는 사실이라
    (스킬을 애초에 verify_skills 대상으로 고른 것 자체가 이미 필수라는 뜻) RAG 평가로서
    의미가 약했다. reason은 "왜 필요한가"를 원문 근거로 설명하는, 그래프에는 없고
    문서를 읽어야만 답할 수 있는 자유 생성 텍스트라 Faithfulness가 실제로 뭔가를 검증한다.
    """
    from src.agent.supervisor import run_analysis
    from langchain_core.messages import ToolMessage
    from src.extraction.normalizer import normalize_skill

    final_report, messages = run_analysis(
        graph,
        job_title=job_family,
        owner=owner,
        portfolio_skills=portfolio_skills,
        return_state=True,
    )
    if not final_report:
        return []

    # verify_skills 결과에서 스킬별 evidence 수집 (근거 검색 자체는 기존과 동일)
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
                    # 30자보다 짧은 근거는 "왜 필요한가"를 설명할 문맥이 없어 평가 재료로 부적합
                    # 그 스킬을 실제 언급하는 근거만 — 무관한 공고 텍스트는 faithfulness를 왜곡
                    if not _evidence_mentions_skill(skill, ev["text"]):
                        continue
                    company = ev.get("company", "")
                    prefix = f"[{company}] " if company else ""
                    texts.append(f"{prefix}{ev['text'][:400]}")
            if texts:
                skill_evidence[normalize_skill(skill)] = texts
                # normalize_skill로 키를 정규화 — missing_required[].skill과 표기가
                # 다를 수 있어서(예: "langgraph" vs "LangGraph") 정규화된 이름으로 매칭

    # gap_result의 missing_required[].reason — LLM이 실제로 쓴 문장을 그대로 채점 대상으로 삼음
    # (더 이상 "X is required" 같은 대리 문장을 코드로 지어내지 않음)
    samples: list[dict] = []
    for item in final_report.get("missing_required") or []:
        if not isinstance(item, dict):
            continue
        skill = item.get("skill")
        reason = item.get("reason")
        if not skill or not reason:
            continue
        contexts = skill_evidence.get(normalize_skill(skill))
        if not contexts:
            # 근거를 못 찾은 스킬은 reason이 있어도 대조할 retrieved_contexts가 없어 평가 불가
            continue
        samples.append({
            "user_input": f"이 직군에서 {skill}이 부족한 이유는 무엇인가?",
            "retrieved_contexts": contexts[:5],
            "response": reason,
        })

    return samples


# ── 스킬-숙련도/연차 표현 평가 (옵션 B — 그래프에 없는 순수 텍스트 정보) ──
#
# 옵션 A(_build_evidence_samples)는 gap_agent의 reason을 채점 대상으로 쓰는데,
# "이 스킬이 왜 필요한가"는 결국 REQUIRES 관계로 어느 정도 유추 가능한 정보다.
# 아래는 Neo4j 그래프에 전혀 없는 정보(스킬별 요구 숙련도·연차)를 원문에서 직접
# 찾아 RAG(검색→생성)로 답하게 하고 채점한다 — 그래프로 대체 불가능해야 Faithfulness가
# 실제로 뭔가를 검증하는 지표가 된다는 게 이번 재설계의 핵심.

_PROFICIENCY_PATTERN = re.compile(
    r"\d+\+?\s*years?[^.]{0,80}"
    r"|proficient[^.]{0,80}|expert[^.]{0,80}|hands-on[^.]{0,80}"
    r"|strong (?:knowledge|experience|understanding)[^.]{0,80}"
    r"|familiar(?:ity)?[^.]{0,80}",
    re.IGNORECASE,
)


def _find_skill_proficiency_excerpts(neo4j, job_family: str, max_samples: int = 5) -> list[dict]:
    """직군 공고 원문에서, 스킬 이름 근처(80자 이내)에 숙련도/연차 표현이 붙은 발췌를 찾는다.

    "Docker가 필요하다"는 REQUIRES로 이미 알 수 있지만, "몇 년/얼마나 능숙해야 하는가"는
    원문 문장을 실제로 읽어야만 알 수 있다 — 이 함수가 그런 문장만 골라낸다.
    """
    query = """
    MATCH (jp:JobPosting)-[:INSTANCE_OF]->(:JobFamily {name: $job_family})
    MATCH (jp)-[:REQUIRES]->(sk:Skill)
    WHERE jp.required_section IS NOT NULL AND jp.required_section <> ''
    RETURN DISTINCT jp.company AS company, jp.required_section AS text, collect(DISTINCT sk.name) AS skills
    """
    rows = neo4j.execute_query(query, job_family=job_family)

    found: list[dict] = []
    for row in rows:
        text = row["text"]
        for skill in row["skills"]:
            match = None
            for kw in _keywords_for(skill):
                match = re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", text, re.IGNORECASE)
                if match:
                    break
            if not match:
                continue
            window = text[max(0, match.start() - 80): min(len(text), match.end() + 80)]
            if _PROFICIENCY_PATTERN.search(window):
                found.append({
                    "company": row["company"],
                    "skill": skill,
                    "excerpt": " ".join(window.split()),
                    # " ".join(text.split()) → 개행·연속공백을 단일 공백으로 정리 (기존 파일의 관용구와 동일)
                })
        if len(found) >= max_samples:
            break
    return found[:max_samples]


def _answer_from_excerpt(skill: str, excerpt: str, openai_client) -> str:
    """발췌 원문만 근거로, 그 스킬의 요구 숙련도/연차를 한 문장으로 답하게 한다.

    프롬프트가 "원문에 없으면 추측 금지"를 명시 — 이 답변 자체가 RAGAS 채점 대상이므로,
    지어내면 Faithfulness가 낮게 나오는 게 맞는 결과다(그래야 지표가 진짜로 검증하는 셈).
    """
    prompt = (
        f"다음은 채용공고 요건 원문의 일부입니다. 이 내용만 근거로 '{skill}'에 대해 "
        f"요구하는 숙련도나 경력 수준을 한국어 한 문장으로 답하세요. "
        f"원문에 없는 내용은 추측하지 마세요.\n\n원문: \"{excerpt}\""
    )
    resp = openai_client.chat.completions.create(
        model="gpt-4o-mini", temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content.strip()


def _build_skill_proficiency_samples(
    neo4j, openai_client, job_families: list[str], per_family: int = 5,
) -> list[dict]:
    """직군별로 스킬-숙련도 발췌를 찾아, 원문만 근거로 답변을 생성하고 RAGAS 샘플로 포장."""
    samples: list[dict] = []
    for jf in job_families:
        for e in _find_skill_proficiency_excerpts(neo4j, jf, max_samples=per_family):
            answer = _answer_from_excerpt(e["skill"], e["excerpt"], openai_client)
            samples.append({
                "user_input": f"이 공고는 {e['skill']}에 대해 어느 정도의 숙련도/경력을 요구하는가?",
                "retrieved_contexts": [e["excerpt"]],
                "response": answer,
            })
    return samples


# ── RAGAS 평가 실행 ──────────────────────────────────────────────

def run_ragas_eval(
    test_cases: list[dict],
    graph,
    neo4j=None,
    openai_client=None,
) -> EvalReport:
    """에이전트 갭 분석 품질을 RAGAS로 측정.

    test_cases 형식:
        [{"job_family": "AI/LLM Engineer", "skills": ["Python", "LangChain"], "owner": "테스트"}]

    neo4j/openai_client를 주면, gap_agent reason(옵션 A)과 별도로 그래프에 없는
    "스킬-숙련도/연차 표현" 샘플(옵션 B, _build_skill_proficiency_samples)도 함께 평가한다.
    옵션 B가 Faithfulness/Answer Relevancy 모두 훨씬 높게 나온다(실측: 0.70대 vs 0.35~0.44) —
    그래프로 대체 불가능한 질문 + 자연어 답변 조합이라야 RAGAS가 의미 있게 작동하기 때문.
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
            for s in skill_samples:
                raw_samples.append(s)
                meta.append({
                    "job_family": job_family,
                    "skills": skills,
                    "n_ctx": len(s["retrieved_contexts"]),
                    "kind": "reason(A)",
                })
            print(f"    → reason 샘플 {len(skill_samples)}개")

        if neo4j is not None and openai_client is not None:
            job_families = sorted({tc["job_family"] for tc in test_cases})
            print(f"\n  스킬-숙련도 발췌 수집 (옵션 B): {job_families}")
            prof_samples = _build_skill_proficiency_samples(neo4j, openai_client, job_families)
            print(f"    → 숙련도 샘플 {len(prof_samples)}개")
            for s in prof_samples:
                raw_samples.append(s)
                meta.append({"job_family": "?", "skills": [], "n_ctx": len(s["retrieved_contexts"]),
                            "kind": "proficiency(B)"})

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
                kind=meta[i]["kind"],
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

    print("=== 갭 분석 에이전트 RAGAS 평가 (옵션 A: reason / 옵션 B: 스킬-숙련도) ===\n")
    report = run_ragas_eval(test_cases, graph, neo4j=neo4j, openai_client=openai_client)

    if report.error:
        print(f"오류: {report.error}")
    else:
        print("\n=== 전체 결과 ===")
        print(report.summary())
        print("\n[케이스별]")
        for s in report.samples:
            label = f"{s.job_family} (보유: {', '.join(s.portfolio_skills[:3])}...)" if s.kind == "reason(A)" else "(스킬-숙련도)"
            print(f"  [{s.kind}] {label}")
            print(f"    Faithfulness={s.faithfulness:.3f} | AnswerRelevancy={s.answer_relevancy:.3f} | 컨텍스트={s.n_contexts}개")

        # 옵션 A(reason) vs 옵션 B(숙련도) 비교 — 그래프로 대체 가능한 질문(A)과 불가능한 질문(B)의
        # Faithfulness/Answer Relevancy 차이를 보여주는 게 이 재설계의 핵심 근거
        for kind in ("reason(A)", "proficiency(B)"):
            group = [s for s in report.samples if s.kind == kind]
            if group:
                avg_f = round(sum(s.faithfulness for s in group) / len(group), 3)
                avg_r = round(sum(s.answer_relevancy for s in group) / len(group), 3)
                print(f"\n[{kind}] 샘플 {len(group)}개 — Faithfulness={avg_f} | AnswerRelevancy={avg_r}")

    neo4j.close()
