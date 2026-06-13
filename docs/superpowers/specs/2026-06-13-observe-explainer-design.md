# 관측 페이지를 "시스템 설명서"로 — Mermaid + 단계 설명 + 실제 예시

**작성일:** 2026-06-13
**목적:** 관측 페이지의 워크플로우 탭을 "이번 분석 디버깅"이 아니라 **"이 Agentic RAG 시스템이 어떻게 작동하는지 설명/소개"**하는 용도로 만든다. 분석 없이 들어와도 시스템 구조·각 단계의 설계 의도가 다 보이고, 분석을 했으면 그 위에 "이번엔 이렇게 처리됐다"는 실제 데이터가 얹힌다. 포트폴리오에서 면접관·방문자가 시스템을 이해하게 하는 것이 성공 기준.

---

## 범위

**포함:**
1. **`GET /graph`** — 실제 LangGraph 구조(Mermaid) + 6개 논리 단계의 설명(설계 의도). 분석과 무관하게 항상 제공.
2. **`trace` 확장** — 각 단계가 실제 처리한 데이터(요약 숫자 → 실제 목록).
3. **워크플로우 탭 재구성** — Mermaid 다이어그램(거친 노드 강조) + 단계별 카드(설명 항상 + 데이터 있으면).

**제외:**
- 실시간 스트리밍, 데이터 탭(현행 유지), 설명 텍스트의 다국어.

---

## 논리 단계 정의 (LangGraph 노드 ↔ 설명 ↔ 실제 데이터)

워크플로우를 6개 논리 단계로 묶는다(15개 raw 노드를 사용자가 이해할 단위로).

| key | 제목 | LangGraph 노드 | 설계 의도(설명 요지) | 실제 데이터(trace) |
|-----|------|----------------|----------------------|--------------------|
| `evaluators` | 1. 다중 소스 평가자 | resume_eval·github_eval·portfolio_eval·deploy_eval | 소스마다 modality가 달라 한 LLM에 못 합침. **주장(이력서) vs 실증(GitHub·배포)을 구분**하려 분리. | 소스별 추출 스킬 목록 + 근거 |
| `consensus` | 2. 교차검증 합의 | consensus | 여러 독립 소스가 일치하면 신뢰. **Verified(실증)/Corroborated(2+소스)/Claimed(주장)** 결정적 판정. | 스킬별 등급 + 뒷받침 소스 |
| `gap_loop` | 3. Gap 루프 (Corrective RAG) | seed_gap·call_model·tools | 증거가 부족하면 **다른 소스를 추가 검색하는 교정 루프**. 단순 키워드 매칭이 아님. | 호출 도구 목록 + 반복 횟수 |
| `fit` | 4. 역량 기반 적합도 | synthesizer (+capability 후처리) | 직군 평균 개별 스킬은 편향 → **핵심 역량 충족**으로. 역방향 직군 추천. | 역량 충족 맵 + 역방향 추천 |
| `critic` | 5. Critic (환각 제거) | critic | LLM-judge가 아니라 **합의(사실)와 대조해 환각을 결정적으로 제거**·검증 라벨 교정. | 제거된 스킬·교정 항목 |
| `coach` | 6. Coach | coach_call_model·coach_tools·finalize_coach | 부족 역량 + 이력서 문장 개선 제안. | 제안 요약 |

설명 텍스트(`description`)는 구현 시 위 "설계 의도"를 2~3문장으로 작성. 차별점(주장 vs 실증, Corrective RAG, 결정적 critic, 역량 적합도)을 드러낸다.

---

## `GET /graph`

분석과 독립적인 시스템 구조·설명. 응답:
```python
{
  "mermaid": "graph TD; ...",          # app.state.graph.get_graph().draw_mermaid()
  "stages": [
    {"key": "evaluators", "title": "1. 다중 소스 평가자",
     "description": "...", "nodes": ["resume_eval","github_eval","portfolio_eval","deploy_eval"]},
    ...  # 6개
  ]
}
```
- `mermaid`: `app.state.graph`가 있으면 `get_graph().draw_mermaid()`. None(openai 키 없음)이면 `mermaid: null` + stages만(프론트는 다이어그램 없이 단계 설명만 표시).
- `stages`: 정적 상수(6단계 설명 + 매핑 노드). 신규 라우터 `src/api/routers/system.py` 또는 main.py.

