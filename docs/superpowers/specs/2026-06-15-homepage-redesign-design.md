# 홈페이지 정식화 설계 (Homepage Redesign)

**작성일:** 2026-06-15
**대상:** `web/index.html`, `web/style.css` (정적 프론트엔드, FastAPI가 같은 출처로 서빙)

## 목표

이력서 분석 도구를 단순 업로드→분석→결과 나열에서 벗어나, 네비게이션·히어로·사용법 안내·푸터를 갖춘 **정식 서비스 홈페이지**처럼 보이게 한다. 기존 분석 흐름과 로직(`app.js`)은 건드리지 않는다.

## 범위

**포함:** `index.html` 구조 확장 + `style.css` 스타일 추가/정리.
**제외:**
- `app.js` 로직 — 무변경. 기존 DOM id를 모두 보존한다.
- 적합도 로직(추천 직군 스킬 레벨화 등) — 별개 작업, 이 spec 밖.
- `observe.html` — 이번엔 손대지 않는다.

## 현재 상태

`index.html`은 `<main>`(max-width 720px) 안에 `<header>` + 3개 `<section class="card">`(업로드/분석/결과)만 있다. 네비·히어로·사용법·푸터가 없다. `style.css`는 카드·버튼·결과 스타일을 보유하고 보라 포인트(`--accent:#4f46e5`)를 쓴다.

## 페이지 구조 (위→아래)

```
<body>
  <nav class="topnav">       ← 화면 상단 고정(sticky), full-width
  <header class="hero">      ← 히어로, full-width 배경
  <main>                     ← max-width 720px 중앙 (기존 폭 유지)
    <section class="how">    ← "어떻게 작동하나요" 3단계 카드
    <section id="step-upload">   ← 기존, 그대로
    <section id="step-analyze">  ← 기존, 그대로
    <section id="step-result">   ← 기존, 그대로
  </main>
  <footer class="site-footer">  ← 푸터, full-width
```

### 1. 네비게이션 바 `<nav class="topnav">`

- 좌측: 로고 텍스트 `Job Skill Analyzer` (`<a href="#top">`, 보라색·굵게).
- 우측: 메뉴 링크 — `소개`(`#hero`), `사용법`(`#how`), `문의`(`#contact`, 푸터), `관측`(`/observe`).
- `position: sticky; top: 0;` + 흰 배경 + 하단 경계선 + 약한 그림자. 스크롤해도 따라온다.
- `<html>`에 `scroll-behavior: smooth;` — 앵커 클릭 시 부드럽게 이동. sticky 네비에 가리지 않도록 앵커 대상에 `scroll-margin-top: 64px;`.

### 2. 히어로 `<header class="hero" id="hero">`

- 헤드라인 `<h1>`: "이력서 한 장으로\n직무 적합도를 진단하세요" (두 줄).
- 설명 `<p>`: "GitHub·배포까지 교차검증하는 Agentic RAG 분석. 적합도와 그 판단의 신뢰도를 분리해 보여줍니다."
- 버튼 `<a class="cta" href="#step-upload">지금 분석하기</a>` — 업로드 섹션으로 스크롤.
- 가운데 정렬, 위아래 넉넉한 여백(64px), 연한 보라 배경(`#f5f3ff`)로 본문과 구분.

### 3. 사용법 `<section class="how" id="how">`

- 제목 `<h2>`: "어떻게 작동하나요".
- 3개 카드 가로 배치(`.how-grid`, flex/grid):
  1. **업로드** — "PDF 이력서를 올립니다"
  2. **조건 설정** — "직군과 GitHub·배포 URL(선택)을 입력합니다"
  3. **결과 확인** — "핵심 역량 충족·검증 등급·개선 제안을 받습니다"
- 각 카드: 번호 배지(보라 원) + 소제목 + 한 줄 설명. 기존 `.card`와 같은 그림자·radius로 통일.
- 모바일(≤640px)에서는 세로 1열.

### 4. 기존 3박스 (업로드/분석/결과)

- 마크업·id·동작 **그대로 유지** (`step-upload`, `step-analyze`, `step-result`, `file`, `upload-btn`, `upload-msg`, `job-family`, `github-url`, `deploy-url`, `analyze-btn`, `analyze-msg`, `progress`, `result`).
- 통일 작업만: 카드 그림자를 공통 변수로, 섹션 제목 `<h2>` 위 여백 일정하게. 기존 `<header>`의 "관측 보기" 인라인 링크는 네비로 옮겼으니 제거.

### 5. 푸터 `<footer class="site-footer" id="contact">`

- 저작권: `© 2026 Job Skill Analyzer`.
- 링크: `GitHub`(저장소 URL), `문의`(`mailto:dagahee0903@gmail.com`), `관측`(`/observe`).
- 연한 배경 + 상단 경계선, 가운데 정렬, 작은 글씨.

## CSS 변경 (`style.css`)

- `:root`에 토큰 추가: `--shadow: 0 1px 3px rgba(0,0,0,.06);` `--shadow-card: 0 2px 8px rgba(0,0,0,.05);` `--bg-accent:#f5f3ff;`.
- `html { scroll-behavior: smooth; }`.
- `.card`에 `box-shadow: var(--shadow-card);` 추가(현재 그림자 없음) — 카드에 입체감, 통일.
- 신규 클래스: `.topnav`, `.topnav .logo`, `.topnav .menu a`, `.hero`, `.hero h1`, `.cta`, `.how`, `.how-grid`, `.how-card`, `.how-card .num`, `.site-footer`.
- full-width 요소(`.topnav`/`.hero`/`.site-footer`)는 자체가 가로 100%, 내부 콘텐츠만 `max-width:720px; margin:0 auto;`로 본문과 좌우 정렬을 맞춘다.
- 반응형: `@media (max-width:640px)`에서 `.how-grid` 1열, 네비 메뉴 글자 축소.
- 보라 포인트(`--accent`)·시스템 폰트 유지. 새 색은 보라 계열(`#f5f3ff`)만 추가.

## 검증

1. `uvicorn src.api.main:app --port <free>` 후 브라우저로 `/` 육안 확인: 네비 고정·앵커 스크롤·히어로·3단계·푸터·반응형(창 좁히기).
2. **회귀:** 업로드→분석→결과 흐름이 그대로 동작하는지(=DOM id 보존 확인). 파일 선택→업로드→분석 시작→결과 렌더까지.
3. `/observe` 링크 이동 정상.
4. 기존 단위 테스트는 프론트엔드와 무관하므로 영향 없음(확인차 `pytest tests/unit/` 1회).

## 비고

단일 페이지 + 앵커 스크롤이라 라우팅·백엔드 변경이 없다. "소개/사용법"을 별도 페이지로 분리하지 않는 이유는 콘텐츠가 짧아 한 페이지 스크롤로 충분하고, 페이지를 늘리면 정적 서빙 경로만 복잡해지기 때문이다(YAGNI).
