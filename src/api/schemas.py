# API 요청·응답에 사용하는 모든 Pydantic 모델
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ── Jobs Request ────────────────────────────────────────────────
class JobsQuery(BaseModel):
    job_family: str = "AI/LLM Engineer"   # 유효 직군명 (Neo4j JobFamily)
    skills: list[str] | None = None   # 이 기술을 필수로 하는 공고만
    days: int = Field(30, ge=1, le=365)


class TrendingSkillsQuery(BaseModel):
    job_family: str = "AI/LLM Engineer"   # 유효 직군명 (Neo4j JobFamily)
    top_n: int = Field(10, ge=1, le=50)


class SalaryQuery(BaseModel):
    job_family: str = "AI/LLM Engineer"   # 유효 직군명 (Neo4j JobFamily)


# ── Portfolio Request ───────────────────────────────────────────
class AnalyzeRequest(BaseModel):
    report_id: str
    job_family: str = "AI/LLM Engineer"   # 유효 직군명 (Neo4j JobFamily)
    owner_name: str | None = None         # None이면 PDF에서 추출한 이름 사용
    github_url: str | None = None         # 선택 — 코드 검증
    deploy_url: str | None = None         # 선택 — 작동 실증


# ── Jobs Response ───────────────────────────────────────────────
class JobSummary(BaseModel):
    id: str
    title: str
    company: str
    location: str | None
    salary_min: float | None
    salary_max: float | None
    contract_type: str | None
    url: str | None
    required_skills: list[str]
    preferred_skills: list[str]


class JobsResponse(BaseModel):
    job_family: str
    total: int
    jobs: list[JobSummary]


class TrendingSkill(BaseModel):
    rank: int
    name: str
    category: str
    frequency: int


class TrendingSkillsResponse(BaseModel):
    job_family: str
    skills: list[TrendingSkill]
    generated_at: str


class SkillSalaryItem(BaseModel):
    skill: str
    avg_salary: float
    posting_count: int
    vs_baseline_pct: float


class SalaryResponse(BaseModel):
    job_family: str
    baseline_avg_salary: float
    total_postings_with_salary: int
    skill_impacts: list[SkillSalaryItem]
    top_salary_skills: list[str]


# ── Portfolio Response ──────────────────────────────────────────
class UploadResponse(BaseModel):
    report_id: str
    candidate_name_hint: str          # PDF 첫 줄 추출 (부정확할 수 있음)
    page_count: int
    text_length: int
    status: Literal["uploaded"]


class AnalyzeAccepted(BaseModel):
    report_id: str
    status: Literal["processing"]
    message: str = "분석을 시작합니다. GET /portfolio/report/{report_id}로 결과를 확인하세요."


class SuggestionItem(BaseModel):
    target_section: str
    missing_skill: str
    original_text: str | None = None
    rewritten_text: str
    expected_impact: str
    priority: Literal["high", "medium", "low"]
    verified: bool = False


class VerificationItem(BaseModel):
    skill: str
    verification: str               # Verified | Corroborated | Claimed
    sources: list[str]


class ReportResponse(BaseModel):
    report_id: str
    status: Literal["processing", "done", "error"]
    owner: str
    job_family: str
    match_rate: float = 0.0
    confidence_level: str | None = None
    advice: str | None = None
    verification_counts: dict[str, int] = Field(default_factory=dict)
    verified_skills: list[VerificationItem] = Field(default_factory=list)
    coaching_summary: str | None = None
    suggestions: list[SuggestionItem] = Field(default_factory=list)
    error_detail: str | None = None
    generated_at: str | None = None
    trace: dict | None = None
    capability_fit: dict | None = None
    recommended_families: list[dict] = Field(default_factory=list)
    capability_evidence: list[dict] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None


# ── Stats Response ───────────────────────────────────────────────
class JobFamilyStat(BaseModel):
    name: str
    posting_count: int
    skill_count: int


class StatsResponse(BaseModel):
    job_families: list[JobFamilyStat]
    totals: dict[str, int]          # postings, skills, relations
