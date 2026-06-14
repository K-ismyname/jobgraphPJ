# FastAPI 앱 진입점 — 라우터 조립, 클라이언트 lifespan 관리
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from dotenv import load_dotenv
from openai import OpenAI
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# uvicorn src.api.main:app 으로 직접 띄울 때도 .env가 적용되도록 — 실행 위치 무관 절대경로
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from src.agent.supervisor import create_supervisor_graph
from src.api.routers import jobs as jobs_router
from src.api.routers import portfolio as portfolio_router
from src.api.routers import stats as stats_router
from src.api.routers import system as system_router
from src.storage.chroma_client import ChromaClient
from src.storage.neo4j_client import Neo4jClient


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    # ── startup ──────────────────────────────────────────────────
    app.state.neo4j = Neo4jClient()
    app.state.chroma = ChromaClient()
    app.state.openai = (
        OpenAI() if os.getenv("OPENAI_API_KEY") else None
    )
    app.state.uploads: dict[str, str] = {}   # report_id → PDF 텍스트
    app.state.reports: dict = {}             # report_id → ReportResponse
    # v3 그래프는 1회 빌드해 재사용 (openai 키 없으면 None — /analyze가 503)
    app.state.graph = (
        create_supervisor_graph(app.state.neo4j, app.state.openai)
        if app.state.openai else None
    )

    yield

    # ── shutdown ─────────────────────────────────────────────────
    app.state.neo4j.close()


app = FastAPI(
    title="Job Skill Analyzer",
    description=(
        "채용공고를 수집·분석하고, 이력서를 올리면 "
        "직무 대비 부족한 기술과 개선 방향을 알려주는 Agentic RAG 시스템"
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(jobs_router.router, prefix="/jobs", tags=["jobs"])
app.include_router(portfolio_router.router, prefix="/portfolio", tags=["portfolio"])
app.include_router(stats_router.router, prefix="/stats", tags=["stats"])
app.include_router(system_router.router, prefix="/graph", tags=["system"])

# 정적 프론트 디렉토리는 실행 위치(CWD)와 무관하게 파일 기준 절대경로로 해석
_WEB_DIR = Path(__file__).resolve().parents[2] / "web"
app.mount("/web", StaticFiles(directory=_WEB_DIR), name="web")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    """프론트 진입점 — 정적 index.html 반환."""
    return FileResponse(_WEB_DIR / "index.html")


@app.get("/observe", include_in_schema=False)
async def observe() -> FileResponse:
    """관측 페이지 — 워크플로우 추적 + 데이터 현황."""
    return FileResponse(_WEB_DIR / "observe.html")


@app.get("/health", tags=["system"])
async def health(request: Request) -> dict:
    """Neo4j·Chroma 연결 상태 반환. 헬스체크용."""
    has_openai = request.app.state.openai is not None
    return {
        "status": "ok",
        "has_openai": has_openai,
    }


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"error": "내부 서버 오류", "detail": str(exc)},
    )
