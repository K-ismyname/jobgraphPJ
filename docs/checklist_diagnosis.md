# 진단 체크리스트 (2026-06-29)

## 🔴 Critical — 즉시 수정

- [x] **C-1a** `tests/unit/test_build_trace.py` 2개 실패 수정
  - `test_build_trace_assembles_from_state`: state에 `messages` 대신 `"gap_trace": {"tool_calls": [...], "iterations": 2}` 주입으로 변경
  - `test_build_trace_empty_state_safe`: `executed_nodes == []` 로 기대값 수정 (or synthesizer 항상 추가로 코드 변경 — H-1과 연계)

- [x] **C-1b** `tests/integration/test_agent.py` 2개 실패 수정
  - `test_graph_has_gap_loop_nodes`: `call_model`이 서브그래프 내부로 이동 → 최상위 노드 기대값에서 제거
  - `test_graph_has_coach_nodes`: `coach_call_model`이 서브그래프 내부 → 최상위 기대값에서 제거

---

## 🟠 High — 곧 수정

- [x] **H-1** `synthesizer` 를 `gap_result` 가드 밖으로 빼기
  - 위치: [nodes.py:233-235](../src/agent/nodes.py#L233-L235)
  - 현재: `if state.get("gap_result"): executed.append("synthesizer")`
  - 수정: 가드 바깥으로 이동 (실제 그래프에선 항상 실행됨, 테스트 기대와도 일치)

- [x] **H-2** `gap_analyzer.py` 데드코드 정리
  - 위치: [src/analysis/gap_analyzer.py](../src/analysis/gap_analyzer.py) 전체
  - `run_gap_analysis`가 `src/` 어디서도 import 안 됨 (테스트에서만 사용)
  - 실제 갭 분석은 [tools.py:58](../src/agent/tools.py#L58) `gap_analysis` 툴이 담당
  - 선택지: (a) `gap_analyzer.py` 삭제 후 `test_gap_analyzer.py`도 제거, (b) tools.py가 이를 호출하도록 통합
  - CLAUDE.md는 `gap_analyzer.py`를 정본으로 명시 → 결정 후 CLAUDE.md도 업데이트

---

## 🟡 Medium — 개선 권장

- [x] **M-1** `create_nodes(tools, neo4j)` 죽은 파라미터 제거
- [x] **M-2** 바인딩만 되고 안 쓰이는 툴 제거 (`market_insights`, `graph_query`)
- [x] **M-3** `_STRENGTH_PRIORITY` 하드코딩 — ponytail 주석으로 의도 명시

---

## 🟢 Low — 나중에

- [ ] **L-1** `gap_trace.iterations` 라벨링 명확화
  - 위치: [nodes.py:419-422](../src/agent/nodes.py#L419-L422)
  - `iterations` = `call_model` 호출 수 (마지막 리포트 생성 call 포함), 실제 tool round 수 ≠ 이 값
  - 관측 페이지에 "LLM 판단 횟수" 또는 "tool round 수 = `len(tool_calls)`" 로 표시 방식 정리

- [ ] **L-2** 서브그래프 `messages` 전파 회귀 방지 테스트
  - 위치: [supervisor.py:169-184](../src/agent/supervisor.py#L169-L184)
  - gap_agent 1회 왕복 후 부모 `messages` 길이가 중복 없이 정확한지 검증하는 테스트 추가

---

## 진행 순서 (권장)

1. C-1a + H-1 묶기 → `synthesizer` 항상 추가 + 테스트 gap_trace 계약으로 갱신
2. C-1b → 통합 테스트 서브그래프 기대값 수정
3. H-2 → gap_analyzer 처리 방향 결정 후 실행
4. M-1~M-3 → 한 커밋으로 묶어 처리
5. L-1~L-2 → 여유 있을 때
