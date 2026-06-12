# gap_result의 보유 스킬 주장을 consensus(결정적 사실)와 대조해 환각을 잡는 검증기 Critic 노드
from __future__ import annotations

from typing import TYPE_CHECKING

from src.extraction.normalizer import normalize_skill

if TYPE_CHECKING:
    from src.agent.state import AppState


def verify_gap_against_consensus(
    gap_result: dict, consensus: dict
) -> tuple[list[dict], dict]:
    """gap_result의 skills를 consensus와 대조해 교정·제거하고, 보정된 skills와 검증 리포트를 반환한다.

    - consensus에 없는 보유 스킬 주장 → 제거 (LLM 환각)
    - verification 라벨이 consensus와 다르면 → consensus 값으로 교정 (부풀림 차단)

    consensus는 결정적 사실(합의 노드 산출)이므로 단일 진실 공급원으로 삼는다.
    """
    skills = gap_result.get("skills") or []
    consensus = consensus or {}
    kept: list[dict] = []
    removed: list[str] = []
    corrections: list[dict] = []
    for item in skills:
        if not isinstance(item, dict):
            continue
        raw = item.get("skill", "")
        name = normalize_skill(raw)
        info = consensus.get(name)
        if info is None:
            removed.append(raw)            # 합의에 없는 보유 주장 → 환각
            continue
        true_verif = info.get("verification")
        if item.get("verification") != true_verif:
            corrections.append(
                {"skill": name, "from": item.get("verification"), "to": true_verif}
            )
            item = {**item, "verification": true_verif}
        kept.append(item)
    report = {"verified": True, "removed_claims": removed, "corrections": corrections}
    return kept, report


def create_critic_node(openai_client=None):
    """Critic 노드 팩토리. gap_result를 consensus와 대조해 결정적으로 검증한다(LLM 미사용).

    openai_client는 그래프 조립부와의 시그니처 일관성용(미사용).
    """
    def critic_node(state: "AppState") -> dict:
        gap_result = state.get("gap_result") or {}
        consensus = state.get("consensus") or {}
        kept, report = verify_gap_against_consensus(gap_result, consensus)
        corrected = {**gap_result, "skills": kept}
        return {"gap_result": corrected, "critic_report": report}

    return critic_node
