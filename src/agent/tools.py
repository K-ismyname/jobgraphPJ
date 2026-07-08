# 에이전트가 사용하는 툴 정의 — Neo4j 클라이언트를 클로저로 캡처
#
# 이 파일이 하는 일: gap_agent(create_tools)와 coach_agent(create_coach_tools)가
# LLM에게 쥐어줄 실제 "도구"들을 정의한다. 각 도구는 @tool로 감싸진 평범한 파이썬 함수이고,
# 내부적으로 지난번 본 neo4j_client.py의 조회 메서드들을 호출해 실제 그래프 데이터를 가져온다.
# LLM은 이 함수들의 이름과 Annotated 설명만 보고 "언제 어떤 인자로 부를지" 스스로 판단한다.

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Annotated

from langchain_core.tools import tool
# @tool 데코레이터 — 평범한 함수를 LLM이 호출 가능한 "도구"로 변환하는 LangChain 기능

from src.common.text_match import keywords_for as _keywords_for, word_match as _word_match
from src.extraction.normalizer import normalize_skill

if TYPE_CHECKING:
    from src.storage.neo4j_client import Neo4jClient

# 적합도는 '핵심 필수' 스킬만 기준으로 — 직군에서 가장 자주 요구되는(빈도 상위) REQUIRES N개.
# 공고마다 나열되는 주변 스킬(빈도 1~2)까지 분모에 넣으면 다 보유해야 적합해지는 비현실적 결과가 나온다.
_CORE_REQUIRED_N = 10
# 이 상수가 왜 중요한가: 만약 "이 직군이 요구하는 모든 스킬"(수십 개, 빈도 1인 것까지 포함)을
# 분모로 매칭률을 계산하면, 실제로 웬만한 지원자는 항상 매칭률이 낮게 나옴 — 모든 공고가
# 조금씩 다른 부차적 기술을 나열하기 때문. 그래서 "정말 많은 공고가 공통으로 요구하는 핵심
# 스킬 10개"만 분모로 삼아야 현실적인 적합도가 나온다는 판단

# ── Cypher 쿼리 ──────────────────────────────────────────────────
_JOB_SKILLS_QUERY = """
MATCH (:JobFamily {name: $job_family})<-[:INSTANCE_OF]-(jp)-[r:REQUIRES|PREFERS]->(s:Skill)
RETURN s.name AS skill, type(r) AS importance, count(jp) AS weight
ORDER BY weight DESC
LIMIT 30
"""
# type(r) → Cypher 함수, 관계 r의 타입 이름을 문자열로 반환 (REQUIRES 또는 PREFERS 중 어느 쪽인지)
# 이 쿼리 하나로 "이 직군의 상위 30개 스킬이, 각각 필수인지 우대인지, 몇 개 공고에서 요구되는지"를 한 번에 얻음


def _evidence_snippet(skill: str, text: str, max_sentences: int = 2, cap: int = 450) -> str:
    """텍스트에서 스킬 키워드가 든 문장을 최대 max_sentences개 모아 근거로.

    단편 1문장은 "그 스킬이 required인지" 문맥이 빈약해 RAGAS faithfulness를
    떨어뜨린다. 키워드 문장을 여러 개 묶어 근거의 충실도를 높인다.
    키워드 문장이 없으면 앞부분을 cap 길이만큼 반환한다.
    """
    kws = _keywords_for(skill)
    matched: list[str] = []
    for sent in re.split(r"[.\n•]", text or ""):
        # 마침표·개행·불릿 기호 중 아무거나 기준으로 문장을 나눔 — nodes.py의 좀 더 정교한 문장 분리(lookbehind)와
        # 달리 여기는 단순한 분리(구분자 자체가 사라짐, 마침표가 문장 끝에 안 남음)
        s = sent.strip()
        if s and any(_word_match(kw, s.lower()) for kw in kws):
            matched.append(s)
            if len(matched) >= max_sentences:
                break
                # 최대 2문장까지만 모으고 멈춤 — nodes.py의 docstring에서 설명한 "RAGAS faithfulness"
                # (생성된 답변이 근거 문서에 얼마나 충실한지 재는 평가 지표)를 높이려는 목적
    if matched:
        return ". ".join(matched)[:cap]
    return (text or "").strip()[:cap]


