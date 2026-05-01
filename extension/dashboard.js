// dashboard.js
// Fetches all stats from the Python backend and populates the dashboard.

const BACKEND = "http://localhost:8000";

// ─── Boot ─────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  init();
  document.getElementById("btn-refresh").addEventListener("click", init);
  document.getElementById("btn-settings").addEventListener("click", () =>
    chrome.runtime.openOptionsPage()
  );
  document.getElementById("btn-reset").addEventListener("click", confirmReset);
  document.getElementById("btn-retry-sm")?.addEventListener("click", init);
  document.getElementById("btn-retry-banner")?.addEventListener("click", (e) => {
    e.preventDefault();
    init();
  });
});

// ─── Data fetching ────────────────────────────────────────────────────────────

async function fetchStats() {
  const res = await fetch(`${BACKEND}/stats`, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function fetchRecentPastes() {
  const res = await fetch(`${BACKEND}/recent-pastes`, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ─── Main init ────────────────────────────────────────────────────────────────

async function init() {
  showError(false);

  try {
    const [stats, recent] = await Promise.all([
      fetchStats(),
      fetchRecentPastes().catch(() => []), // non-fatal if endpoint missing
    ]);

    renderKPIs(stats);
    renderGauge(stats);
    renderStreak(stats);
    renderCalendar(stats);
    renderBarChart(stats);
    renderConceptCloud(stats);
    renderRecentPastes(recent);
  } catch (err) {
    showError(true, err.message);
  }
}

// ─── Error banner ─────────────────────────────────────────────────────────────

function showError(visible) {
  document.getElementById("error-banner").style.display = visible ? "flex" : "none";
}

// ─── KPI strip ────────────────────────────────────────────────────────────────

function renderKPIs(data) {
  const {
    total_intercepts  = 0,
    read_before_paste = 0,
    total_concepts    = 0,
    streak_days       = 0,
    today_intercepts  = 0,
    today_read        = 0,
  } = data;

  set("kpi-intercepts", total_intercepts);
  set("kpi-read",       read_before_paste);
  set("kpi-concepts",   total_concepts);
  set("kpi-streak",     streak_days);

  // Deltas (today's contribution)
  setDelta("kpi-intercepts-delta", today_intercepts, "today");
  setDelta("kpi-read-delta",       today_read,       "today");
  setDelta("kpi-concepts-delta",   null,             "");
  document.getElementById("kpi-streak-sub").textContent =
    streak_days >= 7 ? "🎉 Keep going!" : streak_days > 0 ? "Active!" : "Start today";
}

function set(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val ?? "—";
}

function setDelta(id, count, label) {
  const el = document.getElementById(id);
  if (!el) return;
  if (count == null || count === 0) {
    el.textContent = "";
    return;
  }
  el.textContent = `+${count} ${label}`;
  el.className = "kpi-delta up";
}

// ─── Read-rate gauge ──────────────────────────────────────────────────────────

function renderGauge(data) {
  const { total_intercepts = 0, read_before_paste = 0 } = data;
  const rate = total_intercepts > 0
    ? Math.round((read_before_paste / total_intercepts) * 100)
    : 0;

  // SVG arc: half-circle (180°), circumference of half = π × r ≈ 138.2 (r=44)
  const halfCirc = Math.PI * 44; // ≈ 138.23
  const filled   = (rate / 100) * halfCirc;

  const arc   = document.getElementById("gauge-arc");
  const label = document.getElementById("gauge-label");
  const pct   = document.getElementById("gauge-pct");
  const desc  = document.getElementById("gauge-desc");

  arc.setAttribute("stroke-dasharray", `${filled} 1000`);
  arc.setAttribute("stroke", rate >= 70 ? "#a6e3a1" : rate >= 40 ? "#f9e2af" : "#f38ba8");

  label.textContent = `${rate}%`;
  pct.textContent   = `${rate}%`;
  pct.style.color   = rate >= 70 ? "var(--green)" : rate >= 40 ? "var(--yellow)" : "var(--red)";

  desc.textContent = total_intercepts === 0
    ? "Start pasting to track your read rate."
    : rate >= 70
    ? "Excellent! You consistently read before pasting."
    : rate >= 40
    ? "Getting there — try reading every snippet."
    : "Lots of blind pastes. Take a moment to read first!";
}

// ─── Streak + calendar ────────────────────────────────────────────────────────

function renderStreak(data) {
  document.getElementById("dash-streak").textContent = data.streak_days ?? 0;
}

function renderCalendar(data) {
  // active_days: array of "YYYY-MM-DD" strings from backend
  const activeDays = new Set(data.active_days ?? []);
  const grid       = document.getElementById("calendar-grid");
  const today      = new Date();

  // Month label
  document.getElementById("cal-month-label").textContent =
    today.toLocaleDateString("en-US", { month: "long", year: "numeric" });

  grid.innerHTML = "";

  // Build 28 days ending today
  for (let i = 27; i >= 0; i--) {
    const d    = new Date(today);
    d.setDate(today.getDate() - i);
    const key  = d.toISOString().slice(0, 10); // "YYYY-MM-DD"
    const isToday  = i === 0;
    const isActive = activeDays.has(key);

    const el = document.createElement("div");
    el.className = "cal-day " + (isToday ? "today" : isActive ? "active" : "inactive");
    el.title = `${key}${isActive ? " — active" : ""}`;
    grid.appendChild(el);
  }
}

// ─── Bar chart — intercepts per day ───────────────────────────────────────────

function renderBarChart(data) {
  // daily_counts: [{date: "YYYY-MM-DD", count: N}] last 14 days from backend
  const dailyCounts = data.daily_counts ?? [];
  const chart = document.getElementById("bar-chart");

  if (dailyCounts.length === 0) {
    chart.innerHTML = `<div class="state-placeholder" style="width:100%">
      <span>No activity yet.</span></div>`;
    return;
  }

  const max = Math.max(...dailyCounts.map((d) => d.count), 1);
  chart.innerHTML = "";

  dailyCounts.forEach(({ date, count }) => {
    const heightPct = (count / max) * 100;
    const dayLabel  = new Date(date + "T00:00:00")
      .toLocaleDateString("en-US", { weekday: "short" })
      .slice(0, 2);

    const col = document.createElement("div");
    col.className = "bar-col";
    col.title = `${date}: ${count} intercept${count !== 1 ? "s" : ""}`;
    col.innerHTML = `
      <div class="bar-fill-wrap">
        <div class="bar-rect" style="height:${heightPct}%"></div>
      </div>
      <div class="bar-day-label">${dayLabel}</div>`;
    chart.appendChild(col);
  });
}

// ─── Concept cloud ────────────────────────────────────────────────────────────

function renderConceptCloud(data) {
  // top_concepts: [{tag: "closure", count: N}] sorted by count desc
  const concepts = data.top_concepts ?? [];
  const cloud    = document.getElementById("concept-cloud");

  if (concepts.length === 0) {
    cloud.innerHTML = `<div class="state-placeholder">
      <div class="icon">🧠</div>
      <span>No concepts yet — intercept your first paste!</span>
    </div>`;
    return;
  }

  const maxCount = concepts[0]?.count ?? 1;

  // Shuffle so it reads like a real cloud (not just sorted large→small)
  const shuffled = [...concepts].sort(() => Math.random() - 0.5);

  cloud.innerHTML = shuffled
    .map(({ tag, count }) => {
      const ratio = count / maxCount;
      const size  = ratio > 0.7 ? "size-lg" : ratio > 0.4 ? "size-md" : ratio > 0.2 ? "size-sm" : "size-xs";
      return `<span class="concept-chip ${size}" title="${count} occurrence${count !== 1 ? "s" : ""}">
        ${escapeHTML(tag)}<span class="chip-count">×${count}</span>
      </span>`;
    })
    .join("");
}

// ─── Recent pastes table ──────────────────────────────────────────────────────

function renderRecentPastes(pastes) {
  const wrap = document.getElementById("recent-pastes-wrap");

  if (!pastes || pastes.length === 0) {
    wrap.innerHTML = `<div class="state-placeholder">
      <div class="icon">📋</div>
      <span>No pastes recorded yet.</span>
    </div>`;
    return;
  }

  const rows = pastes
    .map(({ snippet = "", tags = [], read_first = false, created_at = "" }) => {
      const tagHTML = tags
        .slice(0, 3)
        .map((t) => `<span class="mini-tag">${escapeHTML(t)}</span>`)
        .join("");

      const timeStr = created_at
        ? timeAgo(new Date(created_at))
        : "—";

      const readBadge = read_first
        ? `<span class="read-badge yes">Read</span>`
        : `<span class="read-badge no">Blind</span>`;

      return `<tr>
        <td class="paste-snippet">${escapeHTML(snippet.slice(0, 60))}…</td>
        <td><div class="paste-tags">${tagHTML}</div></td>
        <td>${readBadge}</td>
        <td class="time-cell">${timeStr}</td>
      </tr>`;
    })
    .join("");

  wrap.innerHTML = `
    <table class="paste-table">
      <thead>
        <tr>
          <th>Code snippet</th>
          <th>Concepts</th>
          <th>Read?</th>
          <th>When</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>`;
}

// ─── Reset ────────────────────────────────────────────────────────────────────

async function confirmReset() {
  const ok = window.confirm(
    "Reset all PasteWise stats?\nThis will delete your intercept history, concept map, and streak. This cannot be undone."
  );
  if (!ok) return;

  try {
    const res = await fetch(`${BACKEND}/reset`, { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    await init(); // reload fresh
  } catch (err) {
    alert(`Reset failed: ${err.message}`);
  }
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function escapeHTML(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function timeAgo(date) {
  const seconds = Math.floor((Date.now() - date) / 1000);
  if (seconds < 60)   return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}