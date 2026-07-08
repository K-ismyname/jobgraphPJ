# 시스템 설명 — LangGraph 구조(Mermaid) + 6개 논리 단계의 설계 의도
#
# 한 줄 요약: 지금까지 우리가 코드로 하나하나 뜯어봤던 supervisor.py의 그래프 구조를,
# 사람이 브라우저에서 그림으로 볼 수 있게 설명 데이터를 만들어주는 파일. main.py의 "/observe"
# 페이지(관측 페이지)가 이 API를 불러서 화면에 그려줄 것으로 보임. 이 파일엔 로직이 거의 없고,
# 전부 "설명 문구"와 "다이어그램 그림"을 미리 써둔 텍스트 상수들입니다.

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.deps import get_graph

router = APIRouter()

_STAGES = [
    # 우리가 지금까지 코드로 본 6단계(평가자 → consensus → gap_agent → synthesizer → critic → coach_agent)를
    # "사람이 읽을 설명 문구"로 다시 정리해둔 것. 실제 실행 로직은 하나도 없고 전부 고정된 텍스트.
    {"key": "evaluators", "title": "1. 다중 소스 평가자",
     "nodes": ["resume_eval", "github_eval", "portfolio_eval", "deploy_eval"],
     # "nodes" 배열은 supervisor.py에서 실제로 쓴 노드 이름 그대로임 — 이게 왜 중요한지는
     # 아래 graph() 함수 설명에서 나옴 (실행된 노드를 하이라이트하는 데 씀)
     "description": "입력한 소스만 각각 다른 평가자가 본다. 소스마다 형식(텍스트·코드·웹)이 달라 한 LLM에 합칠 수 없고, 무엇보다 '할 줄 안다는 주장(이력서)'과 '코드로 실증됨(GitHub·배포)'을 구분하려고 분리했다.",
     "sources": [
         {"name": "이력서 (PDF)", "sees": "텍스트를 읽어 보유 스킬을 추출", "verdict": "주장 (Claimed)"},
         {"name": "포트폴리오 (PDF)", "sees": "텍스트 + 이미지(vision)로 프로젝트 규모·성과 파악", "verdict": "주장 보강"},
         {"name": "GitHub", "sees": "레포 코드·README·의존성을 읽어 실제 사용을 확인", "verdict": "실증 (Verified)"},
         {"name": "배포 URL", "sees": "작동하는 웹(HTML·헤더)을 확인", "verdict": "작동 실증 (Verified)"},
     ]},
    {"key": "consensus", "title": "2. 교차검증 합의",
     "nodes": ["consensus"],
     "description": "여러 독립 소스가 같은 스킬을 가리키면 신뢰가 올라간다(법정·저널리즘의 교차검증 원칙). GitHub/배포로 실증되면 Verified, 2개 이상 소스가 일치하면 Corroborated, 한 소스(이력서)뿐이면 Claimed로 결정적으로 판정한다."},
    {"key": "gap_loop", "title": "3. Gap 루프 (Corrective RAG)",
     "nodes": ["seed_gap", "gap_agent"],
     "description": "단순 키워드 매칭이 아니다. 증거가 부족하면 에이전트가 다른 소스를 추가로 검색하는 교정 루프를 돈다 — '이 답을 신뢰할 근거가 충분한가'를 스스로 판단한다. (gap_agent는 내부에 call_model↔tools 루프를 가진 서브그래프)"},
    {"key": "fit", "title": "4. 스킬 기반 적합도",
     "nodes": ["synthesizer"],
     "description": "직군 핵심 스킬(빈도 상위 10개)과 이력서 스킬을 개별 비교해 적합도를 낸다. 역량 묶음으로 뭉뚱그리면 직군이 구분되지 않아(Data Analyst와 Data Engineer가 동일해짐), 스킬 단위로 비교해 변별력을 확보했다. 어느 직군에 맞는지 역방향으로도 추천한다."},
    {"key": "critic", "title": "5. Critic (환각 제거)",
     "nodes": ["critic"],
     "description": "LLM이 스스로 채점하면 환각이 남는다. Critic은 판단하지 않고, 리포트의 주장을 합의(사실)와 대조해 합의에 없는 환각을 제거하고 부풀린 검증 라벨을 교정한다 — 결정적으로."},
    {"key": "coach", "title": "6. Coach",
     "nodes": ["coach_agent"],
     "description": "부족한 스킬과, 이력서·코드를 어떻게 보강하면 좋을지 구체적인 문장을 공고 근거와 GitHub 코드에 기반해 제안한다. (coach_agent는 내부 코칭 루프 서브그래프)"},
]
# 이 리스트 하나가 지금까지 우리가 12개 파일을 읽으며 알아낸 걸, 사용자에게 보여줄
# "요약 브리핑"으로 미리 정리해둔 것이라고 보면 됩니다. 코드가 바뀌면 이 설명도 같이 업데이트해줘야
# 실제 동작과 화면 설명이 어긋나지 않습니다 (자동으로 동기화되는 게 아니라 사람이 손으로 맞추는 부분).


_OVERVIEW = (
    "입력한 소스(이력서·GitHub·포트폴리오·배포)만 골라 병렬로 평가한 뒤, 합의 노드가 여러 소스를 "
    "교차검증해 스킬별 검증등급(Verified/Corroborated/Claimed)을 결정적으로 판정합니다. "
    "Gap 에이전트는 근거가 부족하면 추가 검색을 스스로 결정하는 Corrective RAG 루프를 돌고, "
    "리포트는 Critic이 합의와 대조해 환각을 제거합니다. 마지막으로 Coach가 부족 스킬 보강·이력서 개선을 "
    "공고 근거와 GitHub 코드에 기반해 제안합니다. 파란 노드는 이번 분석에서 실제 실행된 경로입니다."
)
# _STAGES가 "6단계 각각의 상세 설명"이라면, 이건 그 전체를 한 문단으로 요약한 것 — 관측 페이지 맨 위에
# "이 시스템이 대충 어떻게 동작하는지" 한눈에 보여주는 인트로 문구로 쓰일 것으로 보임

