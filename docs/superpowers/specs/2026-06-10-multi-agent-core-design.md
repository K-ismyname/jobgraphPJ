# 멀티 에이전트 코어 전환 설계 — Plan-and-Execute + Critic

> 작성일: 2026-06-10
> 대상: Job Skill Analyzer의 오케스트레이션을 순차 듀얼 에이전트 → Plan-and-Execute + Critic 멀티 에이전트로 전환
> 범위: 풀스택 멀티 에이전트 로드맵의 **첫 번째 서브프로젝트(코어 전환)**

---

## 1. 배경과 패턴 선택

### 현재 상태

현재 `supervisor.py`는 단일 평면 StateGraph다.

```
resume → [github?] → call_model ↔ tools (Gap 루프) → generate
       → [match_rate≥80%?] → coach_call_model ↔ coach_tools → finalize_coach → END
```

순차 듀얼 에이전트(Gap 루프 + Coach 루프)로, 진정한 멀티 에이전트 오케스트레이션이 아니다. "Supervisor"는 사실상 `match_rate ≥ 80%` 조건부 엣지 한 줄이다.

### 왜 Supervisor 라우팅이 아니라 Plan-and-Execute인가

후보였던 Supervisor 동적 라우팅은 "매 턴 LLM이 다음 에이전트를 선택"하는 패턴이다. 그러나 이 도메인은 워크플로우가 거의 결정적(프로필 → 검색 → 갭 → 시장 → 코칭)이라, 매 턴 라우팅은 실익보다 전시 효과에 가깝고 "왜 동적인가"를 방어해야 하는 부담이 남는다.

이 프로젝트의 특성에 패턴을 맞춘 결과가 Plan-and-Execute다.

| 특성 | 함의 |
|------|------|
| 워크플로우가 거의 결정적 | 매 턴 라우팅의 실익이 약함 |
| 다중 입력 (PDF/텍스트/GitHub 조합) | 입력마다 "무엇을 조사할지"가 달라짐 → 여기에 동적성이 필요 |
| 약점 = RAGAS Faithfulness 0.0~0.29 | 생성-검증(Critic) 루프가 약점을 직접 공략 |
| 차별점 = "왜 믿을 수 있나" | 에이전트의 사고 과정(조사 계획)이 눈에 보여야 함 |

**핵심 통찰: 동적성을 "매 턴 라우팅"이 아니라 "입력별 조사 계획"과 "근거 검증 재계획"에 둔다.**

Plan-and-Execute의 이점:
1. 동적성이 정당함 — 입력 조합마다 계획이 달라지므로 "왜 동적인가"에 자연스럽게 답이 됨
2. Critic→Replan 루프가 Faithfulness를 구조적으로 공략하고 "왜 믿을 수 있나"를 코드로 증명
3. 비용 효율 — LLM 호출 2회+α (vs Supervisor 6~8회), 계획이 실행 경계를 정해 무한루프 위험이 낮음
4. "조사 계획"이 명시적 산출물이라 포트폴리오에서 보여주기 좋음
5. 병렬화(Send)가 Executor 단계에 자연스럽게 들어감

---

## 2. 범위

이번 서브프로젝트의 목표: **Plan-and-Execute + Critic 골격이 end-to-end로 동작하고, 배포 가능한 상태.**

- **포함:** Planner, Executor(병렬), Synthesizer, Critic, Replan 루프, 기존 Coach 연결
- **전제:** 현재 동작하는 미커밋 코드를 베이스라인으로 먼저 커밋 (회귀 기준점 확보)
- **제외(다음 서브프로젝트):** 에이전트 프롬프트 정교화, Market 스킬별 병렬, RAGAS 재측정, FastAPI/배포

신규 작성은 **Planner와 Critic 둘뿐**이며, 나머지는 오케스트레이션 머리만 교체해 기존 자산(8개 툴, 하이브리드 검색, Coach 루프)을 재사용한다.

---

## 3. 전체 그래프

