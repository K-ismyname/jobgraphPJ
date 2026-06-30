# 결과 화면 재설계 — 5개 스킬 구조

## 배경 / 목적

현재 이력서 분석 결과 화면은 **적합도 점수(예: 40/100 게이지)**를 핵심 지표로 보여준다. 그런데 이 점수는:

- 직군 핵심 스킬 10개 중 보유 개수를 단순 환산 — 스킬별 중요도(공고 빈도)를 무시
- "40점"이 사용자에게 어떤 행동을 하라는 건지 안 와닿음 (actionable하지 않음)

또한 연계 스킬 추천 멘트가 일반론("Operations Research: 문제 해결에 도움됩니다")이라 도움이 안 된다.

**목적:** 점수 중심 화면을 **행동가능한 5개 스킬 구조**로 재설계한다.

## 5개 구조

| # | 항목 | 의미 | 데이터 출처 |
|---|---|---|---|
| ① | 충족한 스킬 | 직군이 요구하고 이미 보유 | `capability_fit.met` (+ 신뢰도) |
| ② | 채우면 좋을 스킬 | 직군이 요구하나 **없는** 스킬 → 학습 대상 | `learning_recommendations` |
| ③ | 코드로 보강할 스킬 | 비슷한 걸 하고 있어 GitHub 코드에 추가하면 실증 | `project_suggestions` |
| ④ | 설명 | ②③ 각 스킬이 **왜 필요한지** | ②의 `reason`, ③의 `why` |
| ⑤ | 코칭 | ②는 학습법, ③은 코드 추가법 | ②의 `how`(신설), ③의 `how` |

④⑤는 평면 항목이 아니라 ②③ 각 스킬에 붙는 속성이다. 화면은 **3개 묶음**(충족 / 채울 것 / 보강할 것)이고, 채울 것·보강할 것 각각에 설명+코칭이 딸린다.

## 화면 레이아웃

```
[신뢰도]  검증 3 · 교차확인 2 · 주장 1        ← 점수 게이지 없음

① 충족한 스킬
   React✓  TypeScript✓  Docker✓  Python✓     ← 가로 배지 + 신뢰도

② 채우면 좋을 스킬 (직군 요구하나 없음 → 학습)
   ┌──────────────────────────────────┐
   │ Kubernetes                       │
   │ 왜: <직군 요구 근거>              │  ← ④ 설명
   │ 어떻게: <학습 방향>              │  ← ⑤ 코칭 (신설)
   └──────────────────────────────────┘

③ 코드로 보강할 스킬 (GitHub 기반)
   ┌──────────────────────────────────┐
   │ docker-compose  (owner/repo)     │
   │ 왜: <보강 이유>                  │  ← ④ 설명
   │ 어떻게: <레포 파일 기준 추가법>  │  ← ⑤ 코칭 (기존 how)
   └──────────────────────────────────┘
```

## 변경 범위

### 백엔드

**`src/api/schemas.py` — `LearningRecommendation`에 `how` 필드 추가**
- 현재: `{skill, reason}`
- 변경: `{skill, reason, how}` — `how`는 ⑤ 학습 코칭

**`src/api/routers/portfolio.py` — `how` 매핑 추가**
- `learning_recommendations` 변환 시 `how` 포함

**`src/agent/nodes.py` — `_COACH_SYSTEM_PROMPT` 강화**
- `learning_recommendations` 출력 형식: `{skill, reason, how}`로 확장
- `reason`(④ 설명): 일반론 금지. "이 직군 공고에서 어떻게 요구되는지 + 보유 스킬과의 연결"을 담도록 지침 + 좋은/나쁜 예시 추가 (interview_coaching처럼)
- `how`(⑤ 학습 코칭): "무엇부터, 어떤 순서로, 보유 스킬을 어떻게 발판으로" 구체적 학습 방향
- `related_skills` 툴 결과(CO_OCCURS)를 ② 근거로 활용

### 프론트

**`web/app.js` — `renderReport` 재작성**
- 제거: 적합도 게이지(`metrics`의 적합도 부분), 코칭 `summary`, `renderInterviewCoaching` 호출
- 유지: 상단 신뢰도 카운트(`verification_counts`)
- ① 충족: `capability_fit.met`를 가로 배지로 — `renderReport` 안에서 직접 렌더 (기존 `renderSkillBadges` 재사용, 이미 충족만 표시하도록 수정됨)
- ② 채울 것: `learning_recommendations`를 `{skill, reason(설명), how(코칭)}` 카드로
- ③ 보강: `project_suggestions`를 `{add_skill, why(설명), how(코칭), repo}` 카드로

**`web/app.js` — `renderCapability` 함수 제거**
- ① 충족 배지는 `renderReport`로 흡수했으므로 `renderCapability` 함수 자체를 삭제
- 그에 딸린 추천 직군(`recommended_families`)·공통 스킬(`common_skill_fit`) 렌더도 함께 사라짐

**`web/style.css`**
- 검증된 스킬 가로 배치용 — 기존 `.cap`(inline-block) 재사용, `.skill-row`(세로)는 미사용 처리

### 제외 (백엔드 데이터는 유지, 화면 렌더링만 제거)

- 적합도 게이지 — 제거 확정
- 면접 코칭(`interview_coaching`) — 화면에서 제거. 데이터 생성·`/observe`는 유지
- 추천 직군(`recommended_families`) — 화면 제거
- 공통 기초 스킬(`common_skill_fit`) — 화면 제거

되살리기 쉽도록 백엔드 생성 로직과 스키마는 건드리지 않는다.

## 검증

- 로컬 서버(`uvicorn src.api.main:app`) 기동 후 이력서+GitHub로 분석 실행 → 결과 화면이 5개 구조로 렌더되는지 육안 확인
- ② 카드에 `reason`(설명)과 `how`(코칭)가 모두 채워지는지, 멘트가 일반론이 아닌 구체적 근거인지 확인
- ③ 카드에 기존 `why`/`how`가 정상 표시되는지 확인
- 면접 코칭·추천 직군·공통 스킬·게이지가 화면에서 사라졌는지 확인

## 비범위 (이번에 하지 않음)

- 공통 스킬 threshold 조정 — 별도로 이미 처리(5→7)
- 직군 데이터 추가 보강 — 별도 과제
- verify_skills 근거(`required_section`) 결손 — 별도 과제
- 면접 코칭 기능 자체의 개선/삭제 — 화면에서만 숨김
