# 홈페이지 정식화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 정적 프론트엔드(`web/index.html`, `web/style.css`)에 네비·히어로·사용법·푸터를 추가해 정식 서비스 홈페이지 형태로 만들되, 기존 분석 흐름(`app.js`)은 무변경으로 보존한다.

**Architecture:** 단일 페이지(`index.html`) 확장 + 앵커 스크롤. 기존 3박스(업로드/분석/결과)의 DOM id를 전부 보존해 `app.js` 계약을 유지한다. 회귀 가드로 "필수 id·신규 섹션 존재"를 검사하는 구조 테스트를 둔다. 백엔드·라우팅 변경 없음.

**Tech Stack:** 정적 HTML5 + CSS(변수 기반), FastAPI 정적 서빙, pytest(구조 검증).

---

## File Structure

- `web/index.html` — 페이지 구조 전면 개편(네비/히어로/사용법/기존3박스/푸터). 기존 id 보존.
- `web/style.css` — 신규 클래스(topnav/hero/how/footer) + 카드 그림자·간격 토큰 추가. 기존 규칙 유지.
- `tests/unit/test_homepage_structure.py` — 신규. `index.html` 문자열에 필수 id와 신규 섹션 마커가 존재하는지 검사(회귀 가드).

기존 보존 필수 id(13개): `top`(신규 body) 제외 — `file`, `upload-btn`, `upload-msg`, `step-upload`, `job-family`, `github-url`, `deploy-url`, `analyze-btn`, `analyze-msg`, `step-analyze`, `progress`, `result`, `step-result`.

---

### Task 1: 구조 회귀 테스트

**Files:**
- Create: `tests/unit/test_homepage_structure.py`

- [ ] **Step 1: Write the test**

`web/index.html`을 읽어 (1) `app.js`가 의존하는 기존 id가 전부 있는지, (2) 개편으로 추가될 신규 섹션 마커가 있는지 검사한다. BeautifulSoup 없이 단순 부분 문자열 검색으로 충분하다.

```python
# index.html이 app.js 계약(필수 id)과 신규 섹션을 모두 갖는지 검사하는 회귀 가드
from pathlib import Path

import pytest

HTML = (Path(__file__).resolve().parents[2] / "web" / "index.html").read_text(encoding="utf-8")

# app.js가 document.getElementById로 참조하는 id — 하나라도 빠지면 분석 흐름이 깨진다
REQUIRED_IDS = [
    "file", "upload-btn", "upload-msg", "step-upload",
    "job-family", "github-url", "deploy-url", "analyze-btn", "analyze-msg", "step-analyze",
    "progress", "result", "step-result",
]

# 홈페이지 개편으로 추가되는 섹션·앵커
NEW_MARKERS = [
    'class="topnav"', 'id="hero"', 'id="how"', 'id="contact"', 'class="cta"',
]


@pytest.mark.parametrize("anchor_id", REQUIRED_IDS)
def test_required_id_present(anchor_id):
    assert f'id="{anchor_id}"' in HTML, f"app.js가 쓰는 id 누락: {anchor_id}"


@pytest.mark.parametrize("marker", NEW_MARKERS)
def test_new_section_present(marker):
    assert marker in HTML, f"홈페이지 섹션 마커 누락: {marker}"
```

- [ ] **Step 2: Run test — 기존 id는 통과, 신규 마커는 실패**

Run: `pytest tests/unit/test_homepage_structure.py -v`
Expected: `test_required_id_present[*]` 13개 PASS, `test_new_section_present[*]` 5개 FAIL (아직 개편 전이라 마커 없음).

- [ ] **Step 3: Commit (테스트만)**

```bash
git add tests/unit/test_homepage_structure.py
git commit -m "test(web): 홈페이지 구조 회귀 가드 — 필수 id·신규 섹션 검사"
```

---

### Task 2: index.html 개편

**Files:**
- Modify: `web/index.html` (전면 교체)
- Test: `tests/unit/test_homepage_structure.py`

- [ ] **Step 1: index.html 전체 교체**

기존 `<header>`의 "관측 보기" 인라인 링크는 네비로 이동했으므로 제거한다. 3박스(업로드/분석/결과)는 마크업·id를 **그대로** 유지한다.

