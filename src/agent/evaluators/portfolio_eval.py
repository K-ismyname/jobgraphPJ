# 포트폴리오 PDF 전체를 분석하는 평가자 — 텍스트 페이지는 텍스트로, 이미지 페이지는 vision으로 (멀티모달)
from __future__ import annotations

import base64
import json
import time
from typing import TYPE_CHECKING, Callable

from src.extraction.normalizer import normalize_skill

if TYPE_CHECKING:
    from src.agent.state import AppState

_MODEL = "gpt-4o-mini"          # 텍스트·vision 모두 gpt-4o-mini (vision 지원)
_MAX_VISION_PAGES = 25          # 이미지 페이지 vision 안전 상한 (텍스트 페이지는 무제한)
_MIN_TEXT_CHARS = 80            # 이 이상 텍스트면 텍스트 페이지로 간주 (미만은 이미지로 vision)
_MAX_RETRIES = 4                # rate limit 포함 재시도 횟수
_RETRY_BASE = 2                 # 지수 백오프 초기 대기(초)

_TEXT_PROMPT = """다음은 포트폴리오에서 추출한 텍스트입니다. 지원자가 실제로 사용/구현한 기술 스킬을 추출하세요.

{text}

아래 JSON만 출력하세요 (코드펜스 없이):
{{"skills": [{{"skill": "LangGraph", "evidence": "멀티에이전트 RAG 파이프라인 구축", "where": "text", "usage_pattern": "StateGraph로 에이전트 노드 구성 및 조건 분기 구현", "depth": "중급"}}]}}

규칙:
- 실제 사용/구현 근거가 있는 기술만. 추측 금지.
- usage_pattern: 이 기술로 구체적으로 무엇을 어떻게 했는지 (없으면 null).
- depth: "기초" | "중급" | "고급" — 포트폴리오 근거 기반, 판단 불가하면 null.
- 연차·학위·소프트스킬·도메인 지식 제외."""

_VISION_PROMPT = """이 포트폴리오 페이지(이미지)에서 지원자가 실제로 사용/구현한 기술 스킬을 추출하세요.
다이어그램의 박스·화살표·라벨, 스크린샷, 이미지 속 텍스트를 모두 근거로 보세요.

아래 JSON만 출력하세요 (코드펜스 없이):
{"skills": [{"skill": "LangGraph", "evidence": "멀티에이전트 RAG 다이어그램에 StateGraph 노드", "where": "diagram", "usage_pattern": "StateGraph로 병렬 평가자 fan-out 구현", "depth": "고급"}]}

규칙:
- 실제 사용/구현 근거가 페이지에 있는 기술만. 추측 금지.
- where: text/diagram/screenshot 중 근거 출처.
- usage_pattern: 이 기술로 구체적으로 무엇을 어떻게 했는지 (없으면 null).
- depth: "기초" | "중급" | "고급" — 페이지 근거 기반, 판단 불가하면 null.
- 연차·학위·소프트스킬·도메인 지식 제외."""


def _extract_page_texts(path: str) -> list[str]:
    """pdfplumber로 페이지별 텍스트를 추출한다 (이미지 페이지는 빈 문자열)."""
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        return [(page.extract_text() or "") for page in pdf.pages]


def _partition_pages(page_texts: list[str]) -> tuple[str, list[int]]:
    """페이지를 텍스트/이미지로 분류한다.

    텍스트 충분(>=_MIN_TEXT_CHARS) → 텍스트 누적(하나로 합침),
    빈약/공백 → vision 대상 페이지 인덱스 목록.
    """
    text_parts: list[str] = []
    image_pages: list[int] = []
    for i, t in enumerate(page_texts):
        stripped = (t or "").strip()
        if len(stripped) >= _MIN_TEXT_CHARS:
            text_parts.append(stripped)
        else:
            image_pages.append(i)
    return "\n\n".join(text_parts), image_pages


def _render_pages(path: str, indices: list[int]) -> list[bytes]:
    """지정한 페이지 인덱스들을 PNG 바이트로 렌더한다 (PyMuPDF, dpi=220)."""
    import fitz  # PyMuPDF

    doc = fitz.open(path)
    try:
        wanted = set(indices)
        return [page.get_pixmap(dpi=220).tobytes("png")
                for i, page in enumerate(doc) if i in wanted]
    finally:
        doc.close()


