# 여러 평가자의 스킬 증거를 검증 상태로 종합하는 결정적 합의 노드 ("서기" 역할)
#
# 이 파일이 하는 일: CLAUDE.md 그래프 다이어그램의 "consensus (검증 등급 결정적 판정 — LLM 미사용)"
# 그 자체다. 4개 평가자(resume_eval, github_eval, portfolio_eval, deploy_eval)가 각각 독립적으로
# 만든 "이 스킬을 봤다"는 결과들을 받아서, 스킬 하나하나에 대해 "얼마나 믿을만한가"를
# Verified/Corroborated/Claimed 세 등급 중 하나로 매긴다. "서기"라는 별명 그대로, 여러 증인의
# 증언을 종합해 사실관계만 정리할 뿐 새로운 판단(LLM 추론)을 더하지 않는다.

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from src.extraction.normalizer import normalize_skill

if TYPE_CHECKING:
    from src.agent.state import AppState

# 실증 가능한 소스 (코드·배포로 검증)
_VERIFIABLE_SOURCES = {"github", "deploy"}
# resume/portfolio는 "본인이 말한 것"이라 아무리 확신에 차 있어도 코드 근거가 될 수 없고,
# github/deploy만 "실제로 동작하는 것을 관측한" 소스로 인정 — 이 구분이 아래 Verified 판정의 핵심 기준


def build_consensus(evaluator_outputs: list[dict]) -> dict:
    """평가자별 [{skill, evidence, source, strength, level_hint}]를 스킬별 검증 상태로 합친다.

    Verified     : 코드 근거(strength="code" — 의존성 파일·주 언어)로 실증됨
    Corroborated : 2개 이상 독립 소스가 일치 (코드 근거는 없지만 서로 뒷받침)
    Claimed      : 1개 소스만 (코드 미확인)

    핵심: 등급은 '어느 소스냐'가 아니라 '증거가 얼마나 강하냐'로 판정한다.
    README·배포 HTML에 스킬명이 적혀 있기만 한 것(strength="mention")은 Verified가 아니다.
    """
    # 1단계: 4개 평가자 결과를 "스킬명" 기준으로 재편성
    by_skill: dict[str, list[dict]] = {}
    for out in evaluator_outputs:
        # out은 {"skills": [...]} 형태 (resume_eval, github_eval 등 각 평가자의 반환값)
        for item in out.get("skills", []):
            name = normalize_skill(item["skill"])
            # 평가자마다 스킬명 표기가 다를 수 있어서(예: github_eval은 "react.js", resume_eval은 "React")
            # 정규화된 이름을 key로 써야 같은 스킬로 묶임
            by_skill.setdefault(name, []).append({**item, "skill": name})
            # setdefault(key, []) → key가 없으면 빈 리스트를 만들어 넣고, 있으면 기존 리스트를 그대로 반환
            # {**item, "skill": name} → 원본 evidence 항목을 복사하면서 skill 필드만 정규화된 이름으로 교체

    # 2단계: 스킬 하나하나에 대해 증거들을 보고 등급 판정
    consensus: dict[str, dict] = {}
    for skill, evidences in by_skill.items():
        sources = {e["source"] for e in evidences}
        # 이 스킬을 언급한 서로 다른 소스(resume/github/portfolio/deploy) 집합 — set이라 자동으로 중복 제거됨
        has_code = any(
            e.get("source") in _VERIFIABLE_SOURCES and e.get("strength") == "code"
            for e in evidences
        )
        # "실증 가능한 소스(github/deploy)에서, 강도가 code(단순 언급이 아니라 실제 코드/설정 근거)인
        # 증거가 하나라도 있는가" — 둘 다 만족해야 함. github_eval.py에서 만든 strength 필드가
        # 여기서 실제로 소비되는 지점
        if has_code:
            status = "Verified"
        elif len(sources) >= 2:
            status = "Corroborated"
            # 코드 근거는 없어도, 서로 다른 소스 2개 이상이 같은 스킬을 언급하면 "교차 확인됨"으로 인정
            # (예: 이력서에도 있고 포트폴리오에도 있으면, 코드 증거는 없어도 어느 정도 신빙성 인정)
        else:
            status = "Claimed"
            # 소스가 딱 하나뿐이면(대개 이력서 단독 주장) 가장 낮은 등급
        result: dict = {"verification": status, "evidences": evidences}
        if status == "Claimed":
            result["flags"] = ["코드·실증 미확인 — 주장/언급만"]
            # flags는 Claimed 등급에만 붙는 경고 표시 — 나중에 리포트에서 "이건 특히 주의해서 보라"는 신호로 쓰일 수 있음
        consensus[skill] = result
    return consensus
    # 반환 형태: {"React": {"verification": "Verified", "evidences": [...]}, "Docker": {...}, ...}
    # 이게 state.py에서 본 AppState.consensus 필드에 그대로 들어감