def create_tools(neo4j: "Neo4jClient") -> list:
    """Gap 에이전트용 툴 목록 생성."""
    # 이 함수가 gap_agent.py의 create_gap_graph()에 넘겨지는 gap_tools 리스트를 실제로 만드는 곳.
    # 안쪽에서 정의된 함수들이 neo4j를 클로저로 붙잡아서, LLM이 도구를 호출할 때마다
    # Neo4jClient 인스턴스를 새로 안 만들고 이미 연결된 걸 재사용함

    @tool
    def gap_analysis(
        job_family: Annotated[str, "분석할 직군명. 반드시 아래 중 하나: Software Engineer / Data Engineer / Data Analyst / Data Scientist / AI/LLM Engineer / ML Engineer / DevOps/SRE / Security Engineer / Frontend Engineer"],
        portfolio_skills: Annotated[list[str], "보유 기술 목록 (이력서에서 추출된 스킬명)"],
        owner: Annotated[str, "지원자 이름 — Neo4j에서 최신 confidence를 조회하는 데 사용"],
    ) -> dict:
        """직군 요구 스킬과 보유 스킬을 비교해 갭과 매칭률을 계산한다.

        confidence 분류:
          high / medium → have_required  (증명된 보유 스킬)
          low           → unverified_required  (보유하나 근거 약함)
          없음          → missing_required
        """
        # 이 도구가 gap_agent 프롬프트의 "1. gap_analysis 먼저 호출"에 해당하는 실제 구현.
        # docstring 전체가 LLM에게 그대로 노출되는 "도구 설명"이라서, 함수 설명을 곧 프롬프트처럼 신중하게 씀
        try:
            rows = neo4j.execute_query(_JOB_SKILLS_QUERY, job_family=job_family)
            if not rows:
                return {"error": f"'{job_family}' 직군 데이터 없음. 유효한 직군명인지 확인하세요."}
                # 에러도 그냥 문자열이 아니라 "무엇이 잘못됐는지" LLM이 읽고 다음 행동을 판단할 수 있게 안내문 형태로 반환

            # rows는 weight(요구 공고 수) 내림차순 → REQUIRES 상위 N개만 '핵심 필수'로
            required = [r for r in rows if r["importance"] == "REQUIRES"][:_CORE_REQUIRED_N]
            preferred = [r for r in rows if r["importance"] == "PREFERS"]
            portfolio_lower = {s.lower() for s in portfolio_skills}

            # Neo4j에서 최신 confidence 조회 (GitHub 업데이트 반영)
            demonstrated = {
                s.name.lower(): s.confidence
                for s in neo4j.get_portfolio_demonstrated_skills(owner)
            }
            # neo4j_client.py에서 본 그 메서드 — DemonstratedSkill 객체 리스트를 {스킬명: confidence} dict로 변환
            # "GitHub 업데이트 반영"이라는 주석 — github_connector.py의 boost_confidence_from_github()가
            # (죽은 코드지만) 원래 이 confidence를 갱신하려던 의도였을 가능성을 시사

            have_req: list = []
            unverified_req: list = []
            for r in required:
                skill_lower = r["skill"].lower()
                if skill_lower in portfolio_lower:
                    conf = demonstrated.get(skill_lower, "medium")
                    # portfolio_skills(이력서에서 뽑힌 스킬)에는 있지만 confidence 정보가 없으면
                    # 기본값 "medium"으로 가정 — "이력서에 있다는 것 자체는 최소한의 신호"로 보는 판단
                    if conf == "low":
                        unverified_req.append(r)
                    else:
                        have_req.append(r)

            missing_req = [r for r in required if r["skill"].lower() not in portfolio_lower]
            have_pref = [r for r in preferred if r["skill"].lower() in portfolio_lower]
            missing_pref = [r for r in preferred if r["skill"].lower() not in portfolio_lower]

            # match_rate: have_required / 전체 required (unverified는 제외)
            match_rate = len(have_req) / len(required) if required else 0.0
            # unverified_req(근거 약한 보유)는 분자에도 안 들어감 — "확실히 보유"라고 인정된 것만 매칭률에 반영
            # (required가 0이면 나눗셈 에러 방지를 위해 0.0으로 방어)

            return {
                "job_family": job_family,
                "match_rate": round(match_rate, 2),
                "required_total": len(required),
                "have_required": [r["skill"] for r in have_req],
                "unverified_required": [
                    {"skill": r["skill"], "weight": r.get("weight") or 1}
                    for r in unverified_req
                ],
                "missing_required": [
                    {"skill": r["skill"], "weight": r.get("weight") or 1}
                    for r in missing_req
                ],
                # missing_required에 weight(요구 공고 수)를 같이 실어 보냄 — 이게 나중에 nodes.py의
                # build_deterministic_reasons()에서 "이 직군 공고 N건이 필수로 요구합니다"라는
                # reason 문장을 만드는 원재료가 됨
                "have_preferred": [r["skill"] for r in have_pref],
                "missing_preferred": [normalize_skill(r["skill"]) for r in missing_pref],
            }
        except Exception as e:
            return {"error": str(e)}
            # 이 도구는 예외를 다시 던지지(raise) 않고 {"error": ...} dict로 반환 — LLM이 이 결과를
            # 받아서 "도구가 실패했다"는 걸 읽고 다음 판단(재시도, 다른 도구, 혹은 그냥 진행)을 스스로 내릴 수 있게 함

    @tool
    def verify_skills(
        skill_names: Annotated[list[str], "근거를 확인할 부족 스킬 목록 (최대 5개)"],
    ) -> dict:
        """여러 부족 스킬의 공고 근거를 한 번에 조회한다(Neo4j 요건 원문 기반)."""
        # gap_agent 프롬프트의 "2. verify_skills — weight 상위 5개를 한 번에" 단계에 대응
        results: dict = {}
        try:
            for skill in skill_names[:5]:
                # 함수 인자로 5개 넘게 들어와도 코드에서 다시 한번 [:5]로 강제 제한 —
                # 프롬프트 지시("최대 5개")만 믿지 않고 코드로도 방어하는 이 프로젝트의 반복 패턴
                posting_ids = neo4j.get_postings_requiring_skill(skill, limit=5)
                evidence = []
                if posting_ids:
                    for s in neo4j.get_posting_sections(posting_ids):
                        text = f"{s.get('required_section') or ''} {s.get('preferred_section') or ''}"
                        sent = _evidence_snippet(skill, text)
                        if sent:
                            evidence.append({"source_id": s["source_id"], "company": s.get("company") or "", "text": sent})
                            # source_id를 evidence마다 남겨두는 이유 — nodes.py의 make_tools_node()가
                            # 이 source_id로 "이미 인용한 공고인지" 중복을 걸러내기 때문 (seen_source_ids)
                if evidence:
                    results[skill] = {"method": "neo4j_text", "posting_count": len(posting_ids), "evidence": evidence}
                else:
                    results[skill] = {"method": "graph_only", "posting_count": len(posting_ids), "evidence": []}
                    # 공고는 있는데(posting_count > 0) 텍스트 근거를 못 뽑았으면 "graph_only" —
                    # gap_agent 프롬프트의 "skip:true 또는 '없음' 메시지가 있으면 graph_only로 처리"라는
                    # 규칙이 참조하는 그 상태값이 여기서 만들어짐
        except Exception as e:
            return {"error": str(e)}
        return results

    @tool
    def skill_unlock(
        skill_names: Annotated[list[str], "추가 보유 시 효과를 계산할 스킬 목록 (최대 3개, missing_required 확정 후 1회만 호출)"],
    ) -> dict:
        """해당 스킬들을 모두 보유했을 때 지원 가능한 공고 수를 반환한다.

        missing_required 상위 3개 스킬을 묶음으로 1회만 호출한다.
        개별 스킬로 반복 호출하지 않는다.
        """
        try:
            count = neo4j.get_skill_unlock_count(skill_names[:3])
            return {"skills": skill_names[:3], "accessible_postings": count}
        except Exception as e:
            return {"error": str(e)}

    @tool
    def posting_trend(
        skill_name: Annotated[str, "트렌드를 조회할 스킬명"],
    ) -> dict:
        """최근 30일 vs 이전 30일 공고 등장 횟수를 비교해 수요 트렌드를 반환한다.

        missing_required 중 우선순위 판단이 필요한 스킬에만 호출한다.
        모든 스킬에 반복 호출하지 않는다.
        """
        try:
            return neo4j.get_skill_trend(skill_name)
            # neo4j_client.py에서 본 그 메서드 — window_days 기본값(30일)을 그대로 씀
        except Exception as e:
            return {"skill": skill_name, "recent_count": 0, "prev_count": 0, "delta_pct": 0.0, "error": str(e)}
            # 실패 시에도 get_skill_trend()가 정상 반환하는 것과 같은 키 구조를 유지 —
            # 호출부(LLM)가 성공/실패 구분 없이 같은 형태의 dict를 받아 처리할 수 있게 일관성을 지킴

    @tool
    def ask_human(
        question: Annotated[str, "사용자에게 물어볼 구체적인 질문"],
    ) -> str:
        """이력서 내용이 불명확하거나 핵심 정보가 누락된 경우 사용자에게 질문한다.

        HITL 확장 지점(설계됨, 기본 비활성). 라이브 활성화하려면 HITL_ENABLED=true +
        supervisor 그래프에 checkpointer 재부착 + API resume 엔드포인트가 필요하다.
        기본은 자동 모드로, 불확실성은 confidence 등급·advice로 논블로킹 처리한다.
        """
        if os.getenv("HITL_ENABLED", "false").lower() != "true":
            return "[자동 모드] 사용자 확인 없이 진행합니다."
            # 기본값 — 이 도구를 LLM이 호출해도, 실제로 사람에게 안 물어보고 즉시 이 문자열만 돌려줌.
            # LLM은 이 응답을 보고 "질문은 못 했지만 일단 진행하라는 뜻이구나"라고 이해하고 다음 판단으로 넘어감
        try:
            from langgraph.types import interrupt as _interrupt  # >=0.3
            # LangGraph 특정 버전 이상에서만 제공되는 기능이라, 함수 안에서 지연 import + 예외 처리로
            # "이 기능이 없는 구버전 환경에서도 프로그램이 죽지 않게" 방어
        except ImportError:
            return "[HITL 미지원 버전] 자동 모드로 진행합니다."
        answer: str = _interrupt({"question": question})
        # interrupt() — LangGraph가 그래프 실행을 그 자리에서 "일시정지"시키고, 사람의 응답이
        # 올 때까지 기다리게 하는 실제 HITL 메커니즘. 다만 CLAUDE.md에 명시된 대로, 이게 실제로
        # 작동하려면 그래프에 checkpointer(중단 지점 상태를 저장하는 장치)가 재부착돼야 하고
        # API에도 resume 엔드포인트가 있어야 함 — 지금은 이 조건이 안 갖춰져 있어 기본 비활성
        return answer

    return [gap_analysis, verify_skills, skill_unlock, posting_trend, ask_human]
    # gap_agent.py의 create_gap_graph(gap_tools)에 넘겨지는 그 리스트 — 순서가 곧
    # LLM에게 제시되는 도구 목록 순서이기도 함 (프롬프트의 1~5단계 순서와 대략 일치)