def _skills_from_vision(data: dict) -> list[dict]:
    """LLM JSON 응답(텍스트·vision 공통)을 평가자 계약 형식으로 변환한다."""
    skills: list[dict] = []
    for item in data.get("skills", []):
        if not isinstance(item, dict) or not item.get("skill"):
            continue
        where = item.get("where", "")
        ev = item.get("evidence", "")
        evidence = f"[포트폴리오/{where}] {ev}".strip() if where else ev
        skills.append({
            "skill": item["skill"],
            "evidence": evidence,
            "source": "portfolio",
            "level_hint": None,
            "usage_pattern": item.get("usage_pattern"),  # 어떻게 썼는지
            "depth": item.get("depth"),                  # 기초/중급/고급
        })
    return skills


def _call_with_retry(fn, max_retries: int = _MAX_RETRIES, base_wait: float = _RETRY_BASE):
    """API 호출 실패(rate limit 포함) 시 지수 백오프로 재시도한다."""
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            wait = base_wait * (2 ** attempt)
            print(f"[portfolio_eval] 재시도 {attempt + 1}/{max_retries - 1} ({wait:.0f}초 대기): {e}")
            time.sleep(wait)


def _merge_skills(all_skills: list[dict]) -> list[dict]:
    """정규화명 기준 중복 제거 (첫 등장 유지)."""
    seen: set[str] = set()
    merged: list[dict] = []
    for s in all_skills:
        key = normalize_skill(s["skill"])
        if key in seen:
            continue
        seen.add(key)
        merged.append(s)
    return merged


def _parse(raw: str) -> dict:
    """LLM 텍스트 응답에서 JSON을 파싱한다 (코드펜스 제거)."""
    raw = (raw or "").strip().replace("```json", "").replace("```", "").strip()
    return json.loads(raw)


def create_portfolio_evaluator(openai_client) -> Callable[["AppState"], dict]:
    """포트폴리오 평가자 팩토리. 전체 페이지를 보되 텍스트는 텍스트로, 이미지는 vision으로 분석한다."""
    def evaluate(state: "AppState") -> dict:
        path = state.get("portfolio_path")
        if not path:
            return {"portfolio_eval": {"skills": []}}
        try:
            page_texts = _extract_page_texts(path)
        except Exception as e:
            print(f"[portfolio_eval] PDF 열기 실패: {e}")
            return {"portfolio_eval": {"skills": []}}

        text_blob, image_pages = _partition_pages(page_texts)
        all_skills: list[dict] = []

        # 텍스트 페이지 전체 → 한 번의 텍스트 호출
        if text_blob.strip():
            try:
                resp = _call_with_retry(lambda: openai_client.chat.completions.create(
                    model=_MODEL, temperature=0, max_tokens=2048,
                    messages=[{"role": "user", "content": _TEXT_PROMPT.format(text=text_blob[:30000])}],
                ))
                all_skills += _skills_from_vision(_parse(resp.choices[0].message.content))
            except Exception as e:
                print(f"[portfolio_eval] 텍스트 분석 실패: {e}")

        # 이미지 페이지 → 페이지별 vision (상한)
        capped = image_pages[:_MAX_VISION_PAGES]
        if capped:
            try:
                images = _render_pages(path, capped)
            except Exception as e:
                print(f"[portfolio_eval] 이미지 렌더 실패: {e}")
                images = []
            for img in images:
                b64 = base64.b64encode(img).decode()
                try:
                    resp = _call_with_retry(lambda b=b64: openai_client.chat.completions.create(
                        model=_MODEL, temperature=0, max_tokens=1500,
                        messages=[{"role": "user", "content": [
                            {"type": "text", "text": _VISION_PROMPT},
                            {"type": "image_url",
                             "image_url": {"url": f"data:image/png;base64,{b}", "detail": "high"}},
                        ]}],
                    ))
                    all_skills += _skills_from_vision(_parse(resp.choices[0].message.content))
                except Exception as e:
                    print(f"[portfolio_eval] 이미지 페이지 분석 실패: {e}")
        if len(image_pages) > _MAX_VISION_PAGES:
            print(f"[portfolio_eval] vision 상한 {_MAX_VISION_PAGES} 초과 — "
                  f"{len(image_pages) - _MAX_VISION_PAGES}장 미분석")

        return {"portfolio_eval": {"skills": _merge_skills(all_skills)}}

    return evaluate
