# 코치 재설계 — 프로젝트 기반 코칭 (Coach: Project-Based)

**작성일:** 2026-06-16
**대상:** `src/agent/nodes.py`(coach 프롬프트·시드), `src/agent/tools.py`(coach 툴), `src/storage/neo4j_client.py`(CO_OCCURS 조회), `src/api/schemas.py`·`web/app.js`(출력), `src/analysis/coach.py`(삭제)

## 목표

코칭을 "부족 스킬을 이력서 문장으로 써넣기"(부정직·공허)에서 **"GitHub 프로젝트를 보고 무엇을 더하면 좋은지"** 로 바꾼다. 1단계에서 만든 repo별 프로젝트 프로필 + 직군 부족 스킬 + 연계 스킬(CO_OCCURS)을 근거로, 프로젝트 보강 제안과 연계 학습 추천을 생성한다.

## 배경

기존 coach는 갭의 부족 스킬마다 "그 스킬을 포함한 이력서 문장"을 지어냈다 — 갖지도 않은 스킬을 써넣으라는 격이라 애매했다(이력서 원문도 안 봄). 1단계로 `github_eval`이 repo별 프로필(summary·tech_stack·observations)을 생산하므로, coach가 이를 받아 "이 프로젝트는 RAG 시스템인데 Docker·CI가 없으니, 추가하면 직군 부족 스킬이 코드로 실증된다" 같은 전문 코칭을 낼 수 있다.

## 범위

**포함:** coach 입력에 GitHub 프로필 추가, 연계 스킬 툴(CO_OCCURS), `_COACH_SYSTEM_PROMPT` 재작성, 출력 스키마(프로젝트 보강 + 연계 학습) 변경, 표시 갱신, `coach.py`(미사용) 삭제.

**제외:** portfolio 프로필(1단계 github만 함). capability_fit(coach는 그래프 내부라 미접근 — gap의 부족 스킬 사용).

## 현재 상태

- `nodes.py:288-292` `coach_init` = gap 분석 결과(JSON)만. github 프로필 없음.
- `nodes.py` `_COACH_SYSTEM_PROMPT` = "부족 스킬마다 이력서 개선 문장 작성".
- `tools.py:209` `create_coach_tools(neo4j)` = `verify_suggestion`(공고 근거)만.
- `schemas.py` `ReportResponse`: `coaching_summary`, `suggestions: list[SuggestionItem]`(target_section·missing_skill·rewritten_text…).
- `app.js` `renderReport`: `suggestions`를 "스킬 → 섹션" 카드로 표시.
- consensus·gap·신뢰도 흐름은 무변경.

## 설계

### 1. coach 입력 — GitHub 프로필 추가

`generate_report`(synthesizer)의 `coach_init`에 `state["github_eval"]["profiles"]`를 함께 넣는다:
```
"아래 갭 분석 + GitHub 프로젝트 프로필을 바탕으로 코칭하세요.\n"
+ gap_json + "\n[GitHub 프로젝트]\n" + profiles_json
```
프로필이 없으면(GitHub 미입력) 그 섹션을 비우고 연계 학습 위주로.

### 2. 연계 스킬 — CO_OCCURS 툴

- `neo4j_client.get_co_occurring_skills(skills: list[str], top_n: int = 8) -> list[str]`: 주어진 스킬들과 `CO_OCCURS`로 연결된 스킬을 가중치 합 상위로, 입력 스킬 제외.
- `create_coach_tools`에 `related_skills(skills)` 툴 추가 — 보유 스킬을 주면 연계 스킬 반환. coach가 학습 추천에 사용. 기존 `verify_suggestion`은 유지(프로젝트 보강 근거 확인용).

### 3. `_COACH_SYSTEM_PROMPT` 재작성

두 종류 코칭, "없는 스킬 써넣기" 금지:
1. **프로젝트 보강** — 각 프로필의 `summary`·`tech_stack`·`observations`와 직군 부족 스킬을 보고, "이 repo에 무엇을 추가/발전시키면 부족 스킬이 코드로 실증되는가". observations(Docker 없음 등)를 우선 활용.
2. **연계 학습** — `related_skills`로 보유 스킬의 인접 스킬 중 미보유를 학습 추천.

### 4. 출력 스키마

```python
class ProjectSuggestion(BaseModel):
    repo: str           # 없으면 "" (일반 제안)
    add_skill: str      # 추가하면 좋은 스킬
    why: str            # 직군/실증 관점 이유
    how: str            # 이 프로젝트에 어떻게 적용

class LearningRecommendation(BaseModel):
    skill: str
    reason: str         # 어떤 보유 스킬과 연계되는지

# ReportResponse
coaching_summary: str | None
project_suggestions: list[ProjectSuggestion]
learning_recommendations: list[LearningRecommendation]
```
기존 `suggestions: list[SuggestionItem]`를 위 두 필드로 대체.

### 5. 표시

- `app.js` `renderReport`: "이력서 개선 제안" 섹션을 **"프로젝트 보강"**(repo·add_skill·why·how) + **"배우면 좋은 연계 스킬"**(skill·reason) 두 블록으로.
- `observe.js` coach 단계: `project_suggestions`/`learning_recommendations` 개수 표시.

### 6. 정리

`src/analysis/coach.py`(미사용 dead code) 삭제.

## 영향받는 테스트

- `nodes.py`/coach 파싱 관련 단위 테스트가 있으면 새 출력 키로 갱신.
- `neo4j_client.get_co_occurring_skills` — 실 Neo4j 통합 테스트(연계 스킬 반환) 추가.
- `schemas` 테스트 — 새 필드 검증.
- `test_api_mapping` — coaching 매핑을 새 구조로.

## 검증

1. `pytest tests/unit/ -q` — 갱신·신규 테스트 통과.
2. 서버에서 GitHub URL 포함 분석 → 결과의 "프로젝트 보강"이 그 repo의 observations(Docker 없음 등)와 직군 부족 스킬을 연결하는지, "연계 스킬"이 보유 스킬과 실제 CO_OCCURS로 이어지는지 육안.

## 비고

coach가 그래프 내부라 `capability_fit`(post-calc)은 못 쓴다 — 대신 gap의 부족 스킬을 근거로 한다(같은 "직군 요구 대비 부족" 정보). 프로젝트별 코칭은 1단계의 repo별 프로필이 있어야 의미가 크므로, GitHub가 없으면 연계 학습 추천 위주로 자연스럽게 축소된다.
