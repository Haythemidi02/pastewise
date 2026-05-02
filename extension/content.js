// content.js
// Injected into every target site (Replit, LeetCode, CodePen, etc.)
// Responsibilities:
//   1. Detect paste events inside code editors
//   2. Read clipboard text
//   3. Call Python backend for explanation
//   4. Render popup overlay via Shadow DOM
//   5. Handle user decision: paste / deep dive / cancel
//   6. Record the event back to backend

(() => {
  // ─── Guard: only run once even if script injected multiple times ───────────
  if (window.__pastewise_loaded) return;
  window.__pastewise_loaded = true;

  const BACKEND = "http://localhost:8000";

  // ─── 1. EDITOR DETECTION ──────────────────────────────────────────────────
  // Returns true if the element that received the paste is inside a known
  // code editor widget, or is itself a textarea (fallback for simple editors).

  function isCodeEditor(element) {
    if (!element) return false;

    // Monaco (VS Code engine) — used by CodeSandbox, StackBlitz, etc.
    if (element.closest(".monaco-editor")) return true;

    // CodeMirror 5 — used by Replit, JSFiddle, older CodePen
    if (element.closest(".CodeMirror")) return true;

    // CodeMirror 6 — newer Replit, etc.
    if (element.closest(".cm-editor")) return true;

    // Ace editor — used by Cloud9, some LeetCode views
    if (element.closest(".ace_editor")) return true;

    // LeetCode's custom editor wrapper
    if (element.closest("[data-layout-path]")) return true;

    // Generic contenteditable divs that look like code editors
    if (
      element.isContentEditable &&
      element.closest("[class*='editor'], [class*='Editor'], [id*='editor']")
    ) return true;

    // Plain textarea as last resort (CodePen's fallback, simple playgrounds)
    if (element.tagName === "TEXTAREA") return true;

    return false;
  }

  // ─── 2. PASTE INTERCEPTION ────────────────────────────────────────────────

  document.addEventListener("paste", async (event) => {
    const target = event.target;

    if (!isCodeEditor(target)) return;

    // Grab clipboard text BEFORE we call preventDefault,
    // because on some browsers readText() needs the original event trust.
    let code = "";
    try {
      code = await navigator.clipboard.readText();
    } catch {
      // Fallback: read from the DataTransfer object attached to the event
      code = event.clipboardData?.getData("text/plain") ?? "";
    }

    // Nothing useful in clipboard — let the paste go through normally
    if (!code.trim()) return;

    // Block the native paste while we show the popup
    event.preventDefault();
    event.stopPropagation();

    // Show loading state immediately so the user knows something is happening
    const popup = createPopup();
    showLoading(popup);

    // Ask the Python backend for a quick explanation
    let result;
    try {
      const response = await fetch(`${BACKEND}/explain`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, mode: "quick" }),
      });

      if (!response.ok) throw new Error(`Backend error: ${response.status}`);
      result = await response.json();
    } catch (err) {
      showError(popup, err.message);
      return;
    }

    // Render the explanation inside the popup
    showExplanation(popup, result, {
      // User chose to paste without reading deeper
      onPaste: () => {
        destroyPopup(popup);
        pasteIntoEditor(target, code);
        recordPaste(false);
      },

      // User wants a line-by-line breakdown first
      onDeepDive: async () => {
        showLoading(popup);
        let deepResult;
        try {
          const response = await fetch(`${BACKEND}/explain`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ code, mode: "deep" }),
          });
          if (!response.ok) throw new Error(`Backend error: ${response.status}`);
          deepResult = await response.json();
        } catch (err) {
          showError(popup, err.message);
          return;
        }

        showDeepDive(popup, deepResult, {
          onPaste: () => {
            destroyPopup(popup);
            pasteIntoEditor(target, code);
            recordPaste(true); // user DID read before pasting
          },
          onCancel: () => destroyPopup(popup),
        });
      },

      // User dismissed the popup without pasting
      onCancel: () => destroyPopup(popup),
    });
  }, true); // capture phase — fires before editor's own paste handler

  // ─── 3. PASTE REPLAYER ────────────────────────────────────────────────────
  // After the user approves, we insert the code into the editor.
  // Strategy: dispatch a real InputEvent so the editor's own history/state
  // stays consistent. Falls back to execCommand for older editors.

  function pasteIntoEditor(target, text) {
    target.focus();

    // Try the modern InputEvent path first (Monaco, CM6 listen to this)
    const inserted = document.execCommand("insertText", false, text);

    if (!inserted) {
      // Last resort for plain textareas
      const start = target.selectionStart ?? 0;
      const end = target.selectionEnd ?? 0;
      const before = target.value.slice(0, start);
      const after = target.value.slice(end);
      target.value = before + text + after;
      target.selectionStart = target.selectionEnd = start + text.length;
      target.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }

  // ─── 4. STAT RECORDING ────────────────────────────────────────────────────

  function recordPaste(readFirst) {
    // Try direct fetch first; fall back to service worker relay
    fetch(`${BACKEND}/record-paste`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ read_first: readFirst }),
    }).catch(() => {
      chrome.runtime.sendMessage({ type: "RECORD_PASTE", read_first: readFirst });
    });
  }

  // ─── 5. SHADOW DOM POPUP ──────────────────────────────────────────────────
  // We mount the popup into a Shadow DOM so our styles never clash with
  // the host page's CSS, and the host page's styles never leak in.

  let hostEl = null;
  let shadowRoot = null;

  function createPopup() {
    hostEl = document.createElement("div");
    hostEl.id = "pastewise-host";
    Object.assign(hostEl.style, {
      position: "fixed",
      top: "0",
      left: "0",
      width: "0",
      height: "0",
      zIndex: "2147483647",
      overflow: "visible",
    });
    document.body.appendChild(hostEl);

    shadowRoot = hostEl.attachShadow({ mode: "open" });

    // Inject styles into the shadow root
    const style = document.createElement("style");
    style.textContent = POPUP_CSS;
    shadowRoot.appendChild(style);

    const container = document.createElement("div");
    container.id = "pw-container";
    shadowRoot.appendChild(container);

    return container;
  }

  function destroyPopup(container) {
    if (container && container.dataset.timerId) {
      clearInterval(parseInt(container.dataset.timerId));
    }
    hostEl?.remove();
    hostEl = null;
    shadowRoot = null;
  }

  // ─── 6. POPUP STATES ──────────────────────────────────────────────────────

  function showLoading(container) {
    container.innerHTML = `
      <div class="pw-popup">
        <div class="pw-header">
          <span class="pw-logo">PasteWise</span>
        </div>
        <div class="pw-loading">
          <div class="pw-spinner"></div>
          <p>Analyzing your code…</p>
        </div>
      </div>`;
  }

  function showError(container, message) {
    container.innerHTML = `
      <div class="pw-popup">
        <div class="pw-header">
          <span class="pw-logo">PasteWise</span>
          <button class="pw-close" id="pw-close">✕</button>
        </div>
        <div class="pw-error">
          <p>⚠ Could not reach backend</p>
          <small>${escapeHTML(message)}</small>
          <small>Make sure the Python server is running on port 8000.</small>
        </div>
        <div class="pw-actions">
          <button class="pw-btn pw-btn-ghost" id="pw-cancel">Dismiss</button>
        </div>
      </div>`;

    shadowRoot.getElementById("pw-close")?.addEventListener("click", () => destroyPopup(container));
    shadowRoot.getElementById("pw-cancel")?.addEventListener("click", () => destroyPopup(container));
  }

  function showExplanation(container, result, { onPaste, onDeepDive, onCancel }) {
    const { summary = "", tags = [], coverage_score = 0 } = result;

    let summaryHTML = escapeHTML(summary);
    let secondsLeft = 0;
    
    // Detect rate limit messages and inject a span for the live countdown
    const match = summary.match(/wait (\d+) seconds/);
    if (match) {
      secondsLeft = parseInt(match[1]);
      summaryHTML = summaryHTML.replace(
        /wait \d+ seconds/,
        `wait <strong id="pw-countdown" style="color: #f9e2af;">${secondsLeft}</strong> seconds`
      );
    }

    const tagHTML = tags
      .map((t) => `<span class="pw-tag">${escapeHTML(t)}</span>`)
      .join("");

    const scoreColor =
      coverage_score >= 70 ? "pw-score-high"
      : coverage_score >= 40 ? "pw-score-mid"
      : "pw-score-low";

    container.innerHTML = `
      <div class="pw-popup">
        <div class="pw-header">
          <span class="pw-logo">PasteWise</span>
          <button class="pw-close" id="pw-close">✕</button>
        </div>

        <div class="pw-body">
          <p class="pw-summary">${summaryHTML}</p>

          <div class="pw-tags">${tagHTML}</div>

          <div class="pw-score-row">
            <span class="pw-score-label">Concept coverage</span>
            <div class="pw-score-bar">
              <div class="pw-score-fill ${scoreColor}" style="width:${coverage_score}%"></div>
            </div>
            <span class="pw-score-num">${coverage_score}</span>
          </div>
        </div>

        <div class="pw-actions">
          <button class="pw-btn pw-btn-ghost" id="pw-cancel">Cancel</button>
          <button class="pw-btn pw-btn-secondary" id="pw-deepdive">Line by line ↓</button>
          <button class="pw-btn pw-btn-primary" id="pw-paste">Paste it</button>
        </div>
      </div>`;

    shadowRoot.getElementById("pw-close")?.addEventListener("click", onCancel);
    shadowRoot.getElementById("pw-cancel")?.addEventListener("click", onCancel);
    shadowRoot.getElementById("pw-paste")?.addEventListener("click", onPaste);
    shadowRoot.getElementById("pw-deepdive")?.addEventListener("click", onDeepDive);

    // Start live countdown if a rate limit was hit
    if (secondsLeft > 0) {
      const timerId = setInterval(() => {
        secondsLeft--;
        const el = container.querySelector("#pw-countdown");
        if (el) {
          el.textContent = Math.max(0, secondsLeft);
        }
        if (secondsLeft <= 0) {
          clearInterval(timerId);
          if (el) el.style.color = "#a6e3a1"; // turn green when ready
        }
      }, 1000);
      container.dataset.timerId = timerId;
    }
  }

  function showDeepDive(container, result, { onPaste, onCancel }) {
    const lines = result.lines ?? [];

    const rowsHTML = lines
      .map(
        ({ code, comment }) => `
        <tr>
          <td class="pw-code">${escapeHTML(code)}</td>
          <td class="pw-comment">${escapeHTML(comment)}</td>
        </tr>`
      )
      .join("");

    container.innerHTML = `
      <div class="pw-popup pw-popup-wide">
        <div class="pw-header">
          <span class="pw-logo">PasteWise · Line by line</span>
          <button class="pw-close" id="pw-close">✕</button>
        </div>

        <div class="pw-body pw-scroll">
          <table class="pw-table">
            <thead>
              <tr>
                <th>Code</th>
                <th>What it does</th>
              </tr>
            </thead>
            <tbody>${rowsHTML}</tbody>
          </table>
        </div>

        <div class="pw-actions">
          <button class="pw-btn pw-btn-ghost" id="pw-cancel">Cancel</button>
          <button class="pw-btn pw-btn-primary" id="pw-paste">Paste it</button>
        </div>
      </div>`;

    shadowRoot.getElementById("pw-close")?.addEventListener("click", onCancel);
    shadowRoot.getElementById("pw-cancel")?.addEventListener("click", onCancel);
    shadowRoot.getElementById("pw-paste")?.addEventListener("click", onPaste);
  }

  // ─── 7. HELPERS ───────────────────────────────────────────────────────────

  function escapeHTML(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // ─── 8. POPUP CSS (injected into Shadow DOM) ──────────────────────────────

  const POPUP_CSS = `
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    #pw-container {
      position: fixed;
      bottom: 28px;
      right: 28px;
      z-index: 2147483647;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 14px;
      line-height: 1.5;
    }

    .pw-popup {
      background: #1e1e2e;
      color: #cdd6f4;
      border: 1px solid #313244;
      border-radius: 12px;
      width: 360px;
      box-shadow: 0 8px 32px rgba(0,0,0,0.45);
      overflow: hidden;
    }

    .pw-popup-wide { width: 620px; }

    /* Header */
    .pw-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 16px;
      border-bottom: 1px solid #313244;
    }

    .pw-logo {
      font-weight: 600;
      font-size: 13px;
      color: #cba6f7;
      letter-spacing: 0.04em;
    }

    .pw-close {
      background: none;
      border: none;
      color: #6c7086;
      cursor: pointer;
      font-size: 14px;
      padding: 2px 6px;
      border-radius: 4px;
      line-height: 1;
    }
    .pw-close:hover { background: #313244; color: #cdd6f4; }

    /* Body */
    .pw-body { padding: 16px; }

    .pw-scroll { max-height: 320px; overflow-y: auto; }

    .pw-summary {
      font-size: 14px;
      color: #cdd6f4;
      margin-bottom: 12px;
      line-height: 1.6;
    }

    /* Tags */
    .pw-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 14px; }

    .pw-tag {
      background: #313244;
      color: #89b4fa;
      border-radius: 20px;
      padding: 2px 10px;
      font-size: 12px;
      font-weight: 500;
    }

    /* Coverage score */
    .pw-score-row {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .pw-score-label { font-size: 12px; color: #6c7086; white-space: nowrap; }

    .pw-score-bar {
      flex: 1;
      height: 6px;
      background: #313244;
      border-radius: 3px;
      overflow: hidden;
    }

    .pw-score-fill { height: 100%; border-radius: 3px; transition: width 0.4s ease; }
    .pw-score-high { background: #a6e3a1; }
    .pw-score-mid  { background: #f9e2af; }
    .pw-score-low  { background: #f38ba8; }

    .pw-score-num { font-size: 12px; color: #6c7086; min-width: 24px; text-align: right; }

    /* Actions */
    .pw-actions {
      display: flex;
      gap: 8px;
      justify-content: flex-end;
      padding: 12px 16px;
      border-top: 1px solid #313244;
    }

    .pw-btn {
      border: none;
      border-radius: 8px;
      padding: 7px 14px;
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      transition: opacity 0.15s;
    }
    .pw-btn:hover { opacity: 0.85; }

    .pw-btn-ghost     { background: transparent; color: #6c7086; }
    .pw-btn-ghost:hover { background: #313244; color: #cdd6f4; opacity: 1; }
    .pw-btn-secondary { background: #313244; color: #89b4fa; }
    .pw-btn-primary   { background: #cba6f7; color: #1e1e2e; }

    /* Loading */
    .pw-loading {
      padding: 24px 16px;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 12px;
      color: #6c7086;
      font-size: 13px;
    }

    .pw-spinner {
      width: 22px;
      height: 22px;
      border: 2px solid #313244;
      border-top-color: #cba6f7;
      border-radius: 50%;
      animation: pw-spin 0.7s linear infinite;
    }

    @keyframes pw-spin { to { transform: rotate(360deg); } }

    /* Error */
    .pw-error {
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 6px;
      color: #f38ba8;
      font-size: 13px;
    }
    .pw-error small { color: #6c7086; font-size: 11px; }

    /* Deep dive table */
    .pw-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }

    .pw-table th {
      text-align: left;
      padding: 6px 8px;
      color: #6c7086;
      font-weight: 500;
      border-bottom: 1px solid #313244;
      position: sticky;
      top: 0;
      background: #1e1e2e;
    }

    .pw-table tr:not(:last-child) td { border-bottom: 1px solid #1e1e2e; }
    .pw-table tr:hover td { background: #181825; }

    .pw-code {
      font-family: "JetBrains Mono", "Fira Code", monospace;
      white-space: pre;
      padding: 5px 8px;
      color: #89b4fa;
      width: 50%;
      vertical-align: top;
    }

    .pw-comment {
      padding: 5px 8px;
      color: #a6adc8;
      vertical-align: top;
    }
  `;
})();