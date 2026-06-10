# 채용공고·이력서에서 기술스택을 LLM으로 추출하는 모듈
import json
import os
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, Field


# ── 채용공고용 모델 ──────────────────────────────────────────────
class ExtractedSkill(BaseModel):
    raw: str = Field(description="공고에 적힌 원문 표현")
    category: Literal["language", "framework", "database", "cloud", "tool", "concept"]
    importance: Literal["required", "preferred"]


class JobSkills(BaseModel):
    job_title: str
    skills: list[ExtractedSkill]


# ── 이력서용 모델 ────────────────────────────────────────────────
class DemonstratedSkill(BaseModel):
    name: str = Field(description="정규화된 기술명")
    category: str = Field(description="language/framework/database/cloud/tool/concept")
    evidence: str = Field(description="이력서 원문 발췌 (1~2문장)")
    confidence: Literal["high", "medium", "low"]


class PortfolioSection(BaseModel):
    section_type: str = Field(description="experience/project/education/skills")
    title: str
    skills: list[DemonstratedSkill]


class ResumeExtraction(BaseModel):
    candidate_name: str
    sections: list[PortfolioSection]


def _get_client() -> OpenAI:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise EnvironmentError(
            "OPENAI_API_KEY 환경변수가 필요합니다. .env 파일을 확인하세요."
        )
    return OpenAI(api_key=key)


def _chat(client: OpenAI, prompt: str, max_tokens: int = 1024) -> str:
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.choices[0].message.content or ""
    return raw.strip().replace("```json", "").replace("```", "").strip()


# ── 채용공고 기술 추출 ───────────────────────────────────────────
def extract_skills(job: dict, client: OpenAI | None = None) -> JobSkills:
    """공고 description에서 기술스택 추출."""
    if client is None:
        client = _get_client()

    prompt = f"""다음 채용공고에서 기술 요구사항을 추출하세요.

공고 제목: {job['title']}
공고 내용:
{job['description']}

각 기술에 대해 원문 표현(raw), 카테고리(category), 중요도(importance)를 판단하세요.
반드시 아래 JSON 스키마로만 응답하고, 다른 텍스트는 출력하지 마세요.

{{
  "job_title": "공고 제목",
  "skills": [
    {{"raw": "Python", "category": "language", "importance": "required"}},
    ...
  ]
}}

category는 language/framework/database/cloud/tool/concept 중 하나.
importance는 required(필수)/preferred(우대) 중 하나."""

    return JobSkills(**json.loads(_chat(client, prompt, max_tokens=1024)))


# ── 이력서 기술 추출 ─────────────────────────────────────────────
def extract_skills_from_resume(
    text: str, client: OpenAI | None = None
) -> ResumeExtraction:
    """이력서 텍스트에서 섹션별 기술 추출."""
    if client is None:
        client = _get_client()

    prompt = f"""다음은 이력서 텍스트입니다. 섹션별로 기술 스택을 추출하세요.

이력서:
{text[:4000]}

규칙:
1. 각 프로젝트/경험을 별도 section으로 분리
2. 기술이 명시적으로 언급된 경우 confidence=high
3. 문맥상 사용했음을 알 수 있는 경우 confidence=medium
4. evidence는 이력서 원문에서 해당 기술을 사용했다는 문장을 그대로 발췌
5. 기술명은 표준 표기로 정규화 (React.js → React, 랭체인 → LangChain)

반드시 아래 JSON 형식으로만 응답하세요:
{{
  "candidate_name": "홍길동",
  "sections": [
    {{
      "section_type": "project",
      "title": "Agentic RAG 시스템",
      "skills": [
        {{
          "name": "LangGraph",
          "category": "framework",
          "evidence": "LangGraph를 활용한 멀티에이전트 파이프라인 구축",
          "confidence": "high"
        }}
      ]
    }}
  ]
}}"""

    return ResumeExtraction(**json.loads(_chat(client, prompt, max_tokens=2048)))


# ── 전처리된 채용공고 스킬 추출 ──────────────────────────────────────
def extract_skills_from_posting(
    job: dict, client: OpenAI | None = None
) -> dict[str, list[dict]]:
    """전처리된 공고에서 required/preferred 스킬 추출.

    Returns:
        {"required": [{"raw", "name", "category"}, ...], "preferred": [...]}
    """
    if client is None:
        client = _get_client()

    required_text = job.get("required_section") or ""
    preferred_text = job.get("preferred_section") or ""

    if required_text:
        context_req = required_text[:2000]
        context_pref = preferred_text[:800] if preferred_text else "(없음)"
        prompt = f"""다음 채용공고 섹션에서 기술스택을 추출하세요.

공고 제목: {job.get('title', '')}

[필수 자격 요건]
{context_req}

[우대 사항]
{context_pref}

아래 JSON 형식으로만 응답하세요. 다른 텍스트 없이:
{{
  "required": [
    {{"raw": "Python 3.x", "name": "Python", "category": "language"}}
  ],
  "preferred": [
    {{"raw": "MLflow experience", "name": "MLflow", "category": "tool"}}
  ]
}}

규칙:
- name: 표준 기술명 (React.js → React, PyTorch → PyTorch)
- category: language / framework / database / cloud / tool / concept 중 하나
- 기술이 아닌 연차·학위 조건은 제외"""
    else:
        full_text = (job.get("text_clean") or job.get("description") or "")[:3000]
        prompt = f"""다음 채용공고에서 기술 요구사항을 추출하세요.

공고 제목: {job.get('title', '')}
내용:
{full_text}

아래 JSON 형식으로만 응답하세요. 다른 텍스트 없이:
{{
  "required": [
    {{"raw": "Python 3.x", "name": "Python", "category": "language"}}
  ],
  "preferred": [
    {{"raw": "Docker experience", "name": "Docker", "category": "tool"}}
  ]
}}

규칙:
- name: 표준 기술명 (React.js → React, PyTorch → PyTorch)
- category: language / framework / database / cloud / tool / concept 중 하나
- 명시적 필수 조건은 required, 우대/선호는 preferred
- 기술이 아닌 연차·학위 조건은 제외"""

    result = json.loads(_chat(client, prompt, max_tokens=1200))
    return {
        "required": result.get("required", []),
        "preferred": result.get("preferred", []),
    }
