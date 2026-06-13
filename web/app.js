// 이력서 분석 데모 — 업로드→분석→폴링→결과 렌더 (바닐라 JS)
const state = { reportId: null };

const $ = (id) => document.getElementById(id);

// innerHTML 삽입 전 HTML 이스케이프 — 이력서 파생 텍스트의 self-XSS 방지
const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
  .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");

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

// 2. 분석 시작
async function startAnalysis() {
  if (!state.reportId) return;
  const body = {
    report_id: state.reportId,
    job_family: $("job-family").value,
    github_url: $("github-url").value || null,
    deploy_url: $("deploy-url").value || null,
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

// 3. 폴링 (3초 간격, 최대 100회 = 5분)
async function pollReport(attempt) {
  if (attempt > 100) {
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
      setTimeout(() => pollReport(attempt + 1), 3000);
      return;
    }
    $("progress").classList.add("hidden");
    if (data.status === "error") {
      $("result").innerHTML = `<p class='msg error'>분석 오류: ${esc(data.error_detail) || "알 수 없음"}</p>`;
      return;
    }
    renderReport(data);
  } catch (err) {
    setTimeout(() => pollReport(attempt + 1), 3000);
  }
}

function renderCapability(d) {
  const cf = d.capability_fit;
  if (!cf) return "";
  const metN = (cf.met || []).length;
  const totalN = metN + (cf.unmet || []).length;
  const met = (cf.met || []).map((c) => `<span class="cap met">${esc(c)} ✓</span>`).join("");
  const unmet = (cf.unmet || []).map((c) => `<span class="cap unmet">${esc(c)} ✗</span>`).join("");
  const ev = (d.capability_evidence || [])
    .map((e) => `<div class="cap-ev">${esc(e.capability)}: ${(e.tools || []).map((t) => `${esc(t.skill)}(${esc(t.verification)})`).join(", ")}</div>`)
    .join("");
  const rec = (d.recommended_families || [])
    .map((r) => `<div class="fam-row"><span>${esc(r.job_family)}</span><span>${Math.round((r.fit || 0) * 100)}%</span></div>`)
    .join("");
  return `
    <h3>${esc(cf.job_family || "")} 핵심 역량 ${metN}/${totalN} 충족</h3>
    <div>${met}${unmet}</div>
    ${ev ? `<h3>역량별 근거 (검증 등급)</h3>${ev}` : ""}
    ${rec ? `<h3>당신에게 맞는 직군</h3>${rec}` : ""}
  `;
}

// 4. 결과 렌더
function renderReport(d) {
  const counts = d.verification_counts || {};
  const skills = (d.verified_skills || [])
    .map((s) => `<div class="skill-row"><span>${esc(s.skill)}</span>
      <span class="badge ${s.verification}">${esc(s.verification)}</span>
      <span class="src">${(s.sources || []).map(esc).join(", ")}</span></div>`)
    .join("");
  const suggestions = (d.suggestions || [])
    .map((s) => `<div class="suggestion">
      <div class="head">${esc(s.missing_skill)} → ${esc(s.target_section)}
        <span class="prio">[${esc(s.priority)}${s.verified ? " · 검증됨" : ""}]</span></div>
      <div class="rew">${esc(s.rewritten_text)}</div>
      <div class="prio">기대효과: ${esc(s.expected_impact)}</div></div>`)
    .join("");

  $("result").innerHTML = `
    ${renderCapability(d)}
    <div class="metrics">
      <div class="metric"><div>신뢰도</div><div class="big">${d.confidence_level ? esc(d.confidence_level) : "-"}</div>
        <div class="prio">Verified ${counts.Verified || 0} · Corroborated ${counts.Corroborated || 0} · Claimed ${counts.Claimed || 0}</div></div>
    </div>
    ${d.advice ? `<p>${esc(d.advice)}</p>` : ""}
    <h3>검증된 스킬</h3>${skills || "<p class='prio'>없음</p>"}
    <h3>코칭</h3>
    ${d.coaching_summary ? `<p>${esc(d.coaching_summary)}</p>` : ""}
    ${suggestions || "<p class='prio'>제안 없음</p>"}
    <p style="margin-top:16px"><a href="/observe?report_id=${encodeURIComponent(state.reportId)}&tab=workflow">→ 이 분석의 실행 과정 보기</a></p>
  `;
}

$("upload-btn").addEventListener("click", uploadResume);
$("analyze-btn").addEventListener("click", startAnalysis);