```html
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Job Skill Analyzer — 이력서 적합도 진단</title>
  <link rel="stylesheet" href="/web/style.css">
</head>
<body id="top">
  <nav class="topnav">
    <div class="nav-inner">
      <a href="#top" class="logo">Job Skill Analyzer</a>
      <div class="menu">
        <a href="#hero">소개</a>
        <a href="#how">사용법</a>
        <a href="#contact">문의</a>
        <a href="/observe">관측</a>
      </div>
    </div>
  </nav>

  <header class="hero" id="hero">
    <div class="hero-inner">
      <h1>이력서 한 장으로<br>직무 적합도를 진단하세요</h1>
      <p>GitHub·배포까지 교차검증하는 Agentic RAG 분석. 적합도와 그 판단의 신뢰도를 분리해 보여줍니다.</p>
      <a class="cta" href="#step-upload">지금 분석하기</a>
    </div>
  </header>

  <main>
    <section class="how" id="how">
      <h2>어떻게 작동하나요</h2>
      <div class="how-grid">
        <div class="how-card"><span class="num">1</span><h3>업로드</h3><p>PDF 이력서를 올립니다.</p></div>
        <div class="how-card"><span class="num">2</span><h3>조건 설정</h3><p>직군과 GitHub·배포 URL(선택)을 입력합니다.</p></div>
        <div class="how-card"><span class="num">3</span><h3>결과 확인</h3><p>핵심 역량 충족·검증 등급·개선 제안을 받습니다.</p></div>
      </div>
    </section>

    <!-- 1단계: 업로드 -->
    <section id="step-upload" class="card">
      <h2>1. 이력서 업로드</h2>
      <label for="file">이력서 (PDF)
        <input type="file" id="file" accept="application/pdf">
      </label>
      <button id="upload-btn">업로드</button>
      <p id="upload-msg" class="msg"></p>
    </section>

    <!-- 2단계: 분석 입력 -->
    <section id="step-analyze" class="card disabled">
      <h2>2. 분석 조건</h2>
      <label>직군
        <select id="job-family">
          <option>Software Engineer</option>
          <option>Data Engineer</option>
          <option>Data Analyst</option>
          <option>Data Scientist</option>
          <option selected>AI/LLM Engineer</option>
          <option>ML Engineer</option>
          <option>DevOps/SRE</option>
          <option>Security Engineer</option>
          <option>Frontend Engineer</option>
          <option>Architect</option>
        </select>
      </label>
      <label>GitHub URL (선택)
        <input type="url" id="github-url" placeholder="https://github.com/owner/repo">
      </label>
      <label>배포 URL (선택)
        <input type="url" id="deploy-url" placeholder="https://my-service.example.com">
      </label>
      <button id="analyze-btn">분석 시작</button>
      <p id="analyze-msg" class="msg"></p>
    </section>

    <!-- 3단계: 결과 -->
    <section id="step-result" class="card disabled">
      <h2>3. 결과</h2>
      <div id="progress" class="hidden"><span class="spinner"></span> 분석 중…</div>
      <div id="result"></div>
    </section>
  </main>

  <footer class="site-footer" id="contact">
    <div class="footer-inner">
      <span>© 2026 Job Skill Analyzer</span>
      <div class="footer-links">
        <a href="https://github.com/K-ismyname/jobgraphPJ">GitHub</a>
        <a href="mailto:dagahee0903@gmail.com">문의</a>
        <a href="/observe">관측</a>
      </div>
    </div>
  </footer>

  <script src="/web/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Run test — 전부 통과**

Run: `pytest tests/unit/test_homepage_structure.py -v`
Expected: 18개 전부 PASS (id 13 + 신규 마커 5).

- [ ] **Step 3: Commit**

```bash
git add web/index.html
git commit -m "feat(web): 홈페이지 구조 — 네비·히어로·사용법 3단계·푸터 추가"
```

---

### Task 3: style.css 스타일

**Files:**
- Modify: `web/style.css`

- [ ] **Step 1: `:root` 토큰 추가 + `html` smooth scroll**

`style.css` 1행의 `:root { ... }` 블록 끝(`--claimed:#9ca3af; }`)을 아래로 교체해 토큰 3개를 추가하고, 바로 다음 줄에 smooth scroll을 추가한다.

```css
:root { --fg:#1a1a2e; --muted:#6b7280; --line:#e5e7eb; --accent:#4f46e5;
  --verified:#16a34a; --corroborated:#d97706; --claimed:#9ca3af;
  --shadow:0 1px 3px rgba(0,0,0,.06); --shadow-card:0 2px 8px rgba(0,0,0,.05);
  --bg-accent:#f5f3ff; }
html { scroll-behavior: smooth; }
```

- [ ] **Step 2: `.card`에 그림자 추가**

`style.css`의 `.card { ... }` 규칙(현재 `padding:20px; margin-bottom:16px; }`로 끝남)에 그림자를 추가한다.

```css
.card { background:#fff; border:1px solid var(--line); border-radius:12px;
  padding:20px; margin-bottom:16px; box-shadow:var(--shadow-card); }
```

- [ ] **Step 3: 파일 끝에 홈페이지 신규 스타일 추가**

