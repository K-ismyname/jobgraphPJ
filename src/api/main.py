# FastAPI 앱 진입점 — 라우터 조립, 클라이언트 lifespan 관리
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from openai import OpenAI
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.agent.supervisor import create_supervisor_graph
from src.api.routers import jobs as jobs_router
from src.api.routers import portfolio as portfolio_router
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
        create_supervisor_graph(app.state.neo4j, app.state.chroma, app.state.openai)
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
