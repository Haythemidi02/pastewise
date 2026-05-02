// options.js
// Handles loading, saving, and validating all PasteWise settings.
// Settings are persisted in chrome.storage.sync (synced across devices)
// and pushed to the Python backend where relevant (port, API key, model).

const SITES = [
  { name: "Replit",       host: "replit.com",       icon: "R" },
  { name: "LeetCode",     host: "leetcode.com",      icon: "L" },
  { name: "CodePen",      host: "codepen.io",        icon: "C" },
  { name: "CodeSandbox",  host: "codesandbox.io",    icon: "S" },
  { name: "GitHub",       host: "github.com",        icon: "G" },
  { name: "StackBlitz",   host: "stackblitz.com",    icon: "B" },
  { name: "JSFiddle",     host: "jsfiddle.net",      icon: "J" },
  { name: "Glitch",       host: "glitch.com",        icon: "~" },
  { name: "Codeforces",   host: "codeforces.com",    icon: "Cf" },
  { name: "AtCoder",      host: "atcoder.jp",        icon: "At" },
  { name: "HackerRank",   host: "hackerrank.com",    icon: "Hr" },
  { name: "Kaggle",       host: "kaggle.com",        icon: "Ka" },
  { name: "Google Colab", host: "colab.research.google.com", icon: "Co" },
];

const DEFAULTS = {
  port:        8000,
  apiKey:      "",
  model:       "gemini-2.5-flash",
  maxTokens:   512,
  enabled:     true,
  shortSnips:  true,
  autoPaste:   false,
  minLines:    3,
  position:    "bottom-right",
  cache:       true,
  history:     true,
  sites:       Object.fromEntries(SITES.map((s) => [s.host, true])),
};

// ─── State ────────────────────────────────────────────────────────────────────

let saved   = { ...DEFAULTS };   // last-saved snapshot
let current = { ...DEFAULTS };   // live form state (may differ from saved)
let dirty   = false;

// ─── DOM refs ─────────────────────────────────────────────────────────────────

const $ = (id) => document.getElementById(id);

const inputs = {
  port:       $("inp-port"),
  apiKey:     $("inp-apikey"),
  model:      $("inp-model"),
  maxTokens:  $("inp-max-tokens"),
  enabled:    $("tog-enabled"),
  shortSnips: $("tog-short"),
  autoPaste:  $("tog-autopaste"),
  minLines:   $("inp-min-lines"),
  position:   $("inp-position"),
  cache:      $("tog-cache"),
  history:    $("tog-history"),
};

// ─── Boot ─────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", async () => {
  renderSiteList();
  await loadSettings();
  populateForm();
  bindEvents();
  checkBackend(false); // silent ping on open
});

// ─── Persistence ─────────────────────────────────────────────────────────────

async function loadSettings() {
  return new Promise((resolve) => {
    chrome.storage.sync.get(DEFAULTS, (data) => {
      // Auto-upgrade deprecated 1.5 models to 2.5
      if (data.model === "gemini-1.5-flash") data.model = "gemini-2.5-flash";
      if (data.model === "gemini-1.5-pro") data.model = "gemini-2.5-pro";
      
      saved   = { ...DEFAULTS, ...data };
      current = { ...saved };
      resolve();
    });
  });
}

async function saveSettings() {
  // Collect form values into `current`
  collectForm();

  // Validate before saving
  if (!validate()) return;

  // Push to chrome.storage.sync
  await new Promise((resolve) => {
    chrome.storage.sync.set(current, resolve);
  });

  // Push relevant settings to Python backend
  await pushToBackend(current);

  saved = { ...current };
  setDirty(false);
  showToast("Settings saved", "success");

  // Update about section
  renderAbout();
}

function discardChanges() {
  current = { ...saved };
  populateForm();
  setDirty(false);
}

// ─── Backend sync ─────────────────────────────────────────────────────────────
// The backend reads its config from .env at startup, but we can push
// runtime config changes via the /config endpoint so restarts aren't needed.

async function pushToBackend(settings) {
  try {
    const res = await fetch(`http://localhost:${settings.port}/config`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        api_key:    settings.apiKey,
        model:      settings.model,
        max_tokens: settings.maxTokens,
        cache:      settings.cache,
        history:    settings.history,
      }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
  } catch (err) {
    // Non-fatal — settings are still saved in chrome.storage
    showToast("Saved locally. Backend unreachable — restart it to apply model/key changes.", "error");
  }
}

// ─── Form population ──────────────────────────────────────────────────────────

function populateForm() {
  inputs.port.value          = current.port;
  inputs.apiKey.value        = current.apiKey;
  inputs.model.value         = current.model;
  inputs.maxTokens.value     = current.maxTokens;
  inputs.enabled.checked     = current.enabled;
  inputs.shortSnips.checked  = current.shortSnips;
  inputs.autoPaste.checked   = current.autoPaste;
  inputs.minLines.value      = current.minLines;
  inputs.position.value      = current.position;
  inputs.cache.checked       = current.cache;
  inputs.history.checked     = current.history;

  // Site toggles
  SITES.forEach(({ host }) => {
    const el = document.getElementById(`site-tog-${host}`);
    if (el) el.checked = current.sites?.[host] ?? true;
  });

  renderAbout();
}

