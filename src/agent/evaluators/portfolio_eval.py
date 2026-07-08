# 포트폴리오 PDF 전체를 분석하는 평가자 — 텍스트 페이지는 텍스트로, 이미지 페이지는 vision으로 (멀티모달)
#
# 이 파일이 하는 일: 4개 병렬 평가자 중 "멀티모달"이라는 CLAUDE.md 표현이 실제로 구현된 곳.
# 포트폴리오 PDF는 이력서와 달리 다이어그램·스크린샷처럼 텍스트로 뽑을 수 없는 페이지가 섞여 있을 수 있음.
# 이 파일은 페이지마다 "텍스트가 충분한가"를 먼저 판단해서, 충분하면 텍스트로만, 부족하면
# 페이지를 이미지로 렌더링해서 vision(이미지를 보는 LLM) 모델에게 보여주는 이원화된 파이프라인을 돈다.

from __future__ import annotations

import base64   # 이미지 바이트를 텍스트로 인코딩 — OpenAI vision API는 이미지를 base64 문자열로 받음
import json
import logging
import time
from typing import TYPE_CHECKING, Callable

from src.extraction.normalizer import normalize_skill

if TYPE_CHECKING:
    from src.agent.state import AppState

logger = logging.getLogger("jobgraph.agent")

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
# 텍스트 프롬프트와 vision 프롬프트가 거의 동일한 구조 — 유일한 차이는 vision 쪽에 "where"(text/diagram/
# screenshot 구분) 필드가 추가된 것. 이미지는 근거의 출처가 다양해서(순수 텍스트/다이어그램 라벨/스크린샷)
# 그걸 구분해서 남겨두면 나중에 "이게 정말 코드 스크린샷인지 그냥 텍스트 설명인지" 신뢰도 판단에 쓸 수 있음


def _extract_page_texts(path: str) -> list[str]:
    """pdfplumber로 페이지별 텍스트를 추출한다 (이미지 페이지는 빈 문자열)."""
    import pdfplumber
    # CLAUDE.md 확정 스택의 PDF 파싱 라이브러리 — "레이아웃 보존, 표 추출 안정적"이라 선택된 그 도구

    with pdfplumber.open(path) as pdf:
        return [(page.extract_text() or "") for page in pdf.pages]
        # 페이지마다 텍스트를 추출 — 순수 이미지(스캔본, 다이어그램)로만 된 페이지는 extract_text()가
        # None을 반환할 수 있어서 "or \"\"" 로 빈 문자열로 방어. 리스트 인덱스 = 페이지 번호(0부터)


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
            # 80자 이상 텍스트가 뽑히면 "이 페이지는 진짜 텍스트 페이지"로 보고 누적
        else:
            image_pages.append(i)
            # 80자 미만이면 "이 페이지는 이미지/다이어그램 위주"로 보고 인덱스만 따로 저장
            # (판단 기준이 "글자 수"라는 단순한 휴리스틱 — 완벽하진 않지만 저비용으로 90% 상황을 커버)
    return "\n\n".join(text_parts), image_pages
    # 텍스트 페이지들은 전부 하나로 합쳐서(한 번의 LLM 호출로 처리), 이미지 페이지는 인덱스만 반환


def _render_pages(path: str, indices: list[int]) -> list[bytes]:
    """지정한 페이지 인덱스들을 PNG 바이트로 렌더한다 (PyMuPDF, dpi=220)."""
    import fitz  # PyMuPDF
    # pdfplumber는 텍스트 추출용이고, PyMuPDF(fitz)는 페이지를 "이미지로 그려내는"(렌더링) 용도로 따로 씀
    # 두 라이브러리가 잘하는 일이 다르므로 목적에 맞게 각각 사용

    doc = fitz.open(path)
    try:
        wanted = set(indices)   # 리스트보다 in 검사가 빠른 집합으로 변환
        return [page.get_pixmap(dpi=220).tobytes("png")
                for i, page in enumerate(doc) if i in wanted]
        # get_pixmap(dpi=220) → 그 페이지를 220 DPI 해상도의 이미지로 렌더링 (해상도가 높을수록
        # 텍스트가 선명해지지만 파일 크기·API 전송 비용도 늘어남 — 220은 그 균형점으로 선택된 값)
        # .tobytes("png") → 렌더링 결과를 PNG 형식의 바이트로 변환
    finally:
        doc.close()
        # try/finally — 리스트를 만드는 도중 에러가 나도 파일 핸들은 반드시 닫히게 보장