```
START
  │
  ▼
Planner ◄───────────────────────┐  입력(PDF/텍스트/GitHub/직무) 보고
  │  "조사 계획" 수립             │  Plan 객체 생성 (+ replan 시 보강)
  ▼                              │
Executor (병렬 Send)             │
 ┌──────────┬──────────┬────────┐│  서로 독립이라 동시 실행
 │ Profile  │Retrieval │ Market ││  · Profile: PDF ∥ GitHub
 │(PDF∥GH)  │(직무요건)│(트렌드)││  · Retrieval: 직무 요구 스킬
 └────┬─────┴────┬─────┴───┬────┘│  · Market: 연봉·수요 트렌드
      └──────────┼─────────┘     │
                 ▼               │
              Gap (종합 비교)     │  Profile+Retrieval 결과로 갭 계산
                 ▼               │
            Synthesizer          │  gap_result JSON 생성
                 ▼               │
             Critic ─────────────┘  근거 충실성 검증
                 │  (불충분 → Replan, 상한 2회)
                 ▼  (충분)
              Coach (기존 루프 그대로) → END
```

**Profile·Retrieval·Market은 서로 독립**이라 동시 실행(Send)하고, **Gap만 그 결과에 의존**해 뒤에 온다.

---

## 4. 컴포넌트와 기존 코드 매핑

| 노드 | 역할 | 기존 코드 |
|------|------|-----------|
| **Planner** 🆕 | 입력 보고 조사 계획(Plan) 생성 | 신규 (LLM 호출 1회) |
| **Profile** | 스킬 추출 + confidence | `resume_agent` + `github_agent` 통합, PDF∥GitHub 병렬화 |
| **Retrieval** | 직무 요구 스킬 검색 | 기존 `graph_query` + `vector_search` 툴 |
| **Gap** | 보유 vs 요구 비교 | 기존 `call_model ↔ tools` 루프 (`gap_analysis`, `verify_skills`, `skill_unlock`) |
| **Market** | 연봉·수요 트렌드 | 기존 `posting_trend`, `market_insights` 툴 |
| **Synthesizer** | gap_result 종합 | 기존 `generate_report` 흡수 |
| **Critic** 🆕 | 근거 충실성 판정 + replan 여부 | 신규 (LLM-as-judge) |
| **Coach** | 이력서 개선 제안 | 기존 `coach_call_model ↔ coach_tools` 루프 그대로 |

---

## 5. 상태 스키마 (AppState 신규 필드)

기존 필드는 모두 유지하고 아래만 추가한다.

```python
# ── Plan-and-Execute ──
plan: dict | None              # Planner가 생성한 조사 계획
replan_count: int              # replan 횟수 (가드레일: 상한 2)

# ── Executor 산출 (병렬 노드가 각자 채움) ──
profile_result: dict | None    # Profile: 보유 스킬 + confidence
retrieved_context: list[dict]  # Retrieval: 직무 요구 근거 (Critic이 판정 근거로 사용)
market_result: dict | None     # Market: 연봉·수요 트렌드

# ── 검증 ──
critic_report: dict | None     # {faithful, unsupported_claims, needs_replan}
```

`retrieved_context`는 Critic이 "갭 주장 vs 실제 검색 근거"를 대조하는 재료이며, Faithfulness 공략의 물리적 연결고리다.

병렬 노드(Profile/Retrieval/Market)가 각기 다른 필드에 쓰므로 상태 쓰기 충돌이 없다.

---

## 6. Plan 객체 — 동적성이 사는 곳

```python
class Step(BaseModel):
    agent: Literal["profile", "retrieval", "market", "gap"]
    goal: str           # 이 step에서 알아내려는 것

class Plan(BaseModel):
    steps: list[Step]
    reason: str         # 왜 이 계획인지 (포트폴리오 시각화용)
```

입력 조합에 따라 Plan이 달라지는 것이 동적성의 정체다.

