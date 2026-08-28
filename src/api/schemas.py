# API 요청·응답에 사용하는 모든 Pydantic 모델
#
# 한 줄 요약: 이 서버가 "무엇을 받고 무엇을 돌려주는지"를 전부 미리 정해둔 명세서 같은 파일.
# 실제 로직은 하나도 없고, 전부 "이 데이터는 이런 필드와 타입을 가져야 한다"는 틀만 있음 —
# state.py가 LangGraph의 "데이터 모양"을 정의했던 것과 똑같은 역할을, 이번엔 API 레이어에서 함.

from __future__ import annotations

from typing import Annotated, Literal
# Literal["a", "b", "c"] → "이 값은 반드시 a, b, c 중 하나여야 한다"는 제한된 타입.
# 그냥 str이라고 하면 아무 문자열이나 다 되지만, Literal은 오타나 잘못된 값이 들어오는 걸 미리 막아줌.

from pydantic import BaseModel, Field
# BaseModel — skill_extractor.py에서 이미 본 그 pydantic 기본 클래스.
# Field — 필드에 "기본값 + 추가 규칙"(최솟값, 최댓값 등)을 같이 지정할 때 쓰는 도구.

BoundedUrlString = Annotated[str, Field(min_length=1, max_length=500)]


# ── Jobs Request ────────────────────────────────────────────────
# 이 아래 클래스들은 jobs.py 라우터가 "URL 쿼리 파라미터"를 받을 때 쓰는 모양들.
# 예: GET /jobs?job_family=Data+Engineer&days=7 → 이 값들이 자동으로 JobsQuery 객체로 채워짐

class JobsQuery(BaseModel):
    job_family: str = "AI/LLM Engineer"   # 유효 직군명 (Neo4j JobFamily)
    # = "AI/LLM Engineer" → 사용자가 job_family를 안 주면 이 기본값이 자동으로 쓰임
    skills: list[str] | None = None   # 이 기술을 필수로 하는 공고만
    days: int = Field(30, ge=1, le=365)
    # Field(30, ge=1, le=365) → 기본값은 30, 그런데 "ge=1"(1 이상), "le=365"(365 이하)라는
    # 조건도 같이 검사함. 사용자가 days=-5나 days=10000 같은 이상한 값을 보내면
    # FastAPI가 자동으로 "잘못된 요청"이라고 거절해줌 (라우터 코드가 직접 검사 안 해도 됨)


class TrendingSkillsQuery(BaseModel):
    job_family: str = "AI/LLM Engineer"   # 유효 직군명 (Neo4j JobFamily)
    top_n: int = Field(10, ge=1, le=50)


class SalaryQuery(BaseModel):
    job_family: str = "AI/LLM Engineer"   # 유효 직군명 (Neo4j JobFamily)


# ── Portfolio Request ───────────────────────────────────────────
class AnalyzeRequest(BaseModel):
    # 이건 URL 쿼리가 아니라, POST 요청의 "본문"(body)으로 받는 모양 — portfolio.py의
    # analyze_portfolio(req: AnalyzeRequest)에서 req가 바로 이 모양으로 자동 채워짐
    report_id: str = Field(min_length=1, max_length=80)
    job_family: str = Field("AI/LLM Engineer", min_length=1, max_length=80)   # 유효 직군명 (Neo4j JobFamily)
    owner_name: str | None = Field(default=None, max_length=80)         # None이면 PDF에서 추출한 이름 사용
    github_urls: list[BoundedUrlString] = Field(default_factory=list, max_length=5)   # 선택 — 코드 검증 (여러 개)
    deploy_urls: list[BoundedUrlString] = Field(default_factory=list, max_length=5)   # 선택 — 작동 실증 (여러 개)
    # Field(default_factory=list) → 기본값이 빈 리스트([])라는 뜻.
    # langfuse_tracer.py에서 이미 봤듯이, 리스트나 딕셔너리 같은 "바뀔 수 있는" 기본값은
    # 그냥 "= []"라고 못 쓰고 이렇게 default_factory로 써야 하는 게 파이썬의 규칙.
    portfolio_report_id: str | None = Field(default=None, max_length=80)  # 선택 — 포트폴리오 PDF 업로드 ID
    access_key: str = Field("", max_length=200)                    # 관리자 분석 키 (env ACCESS_KEY 설정 시 필수)


# ── Jobs Response ───────────────────────────────────────────────
# 여기부터는 "서버가 브라우저에게 돌려주는 응답"의 모양들

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
    # jobs.py의 list_jobs()가 Neo4j 조회 결과를 이 모양으로 하나씩 바꿔서 반환하던 것 — 지난번에 본 그 코드


class JobsResponse(BaseModel):
    job_family: str
    total: int
    jobs: list[JobSummary]
    # JobSummary 여러 개를 담은 "최종 응답 봉투" — total은 몇 개가 왔는지 미리 알려줘서
    # 프론트엔드가 "총 42개 공고" 같은 걸 바로 보여줄 수 있게 함


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
    # salary_analyzer.py의 SkillSalaryImpact(내부 계산용)와 필드가 거의 똑같은데,
    # 이건 API 응답 전용으로 따로 만든 클래스 — jobs.py에서 설명했던 "레이어 분리" 그 지점


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
    # status가 "uploaded"라는 딱 한 가지 값만 되게 정해둔 것 — 이 응답은 항상 "업로드 성공"일 때만
    # 오는 거라 다른 상태가 될 일이 없다는 걸 타입으로도 명확히 드러냄


class PortfolioUploadResponse(BaseModel):
    portfolio_report_id: str
    page_count: int
    status: Literal["uploaded"]


