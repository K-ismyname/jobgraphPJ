# 여러 평가자의 스킬 증거를 검증 상태로 종합하는 결정적 합의 노드 ("서기" 역할)
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from src.extraction.normalizer import normalize_skill

if TYPE_CHECKING:
    from src.agent.state import AppState

# 실증 가능한 소스 (코드·배포로 검증)
_VERIFIABLE_SOURCES = {"github", "deploy"}


def build_consensus(evaluator_outputs: list[dict]) -> dict:
    """평가자별 [{skill, evidence, source, level_hint}]를 스킬별 검증 상태로 합친다.

    Verified     : github/deploy 등 실증 소스에 증거
    Corroborated : 2개 이상 소스가 일치
    Claimed      : 1개 소스만 (코드 미확인 시 flag)
    """
    by_skill: dict[str, list[dict]] = {}
    for out in evaluator_outputs:
        for item in out.get("skills", []):
            name = normalize_skill(item["skill"])
            by_skill.setdefault(name, []).append({**item, "skill": name})

    consensus: dict[str, dict] = {}
    for skill, evidences in by_skill.items():
        sources = {e["source"] for e in evidences}
        if sources & _VERIFIABLE_SOURCES:
            status = "Verified"
        elif len(sources) >= 2:
            status = "Corroborated"
        else:
            status = "Claimed"
        result: dict = {"verification": status, "evidences": evidences}
        if status == "Claimed":  # Claimed는 정의상 실증 소스(github/deploy)가 없음
            result["flags"] = ["코드 미확인 — 주장만"]
        consensus[skill] = result
    return consensus


# 검증 등급 강한 순 (요약 정렬용)
_GRADE_RANK = {"Verified": 0, "Corroborated": 1, "Claimed": 2}


def build_verification_summary(consensus: dict) -> dict:
    """consensus를 최종 리포트용 검증 요약으로 정리한다 (신뢰도 축 산출물).

    {"counts": {Verified, Corroborated, Claimed}, "skills": [{skill, verification, sources}]}
    skills는 강한 검증(Verified) 순으로 정렬.
    """
    counts = {"Verified": 0, "Corroborated": 0, "Claimed": 0}
    skills: list[dict] = []
    for skill, info in (consensus or {}).items():
        grade = (info or {}).get("verification")
        sources = sorted({e.get("source") for e in (info or {}).get("evidences", []) if e.get("source")})
        skills.append({"skill": skill, "verification": grade, "sources": sources})
        if grade in counts:
            counts[grade] += 1
    skills.sort(key=lambda s: (_GRADE_RANK.get(s["verification"], 9), s["skill"]))
    return {"counts": counts, "skills": skills}


def create_consensus_node() -> Callable[["AppState"], dict]:
    """합의 노드 팩토리. 평가자 결과를 합쳐 consensus에 쓴다."""
    def consensus_node(state: "AppState") -> dict:
        outputs = [state[k] for k in ("resume_eval", "github_eval", "portfolio_eval", "deploy_eval") if state.get(k)]
        return {"consensus": build_consensus(outputs)}
    return consensus_node
