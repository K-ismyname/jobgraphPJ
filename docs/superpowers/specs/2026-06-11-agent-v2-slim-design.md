# 에이전트 v2 슬림화 설계 — 4-에이전트 + 길 B Critic

> 작성일: 2026-06-11
> 대상: 멀티에이전트 코어 v1(7노드)을 4-에이전트로 슬림화하고, Critic을 재검색 루프에서 근거 등급화로 전환
> 전제: 현재 코드는 v1(merge 완료). 이 문서는 v2 목표 구조. 구현은 후속.

---

## 1. 배경 — v1의 문제

v1은 7노드(Planner·Profile·Retrieval·Market·Gap·Critic·Coach) + Plan-and-Execute + Critic replan 루프로 구성됐다. **데이터 흐름을 추적한 결과 3개 노드가 제값을 못 함**이 확인됐다:

| 노드 | 문제 | 근거 |
|------|------|------|
| **Market** | 데드 노드 | `market_result`를 읽는 곳이 0개 (써넣고 버려짐) |
| **Retrieval** | 중복 | `retrieved_context`를 Critic만 사용하는데, Gap이 `verify_skills`로 따로 같은 검색 수행 |
| **Planner** | LLM 장식 | `plan`에서 실제 쓰이는 건 `steps`의 agent 목록뿐. LLM이 만든 `goal`·`reason`은 미사용 |

또한 **Critic의 replan 루프가 무의미**하다: 재검색은 "문서는 있는데 못 찾은 경우(검색 miss)"에만 효과인데, 데이터가 적어(321 공고) "데이터 부족·LLM 환각"이 주 원인이다. 같은 데이터를 다른 각도로 재조회해도 없는 근거는 생기지 않는다.

**원칙:** "판단하는 것만 에이전트, 조회·검색은 도구."

---

## 2. 결정 사항

| 항목 | 결정 |
|------|------|
| 에이전트 | **Profile · Gap · Critic · Coach** (4개) |
| 제거 | Planner(결정적 분기로 대체), Market(데드), Retrieval(중복) |
| 도구 유지 | `market_insights`·`vector_search`·`verify_skills`·`skill_unlock`은 **Gap의 도구로** 잔류 |
| Critic | **길 B (등급화)** — replan 루프 제거, 각 주장에 근거 등급(high/low) + 환각 제거 |
| Learning Path | **제외** — 주차별 소요시간 데이터가 없어 LLM 추측 = "근거 기반" 철학과 모순 |

---

## 3. v1 → v2 변경

| 컴포넌트 | v1 | v2 |
|----------|-----|-----|
| Planner | LLM 계획 노드 | **제거** — 입력 분기는 결정적 함수로 (Profile 또는 진입부) |
| Profile | resume+github 통합 | 유지 |
| Retrieval | 독립 노드 | **제거** — 검색은 Gap 도구로 |
| Market | 독립 노드 | **제거** — 시장 정보 필요 시 Gap이 `market_insights` 툴로 |
| Gap | call_model↔tools 루프 | 유지 (도구 루프) |
| Critic | replan 트리거 | **길 B 등급화로 재작성** |
| Coach | coach 루프 | 유지 |

---

## 4. v2 그래프 구조

```
START → Profile → Gap(call_model ↔ tools) → Critic(등급화) → Coach(루프) → END
        스킬추출   분석 + 근거 수집           근거 등급 매김    개선 제안
```

- v1의 **Send 병렬·executor_dispatch·replan 라우팅·planner 재진입이 전부 제거**된다 → 거의 선형.
- Gap 내부의 도구 루프, Coach 내부의 검증 루프는 유지되므로 그래프 표현은 여전히 의미가 있다.
- 입력 조합 분기(PDF/텍스트/GitHub 유무)는 Profile 내부의 결정적 if문으로 처리 (LLM 불필요).

---

## 5. 길 B Critic 상세

### 입력
- `gap_result`의 주장들 (missing_required의 각 스킬 + reason)
- 그 주장의 **근거** — Gap이 `verify_skills`로 수집해 종합한 결과 (v1의 별도 `retrieved_context` 대신 Gap이 이미 모은 근거를 재활용 → 중복 제거)

### 처리 (한 번, 루프 없음)
각 주장을 근거와 대조해 등급을 매긴다:
```
"LangGraph 부족" → 공고 12건 근거 → high ✓
"PyTorch 부족 (딥러닝 필수)" → 근거 텍스트에 없음 → low ⚠
"Kafka 부족" → gap이 지어낸 환각, 근거 0 → 제거 또는 low
```

