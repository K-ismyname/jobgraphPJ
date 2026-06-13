// 관측 페이지 — 워크플로우 추적(report_id의 trace) + 데이터 현황(/stats)
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
  .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");

// 탭 전환
function showTab(name) {
  const wf = name === "workflow";
  $("panel-workflow").classList.toggle("hidden", !wf);
  $("panel-data").classList.toggle("hidden", wf);
  $("tab-workflow").classList.toggle("active", wf);
  $("tab-data").classList.toggle("active", !wf);
  if (wf) loadWorkflow(); else loadData();
}
$("tab-workflow").addEventListener("click", () => showTab("workflow"));
$("tab-data").addEventListener("click", () => showTab("data"));

// ── 워크플로우 탭 ──
async function loadWorkflow() {
  const params = new URLSearchParams(location.search);
  const reportId = params.get("report_id");
  if (!reportId) {
    $("workflow").innerHTML = "<p class='prio'>분석을 먼저 실행하세요. 분석 결과 화면의 '실행 과정 보기'로 들어오면 그 분석의 흐름이 표시됩니다.</p>";
    return;
  }
  try {
    const res = await fetch(`/portfolio/report/${reportId}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const d = await res.json();
    if (!d.trace) {
      $("workflow").innerHTML = "<p class='prio'>이 분석에는 실행 추적 정보가 없습니다.</p>";
      return;
    }
    renderTrace(d.trace);
  } catch (e) {
    $("workflow").innerHTML = `<p class='msg error'>불러오기 실패: ${esc(e.message)}</p>`;
  }
}

function renderTrace(t) {
  const ev = (t.evaluators || []).map((e) => `${esc(e.source)} ${e.skill_count}개`).join(" · ") || "없음";
  const c = t.consensus || {};
  const tools = (t.gap_loop?.tool_calls || []).map(esc).join(", ") || "없음";
  const cr = t.critic || {};
  $("workflow").innerHTML = `
    <div class="step"><h4>1. 평가자 (소스별 스킬 추출)</h4>${ev}</div>
    <div class="step"><h4>2. 합의 — 검증 등급 분포</h4>
      Verified ${c.Verified || 0} · Corroborated ${c.Corroborated || 0} · Claimed ${c.Claimed || 0}</div>
    <div class="step"><h4>3. Gap 루프 (Corrective RAG)</h4>
      도구: ${tools} · 반복 ${t.gap_loop?.iterations || 0}회</div>
    <div class="step"><h4>4. Critic (결정적 검증)</h4>
      환각 제거 ${cr.removed || 0} · 검증 라벨 교정 ${cr.corrected || 0}</div>
    <div class="step"><h4>5. Coach</h4>제안 ${t.coach?.suggestion_count || 0}개</div>
  `;
}

// ── 데이터 탭 ──
let dataLoaded = false;
async function loadData() {
  if (dataLoaded) return;
  dataLoaded = true;
  try {
    const res = await fetch("/stats");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const d = await res.json();
    const fams = (d.job_families || [])
      .map((f) => `<div class="stat-row"><span>${esc(f.name)}</span>
        <span>공고 ${f.posting_count} · 스킬 ${f.skill_count}</span></div>`).join("");
    const tot = d.totals || {};
    $("data").innerHTML = `
      <h3>전체</h3>
      <div class="stat-row"><span>공고</span><span>${tot.postings || 0}</span></div>
      <div class="stat-row"><span>스킬</span><span>${tot.skills || 0}</span></div>
      <div class="stat-row"><span>요구/우대 관계</span><span>${tot.relations || 0}</span></div>
      <div class="stat-row"><span>벡터 청크</span><span>${d.chroma_chunks ?? "—"}</span></div>
      <h3>직군별</h3>${fams}
    `;
  } catch (e) {
    dataLoaded = false;
    $("data").innerHTML = `<p class='msg error'>데이터 현황 불러오기 실패: ${esc(e.message)}</p>`;
  }
}

// 진입 시: tab 쿼리로 초기 탭 결정. showTab이 해당 탭의 로더(loadWorkflow/loadData)를 호출한다.
const initTab = new URLSearchParams(location.search).get("tab") === "data" ? "data" : "workflow";
showTab(initTab);
