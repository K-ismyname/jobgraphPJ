# gap_result의 보유 스킬 주장을 consensus(결정적 사실)와 대조해 환각을 잡는 검증기 Critic 노드
from __future__ import annotations

from typing import TYPE_CHECKING

from src.extraction.normalizer import normalize_skill

if TYPE_CHECKING:
    from src.agent.state import AppState


def verify_gap_against_consensus(
    gap_result: dict, consensus: dict
) -> tuple[list[dict], list[dict], dict]:
    """gap_result를 consensus와 대조해 두 종류의 환각을 결정적으로 제거한다.

    [보유 스킬 환각] gap_result.skills 중 consensus에 없는 항목 → 제거
    [부족 스킬 환각] gap_result.missing_required 중 consensus에 있는 항목 → 제거
                    (LLM이 이미 보유한 스킬을 "부족"이라고 잘못 표기한 경우)

    verification 라벨이 consensus와 다르면 → consensus 값으로 교정 (부풀림 차단)
    consensus는 결정적 사실(합의 노드 산출)이므로 단일 진실 공급원으로 삼는다.
    """
    consensus = consensus or {}
    consensus_names: set[str] = {normalize_skill(k) for k in consensus}

    # ── 보유 스킬 검증 ──────────────────────────────────────────
    skills = gap_result.get("skills") or []
    kept: list[dict] = []
    removed_claims: list[str] = []
    corrections: list[dict] = []
    for item in skills:
        if not isinstance(item, dict):
            continue
        raw = item.get("skill", "")
        name = normalize_skill(raw)
        info = consensus.get(name)
        if info is None:
            removed_claims.append(raw)          # 합의에 없는 보유 주장 → 환각
            continue
        true_verif = info.get("verification")
        if item.get("verification") != true_verif:
            corrections.append({"skill": name, "from": item.get("verification"), "to": true_verif})
            item = {**item, "verification": true_verif}
        kept.append(item)

    # ── 부족 스킬 검증 ──────────────────────────────────────────
    missing = gap_result.get("missing_required") or []
    clean_missing: list[dict] = []
    false_missing: list[str] = []
    for item in missing:
        raw = item.get("skill", "") if isinstance(item, dict) else str(item)
        name = normalize_skill(raw)
        if name in consensus_names:
            false_missing.append(raw)           # 이미 보유한 스킬을 "부족"이라고 주장 → 환각
        else:
            clean_missing.append(item)

    report = {
        "verified": True,
        "removed_claims": removed_claims,
        "false_missing": false_missing,
        "corrections": corrections,
    }
    return kept, clean_missing, report


def create_critic_node(openai_client=None):
    """Critic 노드 팩토리. gap_result를 consensus와 대조해 결정적으로 검증한다(LLM 미사용).

    openai_client는 그래프 조립부와의 시그니처 일관성용(미사용).
    """
    def critic_node(state: "AppState") -> dict:
        gap_result = state.get("gap_result") or {}
        consensus = state.get("consensus") or {}
        kept, clean_missing, report = verify_gap_against_consensus(gap_result, consensus)
        corrected = {**gap_result, "skills": kept, "missing_required": clean_missing}
        return {"gap_result": corrected, "critic_report": report}

    return critic_node
