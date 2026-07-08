# LangGraph 에이전트 공유 상태 정의 — Supervisor + 서브 에이전트 State
#
# 이 파일이 하는 일: Layer 3(에이전트) 전체가 공유하는 "데이터의 모양"만 정의한다.
# 실제로 무슨 계산을 하는 로직은 하나도 없고, "이 그래프를 흐르는 데이터는 이런 필드들을 가진다"는
# 틀(스키마)만 여기 있다 — pipeline.py에서 봤던 dict 구조를, LangGraph 세계에서는 이렇게
# TypedDict로 미리 선언해두고 그래프 전체가 이 틀을 공유하며 읽고 쓴다.
#
# LangGraph의 핵심 개념: 그래프의 각 노드(함수)는 "전체 상태(State)"를 받아서,
# 그 상태의 일부를 바꾼 dict를 반환한다. 그 반환값이 자동으로 전체 상태에 병합된다.
# 이 파일은 그 "전체 상태"가 정확히 어떤 필드로 구성되는지를 정의하는 곳.

from __future__ import annotations

from typing import Annotated
# Annotated[타입, 부가정보] → "이 필드는 이 타입이지만, 추가로 이런 메타데이터도 붙어있다"고
# 표시하는 문법. LangGraph는 이 부가정보를 보고 "이 필드를 어떻게 업데이트할지"를 결정함 (아래 add_messages 설명 참고)

from langchain_core.messages import BaseMessage
# LangChain/LangGraph 생태계의 "대화 메시지" 기본 타입. HumanMessage, AIMessage, ToolMessage 등이 이걸 상속함
# (사람 메시지, AI 응답, 툴 실행 결과 메시지를 전부 이 BaseMessage 계열로 다룸)

from langgraph.graph.message import add_messages
# add_messages는 "리듀서(reducer) 함수" — 새 메시지가 들어왔을 때 기존 메시지 리스트에
# "이어붙이는" 방식으로 병합하라고 LangGraph에게 알려주는 특수 함수.
# 이게 왜 필요한가: 보통 State의 필드는 새 값이 오면 "덮어쓰기"가 기본 동작인데,
# 대화 messages는 덮어쓰면 이전 대화가 사라지므로, "덮어쓰지 말고 이어붙여라"라는 특별 규칙이 필요함

from typing_extensions import TypedDict
# TypedDict — "이 dict는 반드시 이런 키와 타입을 가져야 한다"고 표시하는 틀.
# pydantic의 BaseModel과 달리 "런타임에 강제로 검증"하지는 않고, 그냥 "이런 모양이어야 한다"는
# 타입 힌트 역할만 함 (실수로 필드명을 틀려도 실행은 되지만, 에디터/타입체커가 경고를 줄 수 있음)
# LangGraph는 State 정의에 보통 이 TypedDict를 씀 (pydantic보다 가볍고 dict 그대로 다루기 쉬워서)

# 무한 루프 방지 상수
MAX_ITERATIONS = 5
COACH_MAX_ITERATIONS = 3
# gap_agent, coach_agent 안에서 "LLM이 툴을 계속 반복해서 부르는" 루프가 있는데,
# LLM이 아무리 판단해도 답이 안 나오는 경우를 대비해 "최대 이만큼 반복하면 강제로 멈춘다"는 안전장치 상수.
# 이 숫자들이 실제로 쓰이는 곳은 gap_agent.py, coach_agent.py에서 볼 수 있을 것


class GapState(TypedDict):
    """GapAgent 전용 State — Supervisor에서 받아서 gap_result 반환."""
    # GapAgent는 LangGraph의 "서브그래프"(그래프 안의 작은 그래프)로 동작하는데,
    # 서브그래프는 부모 그래프(AppState)의 상태 전체가 아니라 자기만의 축소된 상태를 가질 수 있음.
    # 이 GapState는 Supervisor의 AppState 중 GapAgent가 필요한 부분만 뽑아 놓은 "부분집합" 틀
    job_family: str          # 분석 대상 직군 (예: "AI/LLM Engineer")
    owner: str                # 이 분석을 요청한 사람 이름/식별자
    consensus: dict | None    # consensus 노드가 만든 신뢰도 등급 결과 (아직 안 봤지만 dict로 전달됨)
    project_contexts: list       # seed_gap에서 github_eval 결과를 받아 synthesizer에 전달
    messages: Annotated[list[BaseMessage], add_messages]
    # BaseMessage 리스트인데, add_messages 리듀서가 붙어있음 → 새 메시지가 오면 기존 리스트에 "추가"됨
    # (이게 gap_agent의 ReAct 루프 — call_model ↔ tools를 오가며 쌓이는 대화 기록)
    iteration: int             # 지금까지 이 루프를 몇 번 돌았는지 (MAX_ITERATIONS와 비교해서 강제 종료 판단)
    seen_source_ids: list[str] # 이미 참조한 공고 source_id들 — 중복으로 같은 공고를 또 찾지 않기 위한 기록
    gap_result: dict | None    # 이 서브그래프의 최종 산출물 (부족한 스킬 분석 결과)


