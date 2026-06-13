# Web UI 설계 — 이력서 분석 데모 (정적 HTML+JS)

**작성일:** 2026-06-13
**목적:** Job Skill Analyzer를 포트폴리오 공개 데모로 쓸 수 있는 단일 웹페이지. 면접관·타인이 URL로 접속해 이력서를 올리고 적합도·신뢰도·코칭 결과를 본다.

---

## 범위

**포함:** 이력서 업로드 → 직군 선택(+선택적 GitHub/배포 URL) → 분석 → 결과(적합도·신뢰도·검증 스킬·코칭) 표시. 단일 페이지, 단일 흐름.

**제외(2차):** 공고/연봉 대시보드(`/jobs`·`/jobs/trending-skills`·`/jobs/salary`는 API로 이미 동작하나 화면은 추후). 로그인·계정·결과 영속 저장. 모바일 최적화는 best-effort(데스크톱 우선).

---

## 아키텍처

- 프론트엔드는 **정적 HTML+JS 한 장**. 빌드 도구·프레임워크 없음.
- **FastAPI가 정적 파일을 직접 서빙** → 프론트와 API가 같은 origin → **CORS 불필요**. HF Spaces 한 컨테이너에 그대로 포함된다.
- 기존 v3 API 엔드포인트를 그대로 소비한다(신규 백엔드 로직 없음).

```
브라우저 (web/index.html + app.js + style.css)
   │  fetch (same-origin)
   ▼
FastAPI (src/api/main.py)
   GET /                     → index.html
   /web/*                    → 정적 자산 (StaticFiles)
   POST /portfolio/upload    → report_id
   POST /portfolio/analyze   → 분석 시작(백그라운드)
   GET  /portfolio/report/{id} → 결과 폴링
```

---

## 화면 흐름 (단일 페이지, 3단계)

페이지는 세 영역(업로드 / 분석입력 / 결과)을 위→아래로 두고, 단계가 진행되면 다음 영역을 활성화한다.

### 1. 업로드
- PDF 파일 선택 또는 드래그&드롭.
- `POST /portfolio/upload` (multipart `file`) → `UploadResponse {report_id, candidate_name_hint, page_count, text_length}`.
- `report_id`를 JS 상태에 보관. `candidate_name_hint`·페이지 수를 "업로드됨: OOO (N쪽)"로 표시.
- 실패(비-PDF 등): 에러 메시지, 다음 단계 비활성.

### 2. 분석 입력
- **직군 드롭다운** — JobFamily 10개를 옵션으로(Software Engineer / Data Engineer / Data Analyst / Data Scientist / AI/LLM Engineer / ML Engineer / DevOps/SRE / Security Engineer / Frontend Engineer / Architect). 기본값 "AI/LLM Engineer".
- **GitHub URL**(선택), **배포 URL**(선택) 텍스트 입력.
- "분석 시작" 버튼 → `POST /portfolio/analyze {report_id, job_family, github_url?, deploy_url?}` → `202 AnalyzeAccepted {status:"processing"}`.

### 3. 진행 → 결과
- `status=processing` 동안 `GET /portfolio/report/{report_id}`를 **3초 간격 폴링**. 스피너 + "분석 중…" 표시. 최대 폴링 시간(예: 5분) 초과 시 타임아웃 안내.
- `status=done`이면 결과 카드 렌더:
  - **적합도** — `match_rate`를 0~100% 게이지/숫자로. (두 축 중 "맞는 스킬을 가졌나")
  - **신뢰도** — `confidence_level`(high/medium/low) 배지 + 검증 분포 `verification_counts {Verified, Corroborated, Claimed}`. (두 축 중 "그 판단이 검증됐나")
  - **검증된 스킬** — `verified_skills[]`: 스킬명 + 등급 배지(Verified/Corroborated/Claimed) + 출처(`sources`) 칩.
  - **코칭** — `coaching_summary` + `suggestions[]`: 부족 스킬·개선 문장(`rewritten_text`)·기대효과·우선순위 배지, `verified`면 표시.
  - `advice` 텍스트.
- `status=error`이면 `error_detail` 표시.

---

## 파일 구조

```
web/
  index.html      # 마크업 (3개 섹션)
  app.js          # 상태·fetch·폴링·렌더링
  style.css       # 카드 기반 미니멀 스타일
src/api/main.py   # StaticFiles 마운트 + GET / → index.html (수정)
```

- `app.js`는 단계별 함수로 분리(`uploadResume`, `startAnalysis`, `pollReport`, `renderReport`). 전역 상태는 `report_id` 하나.
- 외부 JS 라이브러리 없음(바닐라). 게이지 등은 CSS로.

---

## 디자인 톤

- 깔끔한 미니멀, 카드 기반. 시스템 폰트. 좁은 중앙 컬럼(읽기 편한 폭).
- **두 축(적합도 ⊥ 신뢰도)을 시각적으로 분리** 강조 — 이 프로젝트의 핵심 설계를 화면에서 드러낸다.
- 검증 등급은 색으로 구분(Verified=강조색, Corroborated=중간, Claimed=옅음).

---

## 에러 처리

| 상황 | 처리 |
|------|------|
| 비-PDF 업로드 / 업로드 4xx | 업로드 영역에 에러 메시지, 분석 비활성 |
| 분석 응답 4xx (잘못된 직군 등) | 입력 영역에 에러 메시지 |
| report `status=error` | `error_detail` 카드 표시 |
| 폴링 타임아웃 | "분석이 지연됩니다. 잠시 후 다시 시도" 안내 |
| 네트워크 실패 | fetch catch → 사용자向 안내 |

---

## 테스트

- 백엔드 API는 기존 테스트로 커버됨(신규 로직 없음).
- **신규**: `GET /`가 200·HTML(`text/html`)을 반환하고, 정적 자산 경로가 200을 반환하는지 스모크 테스트(TestClient).
- UI 상호작용(업로드→폴링→렌더)은 수동 확인(정적 파일이라 자동 테스트 비용 대비 가치 낮음).

---

## 비결정 사항(구현 중 확정)

- 게이지 시각화 방식(원형 vs 막대) — CSS로 단순 막대부터.
- 직군 목록을 하드코딩 vs `/jobs` 계열에서 동적 로드 — MVP는 하드코딩(API 의존 줄임).