def _skills_from_vision(data: dict) -> list[dict]:
    """LLM JSON 응답(텍스트·vision 공통)을 평가자 계약 형식으로 변환한다."""
    # 이름은 "vision"이지만 실제로는 텍스트 응답 파싱에도 재사용됨(공통 변환기) — _TEXT_PROMPT와
    # _VISION_PROMPT의 응답 스키마가 거의 같아서 하나의 변환 함수로 처리 가능
    skills: list[dict] = []
    for item in data.get("skills", []):
        if not isinstance(item, dict) or not item.get("skill"):
            continue
        where = item.get("where", "")
        ev = item.get("evidence", "")
        evidence = f"[포트폴리오/{where}] {ev}".strip() if where else ev
        # where가 있으면 "[포트폴리오/diagram] 근거텍스트" 형태로, 없으면(텍스트 프롬프트 응답) 그냥 근거만
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
            # fn은 인자 없는 함수(클로저) — 호출부에서 lambda로 감싸서 넘겨줌. 성공하면 여기서 즉시 반환
        except Exception as e:
            if attempt == max_retries - 1:
                raise
                # 마지막 시도(attempt가 max_retries-1)에서도 실패하면, 더 재시도하지 않고 예외를 그대로 다시 던짐
            wait = base_wait * (2 ** attempt)
            # 지수 백오프: 시도할 때마다 대기 시간이 2배씩 늘어남 (2초 → 4초 → 8초 → ...)
            # rate limit(요청이 너무 잦다는 에러)에 걸렸을 때, 바로 재시도하면 또 걸릴 확률이 높아서
            # 점점 더 오래 기다리며 재시도하는 게 표준적인 대응 방식
            logger.warning(f"[portfolio_eval] 재시도 {attempt + 1}/{max_retries - 1} ({wait:.0f}초 대기): {e}")
            time.sleep(wait)
    # skill_extractor.py의 _chat_json()도 재시도 로직이 있었지만 거긴 "최대 2회, 고정" 방식이었고,
    # 여긴 "최대 4회, 지수 백오프"로 더 정교함 — vision API 호출이 이미지 데이터 때문에 더 무겁고
    # rate limit에 걸리기 쉬워서 재시도 전략을 더 신경 써서 짠 것으로 보임


def _merge_skills(all_skills: list[dict]) -> list[dict]:
    """정규화명 기준 중복 제거 (첫 등장 유지)."""
    seen: set[str] = set()
    merged: list[dict] = []
    for s in all_skills:
        key = normalize_skill(s["skill"])
        # 중복 판단 기준을 원본 스킬명이 아니라 "정규화된 이름"으로 함 —
        # "React"와 "react.js"가 서로 다른 텍스트/이미지 페이지에서 각각 발견돼도 같은 스킬로 인식하고 하나만 남김
        if key in seen:
            continue
        seen.add(key)
        merged.append(s)
    return merged


def _parse(raw: str) -> dict:
    """LLM 텍스트 응답에서 JSON을 파싱한다 (코드펜스 제거)."""
    raw = (raw or "").strip().replace("```json", "").replace("```", "").strip()
    return json.loads(raw)
    # CLAUDE.md 코드 컨벤션에 명시된 "LLM 응답은 항상 JSON 펜스 제거 후 파싱" 규칙이 그대로 구현된 부분