def create_coach_tools(neo4j: "Neo4jClient") -> list:
    """Coach 에이전트 전용 툴 목록 생성."""
    # gap_agent와 완전히 별개의, 더 작은 도구 세트 — coach_agent.py가 이걸 가져다 쓸 것으로 예상

    @tool
    def verify_suggestion(
        skill: Annotated[str, "검증할 스킬명"],
        suggestion_text: Annotated[str, "검증할 이력서 개선 제안 텍스트"],
    ) -> dict:
        """제안이 실제 채용공고 요건에 근거하는지 증거 텍스트를 가져온다.

        LLM이 이 증거를 보고 제안의 구체성과 공고 정합성을 스스로 판단한다.
        이 툴은 데이터만 반환하며, 판단은 하지 않는다.
        """
        # docstring의 마지막 문장이 이 프로젝트의 도구 설계 철학을 명확히 보여줌 —
        # "도구는 사실만 가져오고, 그 사실을 어떻게 해석할지는 LLM(또는 결정적 코드)의 몫"이라는 역할 분리.
        # gap_analysis처럼 스스로 계산까지 하는 도구도 있지만, 이 도구는 순수하게 데이터 조회만 함
        try:
            ids = neo4j.get_postings_requiring_skill(skill, limit=2)
            if not ids:
                return {"skill": skill, "evidence": "", "company": "",
                        "note": "해당 스킬의 공고 텍스트 없음 — 제안을 더 일반적으로 작성하세요."}
                # 근거가 없을 때도 LLM이 다음에 뭘 해야 할지 힌트를 주는 note를 포함 — 그냥 빈 값만
                # 주는 게 아니라 "이 상황에서 어떻게 행동하라"는 안내까지 도구 응답에 담는 패턴
            secs = neo4j.get_posting_sections(ids)
            s = secs[0] if secs else {}
            text = (s.get("required_section") or s.get("preferred_section") or "")[:400]
            return {"skill": skill, "evidence": text, "company": s.get("company") or ""}
        except Exception as e:
            return {"skill": skill, "evidence": "", "company": "", "error": str(e)}

    @tool
    def related_skills(
        skills: Annotated[list[str], "보유 스킬 목록"],
    ) -> dict:
        """보유 스킬과 공고에서 자주 함께 요구되는(CO_OCCURS) 연계 스킬을 반환한다."""
        # nodes.py의 _COACH_SYSTEM_PROMPT에서 "related_skills 툴로 찾은 연계 미보유 스킬을
        # 학습 추천"한다고 언급된 그 도구
        try:
            return {"related": neo4j.get_co_occurring_skills(skills, top_n=8)}
        except Exception as e:
            return {"related": [], "error": str(e)}

    return [verify_suggestion, related_skills]