function collectForm() {
  current.port       = parseInt(inputs.port.value, 10) || 8000;
  current.apiKey     = inputs.apiKey.value.trim();
  current.model      = inputs.model.value;
  current.maxTokens  = parseInt(inputs.maxTokens.value, 10);
  current.enabled    = inputs.enabled.checked;
  current.shortSnips = inputs.shortSnips.checked;
  current.autoPaste  = inputs.autoPaste.checked;
  current.minLines   = parseInt(inputs.minLines.value, 10);
  current.position   = inputs.position.value;
  current.cache      = inputs.cache.checked;
  current.history    = inputs.history.checked;

  // Site toggles
  current.sites = {};
  SITES.forEach(({ host }) => {
    const el = document.getElementById(`site-tog-${host}`);
    current.sites[host] = el ? el.checked : true;
  });
}

// ─── Validation ───────────────────────────────────────────────────────────────

function validate() {
  let ok = true;

  // API key: must start with "AIza" if provided
  const keyErr = $("err-apikey");
  if (current.apiKey && !current.apiKey.startsWith("AIza")) {
    keyErr.classList.add("visible");
    ok = false;
  } else {
    keyErr.classList.remove("visible");
  }

  return ok;
}

// ─── Dirty state ─────────────────────────────────────────────────────────────

function setDirty(isDirty) {
  dirty = isDirty;
  $("save-bar").classList.toggle("visible", isDirty);
}

function markDirty() {
  setDirty(true);
}

// ─── Event bindings ───────────────────────────────────────────────────────────

function bindEvents() {
  // Save / discard
  $("btn-save").addEventListener("click", saveSettings);
  $("btn-discard").addEventListener("click", discardChanges);

  // Reset all data
  $("btn-reset").addEventListener("click", confirmReset);

  // Backend test
  $("btn-test-connection").addEventListener("click", () => checkBackend(true));

  // API key eye toggle
  $("btn-eye").addEventListener("click", toggleKeyVisibility);

  // Any input change → mark dirty
  Object.values(inputs).forEach((el) => {
    const event = el.type === "checkbox" ? "change" : "input";
    el.addEventListener(event, markDirty);
  });

  // Site toggles (attached after renderSiteList)
  SITES.forEach(({ host }) => {
    const el = document.getElementById(`site-tog-${host}`);
    el?.addEventListener("change", markDirty);
  });

  // Port change → re-check backend after short delay
  inputs.port.addEventListener("input", () => {
    clearTimeout(inputs.port._timer);
    inputs.port._timer = setTimeout(() => checkBackend(false), 800);
  });
}

// ─── Site list rendering ──────────────────────────────────────────────────────

function renderSiteList() {
  const list = $("site-list");
  list.innerHTML = SITES.map(({ name, host, icon }) => `
    <div class="site-row">
      <div class="site-info">
        <div class="site-favicon">${icon}</div>
        <div>
          <div class="site-name">${name}</div>
          <div class="site-host">${host}</div>
        </div>
      </div>
      <label class="toggle-wrap">
        <input type="checkbox" id="site-tog-${host}" checked />
        <div class="toggle-track"></div>
        <div class="toggle-thumb"></div>
      </label>
    </div>
  `).join("");
}

// ─── Backend connection check ─────────────────────────────────────────────────

async function checkBackend(showResult) {
  const port   = parseInt(inputs.port.value, 10) || 8000;
  const dot    = $("backend-dot");
  const status = $("backend-status");

  dot.className    = "status-dot checking";
  status.textContent = "Checking…";

  try {
    const res = await fetch(`http://localhost:${port}/health`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });

    if (res.ok) {
      dot.className      = "status-dot online";
      status.textContent = "Online";
      if (showResult) showToast("Backend is reachable ✓", "success");
    } else {
      throw new Error(`HTTP ${res.status}`);
    }
  } catch {
    dot.className      = "status-dot offline";
    status.textContent = "Offline";
    if (showResult) showToast("Cannot reach backend — is it running?", "error");
  }
}

// ─── API key eye toggle ───────────────────────────────────────────────────────

function toggleKeyVisibility() {
  const inp  = inputs.apiKey;
  const icon = $("icon-eye");
  const show = inp.type === "password";

  inp.type = show ? "text" : "password";

  // Swap icon: open eye ↔ crossed eye
  icon.innerHTML = show
    ? `<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94"/>
       <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19"/>
       <line x1="1" y1="1" x2="23" y2="23"/>`
    : `<path d="M1 12S5 4 12 4s11 8 11 8-4 8-11 8S1 12 1 12Z"/>
       <circle cx="12" cy="12" r="3"/>`;
}

// ─── Reset ────────────────────────────────────────────────────────────────────

async function confirmReset() {
  const ok = window.confirm(
    "Reset all PasteWise data?\n\n" +
    "This will delete:\n" +
    "  • All intercept and paste stats\n" +
    "  • Your concept history and streak\n" +
    "  • Cached AI responses\n" +
    "  • Recent paste history\n\n" +
    "Your settings will be kept. This cannot be undone."
  );
  if (!ok) return;

  const port = parseInt(inputs.port.value, 10) || 8000;

  try {
    const res = await fetch(`http://localhost:${port}/reset`, { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    showToast("All data reset successfully", "success");
  } catch (err) {
    showToast(`Reset failed: ${err.message}`, "error");
  }
}

// ─── About section ────────────────────────────────────────────────────────────

function renderAbout() {
  const port  = inputs.port.value || 8000;
  $("about-backend").textContent = `localhost:${port}`;
  $("about-model").textContent   = inputs.model.value;
}

// ─── Toast ────────────────────────────────────────────────────────────────────

let toastTimer = null;

function showToast(message, type = "success") {
  const toast = $("toast");
  $("toast-msg").textContent = message;
  toast.className = `toast ${type} show`;

  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.classList.remove("show");
  }, 3200);
}