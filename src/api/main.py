# FastAPI 앱 진입점 — 라우터 조립, 클라이언트 lifespan 관리
#
# 한 줄 요약: 이 프로젝트의 웹 서버가 시작되는 파일. Layer 3(supervisor.py)를 감싸서
# "브라우저가 요청을 보내면 그래프를 실행해서 답을 돌려주는" 웹 API로 노출시킵니다.
# CLAUDE.md의 "FastAPI + Docker" 확정 스택 중 FastAPI 부분이 이 파일부터 시작됩니다.

from __future__ import annotations

import logging
import os
import tempfile
from contextlib import asynccontextmanager
# asynccontextmanager — "시작할 때 한 번, 끝날 때 한 번" 실행되는 코드 블록을 쉽게 만드는 도구.
# 아래 lifespan()이 바로 이걸로 만든, "서버 켤 때 준비하고 끌 때 정리하는" 함수.
from pathlib import Path
from typing import AsyncGenerator

from dotenv import load_dotenv
from openai import OpenAI
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
# FastAPI — 파이썬으로 웹 API 서버를 만드는 라이브러리. CLAUDE.md 확정 스택.

# uvicorn src.api.main:app 으로 직접 띄울 때도 .env가 적용되도록 — 실행 위치 무관 절대경로
load_dotenv(Path(__file__).resolve().parents[2] / ".env")
# pipeline.py, tools.py 등 다른 여러 파일에서 이미 본 패턴 — "이 파일 기준으로 몇 단계 위가
# 프로젝트 루트다"를 계산해서, 어디서 실행하든 항상 같은 .env 파일을 찾아 읽음

from src.agent.supervisor import create_supervisor_graph
from src.api.deps import BoundedDict
# 아직 안 본 deps.py의 클래스 — 이름으로 짐작하면 "개수 제한 있는 dict"
from src.api.routers import jobs as jobs_router
from src.api.routers import portfolio as portfolio_router
from src.api.routers import system as system_router
from src.storage.neo4j_client import Neo4jClient

logger = logging.getLogger("jobgraph.api")

# 데모 서버 메모리 상한 — report_id 단위 항목 최대 보관 수
_MAX_INFLIGHT = 500
# langfuse_tracer.py의 deque(maxlen=1000)이랑 같은 목적 — 서버를 오래 켜둬도
# 메모리가 끝없이 늘어나지 않게 "최대 이만큼만 기억한다"는 상한을 둠


def _cleanup_evicted_upload(key: object, value: object) -> None:
    """uploads에서 포트폴리오 임시 파일 항목이 밀려날 때 실제 파일도 삭제한다."""
    if not (isinstance(key, str) and key.startswith("pf:") and isinstance(value, str)):
        return
    tmp_dir = os.path.realpath(tempfile.gettempdir())
    path = os.path.realpath(value)
    if not path.startswith(tmp_dir + os.sep):
        logger.warning("임시 디렉터리 밖 포트폴리오 경로는 삭제하지 않음: %s", value)
        return
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning("축출된 포트폴리오 임시 파일 삭제 실패: %s", value, exc_info=True)


def _cleanup_upload_store(uploads: object) -> None:
    """서버 종료 시 uploads에 남은 포트폴리오 임시 파일을 모두 정리한다."""
    if not hasattr(uploads, "items"):
        return
    for key, value in list(uploads.items()):
        _cleanup_evicted_upload(key, value)
    if hasattr(uploads, "clear"):
        uploads.clear()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    # 이 함수가 바로 "서버가 켜질 때 한 번, 꺼질 때 한 번" 실행되는 부분.
    # yield 를 기준으로 위쪽은 "켜질 때(startup)", 아래쪽은 "꺼질 때(shutdown)" 코드임.

    # ── startup ──────────────────────────────────────────────────
    app.state.neo4j = Neo4jClient()
    # app.state — FastAPI 앱 전체에서 공유하는 "짐칸" 같은 곳. 여기 넣어두면
    # 어떤 요청이 와도(라우터 함수 안에서) request.app.state.neo4j로 똑같은 연결을 꺼내 쓸 수 있음.
    # 요청이 올 때마다 새로 만드는 게 아니라, 서버 켤 때 딱 한 번만 만들어서 계속 재사용하는 것.
    app.state.openai = (
        OpenAI(max_retries=6) if os.getenv("OPENAI_API_KEY") else None
    )
    # OpenAI 키가 없으면 openai 클라이언트를 아예 안 만들고 None으로 둠 —
    # CLAUDE.md 규칙("키 없으면 mock/비활성")대로, 키가 없어도 서버 자체는 죽지 않고 뜨게 함
    app.state.uploads = BoundedDict(_MAX_INFLIGHT, on_evict=_cleanup_evicted_upload)   # report_id → PDF 텍스트
    app.state.reports = BoundedDict(_MAX_INFLIGHT)   # report_id → ReportResponse
    # v3 그래프는 1회 빌드해 재사용 (openai 키 없으면 None — /analyze가 503)
    app.state.graph = (
        create_supervisor_graph(app.state.neo4j, app.state.openai)
        if app.state.openai else None
    )
    # supervisor.py의 그래프 조립 함수를 서버 켤 때 딱 한 번만 호출해서 app.state.graph에 저장.
    # 이게 왜 중요한가: 그래프를 매 요청마다 새로 만들면 느리고 낭비니까, 한 번 만들어서 계속 재사용함.
    # openai 클라이언트가 None이면 그래프도 만들지 않고 None — 나중에 /analyze 요청이 오면
    # "그래프가 없다"는 걸로 503(서비스 이용 불가) 에러를 낼 수 있음

    yield
    # yield 지점에서 서버가 실제로 요청을 받기 시작함. 서버가 꺼질 때까지 이 지점에서 "멈춰있다가",
    # 꺼지라는 신호가 오면 아래(shutdown) 코드로 이어서 실행됨.

    # ── shutdown ─────────────────────────────────────────────────
    _cleanup_upload_store(app.state.uploads)
    app.state.neo4j.close()
    # 서버가 꺼질 때 Neo4j 연결을 정리 — pipeline.py의 step_ingest()에서 본 것과 같은 습관


