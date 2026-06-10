# FastAPI 의존성 주입 함수 모음
from __future__ import annotations

from openai import OpenAI
from fastapi import Request

from src.storage.chroma_client import ChromaClient
from src.storage.neo4j_client import Neo4jClient


def get_neo4j(request: Request) -> Neo4jClient:
    return request.app.state.neo4j


def get_chroma(request: Request) -> ChromaClient:
    return request.app.state.chroma


def get_openai(request: Request) -> OpenAI | None:
    return request.app.state.openai


def get_uploads(request: Request) -> dict[str, str]:
    """report_id → PDF 텍스트 매핑."""
    return request.app.state.uploads


def get_reports(request: Request) -> dict[str, object]:
    """report_id → ReportResponse 매핑."""
    return request.app.state.reports
