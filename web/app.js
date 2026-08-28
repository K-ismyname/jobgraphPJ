// 이력서 분석 데모 — 업로드→분석→폴링→결과 렌더 (바닐라 JS)
const state = { reportId: null, portfolioReportId: null };
const POLL_INTERVAL_MS = 3000;
const MAX_POLL_ATTEMPTS = 200; // 백엔드 분석 유실 판단(10분)과 맞춤

const $ = (id) => document.getElementById(id);

// innerHTML 삽입 전 HTML 이스케이프 — 이력서 파생 텍스트의 self-XSS 방지
const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
  .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");

// href용 — http/https만 허용해 javascript: 등 스킴 XSS 차단 (esc는 스킴을 못 막음)
const safeUrl = (u) => {
  try {
    const p = new URL(String(u ?? ""));
    return p.protocol === "http:" || p.protocol === "https:" ? p.href : "";
  } catch {
    return "";
  }
};

function setMsg(el, text, isError = false) {
  el.textContent = text;
  el.classList.toggle("error", isError);
}

// 1. 업로드
async function uploadResume() {
  const file = $("file").files[0];
  if (!file) return setMsg($("upload-msg"), "PDF 파일을 선택하세요.", true);
  const fd = new FormData();
  fd.append("file", file);
  setMsg($("upload-msg"), "업로드 중…");
  try {
    const res = await fetch("/portfolio/upload", { method: "POST", body: fd });
    if (!res.ok) {
      const e = await res.json().catch(() => ({}));
      return setMsg($("upload-msg"), `업로드 실패: ${e.detail || res.status}`, true);
    }
    const data = await res.json();
    state.reportId = data.report_id;
    setMsg($("upload-msg"), `업로드됨: ${data.candidate_name_hint} (${data.page_count}쪽)`);
    $("step-analyze").classList.remove("disabled");
  } catch (err) {
    setMsg($("upload-msg"), `네트워크 오류: ${err.message}`, true);
  }
}

// 1-b. 포트폴리오 PDF 업로드 (선택)
async function uploadPortfolio() {
  const file = $("portfolio-file").files[0];
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  setMsg($("portfolio-msg"), "업로드 중…");
  try {
    const res = await fetch("/portfolio/upload-portfolio", { method: "POST", body: fd });
    if (!res.ok) {
      const e = await res.json().catch(() => ({}));
      return setMsg($("portfolio-msg"), `실패: ${e.detail || res.status}`, true);
    }
    const data = await res.json();
    state.portfolioReportId = data.portfolio_report_id;
    setMsg($("portfolio-msg"), `업로드됨 (${data.page_count}쪽)`);
  } catch (err) {
    setMsg($("portfolio-msg"), `네트워크 오류: ${err.message}`, true);
  }
}

// 2. 분석 시작
async function startAnalysis() {
  if (!state.reportId) return;
  const body = {
    report_id: state.reportId,
    job_family: $("job-family").value,
    github_urls: collectUrls("github-urls"),
    deploy_urls: collectUrls("deploy-urls"),
    access_key: sessionStorage.getItem("access_key") || "",
    ...(state.portfolioReportId ? { portfolio_report_id: state.portfolioReportId } : {}),
  };
  setMsg($("analyze-msg"), "");
  try {
    const res = await fetch("/portfolio/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const e = await res.json().catch(() => ({}));
      // 429: 데모 일일 한도(3회) 초과 — 관리자 키 있으면 입력 후 무제한
      if (res.status === 429) {
        const k = prompt("오늘 데모 분석 한도(3회)에 도달했습니다.\n관리자 키가 있으면 입력하세요 (없으면 취소):");
        if (k) { sessionStorage.setItem("access_key", k); return startAnalysis(); }
        return setMsg($("analyze-msg"), e.detail || "오늘 데모 한도(3회)를 모두 사용했습니다. 내일 다시 시도하세요.", true);
      }
      return setMsg($("analyze-msg"), `분석 시작 실패: ${e.detail || res.status}`, true);
    }
    $("step-result").classList.remove("disabled");
    $("progress").classList.remove("hidden");
    $("result").innerHTML = "";
    pollReport(0);
  } catch (err) {
    setMsg($("analyze-msg"), `네트워크 오류: ${err.message}`, true);
  }
}