| 입력 | Planner가 세우는 계획 |
|------|----------------------|
| PDF만 | profile(PDF) → retrieval ∥ market → gap |
| PDF + GitHub | profile(PDF∥GitHub) → retrieval ∥ market → gap |
| resume_skills 주입 (RAGAS) | profile **스킵** → retrieval ∥ market → gap |

**역할 분리:** Plan의 `steps`는 "무엇을 조사할지(어떤 항목을 포함/제외할지)"만 정한다. 실행 순서와 병렬 여부는 Executor가 고정 의존성 규칙으로 결정한다 — `profile`/`retrieval`/`market`은 서로 독립이라 병렬 그룹, `gap`은 profile·retrieval 결과에 의존하므로 병렬 그룹 완료 후 단독 실행. 즉 Planner는 동적이지만 Executor의 의존성 위상은 고정이라, 동적성과 안정성이 분리된다.

---

## 7. Replan 루프 — 진짜 동적 분기

```
Critic 판정 → critic_report = {
    faithful: bool,
    unsupported_claims: ["LangGraph 갭 주장의 근거 약함", ...],
    needs_replan: bool
}

if needs_replan and replan_count < 2:
    → Planner로 복귀 (Command goto="planner", replan_count += 1)
      Planner는 critic_report를 보고 "약한 근거만 재조사"하는 보강 계획 수립
      (이미 충분한 step은 건너뜀)
else:
    → Coach로 진행
```

LangGraph `Command(goto=...)`로 replan 점프, `Send()`로 Executor 병렬을 구현한다. 두 API 모두 설치 버전에서 동작 확인 완료.

### Critic 판정 방법

- 입력: `gap_result`의 각 주장(예: `missing_required`의 reason) + `retrieved_context`(실제 공고 근거)
- LLM-as-judge: 주장별로 "이 근거가 실제로 이 주장을 뒷받침하는가?" 판정
- 출력: `faithful`(bool), `unsupported_claims`(list), `needs_replan`(bool)

---

## 8. 가드레일 (에러 처리)

| 상황 | 처리 |
|------|------|
| replan 무한 반복 | `replan_count >= 2`면 강제로 Coach 진행 |
| 병렬 노드 하나 실패 | 해당 결과 빈 값, 나머지 진행 (기존 try/except 패턴) |
| Critic LLM 실패 | `faithful=True`로 통과 (보수적 — 루프를 막지 않음) |
| Plan 파싱 실패 | 전체 step 기본 계획으로 fallback |

---

## 9. 테스트 전략

- **단위:** Plan 파싱 / 입력별 계획 생성(GitHub 유무, skills 주입) / replan 카운터 상한 / Critic 판정 파싱
- **통합:** end-to-end 입력 조합별 경로 / replan 발동 케이스(근거 약한 주장 주입 → replan 1회 발동 확인) / Profile PDF∥GitHub 병렬 동작
- **회귀:** 베이스라인 대비 `gap_result`·`final_report` 구조 유지

---

## 10. 구현 순서 (writing-plans에서 상세화)

1. **베이스라인 커밋** — 현재 동작 코드를 논리 단위로 커밋 (회귀 기준점)
2. **state.py** — AppState 신규 필드 추가 (의존성 없음)
3. **Plan 객체 + Planner 노드** — 입력별 계획 생성 + 단위 테스트
4. **Executor 병렬화** — Profile(PDF∥GitHub)·Retrieval·Market을 Send로 dispatch
5. **Synthesizer** — 기존 generate_report 흡수
6. **Critic 노드** — LLM-as-judge + critic_report
7. **Replan 루프** — Command 라우팅 + replan_count 가드레일
8. **그래프 재조립** — supervisor.py 재작성, 회귀 테스트

---

## 11. 다음 서브프로젝트 (이번 범위 밖)

- **Layer 6 배포** — FastAPI SSE + Docker + HF Spaces (코어 직후, 데모 URL 확보)
- **전문화 + 고도화** — 에이전트 프롬프트 정교화, Market 스킬별 병렬
- **평가** — RAGAS 재측정(특히 Faithfulness before/after), Langfuse에 plan·critic 트레이스