def expand_umbrella_skills(consensus: dict, neo4j) -> dict:
    """검증된 구체 스킬로 상위 카테고리 스킬(LLM·GenAI 등)을 간접 실증한다.

    "LangGraph로 멀티에이전트를 짰는데 'LLM 경험 부족'"이라는 오탐의 원인은
    스킬 매칭이 리터럴 이름 비교라는 것 — PART_OF 체인(LangGraph→…→LLM)을 타고
    상위 스킬을 consensus에 결정적으로 추가해, critic의 false_missing 로직이
    missing_required에서 자동으로 걸러내게 한다.

    규칙:
    - 근거는 Verified/Corroborated 스킬만 (Claimed 주장을 상위로 세탁하지 않음)
    - 상위 스킬의 기존 등급이 간접 실증 등급보다 같거나 강하면 그대로 둔다
      (직접 Verified를 간접 Corroborated로 낮추지 않음) — 단 기존이 더 약하면(Claimed 등)
      업그레이드한다. 이력서에 "AI" 한 단어가 적혀 있어 Claimed로 먼저 잡힌 게
      LangGraph 등 강한 간접 증거를 막아버리는 문제를 막는다 (직접 증거는 보존해 병기).
    - 등급은 근거 스킬 중 최고 등급을 따름
    """
    # 이 함수가 왜 필요한지 docstring의 예시가 정확함: build_consensus()는 "이름이 정확히 일치하는지"만
    # 보는 리터럴 매칭이라서, 지원자가 "LangGraph"를 아무리 잘 다뤄도 "LLM"이라는 이름 자체가
    # 별도로 언급되지 않으면 "LLM 스킬은 확인 안 됨"으로 오판할 수 있음. neo4j_client.py에서 봤던
    # get_covered_umbrella_skills()(PART_OF 체인 조회)를 이용해 이 오판을 코드로 교정하는 함수
    if not consensus or neo4j is None:
        return consensus
        # neo4j 없이도(테스트 환경 등) build_consensus()의 기본 결과는 그대로 쓸 수 있게 방어

    strong = {
        skill: info for skill, info in consensus.items()
        if (info or {}).get("verification") in ("Verified", "Corroborated")
    }
    # "충분히 신뢰할 수 있는" 스킬만 골라냄 — Claimed(주장뿐)는 상위 스킬을 실증하는 근거로 못 씀
    if not strong:
        return consensus
    try:
        covered = neo4j.get_covered_umbrella_skills(list(strong))
        # 지난번 neo4j_client.py에서 본 그 메서드 — {"LLM": ["LangGraph"], "GenAI": ["LangGraph", "RAG"]} 형태로,
        # "이 보유 스킬들이 PART_OF 체인을 타고 어떤 상위 개념 스킬까지 실증하는지"를 반환
    except Exception:
        return consensus
        # Neo4j 조회가 실패해도 원래 consensus라도 반환 — 이 보강 기능이 실패했다고 전체 흐름이 끊기면 안 됨

    rank = {"Verified": 0, "Corroborated": 1, "Claimed": 2}
    # 숫자가 작을수록 강한 등급 — 아래에서 "기존 등급이 이미 강하면 안 건드린다"는 비교에 씀
    for umbrella, via in (covered or {}).items():
        # umbrella = 상위 스킬명(예: "LLM"), via = 그 근거가 된 구체 스킬 리스트(예: ["LangGraph"])
        name = normalize_skill(umbrella)
        via_known = [v for v in via if normalize_skill(v) in strong]
        # via(neo4j가 알려준 근거 스킬) 중, 실제로 이 사람이 strong(Verified/Corroborated) 상태로
        # 보유한 것만 다시 필터링 — neo4j 데이터와 이 사람의 실제 consensus를 한 번 더 교차검증
        if not via_known:
            continue
        derived_grade = ("Verified"
                          if any(strong[normalize_skill(v)]["verification"] == "Verified" for v in via_known)
                          else "Corroborated")
        # 근거 스킬 중 하나라도 Verified가 있으면 상위 스킬도 Verified로, 아니면(전부 Corroborated면) Corroborated로
        # — "등급은 근거 스킬 중 최고 등급을 따른다"는 docstring 규칙의 실제 구현
        existing = consensus.get(name)
        existing_grade = (existing or {}).get("verification")
        if existing and rank.get(existing_grade, 9) <= rank[derived_grade]:
            continue  # 기존 등급이 이미 같거나 강함 — 유지
            # rank.get(existing_grade, 9) → existing_grade가 없으면(이례적 상황) 9라는 매우 큰 값으로 취급해
            # "기존이 없으니 당연히 업그레이드해야 한다"는 쪽으로 자연스럽게 처리
            # 기존 등급의 rank가 derived_grade의 rank보다 작거나 같다(=더 강하거나 같다)면 건드리지 않음
        derived_evidence = {
            "skill": name,
            "evidence": f"{', '.join(sorted(via_known))} 실증으로 간접 확인 (PART_OF)",
            "source": "derived",
            # source가 "derived"(파생됨)라는 완전히 새로운 값 — resume/github/portfolio/deploy 중
            # 어디에서도 안 왔고, 순전히 그래프 관계 추론으로 만들어진 증거임을 명시
            "level_hint": None,
        }
        prior_evidences = (existing or {}).get("evidences") or []
        consensus[name] = {
            "verification": derived_grade,
            "evidences": prior_evidences + [derived_evidence],
            # 기존 증거를 지우지 않고 새 파생 증거를 이어붙임 — docstring의 "직접 증거는 보존해 병기"
            "flags": [f"간접 실증 — {', '.join(sorted(via_known))} 기반"],
        }
    return consensus
    # 이 함수는 인자로 받은 consensus dict를 직접 수정(consensus[name] = ...)하면서 그 자체를 반환함 —
    # 새 dict를 만들어 반환하는 대신 원본을 그 자리에서 변경하는 "in-place 수정" 스타일