`style.css` 맨 끝에 아래를 덧붙인다. full-width 요소는 자체가 100%, 내부 `*-inner`만 720px로 본문과 좌우 정렬을 맞춘다. 앵커 대상이 sticky 네비에 가리지 않도록 `scroll-margin-top`을 준다.

```css
/* ── 홈페이지 ── */
.topnav { position:sticky; top:0; z-index:10; background:#fff;
  border-bottom:1px solid var(--line); box-shadow:var(--shadow); }
.nav-inner { max-width:720px; margin:0 auto; padding:12px 20px;
  display:flex; align-items:center; justify-content:space-between; }
.topnav .logo { font-weight:700; color:var(--accent); text-decoration:none; font-size:1.05rem; }
.topnav .menu a { color:var(--muted); text-decoration:none; margin-left:18px; font-size:.9rem; }
.topnav .menu a:hover { color:var(--accent); }

.hero { background:var(--bg-accent); }
.hero-inner { max-width:720px; margin:0 auto; padding:64px 20px; text-align:center; }
.hero h1 { margin:0 0 16px; font-size:2rem; line-height:1.3; }
.hero p { color:var(--muted); margin:0 0 24px; font-size:1rem; }
.cta { display:inline-block; background:var(--accent); color:#fff; text-decoration:none;
  padding:12px 28px; border-radius:8px; font-size:1rem; font-weight:600; }
.cta:hover { opacity:.92; }

.how { margin-bottom:24px; }
.how > h2 { font-size:1.1rem; margin:8px 0 12px; }
.how-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }
.how-card { background:#fff; border:1px solid var(--line); border-radius:12px;
  padding:18px; box-shadow:var(--shadow-card); }
.how-card .num { display:inline-flex; align-items:center; justify-content:center;
  width:26px; height:26px; border-radius:50%; background:var(--accent); color:#fff;
  font-size:.85rem; font-weight:700; }
.how-card h3 { margin:10px 0 4px; font-size:.95rem; }
.how-card p { margin:0; color:var(--muted); font-size:.85rem; }

/* 앵커가 sticky 네비에 가리지 않도록 */
#hero, #how, #step-upload, #contact { scroll-margin-top:64px; }

.site-footer { background:#fff; border-top:1px solid var(--line); margin-top:40px; }
.footer-inner { max-width:720px; margin:0 auto; padding:20px;
  display:flex; align-items:center; justify-content:space-between;
  color:var(--muted); font-size:.82rem; }
.footer-links a { color:var(--muted); text-decoration:none; margin-left:14px; }
.footer-links a:hover { color:var(--accent); }

@media (max-width:640px) {
  .how-grid { grid-template-columns:1fr; }
  .hero h1 { font-size:1.6rem; }
  .topnav .menu a { margin-left:12px; font-size:.82rem; }
  .footer-inner { flex-direction:column; gap:8px; text-align:center; }
  .footer-links a { margin:0 7px; }
}
```

- [ ] **Step 4: Commit**

```bash
git add web/style.css
git commit -m "feat(web): 홈페이지 스타일 — 네비·히어로·3단계 카드·푸터 + 카드 그림자 통일"
```

---

### Task 4: 통합 검증

**Files:** (없음 — 검증 전용)

- [ ] **Step 1: 전체 단위 테스트**

Run: `pytest tests/unit/ -q`
Expected: 기존 테스트 + `test_homepage_structure.py` 18개 모두 PASS. 프론트엔드 변경이라 다른 테스트에 영향 없음.

- [ ] **Step 2: 서버 띄워 육안 확인**

비어있는 포트로 실행(8000/8055/8060이 점유될 수 있음):

```bash
uvicorn src.api.main:app --port 8071
```

브라우저로 `http://localhost:8071/` 열어 확인:
- 네비가 스크롤해도 상단 고정, 메뉴 클릭 시 해당 섹션으로 부드럽게 이동(소개/사용법/문의)
- "관측" 클릭 시 `/observe`로 이동
- 히어로 '지금 분석하기' 클릭 시 업로드 섹션으로 스크롤
- 3단계 카드가 가로 3열, 창을 640px 이하로 좁히면 세로 1열
- 푸터에 저작권·GitHub·문의(mailto)·관측 표시

- [ ] **Step 3: 회귀 — 분석 흐름 동작 확인**

같은 서버에서 PDF 이력서 업로드 → 분석 시작 → 결과 렌더까지 정상 동작하는지 확인(DOM id 보존 검증). 업로드 버튼 활성화, 분석 박스 활성화, 결과 표시가 기존과 동일해야 한다.

- [ ] **Step 4: 서버 종료**

확인 끝나면 uvicorn 프로세스 종료(Ctrl+C 또는 해당 PID kill).