// 3. 폴링 (3초 간격, 최대 200회 = 10분)
async function pollReport(attempt) {
  if (attempt > MAX_POLL_ATTEMPTS) {
    $("progress").classList.add("hidden");
    $("result").innerHTML = "<p class='msg error'>분석이 지연됩니다. 잠시 후 다시 시도하세요.</p>";
    return;
  }
  try {
    const res = await fetch(`/portfolio/report/${state.reportId}`);
    if (!res.ok) {
      // 4xx(만료된 report_id 등)는 재시도해도 무의미 — 즉시 중단
      if (res.status >= 400 && res.status < 500) {
        $("progress").classList.add("hidden");
        $("result").innerHTML = `<p class='msg error'>결과를 찾을 수 없습니다 (HTTP ${res.status}).</p>`;
        return;
      }
      throw new Error(`HTTP ${res.status}`);
    }
    const data = await res.json();
    if (data.status === "processing") {
      $("progress").innerHTML = `<span class="spinner"></span> ${esc(data.phase || "분석 중…")}`;
      setTimeout(() => pollReport(attempt + 1), POLL_INTERVAL_MS);
      return;
    }
    $("progress").classList.add("hidden");
    if (data.status === "error") {
      $("result").innerHTML = `<p class='msg error'>분석 오류: ${esc(data.error_detail) || "알 수 없음"}</p>`;
      return;
    }
    renderReport(data);
  } catch (err) {
    setTimeout(() => pollReport(attempt + 1), POLL_INTERVAL_MS);
  }
}

// 신뢰도 등급 한국어 라벨 (class는 영문 유지 — CSS .badge.Verified 등)
const TRUST_KO = { Verified: "검증됨", Corroborated: "교차확인", Claimed: "주장" };
const trustKo = (v) => TRUST_KO[v] || v || "-";

// 신뢰도 용어 설명 범례
const TRUST_LEGEND = `
  <div class="legend">
    <div class="lg"><span class="dotc Verified"></span><b>검증됨</b><span class="en">Verified</span> — GitHub 코드·배포 URL로 실제 확인</div>
    <div class="lg"><span class="dotc Corroborated"></span><b>교차확인</b><span class="en">Corroborated</span> — 2개 이상 출처가 일치</div>
    <div class="lg"><span class="dotc Claimed"></span><b>주장</b><span class="en">Claimed</span> — 이력서 진술만, 코드 미확인</div>
  </div>`;

function renderSkillBadges(met) {
  // 충족한 스킬만 표시 — 미충족은 '배우면 좋은 연계 스킬' 섹션에서 다룬다.
  return (met || []).map((m) =>
    `<span class="cap met">${esc(m.skill)} ✓ <span class="badge ${esc(m.verification)}">${trustKo(m.verification)}</span></span>`).join("");
}