## `trace` 확장 (`_build_trace`)

현재 요약 숫자(skill_count, counts)에 더해 실제 목록을 담는다(모두 state에 존재):
```python
trace = {
  "executed_nodes": [...],   # 거친 LangGraph 노드(강조용) — 입력에 있던 평가자 + 합의·gap·synth·critic·coach
  "evaluators": [{"source","skill_count","skills": [{"skill","evidence","level_hint"}]}],
  "consensus": {"counts": {...}, "skills": [{"skill","verification","sources"}]},
  "gap_loop": {"tool_calls": [...], "iterations": n},
  "critic": {"removed": n, "corrected": n, "removed_skills": [...], "corrections": [...]},
  "coach": {"suggestion_count": n},
}
```
- `evaluators[].skills`: `state["<src>_eval"]["skills"]`에서 skill·evidence·level_hint.
- `consensus`: `build_verification_summary(state["consensus"])` 통째(counts+skills).
- `critic.removed_skills`/`corrections`: `state["critic_report"]`의 `removed_claims`·`corrections`.
- `executed_nodes`: 결정적 추론.

기존 trace 소비처(observe.js renderTrace)는 이 확장으로 재작성한다. `capability_fit`/`recommended_families`는 `final_report`에 이미 있으므로(별도 후처리) 워크플로우 탭의 `fit` 단계가 `report`에서 직접 읽는다.

## 워크플로우 탭 재구성 (observe.html/observe.js)

- **Mermaid.js**(CDN `<script>` 1개) 로드. `/graph`의 `mermaid`를 렌더. `report`가 있으면 `trace.executed_nodes`로 거친 노드를 색 강조(mermaid `classDef` 주입).
- **단계 카드 6개**(`/graph`의 stages 순서): 각 카드 = 제목 + 설명(항상) + (report 있으면) 그 단계 실제 데이터.
  - evaluators: 소스별 스킬 칩 + 근거 펼침.
  - consensus: 스킬별 등급 배지 + 소스.
  - gap_loop: 도구 목록 + 반복.
  - fit: 역량 met/unmet + 역방향(report의 capability_fit/recommended_families 재사용).
  - critic: 제거 스킬·교정.
  - coach: 제안 수.
- report_id 없으면: 설명만(데이터 자리에 "분석하면 실제 예시가 표시됩니다").

진입 흐름: observe.js가 항상 `/graph` 호출(설명·다이어그램). `report_id` 쿼리 있으면 `/report/{id}`도 호출해 결합.

---

## 에러 처리

| 상황 | 처리 |
|------|------|
| `app.state.graph` None | `mermaid: null` — 다이어그램 생략, 단계 설명은 표시 |
| Mermaid CDN 로드 실패 | 다이어그램 영역에 "다이어그램 로드 실패", 단계 카드는 정상 |
| report에 trace 없음/구버전 | 단계 카드는 설명만 |
| `/graph` 실패 | 워크플로우 탭에 오류, 데이터 탭은 정상 |

## 테스트

- `GET /graph` 200, `stages` 6개·각 key 존재, mermaid 문자열 또는 null(통합/단위 — graph mock).
- `_build_trace` 확장 단위: evaluators[].skills, consensus.skills, critic.removed_skills 채워짐.
- observe 정적 서빙 회귀.
- UI는 수동 확인(설명 항상 표시 + report_id 결합).

---

## 비결정 사항(구현 중 확정)

- Mermaid CDN 버전 핀(예: mermaid@10). 오프라인이면 다이어그램만 생략.
- executed_nodes 강조를 mermaid classDef 주입 vs 카드 "실행됨" 배지 — 다이어그램 강조 우선, 어려우면 카드 배지로.
- 설명 텍스트 분량(2~3문장/단계).