def create_portfolio_evaluator(openai_client) -> Callable[["AppState"], dict]:
    """포트폴리오 평가자 팩토리. 전체 페이지를 보되 텍스트는 텍스트로, 이미지는 vision으로 분석한다."""
    def evaluate(state: "AppState") -> dict:
        path = state.get("portfolio_path")
        if not path:
            return {"portfolio_eval": {"skills": []}}
            # 포트폴리오를 안 줬으면 조기 반환 — 다른 평가자들과 동일한 패턴
        try:
            page_texts = _extract_page_texts(path)
        except Exception as e:
            logger.warning(f"[portfolio_eval] PDF 열기 실패: {e}")
            return {"portfolio_eval": {"skills": []}}

        text_blob, image_pages = _partition_pages(page_texts)
        all_skills: list[dict] = []

        # ── 텍스트 페이지 전체 → 한 번의 텍스트 호출 ──
        if text_blob.strip():
            try:
                resp = _call_with_retry(lambda: openai_client.chat.completions.create(
                    model=_MODEL, temperature=0, max_tokens=2048,
                    response_format={"type": "json_object"},
                    messages=[{"role": "user", "content": _TEXT_PROMPT.format(text=text_blob[:30000])}],
                ))
                # 텍스트 페이지가 몇 장이든, 다 합쳐서 LLM 호출은 딱 한 번만 — 페이지마다 호출하면
                # 비용·시간이 페이지 수에 비례해 늘어나므로, 텍스트는 통째로 넘기는 게 효율적
                all_skills += _skills_from_vision(_parse(resp.choices[0].message.content))
            except Exception as e:
                logger.warning(f"[portfolio_eval] 텍스트 분석 실패: {e}")
                # 텍스트 분석이 실패해도 아래 이미지 분석은 계속 진행 (부분 실패 허용)

        # ── 이미지 페이지 → 페이지별 vision (상한) ──
        capped = image_pages[:_MAX_VISION_PAGES]
        # 이미지 페이지는 텍스트와 달리 "한 번에 다 몰아서" 처리할 수 없음 — vision API는 페이지별로
        # 개별 호출해야 하므로, 상한(25장)을 둬서 포트폴리오가 아주 길어도 비용이 무한정 늘지 않게 방어
        if capped:
            try:
                images = _render_pages(path, capped)
            except Exception as e:
                logger.warning(f"[portfolio_eval] 이미지 렌더 실패: {e}")
                images = []
            for img in images:
                b64 = base64.b64encode(img).decode()
                # PNG 바이트를 base64 문자열로 인코딩 — OpenAI vision API가 이미지를 이 형식으로 받음
                try:
                    resp = _call_with_retry(lambda b=b64: openai_client.chat.completions.create(
                        model=_MODEL, temperature=0, max_tokens=1500,
                        response_format={"type": "json_object"},
                        messages=[{"role": "user", "content": [
                            {"type": "text", "text": _VISION_PROMPT},
                            {"type": "image_url",
                             "image_url": {"url": f"data:image/png;base64,{b}", "detail": "high"}},
                        ]}],
                    ))
                    # messages의 content가 리스트인 게 핵심 — 텍스트 프롬프트와 이미지를 함께 담아 보내는
                    # 멀티모달 메시지 형식. "data:image/png;base64,{b}"는 이미지를 URL이 아니라 데이터 자체를
                    # 담아 보내는 표준 방식(data URI). detail="high"는 이미지를 더 정밀하게 분석하라는 옵션
                    # (lambda b=b64: ...) — for 루프 안에서 lambda를 쓸 때 흔한 함정을 피하는 관용구:
                    # 그냥 "lambda: ...b64..."라고 쓰면 루프가 다 돈 뒤 lambda가 실행될 때 b64가
                    # "마지막 루프의 값"으로 고정될 위험이 있어서, 기본값(b=b64)으로 그 시점의 값을 강제로 붙잡아둠
                    all_skills += _skills_from_vision(_parse(resp.choices[0].message.content))
                except Exception as e:
                    logger.warning(f"[portfolio_eval] 이미지 페이지 분석 실패: {e}")
                    # 이미지 한 장이 실패해도 나머지 이미지들은 계속 처리 (반복문 안의 개별 실패 격리)
        if len(image_pages) > _MAX_VISION_PAGES:
            logger.warning(f"[portfolio_eval] vision 상한 {_MAX_VISION_PAGES} 초과 — "
                  f"{len(image_pages) - _MAX_VISION_PAGES}장 미분석")
            # 상한을 넘어서 분석 안 된 페이지가 있다는 사실을 로그로 명시 — 조용히 누락시키지 않고 흔적을 남김

        return {"portfolio_eval": {"skills": _merge_skills(all_skills)}}

    return evaluate