class CoachState(TypedDict):
    """CoachAgent 전용 State — Supervisor에서 받아서 final_report 반환."""
    job_family: str
    owner: str
    consensus: dict | None
    gap_result: dict | None      # GapAgent가 만든 결과를 이어받아 코칭에 활용
    project_contexts: list
    gap_trace: dict | None        # synthesizer가 채운 gap 루프 정보 (iterations, tool_calls)
    coach_messages: Annotated[list[BaseMessage], add_messages]
    # gap_agent의 messages와는 "완전히 별개의 대화 기록"임 — 필드 이름 자체가 다름(messages vs coach_messages)
    # 왜 분리했는가: 만약 하나의 messages 필드를 gap_agent와 coach_agent가 같이 쓰면,
    # coach_agent가 시작할 때 gap_agent의 긴 ReAct 대화 기록까지 전부 LLM에게 다시 보여주게 되어
    # 불필요하게 비용이 늘고 맥락이 섞일 위험이 있음 — 그래서 서로 다른 이름의 채널로 분리
    coach_iteration: int
    coaching_result: dict | None
    final_report: dict | None    # 이 서브그래프의 최종 산출물 — 사용자에게 보여줄 완성된 리포트
    critic_report: dict | None    # critic 노드가 만든 검증 결과도 여기서 같이 들고 있음


class AppState(TypedDict):
    """Supervisor 전체 플로우의 단일 공유 상태.

    Resume → Gap 루프 → GitHub → Coach 모든 노드가 이 상태를 읽고 쓴다.
    이전의 AgentState(단일 에이전트 전용)는 이 TypedDict에 병합되었다.
    """
    # 이 AppState가 Layer 3 전체의 "메인 상태"임 — supervisor.py가 조립하는 StateGraph 전체가
    # 이 틀을 공유하고, GapState/CoachState는 이 AppState의 관련된 부분만 골라서 서브그래프에 넘기는 것

    # ── Supervisor 입력 ──────────────────────────────────────────
    # 사용자가 API를 통해 맨 처음 넣는 값들 — 그래프 실행이 시작될 때 이미 채워져 있어야 하는 필드들
    job_family: str
    owner: str
    pdf_path: str | None            # 이력서 PDF 파일 경로 (없으면 None — resume_eval을 건너뜀)
    portfolio_path: str | None   # 포트폴리오 PDF 경로 (멀티모달 평가자 입력)
    github_urls: list[str]           # GitHub 저장소 URL들 (여러 개 가능해서 리스트)
    deploy_urls: list[str]       # 배포 URL 목록 (작동 실증 평가자 입력)
    # 이 네 가지 입력 필드(pdf_path, portfolio_path, github_urls, deploy_urls) 중
    # "값이 채워진 것"만 dispatch 노드가 Send로 병렬 fan-out함 — CLAUDE.md에서 본 "입력에 있는 소스만" 부분

    # ── Resume Agent ─────────────────────────────────────────────
    resume_skills: list[str]
    resume_text: str | None

    # ── Gap 분석 루프 ─────────────────────────────────────────────
    messages: Annotated[list[BaseMessage], add_messages]
    iteration: int
    seen_source_ids: list[str]

    # ── Coach 루프 (Gap 루프와 히스토리 분리) ─────────────────────
    coach_messages: Annotated[list[BaseMessage], add_messages]
    coach_iteration: int

    # ── 각 에이전트 결과 ──────────────────────────────────────────
    gap_result: dict | None
    coaching_result: dict | None
    final_report: dict | None

    # ── Critic 검증 ──
    critic_report: dict | None

    # ── v3: 다중 소스 평가 ──
    # 주석의 "v3"는 이 필드 그룹이 프로젝트가 발전하면서 세 번째 버전으로 개편됐다는 이력을 뜻함
    # (CLAUDE.md에도 나온, resume_eval/github_eval/portfolio_eval/deploy_eval 4개 병렬 평가자의 결과 저장소)
    resume_eval: dict | None     # {"skills": [{skill, evidence, source, level_hint}]}
    github_eval: dict | None
    portfolio_eval: dict | None
    deploy_eval: dict | None
    consensus: dict | None       # {skill: {verification, evidences, flags?}}
    # 4개 평가자가 병렬로 채운 위 4개 필드를 종합해서, consensus 노드가 이 필드 하나로 합친 결과를 만듦

    # ── 멀티 에이전트: 서브그래프 간 전달 데이터 ──
    project_contexts: list       # github_eval → GapAgent(synthesizer) → CoachAgent
    gap_trace: dict | None       # synthesizer가 채운 gap 루프 정보 → _build_trace에서 읽음
    # 이 두 필드는 이름 그대로 "서로 다른 서브그래프 사이에서 데이터를 넘겨주는 통로" 역할.
    # GapState, CoachState 양쪽 모두에 이 두 필드가 공통으로 들어있는 이유가 여기 있음 —
    # AppState(부모) → GapState(자식1) → 결과를 다시 AppState로 → CoachState(자식2)로 전달되는 경로이기 때문