// 4. 결과 렌더 — 5개 스킬 구조 (충족 / 채울 것 / 보강)
function renderReport(d) {
  const counts = d.verification_counts || {};
  const cf = d.capability_fit || {};
  const understanding = d.project_understanding || {};

  // ① 충족한 스킬 — 직군 핵심 중 보유 (가로 배지 + 신뢰도)
  const met = renderSkillBadges(cf.met);
  const hasProjectCoaching = Boolean(
    understanding.one_liner || understanding.architecture || understanding.data_flow
    || (d.evidence_cards || []).length || (d.project_roadmap || []).length
    || (d.project_suggestions || []).length || (d.portfolio_sentences || []).length
  );
  const hasVerifiedEvidence = (counts.Verified || 0) + (counts.Corroborated || 0) > 0;
  const githubProfiles = (((d.trace || {}).coach || {}).github_profiles || []);
  const githubNotice = (!hasProjectCoaching && !hasVerifiedEvidence)
    ? `<div class="notice">
        GitHub 코드 근거가 잡히지 않아 프로젝트 이해·코드 근거 카드가 비어 있습니다.
        ${githubProfiles.length ? "관측 페이지에서 GitHub 분석 결과를 확인하세요." : "GitHub URL이 제대로 입력됐는지 확인하고 다시 분석해 주세요."}
      </div>`
    : "";

  const coachingSummary = d.coaching_summary
    ? `<h3>코칭 요약</h3><div class="suggestion rich-section"><div class="head">${esc(d.coaching_summary)}</div></div>`
    : "";

  const designChoices = (understanding.core_design_choices || [])
    .map((x) => `<li>${esc(x)}</li>`)
    .join("");
  const projectUnderstanding = (
    understanding.one_liner || understanding.architecture || understanding.data_flow || designChoices
  ) ? `<h3>프로젝트 이해</h3>
    <div class="suggestion rich-section">
      ${understanding.one_liner ? `<div class="head">${esc(understanding.one_liner)}</div>` : ""}
      ${understanding.architecture ? `<div class="rew">구조: ${esc(understanding.architecture)}</div>` : ""}
      ${understanding.data_flow ? `<div class="prio">흐름: ${esc(understanding.data_flow)}</div>` : ""}
      ${designChoices ? `<ul class="compact-list">${designChoices}</ul>` : ""}
    </div>` : "";

  const evidenceCards = (d.evidence_cards || [])
    .map((s) => `<div class="suggestion evidence-card">
      <div class="head">${esc(s.skill)}</div>
      ${s.evidence ? `<div class="prio">근거: ${esc(s.evidence)}</div>` : ""}
      ${s.what_it_shows ? `<div class="rew">${esc(s.what_it_shows)}</div>` : ""}
      ${s.interview_angle ? `<div class="prio">면접: ${esc(s.interview_angle)}</div>` : ""}
    </div>`)
    .join("");

  const roadmap = (d.project_roadmap || [])
    .map((s, i) => `<div class="suggestion">
      <div class="head">${i + 1}. ${esc(s.step || "프로젝트 보강")}</div>
      ${s.why ? `<div class="prio">왜: ${esc(s.why)}</div>` : ""}
      ${s.how ? `<div class="rew">어떻게: ${esc(s.how)}</div>` : ""}
    </div>`)
    .join("");

  const portfolioSentences = (d.portfolio_sentences || [])
    .map((s) => `<div class="sentence">${esc(s)}</div>`)
    .join("");

  const interviewCoaching = (d.interview_coaching || [])
    .map((s) => `<div class="suggestion interview-card ${esc(s.type || "strength")}">
      <div class="head">${s.type === "gap" ? "갭 대응" : "강점 어필"} · ${esc(s.title)}</div>
      <div class="rew">${esc(s.coaching)}</div>
    </div>`)
    .join("");

  // ② 채우면 좋을 스킬 — 없는 직군 핵심 → 학습 (왜 + 어떻게)
  const learnings = (d.learning_recommendations || [])
    .map((s) => `<div class="suggestion">
      <div class="head">${esc(s.skill)}</div>
      <div class="prio">왜: ${esc(s.reason)}</div>
      ${s.how ? `<div class="rew">어떻게: ${esc(s.how)}</div>` : ""}</div>`)
    .join("");

  // ③ 코드로 보강할 스킬 — GitHub 기반 (왜 + 어떻게)
  const projects = (d.project_suggestions || [])
    .map((s) => `<div class="suggestion">
      <div class="head">${esc(s.add_skill)}${s.repo ? ` <span class="prio">(${esc(s.repo)})</span>` : ""}</div>
      <div class="prio">왜: ${esc(s.why)}</div>
      <div class="rew">어떻게: ${esc(s.how)}</div></div>`)
    .join("");

  // 지원해볼 만한 회사 — 검증 스킬 매칭 + 지원 링크 있는 공고
  const postings = (d.recommended_postings || [])
    .map((p) => `<div class="skill-row">
      <span>${esc(p.title)}${p.company ? ` · ${esc(p.company)}` : ""}</span>
      <span class="prio">${Math.round(p.match_pct || 0)}% 매칭</span>
      ${safeUrl(p.url) ? `<a class="src" href="${esc(safeUrl(p.url))}" target="_blank" rel="noopener">지원 →</a>` : ""}</div>`)
    .join("");

  $("result").innerHTML = `
    <div class="trust-pills">
      <span class="tpill Verified">● 검증됨 ${counts.Verified || 0}</span>
      <span class="tpill Corroborated">● 교차확인 ${counts.Corroborated || 0}</span>
      <span class="tpill Claimed">● 주장 ${counts.Claimed || 0}</span>
    </div>
    ${TRUST_LEGEND}
    <h3>충족한 스킬</h3>
    <div>${met || "<p class='prio'>없음</p>"}</div>
    ${coachingSummary}
    ${githubNotice}
    ${projectUnderstanding}
    ${evidenceCards ? `<h3>코드 근거 기반 강점</h3>${evidenceCards}` : ""}
    ${interviewCoaching ? `<h3>면접 코칭</h3>${interviewCoaching}` : ""}
    ${portfolioSentences ? `<h3>포트폴리오 문장</h3><div class="sentence-box">${portfolioSentences}</div>` : ""}
    ${learnings ? `<h3>채우면 좋을 스킬</h3>${learnings}` : ""}
    ${projects ? `<h3>코드로 보강할 스킬</h3>${projects}` : ""}
    ${roadmap ? `<h3>프로젝트 보강 로드맵</h3>${roadmap}` : ""}
    ${postings ? `<h3>지원해볼 만한 회사</h3>${postings}` : ""}
    <p style="margin-top:16px"><a href="/observe?report_id=${encodeURIComponent(state.reportId)}&tab=workflow">→ 이 분석의 실행 과정 보기</a></p>
    <p style="margin-top:8px"><button id="delete-report" class="ghost" type="button">리포트 삭제</button></p>
  `;
  $("delete-report").addEventListener("click", deleteCurrentReport);
}