### 출력
```python
critic_report = {
    "graded_claims": [
        {"skill": "LangGraph", "confidence": "high", "evidence_count": 12},
        {"skill": "PyTorch",   "confidence": "low",  "note": "공고 근거 없음"},
    ],
    "removed": ["Kafka"],   # 환각으로 판단해 제거한 주장
}
```
판정 후 **Coach로 직행**한다 (Gap으로 되돌아가는 replan 없음). `needs_replan`·`decide_replan`·`route_after_critic`·`MAX_REPLAN`은 제거된다.

### 최종 리포트 반영
Coach·final_report가 등급을 노출한다:
```
부족 필수 스킬:
  • LangGraph [확실 ✓] 공고 12건 — 우선 준비
  • PyTorch   [근거 약함 ⚠] — 참고만
```

---

## 6. 상태(AppState) 정리

**제거할 필드:**
- `plan`, `replan_count` (Planner·replan 제거)
- `market_result` (Market 제거)
- `retrieved_context` (Retrieval 제거 — Critic은 Gap 근거 재활용)

**유지/변경:**
- `profile_result`, `gap_result`, `coaching_result`, `final_report`, `messages`, `coach_messages` 유지
- `critic_report` 구조를 등급화 형태로 변경 (위 §5)

---

## 7. 변경 파일

| 파일 | 종류 |
|------|------|
| `src/agent/supervisor.py` | 수정 — 그래프 재조립 (3노드·replan 라우팅·Send 제거) |
| `src/agent/critic.py` | 수정 — 길 B 등급화로 재작성 (`decide_replan`·`needs_replan` 제거) |
| `src/agent/state.py` | 수정 — 미사용 필드 4개 제거 |
| `src/agent/planner.py` | 제거 (입력 분기 로직은 Profile/진입부로 이전) |
| `src/agent/market_agent.py` | 제거 |
| `src/agent/retrieval_agent.py` | 제거 |
| `src/agent/nodes.py` | 수정 — Critic 등급 소비, replan 시드 제거 |
| `tests/` | 관련 테스트 정리 (executor_dispatch·planner·market·retrieval 테스트 제거, critic 등급화 테스트 추가) |

---

## 8. 테스트 전략

- **Critic 등급화**: 주장+근거 → 올바른 등급(근거 충분→high, 없음→low, 환각→제거) 판정 (mock LLM 또는 결정적 헬퍼)
- **그래프 구조**: 4개 핵심 노드 존재, replan 엣지·executor_dispatch 부재 확인
- **회귀**: `gap_result`·`final_report` 구조 유지, end-to-end 1회 정상 종료
- **제거 검증**: planner/market/retrieval import가 어디서도 안 쓰이는지

---

## 9. 트레이드오프

| | v1 | v2 |
|---|-----|-----|
| 화려함 (병렬/라우팅/replan) | 높음 | 낮음 |
| 정직함 (근거 등급) | 약함 | 강함 |
| 단순함·유지보수 | 복잡 | 단순 |
| 각 노드가 제값? | ✗ (3개 미연결/중복/장식) | ✅ |
| LLM 호출 수 | 많음 | 적음 (Planner·replan 제거) |

화려한 오케스트레이션을 잃는 대신, **정직함·단순함·각 노드의 실효성**을 얻는다.

---

## 10. 멀티에이전트 정당성

replan 루프가 없어도 v2는 멀티에이전트다. **Gap(생성자)과 Critic(검증자)의 분리**가 핵심 — 자기 답을 자기가 검증하면 편향되므로 독립 검증자가 따로 등급을 매긴다. 이 생성자-검증자 분리가 멀티에이전트의 본질이고, 병렬·라우팅·replan은 이 도메인엔 불필요한 장식이었다.

---

## 11. 포트폴리오 서사

"7개로 화려하게 만들었으나 데이터 흐름 추적 결과 3개가 미연결·중복·장식임을 발견 → 4개로 슬림화 + Critic을 '재검색'에서 '정직한 근거 등급화'로 전환." **만들고 → 측정·분석하고 → 덜어낸** 의사결정 과정이 "노드 수 자랑"보다 강한 신호다.

---

## 12. 구현 순서 (writing-plans에서 상세화)

1. 베이스라인 확인 (현재 v1 테스트 통과)
2. `critic.py` 길 B 재작성 + 단위 테스트
3. `state.py` 미사용 필드 제거
4. `supervisor.py` 그래프 재조립 (3노드·replan 제거, Critic→Coach 직결)
5. planner/market/retrieval 파일 제거 + 관련 테스트 정리
6. end-to-end 검증 + 회귀