app = FastAPI(
    title="Job Skill Analyzer",
    description=(
        "채용공고를 수집·분석하고, 이력서를 올리면 "
        "직무 대비 부족한 기술과 개선 방향을 알려주는 Agentic RAG 시스템"
    ),
    version="0.1.0",
    lifespan=lifespan,
)
# 여기서 실제로 "서버 객체"가 만들어짐. lifespan=lifespan → 위에서 만든 시작/종료 함수를 이 서버에 연결.
# title, description은 FastAPI가 자동으로 만들어주는 API 문서 페이지(/docs)에 표시되는 정보.

app.include_router(jobs_router.router, prefix="/jobs", tags=["jobs"])
app.include_router(portfolio_router.router, prefix="/portfolio", tags=["portfolio"])
app.include_router(system_router.router, prefix="/graph", tags=["system"])
# "라우터"란: 관련된 API 주소들을 하나로 묶어놓은 묶음. 예를 들어 jobs_router 안에
# "/jobs/xxx", "/jobs/yyy" 같은 여러 주소가 정의돼 있고, 여기서 그걸 전부
# "/jobs"라는 접두어를 붙여서 이 서버에 한 번에 등록함. (아직 안 본 3개 파일)

# 정적 프론트 디렉토리는 실행 위치(CWD)와 무관하게 파일 기준 절대경로로 해석
_WEB_DIR = Path(__file__).resolve().parents[2] / "web"
app.mount("/web", StaticFiles(directory=_WEB_DIR), name="web")
# "/web"으로 시작하는 주소로 요청이 오면, web 폴더 안의 파일(HTML, CSS, JS 등)을 그대로 돌려주라는 설정.
# 이게 있어야 브라우저가 이 서버에 접속했을 때 화면(프론트엔드)을 볼 수 있음.


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    """프론트 진입점 — 정적 index.html 반환."""
    # @app.get("/") → "누가 이 서버의 맨 앞 주소(/)로 GET 요청을 보내면 이 함수를 실행해라"는 뜻.
    # include_in_schema=False → 이 주소는 API 문서(/docs)에는 안 보이게 숨김 (내부 페이지 라우팅용이라서)
    return FileResponse(_WEB_DIR / "index.html")
    # web/index.html 파일 그대로를 응답으로 돌려줌 — 브라우저는 이걸 받아서 화면을 그림


@app.get("/observe", include_in_schema=False)
async def observe() -> FileResponse:
    """관측 페이지 — 워크플로우 추적 + 데이터 현황."""
    return FileResponse(_WEB_DIR / "observe.html")
    # CLAUDE.md에서 말한 "관측 페이지" — nodes.py의 _build_trace()가 만든 데이터를
    # 눈으로 보여주는 화면일 것으로 예상됨


@app.get("/health", tags=["system"])
async def health(request: Request) -> dict:
    """서비스 상태·OpenAI 키 보유 여부 반환. 헬스체크용."""
    # "헬스체크"란: 서버가 살아있는지, 제대로 설정됐는지 간단히 확인하는 용도의 주소.
    # 배포 환경(Docker, 클라우드)이 주기적으로 이 주소를 두드려서 "서버 괜찮나?" 확인하는 데 씀.
    has_openai = request.app.state.openai is not None
    # request.app.state → 라우터 함수 안에서 위에서 만든 app.state에 접근하는 방법
    return {
        "status": "ok",
        "has_openai": has_openai,
    }


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # "이 서버 전체에서 처리 안 된 에러가 하나라도 발생하면, 이 함수가 대신 응답을 만들어라"는 설정.
    # 이게 없으면 에러 발생 시 파이썬 에러 메시지(스택 트레이스, 파일 경로 등)가 그대로 사용자에게
    # 노출될 위험이 있음 — 이건 보안 문제(내부 구조 정보 유출)가 될 수 있음.

    # 상세(스택·Neo4j URI·경로 등)는 서버 로그에만, 응답엔 일반 메시지만 — 공개 데모 정보 노출 방지
    logger.exception("처리되지 않은 예외: %s %s", request.method, request.url.path)
    # logger.exception() → 에러 메시지 + 어디서 났는지(스택 트레이스)까지 전부 서버 로그 파일에 기록.
    # 이건 개발자만 보는 곳이라 상세 정보를 다 남겨도 괜찮음.
    return JSONResponse(
        status_code=500,
        content={"error": "내부 서버 오류가 발생했습니다."},
    )
    # 하지만 사용자(브라우저)에게 돌려주는 응답은 딱 이 한 줄짜리 일반 메시지뿐 —
    # 서버 내부가 어떻게 생겼는지(어떤 DB를 쓰는지, 어느 파일에서 에러가 났는지) 전혀 안 알려줌