# 실제 LangGraph 구조를 반영한 상세 다이어그램. draw_mermaid()는 서브그래프 내부 루프를
# 접어 밋밋하므로, Gap·Coach 서브그래프의 내부 루프까지 손으로 표현한다.
# 최상위 노드 id는 실제 노드명과 일치시켜 executed_nodes 하이라이트가 붙게 한다.
_WORKFLOW_MERMAID = """flowchart TD
  START([이력서·GitHub·포트폴리오·배포 URL]) --> DISP{입력 소스 확인}
  DISP -->|이력서| resume_eval["이력서 평가자<br/>텍스트 → 스킬 추출"]
  DISP -->|GitHub| github_eval["GitHub 평가자<br/>레포 코드 분석"]
  DISP -->|포트폴리오| portfolio_eval["포트폴리오 평가자<br/>텍스트 + vision"]
  DISP -->|배포 URL| deploy_eval["배포 평가자<br/>작동 실증"]
  resume_eval --> consensus
  github_eval --> consensus
  portfolio_eval --> consensus
  deploy_eval --> consensus
  consensus["합의<br/>검증등급 결정적 판정"] --> seed_gap["seed_gap<br/>Gap 진입 상태 변환"]
  seed_gap --> gap_agent
  subgraph gap_agent["Gap 에이전트 — Corrective RAG 루프"]
    direction LR
    gcm["call_model<br/>증거 충분한가?"] -->|부족하면 재검색| gtl["tools<br/>gap_analysis · verify_skills · skill_unlock"]
    gtl --> gcm
  end
  gap_agent --> synthesizer["synthesizer<br/>적합도 + 신뢰도 리포트"]
  synthesizer --> critic["critic<br/>합의 대조 · 환각 제거"]
  critic --> coach_agent
  subgraph coach_agent["Coach 에이전트 — 코칭 루프"]
    direction LR
    ccm["coach_call_model"] -->|근거 확인| ctl["coach_tools<br/>verify_suggestion · related_skills"]
    ctl --> ccm
    ccm --> fc["finalize_coach<br/>코칭 확정"]
  end
  coach_agent --> DONE([최종 리포트<br/>충족·채울것·보강·회사추천])
"""
# Mermaid — 텍스트로 다이어그램(순서도, 그래프 등)을 그리는 미니 언어. 이 문자열을 프론트엔드의
# Mermaid 렌더링 라이브러리에 넘기면, 브라우저가 이걸 읽어서 실제 박스·화살표 그림으로 그려줌.
# 문법 요약:
#   A --> B          → A에서 B로 화살표
#   A -->|글자| B     → 화살표 위에 라벨(설명) 붙이기
#   NODE["박스 안 글자"] → 노드를 사각형 박스로, 안에 글자 표시 (<br/>은 HTML 줄바꿈 태그)
#   START([...])      → 둥근 모양의 시작/끝 노드
#   DISP{...}         → 마름모 모양의 분기(판단) 노드
#   subgraph 이름["제목"] ... end → 그 안의 노드들을 하나의 큰 박스로 묶어서 표시 (서브그래프 표현)
#
# 주석에 적힌 이유가 흥미로운 지점: LangGraph가 자체적으로 제공하는 draw_mermaid() 기능을 쓰면
# gap_agent, coach_agent 같은 서브그래프 "내부"가 하나의 박스로 뭉뚱그려져서 안 보임 — 그래서
# 이 프로젝트는 자동 생성 대신, 서브그래프 내부 루프(call_model↔tools)까지 사람이 직접 손으로
# 이 문자열을 써서 더 자세히 보이게 만듦. 즉 이 다이어그램은 "코드에서 자동으로 뽑아낸 것"이 아니라
# "사람이 실제 구조를 보고 손으로 그려서 고정해둔 것" — supervisor.py 구조가 바뀌면 이것도 같이 고쳐야 함


@router.get("")
async def graph(graph=Depends(get_graph)) -> dict:
    """LangGraph 구조(Mermaid) + 개요 + 단계 설명. graph 없으면 mermaid는 None."""
    # 함수 이름이 graph, 매개변수 이름도 graph — 이름이 겹치는데, 매개변수 graph가 함수 안에서
    # 함수 자기 자신(전역 이름 graph)을 가려버림. 이 함수 본문 안에서는 "graph"라고 쓰면 매개변수를
    # 가리키게 됨 — 헷갈리기 쉬운 네이밍이지만, 여기선 이 매개변수를 딱 한 번(is not None 확인)만
    # 써서 실제로 문제는 안 생기는 상황
    mermaid = _WORKFLOW_MERMAID if graph is not None else None
    # deps.py의 get_graph()가 반환하는 그 값 — main.py에서 OpenAI 키가 없으면 그래프 자체가
    # None이었던 것과 연결됨. 그래프가 아예 안 만들어진 상태(키 없음)면, "실행할 그래프가 없으니
    # 다이어그램도 보여줄 필요 없다"는 판단으로 mermaid를 None으로 둠
    return {"mermaid": mermaid, "overview": _OVERVIEW, "stages": _STAGES}
    # 이 API는 Neo4j도 OpenAI도 전혀 안 건드림 — 순수하게 "미리 써둔 설명 텍스트"만 그대로 돌려줌.
    # 그래서 이 파일 전체에서 실제 "로직"이라고 부를 만한 부분은 사실상 이 한 줄(if/else)이 전부입니다.
