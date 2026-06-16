// 관측 페이지 — 분석 워크플로우 추적(report_id의 trace 기반)
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
  .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
if (window.mermaid) mermaid.initialize({ startOnLoad: false });

// report.trace에서 단계별 데이터 변화를 한 줄 요약
function flowSummary(report) {
  const t = report.trace || {};
  const extracted = new Set((t.evaluators || []).flatMap((e) => (e.skills || []).map((s) => s.skill))).size;
  const cons = (t.consensus && t.consensus.skills) || [];
  const verified = cons.filter((s) => s.verification === "Verified").length;
  const cf = report.capability_fit || {};
  const met = (cf.met || []).length, unmet = (cf.unmet || []).length;
  const corrected = (t.critic && t.critic.corrected) || 0;
  const suggestions = ((t.coach && t.coach.project_suggestion_count) || 0) + ((t.coach && t.coach.learning_count) || 0);
  return `스킬 ${extracted} 추출 → 합의 ${cons.length}(Verified ${verified}) → 부족 역량 ${unmet} → 적합도 ${met}/${met + unmet} → 교정 ${corrected} → 제안 ${suggestions}`;
}

// 단계 카드 헤더용 수치 배지 목록
function stageBadges(key, report) {
  const t = report.trace || {};
  if (key === "evaluators") {
    const ev = t.evaluators || [];
    const sk = new Set(ev.flatMap((e) => (e.skills || []).map((s) => s.skill))).size;
    return [`소스 ${ev.length}`, `스킬 ${sk}`];
  }
  if (key === "consensus") {
    const c = (t.consensus && t.consensus.skills) || [];
    const cnt = (v) => c.filter((s) => s.verification === v).length;
    return [`Verified ${cnt("Verified")}`, `Corroborated ${cnt("Corroborated")}`, `Claimed ${cnt("Claimed")}`];
  }
  if (key === "gap_loop") {
    const g = t.gap_loop || {};
    return [`반복 ${g.iterations || 0}회`, `도구 ${(g.tool_calls || []).length}`];
  }
  if (key === "fit") {
    const cf = report.capability_fit || {};
    const m = (cf.met || []).length, u = (cf.unmet || []).length;
    return [`적합도 ${m}/${m + u}`];
  }
  if (key === "critic") {
    const cr = t.critic || {};
    return [`제거 ${(cr.removed_skills || []).length}`, `교정 ${cr.corrected || 0}`];
  }
  if (key === "coach") return [`프로젝트 ${(t.coach && t.coach.project_suggestion_count) || 0}`, `학습 ${(t.coach && t.coach.learning_count) || 0}`];
  return [];
}

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
  // 흐름 요약 띠
  let band;
  if (report && report.trace) {
    band = `<div class="flow-band">${esc(flowSummary(report))}</div>`;
  } else {
    band = `<div class="flow-band muted">분석을 실행하면 실제 데이터 흐름이 채워집니다.</div>`;
  }

  // 다이어그램 (실행 경로 강조 + 미실행 dim)
  let diagram = "";
  if (g.mermaid && window.mermaid) {
    let src = g.mermaid;
    const ex = (report && report.trace && report.trace.executed_nodes) || [];
    if (ex.length) {
      const allNodes = (g.stages || []).flatMap((s) => s.nodes || []);
      const dim = allNodes.filter((n) => !ex.includes(n));
      src += "\n" + ex.map((n) => `class ${n} executed;`).join("\n");
      if (dim.length) src += "\n" + dim.map((n) => `class ${n} dimmed;`).join("\n");
      src += "\nclassDef executed fill:#4f46e5,color:#fff,stroke:#4f46e5,stroke-width:2px;";
      src += "\nclassDef dimmed fill:#f3f4f6,color:#9ca3af,stroke:#e5e7eb;";
    }
    try {
      const { svg } = await mermaid.render("wfgraph", src);
      diagram = `<div class="diagram">${svg}</div>`;
    } catch (e) {
      diagram = "<p class='prio'>다이어그램 로드 실패</p>";
    }
  }

  const cards = (g.stages || []).map((st) => renderStage(st, report)).join("");
  $("workflow").innerHTML = band + diagram + cards;
}

function renderStage(st, report) {
  const t = report && report.trace;
  const badges = (report && t)
    ? stageBadges(st.key, report).map((b) => `<span class="badge-num">${esc(b)}</span>`).join("")
    : "";
  let data = "<div class='cap-ev'>분석하면 이 단계의 실제 처리 결과가 표시됩니다.</div>";
  if (report && t) data = `<div class="stage-data">${stageData(st.key, t, report)}</div>`;
  return `<div class="step"><h4>${esc(st.title)} ${badges}</h4><p class="cap-ev">${esc(st.description)}</p>${data}</div>`;
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
    if (!cf) return "적합도 정보 없음";
    const rec = (report.recommended_families || []).slice(0, 3).map((r) => `${esc(r.job_family)} ${r.matched_count}개`).join(" · ");
    const metNames = (cf.met || []).map((m) => esc(m.skill)).join(", ");
    return `핵심 스킬 ${(cf.met || []).length}/${cf.total || 0} 충족 (${metNames})<br>맞는 직군: ${rec}`;
  }
  if (key === "critic")
    return `제거된 주장: ${(t.critic && t.critic.removed_skills || []).map(esc).join(", ") || "없음"} · 교정 ${(t.critic && t.critic.corrected) || 0}건`;
  if (key === "coach")
    return `프로젝트 보강 ${(t.coach && t.coach.project_suggestion_count) || 0}개 · 연계 학습 ${(t.coach && t.coach.learning_count) || 0}개`;
  return "";
}

// 진입 시 워크플로우 로드
loadWorkflow();
