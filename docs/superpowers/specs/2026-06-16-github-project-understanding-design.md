# GitHub 평가자 프로젝트 이해 강화 설계 (github_eval Project Understanding)

**작성일:** 2026-06-16
**대상:** `src/agent/evaluators/github_eval.py`, `src/agent/supervisor.py` + 테스트

## 목표

`github_eval`을 "스킬 단어 추출기"에서 **"프로젝트 이해기"** 로 강화한다. README·repo 설명·구조·의존성을 LLM이 읽어 repo별 프로필(무엇을 하는 프로젝트인지, 어떤 기술로 구현했는지, 무엇이 빠졌는지)을 생성한다. 이 프로필은 2단계(coach 재설계)의 근거가 된다.

## 배경

코칭이 "없는 스킬을 이력서에 써넣어라" 수준으로 애매했다. 더 전문적인 코칭(프로젝트를 보고 "이 프로젝트에 무엇을 더하면 좋은지")을 하려면, coach가 "스킬 목록"이 아니라 "프로젝트가 무엇인지"를 알아야 한다. 그 이해를 생산하는 게 이 단계다. 검증(신뢰도) 산출에 쓰는 스킬 추출은 결정적이어야 하므로, **이해(LLM)와 검증(단어 매칭)을 분리**한다.

## 범위

**포함:** `github_eval`이 repo별 프로필을 LLM으로 생성. README + repo description + topics + 파일 구조 + 의존성을 입력으로. 반환에 `profiles` 추가. supervisor가 openai 전달.

**제외:** coach 재설계(2단계, 별도 spec). portfolio_eval 강화(효과 본 뒤). 검증용 스킬 추출 로직 변경(그대로 유지).

## 현재 상태

- `create_github_evaluator(neo4j)` — openai 없음. `_eval_one(url, vocab)`이 언어·README·의존성에서 `_skills_from_sources`(vocab 단어 매칭)로 스킬 추출 → `{"github_eval": {"skills": [...]}}`.
- `supervisor.py:131` `github_eval = create_github_evaluator(neo4j)`. 바로 위 132행에서 `portfolio_eval`은 `openai_client`를 받는다.
- consensus는 평가자 출력의 `skills`만 사용.

## 설계

### 1. openai 주입

`create_github_evaluator(neo4j, openai_client)` 로 시그니처 확장. `supervisor.py:131`에서 `openai_client` 전달. openai가 None이면 프로필 생성을 건너뛰고 `profiles: []`(검증 스킬은 그대로 동작) — mock 모드 안전.

### 2. 입력 수집 (GitHub API)

기존 언어·README·의존성에 더해 **repo 엔드포인트**(`GET /repos/{owner}/{repo}`)에서 `description`과 `topics`를 가져온다(호출 1회 추가). README가 부실하면 description·topics·구조·의존성으로 보완.

### 3. repo별 프로필 생성 (LLM)

repo마다 아래를 LLM(gpt-4o-mini)에 주고 JSON 추출:
- 입력: README(전문, 길면 앞부분 절단) + description + topics + 파일 트리(이름 목록) + 의존성 텍스트.
- 출력:
```json
{
  "repo": "owner/repo",
  "summary": "이 프로젝트가 무엇을 하는지 한두 문장",
  "tech_stack": ["사용 기술"],
  "observations": ["눈에 띄는 점·빠진 것 — 예: Dockerfile 없음, 테스트 없음, CI 설정 없음"]
}
```
- `_profile_one(owner, repo, readme, description, topics, file_names, manifest_text, openai)` 헬퍼로 분리. LLM 호출 실패·파싱 실패 시 `summary`만 빈 프로필 반환(전체 흐름 중단 없음).

### 4. 검증용 스킬은 그대로

`_skills_from_sources`(vocab 단어 매칭) 유지. LLM 프로필의 `tech_stack`은 **검증에 쓰지 않는다**(환각 차단). 신뢰도(Verified)는 기존 결정적 매칭으로만.

### 5. 반환·state

- `evaluate` 반환: `{"github_eval": {"skills": [...합집합, 검증용], "profiles": [repo별 프로필]}}`.
- consensus는 `skills`만 쓰므로 **무변경**. `profiles`는 `state["github_eval"]`에 남아 2단계 coach가 사용.

## 영향받는 테스트

- `test_github_eval.py`: 기존 스킬 테스트(빈 결과 가드) 유지. `_profile_one`을 mock LLM 응답으로 파싱하는 단위 테스트 추가. `create_github_evaluator`에 openai 인자 추가 — 기존 테스트의 `create_github_evaluator(_FakeNeo4j(...))` 호출을 `create_github_evaluator(_FakeNeo4j(...), None)`로 갱신(openai None → 프로필 생략, 스킬 동작 동일).

## 검증

1. `pytest tests/unit/ -q` — 갱신·신규 테스트 통과.
2. 서버에서 실제 GitHub repo URL로 분석 → `state["github_eval"]["profiles"]`에 repo별 `summary`·`tech_stack`·`observations`가 채워지는지 확인(관측 페이지 evaluators 단계 또는 trace).

## 비고

- **비용** — repo당 gpt-4o-mini 1회 추가. 다중 URL이면 repo 수만큼.
- **GitHub API** — repo 엔드포인트 호출 1회 추가(rate limit 영향 미미, GITHUB_TOKEN 있으면 여유).
- 2단계(coach)가 이 `profiles`를 소비해 "이 프로젝트에 X를 더하면 직군 부족 스킬이 실증된다"는 코칭을 생성한다 — 별도 spec.
