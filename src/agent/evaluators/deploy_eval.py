# 배포 URL을 fetch해 작동 실증 + 프론트 기술을 추출하는 평가자 (웹 modality)
#
# 이 파일이 하는 일: 4개 평가자 중 가장 단순하다. 사용자가 준 배포 URL(실제 서비스 주소)에
# HTTP 요청을 보내서, 응답이 오면(=배포가 실제로 작동한다는 실증) HTML 본문과 응답 헤더를
# 텍스트로 합쳐 직군 스킬 키워드가 있는지 매칭한다. GitHub처럼 코드를 읽는 게 아니라
# "겉으로 드러난 흔적"만 보는 가장 얕은 검증이라, strength가 항상 "mention"(단순 언급)으로 고정된다.

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

import httpx

from src.common.text_match import word_match as _word_match, keywords_for as _keywords_for

if TYPE_CHECKING:
    from src.agent.state import AppState
    from src.storage.neo4j_client import Neo4jClient


logger = logging.getLogger("jobgraph.agent")

def _build_text(html: str, headers: dict[str, str]) -> str:
    """HTML 본문 + 응답 헤더를 매칭용 소문자 텍스트로 합친다."""
    header_text = " ".join(f"{k} {v}" for k, v in headers.items())
    # 왜 헤더까지 보는가: 응답 헤더에는 "X-Powered-By: Express", "Server: nginx" 같은
    # 프레임워크·서버 정보가 실려오는 경우가 있어서, HTML 본문만으로는 못 잡는 배포 기술 흔적을
    # 헤더에서 추가로 잡을 수 있음 (예: FastAPI로 배포하면 특정 헤더 패턴이 남을 수 있음)
    return f"{html} {header_text}".lower()
    # 본문과 헤더를 한 문자열로 합쳐서 이후 키워드 매칭을 한 번에 처리할 수 있게 함


def _skills_from_deploy(text: str, vocab: list[str]) -> list[dict]:
    """직군 스킬 어휘를 배포 텍스트에 단어경계+별칭 매칭한다 (source=deploy → 실증).

    raw HTML은 노이즈가 많아 1~2자 키워드(go/js/ts/c/r 등)는 오탐 위험이 크므로 제외한다.
    """
    skills: list[dict] = []
    for skill in vocab:
        keywords = [kw for kw in _keywords_for(skill) if len(kw) >= 3]
        # 키워드 길이가 3자 미만이면 제외 — "Go"라는 언어의 키워드 "go"가 HTML 안 아무 단어에나
        # ("google", "going" 등, word_match가 막아주긴 하지만) 우연히 등장할 여지 자체를 원천 차단.
        # HTML은 정제된 채용공고 텍스트와 달리 광고 스크립트·메타태그 등 노이즈가 훨씬 많아서
        # github_eval.py나 다른 평가자보다 한 단계 더 보수적인 필터를 추가로 걺
        if any(_word_match(kw, text) for kw in keywords):
            skills.append({
                "skill": skill,
                "evidence": f"배포 URL 작동 확인 — {skill} 사용 흔적",
                "source": "deploy",
                # HTML·헤더 키워드는 코드가 아니라 단순 언급 — 단독으로 Verified를 주지 않는다.
                # (배포가 '작동'한다는 사실은 확인되나, 특정 스킬 사용의 코드 근거는 아님)
                "strength": "mention",
                # github_eval.py에서 본 strength("code" vs "mention") 개념이 여기서도 그대로 쓰임 —
                # 다만 deploy_eval은 애초에 코드를 안 읽으므로 "code" 등급을 절대 줄 수 없고 항상 "mention"
                "level_hint": "실무",
            })
    return skills


def create_deploy_evaluator(neo4j: "Neo4jClient") -> Callable[["AppState"], dict]:
    """배포 URL 평가자 팩토리. 작동하는 배포에서 직군 스킬을 코드 외부 근거로 확인한다."""
    def _eval_one(url: str, vocab) -> list:
        try:
            resp = httpx.get(url, timeout=10, follow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0 (job-skill-analyzer)"})
            # follow_redirects=True → 배포 URL이 다른 주소로 리다이렉트돼도(흔한 경우) 따라가서 최종 응답을 받음
            # User-Agent를 명시하는 이유: 일부 서버가 User-Agent가 없거나 "봇스러운" 요청을 차단하는데,
            # 브라우저처럼 보이는 값을 넣어 정상적인 응답을 받을 확률을 높임 (동시에 어떤 프로젝트의
            # 요청인지 식별 가능하게 이름도 남김 — 서버 운영자가 로그에서 알아볼 수 있게)
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"[deploy_eval] URL fetch 실패 (미작동/접근불가): {e}")
            return []
            # 이 함수의 존재 목적 자체가 "배포가 실제로 작동하는지 실증"이므로, fetch 실패는 곧
            # "이 배포는 작동 증거가 없다"는 뜻 — 에러를 삼키고 조용히 빈 리스트 반환
        text = _build_text(resp.text, dict(resp.headers))
        # resp.headers는 httpx의 전용 헤더 객체라서, 일반 dict 함수(items() 등)를 확실히 쓰려고 dict()로 변환
        return _skills_from_deploy(text, vocab)

    def evaluate(state: "AppState") -> dict:
        urls = state.get("deploy_urls") or []
        if not urls:
            return {"deploy_eval": {"skills": []}}
            # 다른 평가자들과 동일한 조기 반환 패턴
        vocab = neo4j.get_job_family_skills(state.get("job_family") or "")
        # 주의: github_eval.py는 exclude_common_threshold=None(필터 없이 전체 30개)을 넘겼지만,
        # 여기는 기본값(threshold=8)을 그대로 씀 — 여러 직군에 공통으로 등장하는 흔한 스킬은 제외된 상태로 조회.
        # deploy_eval은 원래도 신뢰도 낮은 얕은 검증이라, 너무 흔한 스킬까지 다 매칭하면 오탐이 늘어나서
        # 이 직군에 특화된 스킬만 보려는 의도로 보임 (메모리 기록의 threshold 차이 관련 이력과 일치)
        if not vocab:
            logger.warning(f"[deploy_eval] 직군 스킬 어휘 없음 (job_family={state.get('job_family')!r})")
            return {"deploy_eval": {"skills": []}}
        merged: list = []
        seen: set = set()
        for url in urls:
            for s in _eval_one(url, vocab):
                key = s.get("skill") if isinstance(s, dict) else s
                if key not in seen:
                    seen.add(key)
                    merged.append(s)
                    # 여러 배포 URL(예: 프론트/백엔드 각각 배포)에서 같은 스킬이 중복 검출돼도 하나만 남김
        return {"deploy_eval": {"skills": merged}}

    return evaluate
