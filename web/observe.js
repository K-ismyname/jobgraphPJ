// 관측 페이지 — 분석 워크플로우 추적(report_id의 trace 기반)
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
  .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
if (window.mermaid) mermaid.initialize({ startOnLoad: false });

// ── 워크플로우 = 시스템 설명 + (분석 있으면) 실제 예시 ──
async function loadWorkflow() {
  let g;
  try {
    const res = await fetch("/graph");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    g = await res.json();
  } catch (e) {
    $("workflow").innerHTML = `<p class='msg error'>구조 불러오기 실패: ${esc(e.message)}</p>`;
    return;
  }
  const reportId = new URLSearchParams(location.search).get("report_id");
  let report = null;
  if (reportId) {
    try {
      const r = await fetch(`/portfolio/report/${reportId}`);
      if (r.ok) report = await r.json();
    } catch (e) { /* report 없이 설명만 */ }
  }
  await renderWorkflow(g, report);
}

async function renderWorkflow(g, report) {
  let diagram = "";
  if (g.mermaid && window.mermaid) {
    let src = g.mermaid;
    const ex = report && report.trace && report.trace.executed_nodes;
    if (ex && ex.length) {
      src += "\n" + ex.map((n) => `class ${n} executed;`).join("\n");
      src += "\nclassDef executed fill:#eef2ff,stroke:#4f46e5,stroke-width:2px;";
    }
    try {
      const { svg } = await mermaid.render("wfgraph", src);
      diagram = `<div class="diagram">${svg}</div>`;
    } catch (e) {
      diagram = "<p class='prio'>다이어그램 로드 실패</p>";
    }
  }
  const cards = (g.stages || []).map((st) => renderStage(st, report)).join("");
  $("workflow").innerHTML = diagram + cards;
}

function renderStage(st, report) {
  const t = report && report.trace;
  let data = "<div class='cap-ev'>분석하면 이 단계의 실제 처리 결과가 표시됩니다.</div>";
  if (report && t) data = `<div class="stage-data">${stageData(st.key, t, report)}</div>`;
  return `<div class="step"><h4>${esc(st.title)}</h4><p class="cap-ev">${esc(st.description)}</p>${data}</div>`;
}

function stageData(key, t, report) {
  if (key === "evaluators")
    return (t.evaluators || []).map((e) =>
      `<div><b>${esc(e.source)}</b> (${e.skill_count}): ${(e.skills || []).map((s) => esc(s.skill)).join(", ")}</div>`).join("") || "없음";
  if (key === "consensus")
    return ((t.consensus && t.consensus.skills) || []).map((s) =>
      `<div class="skill-row"><span>${esc(s.skill)}</span><span class="badge ${s.verification}">${esc(s.verification)}</span><span class="src">${(s.sources || []).map(esc).join(", ")}</span></div>`).join("") || "없음";
  if (key === "gap_loop")
    return `도구: ${(t.gap_loop && t.gap_loop.tool_calls || []).map(esc).join(", ") || "없음"} · 반복 ${(t.gap_loop && t.gap_loop.iterations) || 0}회`;
  if (key === "fit") {
    const cf = report.capability_fit;
    if (!cf) return "역량 정보 없음";
    const rec = (report.recommended_families || []).slice(0, 3).map((r) => `${esc(r.job_family)} ${Math.round((r.fit || 0) * 100)}%`).join(" · ");
    return `핵심 역량 ${(cf.met || []).length}/${(cf.met || []).length + (cf.unmet || []).length} 충족 (${(cf.met || []).map(esc).join(", ")})<br>맞는 직군: ${rec}`;
  }
  if (key === "critic")
    return `제거된 주장: ${(t.critic && t.critic.removed_skills || []).map(esc).join(", ") || "없음"} · 교정 ${(t.critic && t.critic.corrected) || 0}건`;
  if (key === "coach")
    return `개선 제안 ${(t.coach && t.coach.suggestion_count) || 0}개`;
  return "";
}

// 진입 시 워크플로우 로드
loadWorkflow();
