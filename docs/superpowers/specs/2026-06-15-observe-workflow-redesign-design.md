# 관측 페이지 개선 설계 (Observe Workflow Redesign)

**작성일:** 2026-06-15
**대상:** `web/observe.html`, `web/observe.js`, `web/style.css`, `/stats` 풀스택(orphan) 제거

## 목표

관측 페이지에서 데이터 탭을 제거하고, 워크플로우 탭을 "이 판단이 어떻게 나왔나"를 시각적으로 따라가는 단독 화면으로 재구성한다. 실제 분석 데이터 흐름(요청 1)과 다이어그램(요청 2)을 묶는다.

## 범위

**포함:**
- `observe.html` — 탭 UI·`panel-data` 제거, 워크플로우 단독.
- `observe.js` — 데이터 탭 로직 제거, 흐름 요약 띠 + 수치 배지 추가.
- `style.css` — 흐름 띠·배지·다이어그램 강조 스타일.
- `/stats` 풀스택 제거(orphan): `src/api/routers/stats.py`, `main.py`의 import·`include_router`, `schemas.py`의 `StatsResponse`·`JobFamilyStat`, `tests/integration/test_stats.py`.

**제외:**
- `/graph` 엔드포인트(`system.py`) — 무변경.
- 적합도 로직(추천 직군 스킬 레벨화 등) — 별개 작업.
- `index.html` 홈페이지 — 무변경.

## 현재 상태

`observe.html`은 탭 2개(`tab-workflow`/`tab-data`)와 패널 2개(`panel-workflow`/`panel-data`)를 가진다. `observe.js`는 탭 전환(`showTab`), 워크플로우(`loadWorkflow`→`/graph`+`/portfolio/report/{id}`, `renderWorkflow`/`renderStage`/`stageData`), 데이터(`loadData`→`/stats`)를 담는다. `/stats`는 `observe.js`에서만 호출된다(`grep` 확인).

워크플로우 탭은 Mermaid 다이어그램(실행 노드 강조) + 6단계 카드(설명 + 텍스트 데이터)가 세로로 나열돼, 다이어그램과 데이터가 시각적으로 분리돼 있다.

## 설계

### 1. 데이터 탭 + `/stats` 제거

- `observe.html`: `<div class="tabs">…</div>`와 `<section id="panel-data">` 삭제. `panel-workflow`만 남기고 `card` 래퍼 유지. 헤더 `<p class="sub">`에서 "데이터 현황" 문구 제거 → "분석 워크플로우가 어떻게 도는지 봅니다."
- `observe.js`: `showTab`, 탭 이벤트 리스너, `loadData`, `dataLoaded`, 진입부 `initTab` 분기 제거. 진입 시 `loadWorkflow()` 직접 호출.
- 백엔드: `main.py`에서 stats import·`include_router` 2줄 삭제, `routers/stats.py` 삭제, `schemas.py`의 `StatsResponse`·`JobFamilyStat` 삭제, `tests/integration/test_stats.py` 삭제.

### 2. 흐름 요약 띠 (워크플로우 최상단)

데이터가 단계를 거치며 어떻게 변했는지 한 줄. report가 있을 때만 렌더, `trace`/`capability_fit`에서 프론트가 계산:

```
스킬 12 추출 → 합의 8(Verified 5) → 부족 역량 2 → 적합도 4/6 → 교정 1 → 제안 3
```

| 항목 | 출처 |
|---|---|
| 추출 N | `trace.evaluators`의 고유 스킬 수(소스 합집합) |
| 합의 M (Verified k) | `trace.consensus.skills.length`, 그중 `verification==="Verified"` 개수 |
| 부족 역량 | `capability_fit.unmet.length` |
| 적합도 N/M | `capability_fit.met.length` / (`met`+`unmet`) |
| 교정 | `trace.critic.corrected` |
| 제안 | `trace.coach.suggestion_count` |

### 3. 강조 다이어그램

Mermaid 구조(`/graph`의 mermaid)는 그대로. 실행 경로를 또렷하게:
- 실행된 노드(`trace.executed_nodes`): 진한 보라 채움(현행 유지·강화).
- **실행 안 된 노드: 흐리게(opacity 낮춤)** — 실제 지나간 길이 한눈에 보이도록 `classDef`로 dim 처리.
- report 없으면 강조 없이 구조만(현행).

### 4. 수치 배지 카드

6단계 카드 헤더에 핵심 수치를 배지로, 설명은 그 아래. report 있을 때만 배지 표시:

| 단계 | 배지 |
|---|---|
| evaluators | `소스 3` `스킬 12` |
| consensus | `Verified 5` `Corroborated 2` `Claimed 1` |
| gap_loop | `반복 1회` `도구 2` |
| fit | `적합도 4/6` |
| critic | `제거 1` `교정 1` |
| coach | `제안 3` |

배지 아래에 기존 `stageData()` 상세는 유지. report 없으면 "분석을 실행하면 실제 데이터가 채워집니다" 안내(현행).

### 5. 데이터 없을 때(분석 전 진입)

흐름 띠 자리에 "분석을 실행하면 실제 데이터 흐름이 채워집니다" 안내. 다이어그램 + 단계 설명은 데이터 없이도 표시 → 시스템 설명서 역할 유지.

## 백엔드

`/graph`(구조+stage 설명) 그대로. 흐름 띠·배지 수치는 모두 프론트가 `/portfolio/report/{id}`의 `trace`·`capability_fit`에서 계산 → 백엔드 추가 없음.

## 검증

1. `pytest tests/unit/ -q` — 프론트·stats 제거가 단위 테스트에 영향 없음 확인(stats는 integration이라 unit 무관).
2. 서버 기동 후 `/stats` → 404(제거 확인), `/observe` → 200.
3. report_id 없이 `/observe`: 탭 없이 다이어그램 + 단계 설명만, 흐름 띠 자리에 안내.
4. report_id 있는 URL(`/observe?report_id=…`): 흐름 띠·강조 다이어그램·배지 카드 표시 육안 확인.

## 비고

데이터 탭은 시스템 규모(공고·스킬 수)를 보여줬으나, 관측의 본래 목적("판단 근거 추적")과 어긋나 산만했다. 제거로 페이지가 한 가지 목적에 집중한다. `/stats`를 함께 지우는 것은 내 변경이 만든 orphan을 정리하는 것이며, 다른 호출처가 없음을 `grep`으로 확인했다.
