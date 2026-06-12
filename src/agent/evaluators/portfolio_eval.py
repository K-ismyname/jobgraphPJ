# 포트폴리오 PDF를 vision으로 분석해 프로젝트 스킬 증거를 추출하는 평가자 (멀티모달 modality)
from __future__ import annotations

import base64
import json
from typing import TYPE_CHECKING, Callable

from src.extraction.normalizer import normalize_skill

if TYPE_CHECKING:
    from src.agent.state import AppState

_VISION_MODEL = "gpt-4o-mini"
_MAX_PAGES = 8

_VISION_PROMPT = """이 포트폴리오 페이지(이미지)에서 지원자가 실제로 사용/구현한 기술 스킬을 추출하세요.
다이어그램의 박스·화살표·라벨, 스크린샷, 본문 텍스트를 모두 근거로 보세요.
보조 텍스트(있으면):
{page_text}

아래 JSON만 출력하세요 (코드펜스 없이):
{{"skills": [{{"skill": "LangGraph", "evidence": "멀티에이전트 RAG 다이어그램에 StateGraph 노드", "where": "diagram"}}]}}

규칙:
- 실제 사용/구현 근거가 페이지에 있는 기술만. 추측 금지.
- where 는 text/diagram/screenshot 중 근거가 나온 곳.
- 연차·학위·소프트스킬·도메인 지식 제외."""


def _render_pdf_pages(path: str, max_pages: int) -> list[bytes]:
    """PDF 앞 max_pages 페이지를 PNG 바이트로 렌더한다 (PyMuPDF, poppler 의존성 없음)."""
    import fitz  # PyMuPDF

    doc = fitz.open(path)
    try:
        pages: list[bytes] = []
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pix = page.get_pixmap(dpi=220)
            pages.append(pix.tobytes("png"))
        return pages
    finally:
        doc.close()


def _page_texts(path: str, n: int) -> list[str]:
    """pdfplumber로 페이지별 보조 텍스트 (실패 시 빈 문자열)."""
    try:
        import pdfplumber

        texts: list[str] = []
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages):
                if i >= n:
                    break
                texts.append(page.extract_text() or "")
        return texts
    except Exception as e:
        print(f"[portfolio_eval] 텍스트 추출 실패: {e}")
        return [""] * n


def _skills_from_vision(data: dict) -> list[dict]:
    """vision JSON 응답을 평가자 계약 형식으로 변환한다."""
    skills: list[dict] = []
    for item in data.get("skills", []):
        if not isinstance(item, dict) or not item.get("skill"):
            continue
        where = item.get("where", "")
        ev = item.get("evidence", "")
        evidence = f"[포트폴리오/{where}] {ev}".strip() if where else ev
        skills.append({"skill": item["skill"], "evidence": evidence,
                       "source": "portfolio", "level_hint": None})
    return skills


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


def create_portfolio_evaluator(openai_client) -> Callable[["AppState"], dict]:
    """포트폴리오 평가자 팩토리. PDF 페이지를 vision으로 분석해 스킬 증거를 추출한다."""
    def evaluate(state: "AppState") -> dict:
        path = state.get("portfolio_path")
        if not path:
            return {"portfolio_eval": {"skills": []}}
        try:
            images = _render_pdf_pages(path, _MAX_PAGES)
        except Exception as e:
            print(f"[portfolio_eval] PDF 렌더 실패: {e}")
            return {"portfolio_eval": {"skills": []}}

        texts = _page_texts(path, len(images))
        all_skills: list[dict] = []
        for i, img in enumerate(images):
            b64 = base64.b64encode(img).decode()
            page_text = (texts[i] if i < len(texts) else "")[:2000]
            try:
                resp = openai_client.chat.completions.create(
                    model=_VISION_MODEL, temperature=0, max_tokens=1500,
                    messages=[{"role": "user", "content": [
                        {"type": "text", "text": _VISION_PROMPT.format(page_text=page_text)},
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "high"}},
                    ]}],
                )
                raw = (resp.choices[0].message.content or "").strip()
                raw = raw.replace("```json", "").replace("```", "").strip()
                all_skills += _skills_from_vision(json.loads(raw))
            except Exception as e:
                print(f"[portfolio_eval] {i + 1}페이지 분석 실패: {e}")
        return {"portfolio_eval": {"skills": _merge_skills(all_skills)}}

    return evaluate
