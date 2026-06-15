# 다중 GitHub/배포 URL 입력 설계 (Multi-URL Input)

**작성일:** 2026-06-15
**대상:** 프론트(`index.html`/`app.js`) + API(`schemas`/`portfolio`) + 에이전트(`state`/`supervisor`/`github_eval`/`deploy_eval`)

## 목표

분석 조건에서 GitHub URL과 배포 URL을 "+ 추가" 버튼으로 여러 개 입력하고, 각 URL을 검증해 스킬을 합집합으로 모은다. 단수 필드를 복수로 완전히 교체한다.

## 범위

**포함:** GitHub·배포 URL 둘 다 다중화. 입력칸 동적 추가 UI + 백엔드 단수→복수 전환 + 평가자 순회.

**제외:** 이력서 PDF(1개 유지), 개수 상한(두지 않음 — 빈 칸만 거름), GitHub 평가 로직 자체(순회만 추가, 스킬 추출 방식 불변).

## 현재 상태

- `app.js:43-44` — `github_url: $("github-url").value || null`, `deploy_url` 동일(단일).
- `schemas.AnalyzeRequest:30-31` — `github_url: str|None`, `deploy_url: str|None`.
- `portfolio.py:91` — `run_supervisor(..., github_url=req.github_url, deploy_url=req.deploy_url, ...)`.
- `supervisor.run_supervisor:206-216` — 파라미터 `github_url`/`deploy_url`. 입력 가드(227)·`initial` state(249-250)에 단수.
- `supervisor.routing_after_resume:101-106` — `state.get("github_url")` 있으면 `Send("github_eval")`, deploy 동일.
- `github_eval.py:92` — `url = state.get("github_url")` 단일 처리 → `{github_eval: {skills}}`.
- `deploy_eval.py:42` — `url = state.get("deploy_url")` 단일 → `{deploy_eval: {skills}}`.
- `state.py:26-27` — `github_url: str|None`, `deploy_url: str|None`.

## 설계

### 1. 프론트 (`index.html` + `app.js`)

- GitHub URL·배포 URL 각 그룹을 컨테이너(`#github-urls`, `#deploy-urls`)로 감싸고, 첫 입력칸 1개 + "+ 추가" 버튼(`#add-github`, `#add-deploy`).
- "+ 추가" 클릭 → 해당 컨테이너에 입력칸 한 줄 추가(삭제 `×` 버튼 포함). 첫 칸은 삭제 버튼 없음.
- 전송 시 컨테이너 내 모든 input 값을 모아 빈 값 제외 배열로: `github_urls`, `deploy_urls`.

### 2. API (`schemas` + `portfolio`)

- `AnalyzeRequest`: `github_url`/`deploy_url` 제거, `github_urls: list[str] = []`, `deploy_urls: list[str] = []` 추가.
- `portfolio.py:91` 호출: `github_urls=req.github_urls, deploy_urls=req.deploy_urls`.

### 3. 에이전트 (`state` + `supervisor` + evaluators)

- `state.py`: `github_url`/`deploy_url` → `github_urls: list[str]`, `deploy_urls: list[str]`.
- `run_supervisor`: 파라미터 `github_url`→`github_urls: list[str] = []`, `deploy_url`→`deploy_urls`. 입력 가드(227)·`initial`(249-250) 갱신.
- `routing_after_resume`: `state.get("github_urls")`(비어있지 않으면) `Send("github_eval")` 1번, deploy 동일.
- `github_eval`: `for url in (state.get("github_urls") or [])` 순회, 각 URL의 스킬을 모아 합집합(스킬명 기준 중복 제거) → `{github_eval: {skills}}`. URL 파싱 실패·레포 미지정은 건너뛰고 다음 URL 진행.
- `deploy_eval`: `for url in (state.get("deploy_urls") or [])` 순회, 합집합 반환.

### 4. consensus

`github_eval`/`deploy_eval`이 합쳐 반환하므로 `consensus.py`는 변경 없음(노드 출력 키 동일).

## 영향받는 테스트

- `run_supervisor`·`AnalyzeRequest`의 `github_url`/`deploy_url`를 참조하는 단위·통합 테스트를 복수 필드로 갱신.
- `github_eval`/`deploy_eval` 다중 URL 순회 테스트 추가(2개 URL → 합집합, 빈 리스트 → 빈 스킬).

## 검증

1. `pytest tests/unit/ -q` — 갱신·신규 테스트 통과.
2. 서버 기동 후 `/`에서 GitHub URL 2개 + 배포 URL 1개 입력 → 분석. 각 URL 스킬이 결과에 반영되는지 육안.
3. "+ 추가"/`×` 버튼 동작, 빈 칸이 전송에서 제외되는지 확인.

## 비고

평가자를 LangGraph map-Send(URL당 노드 인스턴스)로 띄우지 않고 **노드 내부 순회**로 처리한다 — 결과 state 키(`github_eval`) 충돌이 없고, 합집합 로직이 한곳에 모여 단순하다. URL 개수가 수백 개가 아닌 이상(현실적으로 한 자릿수) 순차 처리로 충분하다.
