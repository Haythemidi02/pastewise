// popup.js
// Runs inside the toolbar popup (popup.html).
// Fetches stats from the Python backend via the service worker,
// then populates the UI.

const BACKEND = "http://localhost:8000";

// ─── DOM refs ────────────────────────────────────────────────────────────────

const stateLoading  = document.getElementById("state-loading");
const stateError    = document.getElementById("state-error");
const stateMain     = document.getElementById("state-main");

const statusPill    = document.getElementById("status-pill");
const statusText    = document.getElementById("status-text");
const siteLabel     = document.getElementById("site-label");

const statIntercepts = document.getElementById("stat-intercepts");
const statRead       = document.getElementById("stat-read");
const statConcepts   = document.getElementById("stat-concepts");
const statToday      = document.getElementById("stat-today");

const readRatePct   = document.getElementById("read-rate-pct");
const readRateBar   = document.getElementById("read-rate-bar");

const conceptsList  = document.getElementById("concepts-list");

const streakCount   = document.getElementById("streak-count");
const streakMsg     = document.getElementById("streak-msg");

// ─── Buttons ─────────────────────────────────────────────────────────────────

document.getElementById("btn-settings").addEventListener("click", openOptions);
document.getElementById("btn-settings-main").addEventListener("click", openOptions);
document.getElementById("btn-settings-err").addEventListener("click", openOptions);
document.getElementById("btn-retry").addEventListener("click", init);
document.getElementById("btn-dashboard").addEventListener("click", openDashboard);

function openOptions() {
  chrome.runtime.openOptionsPage();
}

function openDashboard() {
  chrome.runtime.sendMessage({ type: "OPEN_DASHBOARD" });
  window.close(); // close the popup after navigation
}

// ─── State helpers ───────────────────────────────────────────────────────────

function showState(name) {
  stateLoading.classList.add("hidden");
  stateError.classList.add("hidden");
  stateMain.classList.add("hidden");

  if (name === "loading") stateLoading.classList.remove("hidden");
  if (name === "error")   stateError.classList.remove("hidden");
  if (name === "main")    stateMain.classList.remove("hidden");
}

// ─── Active tab site label ────────────────────────────────────────────────────

async function getActiveTabHost() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.url) return null;
    const url = new URL(tab.url);
    return url.hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}

// ─── Stats fetching ───────────────────────────────────────────────────────────
// We try a direct fetch first (fastest). If the page's CSP blocks it,
// the service worker relay is the fallback.

async function fetchStats() {
  // Direct fetch
  try {
    const res = await fetch(`${BACKEND}/stats`, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } catch {
    // Relay through service worker
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage({ type: "GET_STATS" }, (response) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
        } else if (!response?.ok) {
          reject(new Error(response?.error ?? "Unknown error"));
        } else {
          resolve(response.data);
        }
      });
    });
  }
}

// ─── Render ───────────────────────────────────────────────────────────────────

function renderStats(data) {
  const {
    total_intercepts = 0,
    read_before_paste = 0,
    total_concepts = 0,
    today_intercepts = 0,
    top_concepts = [],
    streak_days = 0,
  } = data;

  // Key numbers
  statIntercepts.textContent = total_intercepts;
  statRead.textContent       = read_before_paste;
  statConcepts.textContent   = total_concepts;
  statToday.textContent      = today_intercepts;

  // Read-before-paste rate
  const rate = total_intercepts > 0
    ? Math.round((read_before_paste / total_intercepts) * 100)
    : 0;

  readRatePct.textContent = `${rate}%`;
  readRateBar.style.width = `${rate}%`;
  readRateBar.className = "bar-fill " + (
    rate >= 70 ? "high" : rate >= 40 ? "mid" : "low"
  );

  // Top concepts (backend returns [{tag, count}] sorted by count desc)
  if (top_concepts.length > 0) {
    conceptsList.innerHTML = top_concepts
      .slice(0, 8)
      .map(({ tag, count }) => `
        <span class="concept-tag">
          ${escapeHTML(tag)}<span class="count">×${count}</span>
        </span>`)
      .join("");
  } else {
    conceptsList.innerHTML = `<span class="no-concepts">No data yet — start pasting!</span>`;
  }

  // Streak
  streakCount.textContent = streak_days;
  streakMsg.textContent = streak_days >= 7
    ? "Keep it up!"
    : streak_days >= 3
    ? "Nice run!"
    : streak_days > 0
    ? "Good start"
    : "";
}

// ─── Init ─────────────────────────────────────────────────────────────────────

async function init() {
  showState("loading");

  // Populate site label while we wait for stats
  getActiveTabHost().then((host) => {
    if (host) siteLabel.textContent = host;
  });

  try {
    const data = await fetchStats();
    renderStats(data);
    showState("main");
  } catch {
    // Backend unreachable
    statusPill.className = "status-pill offline";
    statusText.textContent = "Backend offline";
    showState("error");
  }
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function escapeHTML(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// ─── Boot ─────────────────────────────────────────────────────────────────────

init();