# 이력서에서 스킬 증거를 추출하는 평가자 (텍스트 modality)
#
# 이 파일이 하는 일: Supervisor 그래프의 dispatch가 병렬로 fan-out하는 4개 평가자 중 하나.
# 사용자가 이력서(PDF 또는 스킬 목록)를 냈을 때, 거기서 "어떤 스킬을 어떤 근거로 갖고 있는지"를
# 뽑아내 AppState의 resume_eval 필드에 담아 반환한다. 이 결과는 나중에 consensus 노드가
# github_eval/portfolio_eval/deploy_eval과 교차검증할 때 재료로 쓰인다.

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable
# Callable[["AppState"], dict] → "AppState를 받아서 dict를 반환하는 함수" 타입을 표현하는 힌트.
# 아래 create_resume_evaluator()가 "함수를 반환하는 함수(팩토리)"라서, 그 반환 타입을 정확히 명시하려고 씀

if TYPE_CHECKING:
    from src.agent.state import AppState
    # TYPE_CHECKING은 실제 실행 시에는 False라서 이 import는 런타임엔 일어나지 않음.
    # 타입 힌트(문자열 "AppState")를 IDE·타입체커가 이해하게 하려는 목적으로만 존재 —
    # 실행 속도에 영향 없이, 순환 import 위험도 피하면서 타입 정보만 제공하는 관용적 패턴

logger = logging.getLogger("jobgraph.agent")
# 이 파일 전용 로거. neo4j_client.py의 "jobgraph.storage"와 이름 체계가 같음 — 프로젝트 전체가
# "jobgraph.모듈이름" 형식으로 로거를 통일해서 나중에 로그를 모듈별로 필터링하기 쉽게 함

