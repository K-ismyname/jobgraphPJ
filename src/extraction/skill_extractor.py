# 채용공고·이력서에서 기술스택을 LLM으로 추출하는 모듈
import json
import os
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, Field


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


# 이력서 전체를 한 번에 처리 (gpt-4o-mini 128K 컨텍스트는 현실 이력서를 모두 수용)
_RESUME_TEXT_CAP = 100_000
# 공고 섹션 잘림 상한 (현실 공고 최대 ~13K자를 넉넉히 수용 — 기존 2000/3000은 다수 공고를 잘랐음)
_POSTING_TEXT_CAP = 20_000


def _chat(client: OpenAI, prompt: str, max_tokens: int = 1024) -> str:
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.choices[0].message.content or ""
    return raw.strip().replace("```json", "").replace("```", "").strip()


# ── 이력서 기술 추출 ─────────────────────────────────────────────
def extract_skills_from_resume(
    text: str, client: OpenAI | None = None
) -> ResumeExtraction:
    """이력서 텍스트에서 섹션별 기술 추출."""
    if client is None:
        client = _get_client()

    if len(text) > _RESUME_TEXT_CAP:
        print(f"[skill_extractor] 이력서가 {len(text)}자 — 상한 {_RESUME_TEXT_CAP}자까지만 처리")
        text = text[:_RESUME_TEXT_CAP]

    prompt = f"""다음은 이력서 텍스트입니다. 섹션별로 기술 스택을 추출하세요.

이력서:
{text}

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

    return ResumeExtraction(**json.loads(_chat(client, prompt, max_tokens=4096)))


# ── 전처리된 채용공고 스킬 추출 ──────────────────────────────────────
def extract_skills_from_posting(
    job: dict, client: OpenAI | None = None
) -> dict[str, list[str]]:
    """전처리된 공고에서 required/preferred 스킬명 추출.

    Returns:
        {"required": ["Python", "RAG", ...], "preferred": ["Docker", ...]}
    """
    if client is None:
        client = _get_client()

    required_text = job.get("required_section") or job.get("bullet_section") or ""
    preferred_text = job.get("preferred_section") or ""

    if required_text:
        context_req = required_text[:_POSTING_TEXT_CAP]
        context_pref = preferred_text[:_POSTING_TEXT_CAP] if preferred_text else "(없음)"
        prompt = f"""다음 채용공고 섹션에서 기술명만 추출하세요.

공고 제목: {job.get('title', '')}

[필수 자격 요건]
{context_req}

[우대 사항]
{context_pref}

아래 JSON 형식으로만 응답하세요. 다른 텍스트 없이:
{{
  "required": ["Python", "PostgreSQL", "Docker"],
  "preferred": ["Kubernetes", "Terraform"]
}}

규칙:
- 기술명은 표준 표기로 정규화 (React.js → React, LangChain → LangChain)
- 연차·학위·소프트스킬(커뮤니케이션 등)은 제외
- 기술이 아닌 도메인 지식(금융, 의료 등)도 제외"""
    else:
        full_text = (job.get("text_clean") or "")[:_POSTING_TEXT_CAP]
        prompt = f"""다음 채용공고에서 요구하는 기술명만 추출하세요.

공고 제목: {job.get('title', '')}
내용:
{full_text}

아래 JSON 형식으로만 응답하세요. 다른 텍스트 없이:
{{
  "required": ["Python", "PostgreSQL", "Docker"],
  "preferred": ["Kubernetes", "Terraform"]
}}

규칙:
- 기술명은 표준 표기로 정규화 (React.js → React)
- 명시적 필수 조건은 required, 우대/선호는 preferred
- 연차·학위·소프트스킬·도메인 지식은 제외"""

    result = json.loads(_chat(client, prompt, max_tokens=1500))
    return {
        "required": result.get("required", []),
        "preferred": result.get("preferred", []),
    }
