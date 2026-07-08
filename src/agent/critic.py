# gap_result의 보유 스킬 주장을 consensus(결정적 사실)와 대조해 환각을 잡는 검증기 Critic 노드
#
# 이 파일이 하는 일: CLAUDE.md 그래프의 critic 노드. gap_agent(nodes.py의 generate_report)가
# LLM으로 만든 gap_result는 어차피 LLM 산출물이라 환각(사실과 다른 서술) 위험이 있는데,
# 이 파일이 그 결과를 consensus(오직 결정적 규칙으로만 만들어진, 이 파이프라인에서 가장 신뢰할 수 있는
# 데이터)와 기계적으로 대조해서, consensus와 모순되는 부분을 잘라내거나 고친다. LLM을 전혀 안 씀.

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
    # "단일 진실 공급원(single source of truth)" — consensus.py가 만든 결과만이 "사실"이고,
    # gap_result(LLM 산출물)는 그 사실과 어긋나면 무조건 consensus 쪽이 이긴다는 원칙을 이 함수가 강제함
    consensus = consensus or {}
    consensus_names: set[str] = {normalize_skill(k) for k in consensus}
    # consensus에 실제로 등장하는 모든 스킬명을 정규화된 형태의 집합으로 미리 만들어둠 —
    # 아래에서 "이 스킬이 consensus에 있는지"를 매번 빠르게 확인(in 검사)하기 위한 준비

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
            # gap_result가 "이 사람은 X를 보유했다"고 적었는데, consensus(4개 평가자를 종합한 사실)에
            # X라는 스킬 자체가 아예 없다면 — 이건 LLM이 어디서도 근거 없이 지어낸 스킬이라는 뜻.
            # kept에 추가하지 않고(=최종 리포트에서 삭제) removed_claims에 기록만 남김
        true_verif = info.get("verification")
        if item.get("verification") != true_verif:
            corrections.append({"skill": name, "from": item.get("verification"), "to": true_verif})
            item = {**item, "verification": true_verif}
            # 스킬 자체는 consensus에 있지만(=진짜 존재하는 보유 스킬), LLM이 매긴 verification 라벨이
            # consensus의 실제 등급과 다르면(예: 진짜는 Claimed인데 LLM이 Verified라고 부풀렸으면)
            # 삭제까지는 안 하고 라벨만 consensus 값으로 강제 교정. {**item, ...}으로 복사본을 만들어
            # 교체하고, 원본 item 변수를 이 복사본으로 갈아끼움(다음 줄의 kept.append가 새 값을 쓰도록)
        kept.append(item)

    # ── 부족 스킬 검증 ──────────────────────────────────────────
    missing = gap_result.get("missing_required") or []
    clean_missing: list[dict] = []
    false_missing: list[str] = []
    for item in missing:
        raw = item.get("skill", "") if isinstance(item, dict) else str(item)
        # missing_required의 각 항목이 dict일 수도 문자열일 수도 있어서 두 형태 모두 처리 —
        # nodes.py의 _gap_missing_names()에서도 봤던 것과 똑같은 방어적 이중 처리
        name = normalize_skill(raw)
        if name in consensus_names:
            false_missing.append(raw)           # 이미 보유한 스킬을 "부족"이라고 주장 → 환각
            # 이 스킬이 consensus_names(실제로 검증된 보유 스킬 목록)에 있다면, gap_result가
            # "부족하다"고 말한 게 완전히 반대로 틀린 것 — 이런 항목은 최종 부족 스킬 목록에서 제외
        else:
            clean_missing.append(item)

    report = {
        "verified": True,
        "removed_claims": removed_claims,
        "false_missing": false_missing,
        "corrections": corrections,
    }
    return kept, clean_missing, report
    # 세 가지를 튜플로 반환: 정제된 보유 스킬 리스트, 정제된 부족 스킬 리스트, 그리고 "무엇을 왜 고쳤는지"의 로그
    # 이 report가 nodes.py의 _build_trace()에서 "critic: removed N개, corrected N개"로 요약되던 그 데이터


def create_critic_node(openai_client=None):
    """Critic 노드 팩토리. gap_result를 consensus와 대조해 결정적으로 검증한다(LLM 미사용).

    openai_client는 그래프 조립부와의 시그니처 일관성용(미사용).
    """
    # 다른 노드 팩토리들(create_call_model, create_resume_evaluator 등)은 대부분 openai_client나
    # neo4j를 실제로 써서 클로저로 캡처하는데, 이 팩토리는 openai_client를 받기는 하지만 안 씀 —
    # docstring에 그 이유가 명시돼 있음: supervisor.py가 모든 노드 팩토리를 "비슷한 모양"으로
    # 호출하고 싶어서, 실제로는 필요 없어도 시그니처를 맞춰두는 관례적 선택으로 보임
    def critic_node(state: "AppState") -> dict:
        gap_result = state.get("gap_result") or {}
        consensus = state.get("consensus") or {}
        kept, clean_missing, report = verify_gap_against_consensus(gap_result, consensus)
        corrected = {**gap_result, "skills": kept, "missing_required": clean_missing}
        # gap_result 전체를 복사하면서 skills와 missing_required 두 필드만 정제된 값으로 교체.
        # gap_result의 다른 필드(match_rate, confidence_level, advice, summary 등)는 그대로 유지됨 —
        # 이 함수가 "보유/부족 스킬 리스트만" 검증 대상으로 삼고, 나머지는 이미 nodes.py의
        # _apply_deterministic_metrics()에서 다른 방식으로 이미 검증(덮어쓰기)됐기 때문
        return {"gap_result": corrected, "critic_report": report}
        # gap_result를 교정된 버전으로 덮어쓰고, critic_report도 별도 필드로 함께 반환 —
        # 둘 다 AppState에 병합되어 이후 coach_agent, _build_trace가 참조하게 됨

    return critic_node