# 검증 등급 강한 순 (요약 정렬용)
_GRADE_RANK = {"Verified": 0, "Corroborated": 1, "Claimed": 2}
# expand_umbrella_skills 안의 rank와 값은 같지만 별도로 다시 정의된 전역 상수 — 함수 지역 변수와
# 모듈 전역 상수로 이름이 겹치지 않게 분리돼 있음 (사실상 중복 정의라 통합 여지가 있어 보이는 지점)


def build_verification_summary(consensus: dict) -> dict:
    """consensus를 최종 리포트용 검증 요약으로 정리한다 (신뢰도 축 산출물).

    {"counts": {Verified, Corroborated, Claimed}, "skills": [{skill, verification, sources}]}
    skills는 강한 검증(Verified) 순으로 정렬.
    """
    # 이 함수가 지난번 nodes.py의 _build_trace(), finalize_coach()에서 여러 번 호출되던 그 함수
    counts = {"Verified": 0, "Corroborated": 0, "Claimed": 0}
    skills: list[dict] = []
    for skill, info in (consensus or {}).items():
        grade = (info or {}).get("verification")
        sources = sorted({e.get("source") for e in (info or {}).get("evidences", []) if e.get("source")})
        # set으로 중복 제거 후 sorted()로 리스트화 — 항상 같은 순서로 나오게 해서 출력 결과가 일관되게 함
        skills.append({"skill": skill, "verification": grade, "sources": sources})
        if grade in counts:
            counts[grade] += 1
            # grade가 "derived" 같은 특이값이면 counts에 없는 키라서 이 if가 조용히 건너뜀 —
            # 사실 expand_umbrella_skills가 만드는 등급은 여전히 Verified/Corroborated이지 "derived"가
            # 아니므로(그건 evidence의 source 필드일 뿐) 이 우려는 기우이지만, 방어적으로 짜여 있음
    skills.sort(key=lambda s: (_GRADE_RANK.get(s["verification"], 9), s["skill"]))
    # 정렬 키가 튜플: (등급 순위, 스킬명) — 등급이 같으면 스킬명 알파벳/가나다순으로 2차 정렬
    return {"counts": counts, "skills": skills}


def create_consensus_node(neo4j=None) -> Callable[["AppState"], dict]:
    """합의 노드 팩토리. 평가자 결과를 합쳐 consensus에 쓴다.

    neo4j가 주어지면 PART_OF 체인으로 상위 카테고리 스킬(LLM 등)을 간접 실증한다.
    """
    def consensus_node(state: "AppState") -> dict:
        outputs = [state[k] for k in ("resume_eval", "github_eval", "portfolio_eval", "deploy_eval") if state.get(k)]
        # 4개 평가자 필드 중 실제로 값이 채워진 것만 골라 리스트로 — dispatch가 fan-out 안 한 평가자는
        # state에 해당 키가 없거나 빈 값이라서 자동으로 제외됨 (예: GitHub URL 안 줬으면 github_eval 자체가 빠짐)
        consensus = build_consensus(outputs)
        consensus = expand_umbrella_skills(consensus, neo4j)
        return {"consensus": consensus}
        # 이 반환값이 AppState.consensus에 병합되고, 이후 gap_agent(nodes.py의 generate_report)와
        # critic이 이 값을 읽어서 각자의 결정적 판단(신뢰도 등급, 환각 제거)의 기준으로 삼음
    return consensus_node