def create_resume_evaluator(openai_client) -> Callable[["AppState"], dict]:
    """이력서 평가자 팩토리. resume_skills 주입 > pdf > resume_text 순."""
    # "팩토리 함수" — 함수를 반환하는 함수. 왜 이런 구조인가:
    # 실제 노드 함수(evaluate)가 openai_client를 매번 인자로 받는 대신, 이 바깥 함수가
    # openai_client를 한 번만 받아서 "클로저"로 붙잡아두면, LangGraph에 등록할 노드 함수(evaluate)는
    # State 하나만 인자로 받는 깔끔한 형태(add_node가 기대하는 시그니처)를 유지할 수 있음
    from src.portfolio.pdf_parser import extract_pdf_text
    from src.extraction.skill_extractor import extract_skills_from_resume
    # 함수 안에서 import — 아직 안 본 pdf_parser.py, 그리고 지난번 이미 본 skill_extractor.py를 재사용
    # (skill_extractor.py의 extract_skills_from_resume이 여기서 실제로 처음 호출되는 걸 확인할 수 있음 —
    #  지난번엔 "아직 어디서도 안 쓰이는 것 같다"고 봤던 그 함수)

    def evaluate(state: "AppState") -> dict:
        # ── 우선순위 1: resume_skills가 이미 주입돼 있으면 그걸 최우선 사용 ──
        if state.get("resume_skills"):
            # resume_skills는 AppState의 필드 — 사용자가 이력서 텍스트/PDF가 아니라
            # 이미 정리된 스킬 목록 자체를 직접 입력했을 때 채워지는 경로로 추정 (예: 프론트엔드에서 태그 입력)
            if state.get("pdf_path") or state.get("resume_text"):
                logger.warning("[resume_eval] resume_skills 주입됨 — pdf_path/resume_text는 무시")
                # 세 가지 입력이 동시에 들어온 경우 "resume_skills가 이긴다"는 우선순위를 명시적으로 경고 로그로 남김
                # (조용히 무시하면 사용자가 "왜 PDF 내용이 반영 안 됐지"라고 헷갈릴 수 있어서 로그로 흔적을 남김)
            seen: set[str] = set()  # 이미 처리한 스킬명 추적 (중복 제거용)
            skills = []
            for s in state["resume_skills"]:
                if s in seen:  # 정확한 중복 제거 (순서 유지)
                    continue
                seen.add(s)
                skills.append({"skill": s, "evidence": "이력서 주입 스킬", "source": "resume", "level_hint": None})
                # evidence(근거)가 "이력서 주입 스킬"이라는 고정 문구 — 실제 문장 근거가 없으니
                # "사용자가 직접 넣은 값"이라는 사실 자체를 근거로 표시. level_hint(확신도 힌트)는 None —
                # 이 경로는 LLM이 판단한 게 아니라 사용자가 그냥 입력한 값이라 확신도를 매길 근거가 없음
            return {"resume_eval": {"skills": skills}}
            # 조건을 만족하면 여기서 함수가 끝남 — 아래의 PDF/텍스트 처리 로직은 실행 안 됨 (조기 반환)

        # ── 우선순위 2: PDF 파일이 있으면 텍스트 추출 시도 ──
        text = None
        if state.get("pdf_path"):
            try:
                text = extract_pdf_text(state["pdf_path"])
            except Exception as e:
                logger.warning(f"[resume_eval] PDF 실패: {e}")
                # PDF 파싱이 실패해도(손상된 파일 등) 여기서 전체가 죽지 않고, text가 None인 채로 아래로 진행

        # PDF가 없거나·실패·공백이면 resume_text로 fallback
        if not (text and text.strip()) and state.get("resume_text"):
            text = state["resume_text"]
            # "text and text.strip()" → text가 None이 아니고, 공백을 제거해도 내용이 남아있어야 참
            # (PDF에서 빈 문자열만 뽑혔거나 공백만 있는 경우까지 "실패"로 취급해 다음 fallback으로 넘어감)

        # ── 셋 다 없으면 빈 결과 ──
        if not (text and text.strip()):
            return {"resume_eval": {"skills": []}}
            # 이력서 관련 입력이 아예 없는 상황 — 에러를 내지 않고 "스킬 없음"으로 조용히 반환.
            # 이래야 dispatch가 이 평가자를 fan-out했더라도 나머지 그래프 흐름이 안 끊기고 계속 진행됨

        # ── 우선순위 3: 텍스트가 확보됐으면 LLM으로 구조화 추출 ──
        try:
            extraction = extract_skills_from_resume(text, openai_client)
            # 지난번 skill_extractor.py에서 본 ResumeExtraction 모델 인스턴스가 여기로 반환됨
            skills = [
                {"skill": sk.name, "evidence": sk.evidence, "source": "resume", "level_hint": sk.confidence}
                for sec in extraction.sections for sk in sec.skills
            ]
            # 이중 for문 컴프리헨션: extraction.sections(섹션 리스트)를 먼저 순회하고,
            # 각 섹션 안의 sec.skills(그 섹션에서 발견된 스킬 리스트)를 또 순회 — 중첩 구조를 평평한 리스트로 펼침
            # (ResumeExtraction은 "섹션 → 스킬들"의 계층 구조인데, 여기선 그 계층을 없애고
            #  "스킬 하나당 한 항목"인 평평한 리스트로 변환해서 다른 평가자들과 같은 모양으로 맞춤)
        except Exception as e:
            logger.warning(f"[resume_eval] 추출 실패: {e}")
            skills = []
            # LLM 호출 자체가 실패해도(네트워크 오류 등) 빈 리스트로 안전하게 처리하고 넘어감
        return {"resume_eval": {"skills": skills}}

    return evaluate
    # create_resume_evaluator()가 최종적으로 반환하는 건 evaluate 함수 자체 (호출된 결과가 아니라 함수 객체)
    # supervisor.py가 이걸 workflow.add_node("resume_eval", create_resume_evaluator(openai_client))처럼
    # 그래프에 등록해서 쓸 것으로 예상됨
