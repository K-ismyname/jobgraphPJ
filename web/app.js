// 이력서 분석 데모 — 업로드→분석→폴링→결과 렌더 (바닐라 JS)
const state = { reportId: null };

const $ = (id) => document.getElementById(id);

// innerHTML 삽입 전 HTML 이스케이프 — 이력서 파생 텍스트의 self-XSS 방지
const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

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
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    if (data.status === "processing") {
      setTimeout(() => pollReport(attempt + 1), 3000);
      return;
    }
    $("progress").classList.add("hidden");
    if (data.status === "error") {
      $("result").innerHTML = `<p class='msg error'>분석 오류: ${data.error_detail || "알 수 없음"}</p>`;
      return;
    }
    renderReport(data);
  } catch (err) {
    setTimeout(() => pollReport(attempt + 1), 3000);
  }
}

// 4. 결과 렌더
function renderReport(d) {
  const pct = d.match_rate <= 1 ? Math.round(d.match_rate * 100) : Math.round(d.match_rate);
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
    <div class="metrics">
      <div class="metric"><div>적합도</div><div class="big">${pct}%</div>
        <div class="gauge"><span style="width:${pct}%"></span></div></div>
      <div class="metric"><div>신뢰도</div><div class="big">${d.confidence_level ? esc(d.confidence_level) : "-"}</div>
        <div class="prio">Verified ${counts.Verified || 0} · Corroborated ${counts.Corroborated || 0} · Claimed ${counts.Claimed || 0}</div></div>
    </div>
    ${d.advice ? `<p>${esc(d.advice)}</p>` : ""}
    <h3>검증된 스킬</h3>${skills || "<p class='prio'>없음</p>"}
    <h3>코칭</h3>
    ${d.coaching_summary ? `<p>${esc(d.coaching_summary)}</p>` : ""}
    ${suggestions || "<p class='prio'>제안 없음</p>"}
  `;
}

$("upload-btn").addEventListener("click", uploadResume);
$("analyze-btn").addEventListener("click", startAnalysis);
