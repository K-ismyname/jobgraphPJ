# 관측 페이지 설계 — 워크플로우 실행 추적 + 데이터 현황

**작성일:** 2026-06-13
**목적:** 이 시스템이 "어떻게 도는지"를 보여주는 단일 관측 페이지(`/observe`). 한 번의 분석이 에이전트 그래프를 거치는 과정과, 그 바탕이 되는 데이터 현황을 두 탭으로 제공한다. 포트폴리오 데모(작동 방식 시각화)이자 개발·디버깅 수단.

---

## 범위

**포함:**
- **워크플로우 탭** — 한 분석(`report_id`)이 거친 단계를 사후 요약으로 표시(평가자·합의·gap 루프·critic·coach).
- **데이터 탭** — Neo4j/Chroma 적재 현황(직군별 공고·스킬 수, 전체 통계, 청크 수).

**제외(YAGNI):**
- 실시간 진행 스트리밍(SSE/WebSocket) — 사후 요약으로 충분.
- Langfuse 임베드 — 외부 의존·키 필요, 우리 도메인 밖.
- 메인 분석 결과 화면의 적합도 표현 개선(% + 체크리스트 + 추천 스킬) — **별도 백로그**(이 spec과 무관, 계산은 그대로).

---

## 아키텍처

기존 정적 프론트(same-origin, FastAPI 서빙) 패턴을 그대로 따른다.

- `web/observe.html` + `web/observe.js`(+ 기존 `web/style.css` 재사용). 상단 탭 2개.
- FastAPI에 `GET /observe` → `observe.html` 라우트 추가(기존 `GET /` 패턴과 동일).
- 워크플로우 데이터: `run_supervisor`가 `final_report`에 `trace`를 추가 → `ReportResponse.trace` → 폴링 시 함께 옴(추가 호출 없음).
- 데이터 현황: 새 `GET /stats` 엔드포인트(Neo4j 집계 + Chroma count). 트렌드·연봉은 기존 `/jobs/*` 재사용.

```
web/observe.html + observe.js  (탭: 워크플로우 / 데이터)
   │ fetch (same-origin)
   ▼
FastAPI
   GET /observe                  → observe.html
   GET /portfolio/report/{id}    → ReportResponse(+trace)   # 워크플로우 탭
   GET /stats                    → 데이터 현황              # 데이터 탭 (신규)
   GET /jobs/trending-skills     → 트렌드 (기존 재사용)
```

---

## 워크플로우 탭

### trace 데이터 구조

`run_supervisor`가 그래프 실행 결과 state에서 조립해 `final_report["trace"]`에 넣는다. 모두 result state에 이미 존재하는 정보다(신규 LLM 호출 없음, 결정적 조립).

```python
trace = {
  "evaluators": [            # 돌린 평가자 (입력에 있던 소스만)
    {"source": "resume", "skill_count": 12},
    {"source": "github", "skill_count": 8},
  ],
  "consensus": {"Verified": 5, "Corroborated": 3, "Claimed": 9},   # 검증 등급 분포
  "gap_loop": {
    "tool_calls": ["gap_analysis", "verify_skills", "vector_search"],  # 호출된 도구(중복 제거)
    "iterations": 2,         # call_model 반복 횟수
  },
  "critic": {"removed": 1, "corrected": 2},   # 환각 제거·검증 라벨 교정 건수
  "coach": {"suggestion_count": 4},
}
```

조립 출처:
- `evaluators`: `resume_eval`/`github_eval`/`portfolio_eval`/`deploy_eval` 중 None 아닌 것 + 각 `skills` 길이.
- `consensus`: `build_verification_summary(consensus)["counts"]` 재사용.
- `gap_loop.tool_calls`: `messages` 중 `ToolMessage`의 `name` 집합. `iterations`: `iteration` 값.
- `critic`: `critic_report`의 제거/교정 건수.
- `coach`: `coaching_result`/`suggestions` 길이.

### 표시

그래프 단계 순서대로 타임라인/카드:
1. **평가자** — 돌린 소스별 칩(이력서 12개, GitHub 8개 …)
2. **합의** — Verified/Corroborated/Claimed 막대 또는 칩
3. **Gap 루프** — 호출 도구 목록 + 반복 횟수
4. **Critic** — 제거 N·교정 M
5. **Coach** — 제안 N개

진입 경로: 메인 분석(`/`) 결과 화면에 "실행 과정 보기" 링크 → `/observe?report_id=<id>&tab=workflow`. observe.js가 쿼리스트링의 `report_id`로 `GET /report/{id}` 호출해 `trace` 렌더. `report_id` 없으면 "분석을 먼저 실행하세요" 안내.

---

## 데이터 탭

### `GET /stats` 응답

```python
{
  "job_families": [
    {"name": "Software Engineer", "posting_count": 105, "skill_count": 256},
    ...   # 10개 직군
  ],
  "totals": {"postings": 274, "skills": <n>, "relations": <n>},
  "chroma_chunks": <n>,
}
```

조립:
- `job_families`: `MATCH (f:JobFamily)<-[:INSTANCE_OF]-(jp) ... count(jp)` + 직군별 REQUIRES 스킬 distinct 수.
- `totals`: 전체 JobPosting·Skill 노드 수, REQUIRES|PREFERS 관계 수.
- `chroma_chunks`: `chroma` 컬렉션 count (ChromaClient에 count 메서드 없으면 추가).

### 표시
- 직군 10개 표/막대: 공고 수·스킬 수.
- 전체 통계 카드: 공고·스킬·관계·청크 수.
- (선택) 트렌드 스킬: `GET /jobs/trending-skills` 재사용해 직군 선택 시 상위 스킬.

---

## 데이터 흐름·스키마 변경

- `src/api/schemas.py`: `ReportResponse`에 `trace: dict | None = None` 추가. 새 `StatsResponse` 모델.
- `src/agent/supervisor.py`(또는 nodes.py finalize_coach): `final_report`에 `trace` 조립 추가.
- `src/api/routers/portfolio.py`: `_map_final_report`가 `trace`를 `ReportResponse`로 전달.
- 새 라우터 또는 main.py: `GET /stats`(Neo4j·Chroma 집계), `GET /observe`(observe.html).

---

## 에러 처리

| 상황 | 처리 |
|------|------|
| `/observe`에 `report_id` 없음 | 워크플로우 탭에 "분석을 먼저 실행하세요" 안내 |
| `report_id`의 report에 `trace` 없음(구버전/에러 분석) | "실행 추적 정보 없음" 표시 |
| `/stats` Neo4j 실패 | 503 + 데이터 탭에 오류 메시지 |
| Chroma count 실패 | `chroma_chunks: null`, 나머지는 정상 표시 |

---

## 테스트

- `GET /observe` 200·HTML 반환(기존 `test_static_serving` 패턴).
- `GET /stats` 형태 검증(통합, 실 Neo4j): `job_families` 10개, `totals.postings > 0`.
- `trace` 조립 로직 단위 테스트: mock result state → trace의 evaluators/consensus/gap_loop/critic 키·값 검증(DB·LLM 불필요).
- UI 상호작용은 수동 확인(정적 파일).

---

## 비결정 사항(구현 중 확정)

- 타임라인 시각화: 세로 카드 목록부터(단순). 화살표 연결은 CSS 여유 시.
- ChromaClient.count: 메서드 없으면 `collection.count()` 래퍼 추가.
