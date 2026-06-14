# 갭 분석 결과를 바탕으로 이력서 개선 제안을 생성하는 모듈
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal

from openai import OpenAI
from pydantic import BaseModel

from src.analysis.gap_analyzer import GapAnalysisResult, SkillGap

if TYPE_CHECKING:
    from src.analysis.salary_analyzer import SalaryAnalysisResult


class ResumeSuggestion(BaseModel):
    target_section: str
    missing_skill: str
    original_text: str | None
    rewritten_text: str
    expected_impact: str
    priority: Literal["high", "medium", "low"]


class CoachingResult(BaseModel):
    owner: str
    job_title: str
    match_rate_before: float
    match_rate_after_estimated: float
    suggestions: list[ResumeSuggestion]
    summary: str


def generate_coaching(
    gap_result: GapAnalysisResult,
    client: OpenAI,
    salary_result: SalaryAnalysisResult | None = None,
) -> CoachingResult:
    """갭 분석 → LLM 이력서 개선 제안."""
    top_missing = sorted(gap_result.missing, key=lambda s: s.job_demand, reverse=True)[:5]

    section_contexts: dict[str, str] = {}

    salary_lines = ""
    if salary_result:
        for s in salary_result.skill_impacts[:3]:
            salary_lines += (
                f"- {s.skill}: 평균 £{s.avg_salary:,.0f} "
                f"(전체 대비 {s.vs_baseline_pct:+.1f}%)\n"
            )

    prompt = _build_prompt(gap_result, top_missing, section_contexts, salary_lines)

    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = (response.choices[0].message.content or "").strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    data = json.loads(raw)
    suggestions = [ResumeSuggestion(**s) for s in data.get("suggestions", [])]

    return CoachingResult(
        owner=gap_result.owner,
        job_title=gap_result.job_title,
        match_rate_before=gap_result.match_rate,
        match_rate_after_estimated=_estimate_match_rate_after(gap_result, suggestions),
        suggestions=suggestions,
        summary=data.get("summary", ""),
    )


def _build_prompt(
    gap_result: GapAnalysisResult,
    top_missing: list[SkillGap],
    contexts: dict[str, str],
    salary_context: str,
) -> str:
    missing_lines = "\n".join([
        f"{i + 1}. {s.skill} (공고 등장 {s.job_demand}회, {s.difficulty})"
        + (f'\n   → 이력서 발췌: "{contexts[s.skill]}"' if contexts.get(s.skill) else "")
        for i, s in enumerate(top_missing)
    ])
    have_list = ", ".join(s.skill for s in gap_result.have[:5])
    # GitHub로 확인된 스킬 — 재증명 제안 불필요
    github_verified = [s.skill for s in gap_result.have if s.confidence == "high"]
    github_section = (
        f"\n[GitHub 검증 완료 — 재증명 제안 불필요]: {', '.join(github_verified)}"
        if github_verified else ""
    )
    salary_section = f"\n\n[연봉 영향 기술]\n{salary_context}" if salary_context else ""
    first_missing = top_missing[0].skill if top_missing else "기술"

    return f"""다음 갭 분석 결과를 보고 이력서 개선 제안을 생성하세요.

[현재 매칭률] {gap_result.match_rate:.0%} ({len(gap_result.have)}/{len(gap_result.have) + len(gap_result.missing)} 기술 보유)
[보유 기술] {have_list}{github_section}

[우선 보완 필요 기술]
{missing_lines}{salary_section}

각 부족 기술에 대해 이력서 개선 제안을 작성하세요.
기존 이력서 발췌가 있으면 그것을 개선하고, 없으면 새 문장을 제안하세요.

반드시 아래 JSON 형식으로만 응답하세요:
{{
  "summary": "전체 개선 방향 2-3문장",
  "suggestions": [
    {{
      "target_section": "가장 관련된 이력서 섹션명",
      "missing_skill": "{first_missing}",
      "original_text": "기존 이력서 문장 (없으면 null)",
      "rewritten_text": "개선된 문장 (해당 기술을 자연스럽게 포함)",
      "expected_impact": "이 수정이 매칭률에 미치는 효과 (1문장)",
      "priority": "high"
    }}
  ]
}}

priority 기준: high(job_demand ≥ 5), medium(3~4), low(1~2)"""


def _estimate_match_rate_after(
    gap_result: GapAnalysisResult,
    suggestions: list[ResumeSuggestion],
) -> float:
    covered = {s.missing_skill for s in suggestions}
    newly_covered = sum(1 for g in gap_result.missing if g.skill in covered)
    total = len(gap_result.have) + len(gap_result.missing)
    if total == 0:
        return 0.0
    return round((len(gap_result.have) + newly_covered) / total, 2)