async function deleteCurrentReport() {
  if (!state.reportId) return;
  if (!confirm("이 분석 리포트와 업로드된 파일을 삭제할까요?")) return;
  try {
    const deletions = [
      fetch(`/portfolio/report/${encodeURIComponent(state.reportId)}`, { method: "DELETE" }),
    ];
    if (state.portfolioReportId) {
      deletions.push(fetch(`/portfolio/upload-portfolio/${encodeURIComponent(state.portfolioReportId)}`, { method: "DELETE" }));
    }
    const results = await Promise.all(deletions);
    const failed = results.find((res) => !res.ok && res.status !== 404);
    if (failed) throw new Error(`HTTP ${failed.status}`);
    state.reportId = null;
    state.portfolioReportId = null;
    $("result").innerHTML = "<p class='msg'>리포트를 삭제했습니다.</p>";
    $("progress").classList.add("hidden");
    $("step-result").classList.add("disabled");
  } catch (err) {
    $("result").innerHTML = `<p class='msg error'>삭제 실패: ${esc(err.message)}</p>`;
  }
}

// URL 입력칸 수집·추가
function collectUrls(containerId) {
  const seen = new Set();
  return Array.from(document.querySelectorAll(`#${containerId} input`))
    .flatMap((i) => {
      const raw = i.value.trim().replace(/\\_/g, "_");
      const urls = raw.match(/https?:\/\/[^\s)\]]+/g);
      return urls || (raw ? [raw] : []);
    })
    .map((u) => u.replace(/[.,;]+$/g, ""))
    .filter((u) => u && !seen.has(u) && seen.add(u));
}
function addUrlField(containerId, placeholder) {
  const row = document.createElement("div");
  row.className = "url-row";
  const input = document.createElement("input");
  input.type = "url";
  input.placeholder = placeholder;
  const del = document.createElement("button");
  del.type = "button";
  del.className = "url-del";
  del.textContent = "×";
  del.addEventListener("click", () => row.remove());
  row.append(input, del);
  document.getElementById(containerId).appendChild(row);
}
$("add-github").addEventListener("click", () => addUrlField("github-urls", "https://github.com/owner/repo"));
$("add-deploy").addEventListener("click", () => addUrlField("deploy-urls", "https://my-service.example.com"));

$("upload-btn").addEventListener("click", uploadResume);
$("portfolio-upload-btn").addEventListener("click", uploadPortfolio);
$("analyze-btn").addEventListener("click", startAnalysis);
$("admin-key").addEventListener("click", (e) => {
  e.preventDefault();
  const cur = sessionStorage.getItem("access_key") || "";
  const k = prompt("관리자 키를 입력하면 이 탭에서 무제한으로 분석할 수 있습니다.\n(비우고 확인하면 해제)", cur);
  if (k === null) return;
  if (k) { sessionStorage.setItem("access_key", k); alert("관리자 키 저장됨 — 이 탭에서 무제한 분석"); }
  else { sessionStorage.removeItem("access_key"); alert("관리자 키 해제 — 하루 3회 제한"); }
});