class AnalyzeAccepted(BaseModel):
    report_id: str
    status: Literal["processing"]
    message: str = "분석을 시작합니다. GET /portfolio/report/{report_id}로 결과를 확인하세요."
    # /analyze API가 "접수했다"고 바로 돌려주는 응답 모양 — portfolio.py에서 본 그 폴링 흐름의 시작점


class ProjectSuggestion(BaseModel):
    repo: str = ""
    add_skill: str
    why: str
    how: str
    # coach_agent(nodes.py)가 만든 project_suggestions 항목 하나를 표현 — 필드 이름이 그때 본
    # {"repo": ..., "add_skill": ..., "why": ..., "how": ...} 그 형태와 그대로 일치함


class LearningRecommendation(BaseModel):
    skill: str
    reason: str          # ④ 설명 — 왜 필요한지 (직군 요구 근거 + 보유 스킬 연결)
    how: str = ""        # ⑤ 학습 코칭 — structure_summary 기반 프로젝트 단위 학습 방향


class VerificationItem(BaseModel):
    skill: str
    verification: Literal["Verified", "Corroborated", "Claimed"]
    # consensus.py의 build_consensus()/expand_umbrella_skills()는 이 세 문자열만 만들어내는
    # 결정적 코드라서 (LLM 자유 출력이 아님), InterviewCoaching.type처럼 별도 방어 함수 없이도
    # 안전하게 Literal로 좁힐 수 있음 — 오타나 새로운 값이 실수로 들어오면 여기서 바로 걸러짐
    sources: list[str]


class RecommendedPosting(BaseModel):
    title: str
    company: str = ""
    url: str = ""
    job_family: str = ""
    match_pct: float = 0.0          # 보유 스킬 대비 매칭률 %
    # neo4j.recommend_job_postings()(neo4j_client.py)가 반환하는 dict와 필드가 대응됨


class InterviewCoaching(BaseModel):
    type: Literal["strength", "gap"]
    # portfolio.py의 _coach_type() 함수가 "이 값이 strength나 gap이 아니면 강제로 strength로
    # 바꾼다"고 방어하던 게 바로 이 Literal 제약 때문 — 여기 안 맞는 값이 그냥 들어가면
    # pydantic이 에러를 내서 리포트 전체가 실패하니, 미리 코드에서 걸러줘야 했던 것
    title: str
    coaching: str


class ProjectUnderstanding(BaseModel):
    one_liner: str = ""
    architecture: str = ""
    data_flow: str = ""
    core_design_choices: list[str] = Field(default_factory=list)


class EvidenceCard(BaseModel):
    skill: str
    evidence: str = ""
    what_it_shows: str = ""
    interview_angle: str = ""


class RoadmapStep(BaseModel):
    step: str = ""
    why: str = ""
    how: str = ""


class ProjectBrief(BaseModel):
    repo: str = ""
    readme_summary: str = ""
    architecture: str = ""
    code_structure: str = ""
    confirmed_stack: list[str] = Field(default_factory=list)
    key_files: list[str] = Field(default_factory=list)
    coaching_angles: list[str] = Field(default_factory=list)


class ReportResponse(BaseModel):
    # 이 프로젝트 전체에서 제일 큰 응답 모양 — Layer 1~5의 결과가 전부 여기 한곳에 모임
    report_id: str
    status: Literal["processing", "done", "error"]
    # 폴링(portfolio.py의 get_report)이 보고 판단하는 그 3가지 상태값
    phase: str | None = None   # 진행 중 현재 단계 (status=processing일 때만 의미)
    # portfolio.py의 _NODE_PHASE 표에서 나온 "소스 평가 중" 같은 문구가 여기 들어감
    started_at: str | None = None
    # 분석 시작 시각(ISO). 백그라운드 작업이 프로세스 재시작 등으로 유실되면 status가
    # "processing"에 영원히 머물러 프론트가 무한 폴링하므로, 조회 시점에 이 값으로
    # 경과 시간을 재서 너무 오래된 건 error로 강등한다 (portfolio.py의 get_report 참고).
    owner: str
    job_family: str
    match_rate: float = 0.0
    confidence_level: str | None = None
    advice: str | None = None
    verification_counts: dict[str, int] = Field(default_factory=dict)
    verified_skills: list[VerificationItem] = Field(default_factory=list)
    coaching_summary: str | None = None
    project_suggestions: list[ProjectSuggestion] = Field(default_factory=list)
    learning_recommendations: list[LearningRecommendation] = Field(default_factory=list)
    interview_coaching: list[InterviewCoaching] = Field(default_factory=list)
    project_understanding: ProjectUnderstanding | None = None
    evidence_cards: list[EvidenceCard] = Field(default_factory=list)
    project_roadmap: list[RoadmapStep] = Field(default_factory=list)
    portfolio_sentences: list[str] = Field(default_factory=list)
    project_briefs: list[ProjectBrief] = Field(default_factory=list)
    error_detail: str | None = None
    generated_at: str | None = None
    trace: dict | None = None
    # nodes.py의 _build_trace()가 만든 그 관측용 데이터 — 타입이 그냥 dict라서
    # 안에 정확히 어떤 필드가 있는지는 여기 스키마만 봐서는 알 수 없음 (자유로운 형태로 남겨둔 것)
    capability_fit: dict | None = None
    common_skill_fit: dict | None = None
    # capability.py의 skill_fit()이 반환하던 그 dict — 이것도 세부 모양은 정해두지 않고 자유롭게 둠
    recommended_families: list[dict] = Field(default_factory=list)
    recommended_postings: list[RecommendedPosting] = Field(default_factory=list)
