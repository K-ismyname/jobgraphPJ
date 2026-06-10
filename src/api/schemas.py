# API 요청·응답에 사용하는 모든 Pydantic 모델
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ── Jobs Request ────────────────────────────────────────────────
class JobsQuery(BaseModel):
    job_title: str = "AI Engineer"
    skills: list[str] | None = None   # 이 기술을 필수로 하는 공고만
    days: int = Field(30, ge=1, le=365)


class TrendingSkillsQuery(BaseModel):
    job_title: str = "AI Engineer"
    top_n: int = Field(10, ge=1, le=50)


class SalaryQuery(BaseModel):
    job_title: str = "AI Engineer"


# ── Portfolio Request ───────────────────────────────────────────
class AnalyzeRequest(BaseModel):
    report_id: str
    job_title: str = "AI Engineer"
    owner_name: str | None = None     # None이면 PDF에서 추출한 이름 사용


class GitHubRequest(BaseModel):
    report_id: str
    github_url: str                   # https://github.com/username


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
    job_title: str
    total: int
    jobs: list[JobSummary]


class TrendingSkill(BaseModel):
    rank: int
    name: str
    category: str
    frequency: int


class TrendingSkillsResponse(BaseModel):
    job_title: str
    skills: list[TrendingSkill]
    generated_at: str


class SkillSalaryItem(BaseModel):
    skill: str
    avg_salary: float
    posting_count: int
    vs_baseline_pct: float


class SalaryResponse(BaseModel):
    job_title: str
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


class GapSkillItem(BaseModel):
    skill: str
    category: str
    have_it: bool
    confidence: Literal["high", "medium", "low"] | None
    evidence: str | None
    related_skills: list[str]
    difficulty: Literal["학습 장벽 낮음", "신규 학습 필요"] | None
    job_demand: int


class SuggestionItem(BaseModel):
    target_section: str
    missing_skill: str
    original_text: str | None
    rewritten_text: str
    expected_impact: str
    priority: Literal["high", "medium", "low"]


class ReportResponse(BaseModel):
    report_id: str
    status: Literal["processing", "done", "error"]
    owner: str
    job_title: str
    match_rate: float
    have: list[GapSkillItem]
    missing: list[GapSkillItem]
    top_missing: list[str]
    suggestions: list[SuggestionItem]
    error_detail: str | None = None   # status=="error"일 때만 채워짐
    generated_at: str | None = None


class GitHubUpdateResponse(BaseModel):
    report_id: str
    skills_boosted: list[str]
    confidence_changes: dict[str, str]  # {"LangChain": "medium → high"}
    status: Literal["updated"]


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
