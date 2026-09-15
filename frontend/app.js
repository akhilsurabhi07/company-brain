/**
 * Company Brain — EXL v6B Controller
 * Clean ChatGPT Dark Theme Enterprise OS
 */

// ─── Real Auth Gate ───────────────────────────────────────────────────────
// Before this, the app loaded straight to chat using whatever tenant_id sat
// in localStorage (or a hardcoded default) — no login, and no backend
// endpoint checked who was asking. Real signup/login (/api/v1/auth/*) always
// existed and worked, it just wasn't wired to anything. This gate is that
// wiring: nothing renders until a real signed JWT is present.
window.authFetch = function (url, options) {
  options = options || {};
  const token = localStorage.getItem("auth_token");
  const headers = Object.assign({}, options.headers || {}, token ? { "Authorization": "Bearer " + token } : {});
  return fetch(url, Object.assign({}, options, { headers })).then((res) => {
    if (res.status === 401) {
      // Token missing/expired/invalid — force back to a real login rather than
      // silently failing or (as before) never having required a token at all.
      localStorage.removeItem("auth_token");
      localStorage.removeItem("tenant_id");
      localStorage.removeItem("user_id");
      location.reload();
    }
    return res;
  });
};

(function authGate() {
  const gate = document.getElementById("auth-gate");
  const existingToken = localStorage.getItem("auth_token");

  if (existingToken) {
    // Already have a real token from a previous session — skip straight to the app.
    // If it's actually expired, the first authFetch() call will 401 and reload us
    // back here.
    gate.classList.add("hidden");
    document.body.classList.remove("unauthenticated");
    bootApp();
    return;
  }

  document.body.classList.add("unauthenticated");
  gate.classList.remove("hidden");

  const loginTab      = document.getElementById("auth-tab-login");
  const signupTab     = document.getElementById("auth-tab-signup");
  const loginForm     = document.getElementById("login-form");
  const signupForm    = document.getElementById("signup-form");
  const errorEl       = document.getElementById("auth-error");
  const inviteBanner  = document.getElementById("invite-banner");

  // ── Invite link handling ──────────────────────────────────────────────
  // A real invite (see POST /api/v1/auth/invite) is shared as a URL like
  // /?invite=TOKEN&email=teammate@co.com&domain=acme.com&company=Acme — this
  // prefills and locks the fields the invite already determines, so the
  // teammate only ever has to set their own password.
  const params = new URLSearchParams(location.search);
  const inviteToken = params.get("invite");
  if (inviteToken) {
    switchTab("signup");
    document.getElementById("signup-invite-token").value = inviteToken;
    const emailInput  = document.getElementById("signup-email");
    const domainInput = document.getElementById("signup-company-domain");
    const nameInput   = document.getElementById("signup-company-name");
    if (params.get("email"))   { emailInput.value = params.get("email"); emailInput.readOnly = true; }
    if (params.get("domain"))  { domainInput.value = params.get("domain"); domainInput.readOnly = true; }
    if (params.get("company")) { nameInput.value = params.get("company"); nameInput.readOnly = true; }
    inviteBanner.textContent = params.get("company")
      ? `You've been invited to join ${params.get("company")}. Set a password to finish joining.`
      : "You've been invited to join a workspace. Set a password to finish joining.";
    inviteBanner.classList.remove("hidden");
  }

  function showError(msg) {
    errorEl.textContent = msg;
    errorEl.classList.remove("hidden");
  }
  function clearError() {
    errorEl.classList.add("hidden");
  }
  function switchTab(which) {
    clearError();
    loginTab.classList.toggle("active", which === "login");
    signupTab.classList.toggle("active", which === "signup");
    loginForm.classList.toggle("hidden", which !== "login");
    signupForm.classList.toggle("hidden", which !== "signup");
  }
  loginTab.addEventListener("click", () => switchTab("login"));
  signupTab.addEventListener("click", () => switchTab("signup"));

  function onAuthSuccess(data) {
    localStorage.setItem("auth_token", data.token);
    localStorage.setItem("tenant_id", data.tenant_id);
    localStorage.setItem("user_id", data.user_id);
    // Real bug found via live testing 2026-08-21: the sidebar footer showed a
    // permanently hardcoded "Surabhi Akhil" / "SA" for every user of the app —
    // a teammate logging into their own real account saw someone else's name.
    // The real email is right here in the login/signup response; save it so
    // the footer can show who's actually signed in.
    if (data.email) localStorage.setItem("user_email", data.email);
    gate.classList.add("hidden");
    document.body.classList.remove("unauthenticated");
    bootApp();
  }

  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    clearError();
    const btn = document.getElementById("login-submit-btn");
    btn.disabled = true;
    try {
      const res = await fetch("/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: document.getElementById("login-email").value.trim(),
          password: document.getElementById("login-password").value,
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Login failed.");
      onAuthSuccess(data);
    } catch (err) {
      showError(err.message || "Could not log in. Please try again.");
    } finally {
      btn.disabled = false;
    }
  });

  signupForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    clearError();
    const btn = document.getElementById("signup-submit-btn");
    btn.disabled = true;
    try {
      const enteredInviteToken = document.getElementById("signup-invite-token").value;
      const res = await fetch("/api/v1/auth/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          company_name: document.getElementById("signup-company-name").value.trim(),
          company_domain: document.getElementById("signup-company-domain").value.trim(),
          email: document.getElementById("signup-email").value.trim(),
          password: document.getElementById("signup-password").value,
          ...(enteredInviteToken ? { invite_token: enteredInviteToken } : {}),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Could not create workspace.");
      onAuthSuccess(data);
    } catch (err) {
      showError(err.message || "Could not create workspace. Please try again.");
    } finally {
      btn.disabled = false;
    }
  });
})();

function bootApp() {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initApp);
  } else {
    initApp();
  }
}

function initApp() {

  // ─── Element References ───────────────────────────────────────────────
  const sidebar           = document.getElementById("sidebar");
  const sidebarToggleBtn  = document.getElementById("sidebar-toggle-btn");
  const sidebarOpenBtn    = document.getElementById("sidebar-open-btn");
  const newChatBtn        = document.getElementById("new-chat-btn");
  const sidebarHistory    = document.getElementById("sidebar-history");
  const pinnedHistory     = document.getElementById("pinned-history");
  const pinnedTitle       = document.getElementById("pinned-section-title");
  const searchInput       = document.getElementById("sidebar-search-input");

  const chatScrollArea    = document.getElementById("chat-scroll-area");
  const welcomeHero       = document.getElementById("welcome-hero");
  const messagesContainer = document.getElementById("messages-container");
  const promptTextarea    = document.getElementById("prompt-textarea");
  const sendBtn           = document.getElementById("send-btn");
  const stopBtn           = document.getElementById("stop-btn");
  let activeAbortController = null;

  const modelSelect       = document.getElementById("model-select");
  const toastEl           = document.getElementById("toast");

  const artifactDrawer    = document.getElementById("artifact-drawer");
  const closeArtifactBtn  = document.getElementById("close-artifact-drawer-btn");

  // ─── App State ────────────────────────────────────────────────────────
  const API_BASE_URL    = "/api/v6a/chat/turn";
  const STREAM_URL      = "/api/v6a/chat/stream";

  // Real bug found via live testing 2026-08-21: the default (index 0, selected on
  // every fresh page load) was "Grounded Mock Engine" → provider "mock", which
  // conversation_service.py maps straight to MockProviderAdapter — a stub that
  // never calls a real model at all. Every new user who never touched this
  // dropdown was silently talking to a fake stub for every single message. The
  // real, working default this whole session's testing has used is sending NO
  // preferred_provider at all, letting the real health-aware auto-router pick —
  // that's now "auto" and is first/default. Mock is kept, for genuine offline
  // testing, but moved last and no longer the default anyone lands on. Names
  // also corrected — "OpenAI 5.6 Sol" was a fabricated model name that doesn't
  // exist; "Groq (Llama 3.3 70B)" didn't match the real model actually used
  // (openai/gpt-oss-120b per RuntimeOrchestrator). Anthropic and the free local
  // fallback were both real, registered providers missing from this list entirely.
  const models = [
    { name: "Auto (Recommended) ˅",    provider: "" },
    { name: "OpenAI",                  provider: "openai" },
    { name: "Groq",                    provider: "groq" },
    { name: "Gemini",                  provider: "gemini" },
    { name: "Anthropic",               provider: "anthropic" },
    { name: "HuggingFace",             provider: "huggingface" },
    { name: "Local (Free, Offline)",   provider: "local" },
    { name: "Mock (Offline Test Stub)", provider: "mock" },
  ];

  // Real bug found via live testing 2026-08-21: the sidebar footer's name and
  // initials were hardcoded in index.html ("Surabhi Akhil" / "SA") for every
  // user, forever — a teammate signing into their own real account still saw
  // someone else's name in their own sidebar. Populate it from the real signed-
  // in identity captured at login.
  (function populateRealUserFooter() {
    const email = localStorage.getItem("user_email");
    if (!email) return;
    const nameEl = document.querySelector(".sidebar-footer .user-profile-btn span");
    const avatarEl = document.querySelector(".sidebar-footer .user-avatar-circle");
    const localPart = email.split("@")[0];
    if (nameEl) nameEl.textContent = localPart;
    if (avatarEl) avatarEl.textContent = localPart.slice(0, 2).toUpperCase();
  })();

  let currentModelIdx  = 0;
  let currentSessionId = "sess_" + Date.now();
  let chatHistory      = [];
  let devModeActive    = false;
  let activeTenant     = localStorage.getItem("tenant_id") || "00000000-0000-0000-0000-000000000001";
  let searchQuery      = "";

  // ─── Toast ────────────────────────────────────────────────────────────
  window.showToast = function(msg) {
    toastEl.textContent = msg;
    toastEl.style.cssText = `
      position: fixed; bottom: 80px; left: 50%; transform: translateX(-50%);
      background: #2f2f2f; color: #fff; border: 1px solid #383838;
      padding: 10px 20px; border-radius: 10px; font-size: 0.85rem;
      z-index: 9999; display: block; opacity: 1; transition: opacity 0.3s;
    `;
    clearTimeout(toastEl._timer);
    toastEl._timer = setTimeout(() => {
      toastEl.style.opacity = "0";
      setTimeout(() => { toastEl.style.display = "none"; }, 300);
    }, 3000);
  };

  // ─── More Submenu Toggle ──────────────────────────────────────────────
  window.toggleMoreSubmenu = function() {
    const sub = document.getElementById("more-submenu");
    if (sub) sub.classList.toggle("hidden");
  };
  if (modelSelect) {
    // Real bug found via live browser testing 2026-08-22: the models[] array
    // above was fixed to put "Auto (Recommended)" first, but the actual
    // <select> element in index.html was a static, hardcoded single
    // <option>"Grounded Mock Engine ˅"</option> that this code never
    // touched — so every real page load still visibly showed "Grounded Mock
    // Engine" with no other choices in the dropdown at all, regardless of
    // what the JS array said. The outgoing request itself was already safe
    // (currentModelIdx pointed at the real "auto" entry), but the UI was
    // both misleading and non-functional as a model picker. Populate the
    // real <option> list from the single source of truth (models[]) so the
    // two can never drift apart again.
    modelSelect.innerHTML = models
      .map((m, idx) => `<option value="${idx}"${idx === currentModelIdx ? " selected" : ""}>${m.name}</option>`)
      .join("");

    modelSelect.addEventListener("change", (e) => {
      currentModelIdx = parseInt(e.target.value, 10) || 0;
      showToast(`Selected model: ${models[currentModelIdx].name.replace(" ˅", "")}`);
    });
  }

  // ─── Three-Dots Menu Toggle ───────────────────────────────────────────
  window.toggleThreeDotsMenu = function() {
    const menu = document.getElementById("three-dots-menu");
    if (menu) menu.classList.toggle("hidden");
  };

  document.addEventListener("click", (e) => {
    const menu = document.getElementById("three-dots-menu");
    const btn  = document.getElementById("three-dots-btn");
    if (menu && !menu.classList.contains("hidden") && !menu.contains(e.target) && e.target !== btn) {
      menu.classList.add("hidden");
    }
  });

  // ─── Profile Menu / Real Logout ────────────────────────────────────────
  // Real gap found via live end-to-end user-journey testing 2026-08-24: no
  // logout existed anywhere in the app. Real logout: clears the actual auth
  // state (the same keys onAuthSuccess sets) and reloads — the exact same
  // path authFetch's own 401 handler already uses for an expired token, so
  // this is proven, existing logic, not a new, separate mechanism.
  window.toggleProfileMenu = function() {
    const menu = document.getElementById("profile-menu");
    if (menu) menu.classList.toggle("hidden");
  };

  window.handleLogout = function() {
    localStorage.removeItem("auth_token");
    localStorage.removeItem("tenant_id");
    localStorage.removeItem("user_id");
    localStorage.removeItem("user_email");
    location.reload();
  };

  document.addEventListener("click", (e) => {
    const menu = document.getElementById("profile-menu");
    const btn  = document.getElementById("user-profile-btn");
    if (menu && !menu.classList.contains("hidden") && !menu.contains(e.target) && e.target !== btn && !btn?.contains(e.target)) {
      menu.classList.add("hidden");
    }
  });

  // ─── Dev Telemetry Toggle ─────────────────────────────────────────────
  window.toggleDevTelemetry = function() {
    devModeActive = !devModeActive;
    showToast(devModeActive ? "Dev Telemetry Mode ON" : "Dev Telemetry Mode OFF");
  };

  // ─── Artifact Drawer Toggle (opens to the gallery, Claude.ai-style) ────
  window.toggleArtifactDrawer = function() {
    if (!artifactDrawer) return;
    const wasHidden = artifactDrawer.classList.contains("hidden");
    artifactDrawer.classList.toggle("hidden");
    if (wasHidden) openArtifactGallery();
  };

  if (closeArtifactBtn) {
    closeArtifactBtn.addEventListener("click", () => artifactDrawer.classList.add("hidden"));
  }
  document.getElementById("close-artifact-drawer-btn-2")?.addEventListener("click", () => artifactDrawer.classList.add("hidden"));
  document.getElementById("artifact-back-btn")?.addEventListener("click", () => openArtifactGallery());

  // ─── Artifact Tab Switcher ────────────────────────────────────────────
  window.switchArtifactTab = function(tabName) {
    ["preview", "code"].forEach(t => {
      const pane = document.getElementById(`art-pane-${t}`);
      const btn  = document.getElementById(`art-tab-${t}`);
      if (t === tabName) {
        pane?.classList.remove("hidden");
        btn?.classList.add("active");
      } else {
        pane?.classList.add("hidden");
        btn?.classList.remove("active");
      }
    });
  };

  // ─── Artifacts (per-session, derived live from real chat content) ─────
  // Detects genuine artifact-worthy content (fenced code blocks, or long
  // multi-heading documents) already present in the assistant's actual
  // responses and builds a real gallery from it — replacing the old
  // artifact drawer, which only ever showed one hardcoded static example
  // regardless of what the assistant actually said. Recomputed from
  // chatHistory (which is already persisted via Store) rather than kept
  // in its own separate store, so there's one source of truth and no
  // risk of the gallery drifting out of sync with what was actually said.
  let sessionArtifacts = [];

  const ARTIFACT_ICONS = { python: "🐍", javascript: "📜", js: "📜", json: "🧾", sql: "🗄️", bash: "💻", sh: "💻", html: "🌐", css: "🎨", markdown: "📄", md: "📄", document: "📄", text: "📄" };

  function detectArtifacts(text, msgIndex) {
    if (!text) return [];
    const found = [];
    let n = 0;

    // 1) Fenced code blocks worth their own artifact (skip tiny inline snippets)
    const codeRe = /```(\w+)?\n([\s\S]*?)```/g;
    let m;
    while ((m = codeRe.exec(text)) !== null) {
      const lang = (m[1] || "text").toLowerCase();
      const content = m[2].trim();
      if (content.length < 60 && content.split("\n").length < 4) continue; // too small to be an "artifact"
      const firstLine = content.split("\n")[0].replace(/^[#/*\-\s]+/, "").trim();
      found.push({
        msgIndex, type: lang, content,
        title: firstLine && firstLine.length < 60 ? firstLine : `${lang.toUpperCase()} snippet`
      });
      n++;
    }

    // 2) Long, multi-heading responses — treat the whole answer as a document
    const headingCount = (text.match(/^#{1,3}\s.+$/gm) || []).length;
    if (headingCount >= 2 && text.length > 500) {
      const firstHeading = (text.match(/^#{1,3}\s(.+)$/m) || [, "Generated Document"])[1];
      found.push({ msgIndex, type: "document", content: text, title: firstHeading.trim() });
    }

    return found;
  }

  // Recomputes the artifact list for the current session from chatHistory.
  // Call after chatHistory changes (new message, session load, reset).
  function refreshArtifacts() {
    sessionArtifacts = [];
    chatHistory.forEach((msg, idx) => {
      if (msg.role === "assistant") sessionArtifacts.push(...detectArtifacts(msg.content, idx));
    });
    updateArtifactBadge();
    const galleryVisible = artifactDrawer && !artifactDrawer.classList.contains("hidden") &&
      !document.getElementById("artifact-gallery-view")?.classList.contains("hidden");
    if (galleryVisible) renderArtifactGallery();
  }

  function updateArtifactBadge() {
    const badge = document.getElementById("artifact-count-badge");
    if (!badge) return;
    if (sessionArtifacts.length > 0) {
      badge.textContent = sessionArtifacts.length > 99 ? "99+" : String(sessionArtifacts.length);
      badge.classList.remove("hidden");
    } else {
      badge.classList.add("hidden");
    }
  }

  function renderArtifactGallery() {
    const grid = document.getElementById("artifact-gallery-grid");
    const heading = document.getElementById("artifact-gallery-heading");
    if (!grid) return;

    if (heading) heading.textContent = sessionArtifacts.length ? `${sessionArtifacts.length} in this conversation` : "This conversation";

    if (!sessionArtifacts.length) {
      grid.innerHTML = `
        <div class="artifact-empty-state">
          <span class="icon">📄</span>
          <div>No artifacts yet.</div>
          <div style="font-size:0.78rem;">Code, specs, and long documents the assistant generates in this chat will show up here.</div>
        </div>`;
      return;
    }

    grid.innerHTML = sessionArtifacts.map((a, i) => `
      <div class="artifact-card" data-idx="${i}">
        <span class="artifact-card-icon">${ARTIFACT_ICONS[a.type] || "📄"}</span>
        <span class="artifact-card-title">${escapeHtml(a.title)}</span>
        <span class="artifact-card-meta">${escapeHtml(a.type)}</span>
      </div>
    `).join("");
  }

  // Event delegation: one listener each for gallery cards and inline chat
  // chips, so every render path (live stream, session load, restore) works
  // without re-binding listeners per element.
  document.getElementById("artifact-gallery-grid")?.addEventListener("click", (e) => {
    const card = e.target.closest(".artifact-card");
    if (card) openArtifactDetail(parseInt(card.dataset.idx, 10));
  });
  messagesContainer?.addEventListener("click", (e) => {
    const chip = e.target.closest(".message-artifact-chip");
    if (chip) openArtifactDetail(parseInt(chip.dataset.idx, 10));
  });

  window.openArtifactGallery = function() {
    document.getElementById("artifact-gallery-view")?.classList.remove("hidden");
    document.getElementById("artifact-detail-view")?.classList.add("hidden");
    renderArtifactGallery();
  };

  // Real artifact pinning (2026-08-22) — the vision calls for a "pin" action
  // on artifacts, same as conversations already have via Store.togglePin.
  // Artifacts have no server-side identity (they're re-derived from
  // chatHistory on every load, not a stored entity — see the Download
  // handler below for the same constraint), so the pin key is
  // session:msgIndex:type, stable across reloads as long as the underlying
  // chat history doesn't change shape.
  const PINNED_ARTIFACTS_KEY = "cb_pinned_artifacts";
  function _artifactPinKey(art) { return `${currentSessionId}:${art.msgIndex}:${art.type}`; }
  function isArtifactPinned(art) {
    try { return !!JSON.parse(localStorage.getItem(PINNED_ARTIFACTS_KEY) || "{}")[_artifactPinKey(art)]; }
    catch { return false; }
  }
  function toggleArtifactPin(art) {
    let pins = {};
    try { pins = JSON.parse(localStorage.getItem(PINNED_ARTIFACTS_KEY) || "{}"); } catch { pins = {}; }
    const key = _artifactPinKey(art);
    if (pins[key]) delete pins[key]; else pins[key] = { title: art.title, type: art.type, pinnedAt: Date.now() };
    localStorage.setItem(PINNED_ARTIFACTS_KEY, JSON.stringify(pins));
    return !!pins[key];
  }

  let _currentArtifact = null;

  window.openArtifactDetail = function(idx) {
    const art = sessionArtifacts[idx];
    if (!art) return;
    _currentArtifact = art;
    if (artifactDrawer) artifactDrawer.classList.remove("hidden");
    document.getElementById("artifact-gallery-view")?.classList.add("hidden");
    document.getElementById("artifact-detail-view")?.classList.remove("hidden");

    document.getElementById("artifact-drawer-title").textContent = art.title;
    const badgeEl = document.getElementById("artifact-detail-type-badge");
    if (badgeEl) badgeEl.textContent = `${ARTIFACT_ICONS[art.type] || "📄"} ${art.type}`;

    const pinBtn = document.getElementById("artifact-pin-btn");
    if (pinBtn) {
      const pinned = isArtifactPinned(art);
      pinBtn.textContent = pinned ? "★ Pinned" : "☆ Pin";
      pinBtn.classList.toggle("pinned", pinned);
    }

    const previewPane = document.getElementById("art-pane-preview");
    const codePane    = document.getElementById("art-pane-code-content");
    if (art.type === "document") {
      previewPane.innerHTML = renderMarkdown(art.content);
    } else {
      previewPane.innerHTML = `<pre style="white-space:pre-wrap;"><code>${escapeHtml(art.content)}</code></pre>`;
    }
    codePane.textContent = art.content;
    switchArtifactTab("preview");
  };

  // Real file extensions for common languages so a downloaded artifact opens
  // correctly in an editor instead of landing as a bare ".txt".
  const ARTIFACT_EXTENSIONS = {
    document: "md", python: "py", javascript: "js", typescript: "ts",
    json: "json", html: "html", css: "css", sql: "sql", bash: "sh",
    shell: "sh", yaml: "yml", java: "java", go: "go", rust: "rs", text: "txt",
  };

  document.getElementById("artifact-download-btn")?.addEventListener("click", () => {
    if (!_currentArtifact) return;
    const ext = ARTIFACT_EXTENSIONS[_currentArtifact.type] || "txt";
    const safeTitle = (_currentArtifact.title || "artifact").replace(/[^a-z0-9\-_. ]/gi, "_").trim() || "artifact";
    const blob = new Blob([_currentArtifact.content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${safeTitle}.${ext}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showToast("Downloaded ✓");
  });

  document.getElementById("artifact-pin-btn")?.addEventListener("click", () => {
    if (!_currentArtifact) return;
    const nowPinned = toggleArtifactPin(_currentArtifact);
    const pinBtn = document.getElementById("artifact-pin-btn");
    if (pinBtn) {
      pinBtn.textContent = nowPinned ? "★ Pinned" : "☆ Pin";
      pinBtn.classList.toggle("pinned", nowPinned);
    }
    showToast(nowPinned ? "Artifact pinned" : "Artifact unpinned");
  });

  // Builds the inline "artifact card" chip(s) shown directly under a chat
  // message that produced one — same source data as the gallery, just
  // surfaced where the user is already looking, matching how Claude.ai
  // and ChatGPT surface generated documents/canvases inline.
  function renderArtifactChipsHTML(msgIndex) {
    const idxs = sessionArtifacts.reduce((acc, a, i) => { if (a.msgIndex === msgIndex) acc.push(i); return acc; }, []);
    if (!idxs.length) return "";
    return `<div style="display:flex;flex-direction:column;gap:8px;">${idxs.map(i => {
      const a = sessionArtifacts[i];
      return `<div class="message-artifact-chip" data-idx="${i}">
        <span class="chip-icon">${ARTIFACT_ICONS[a.type] || "📄"}</span>
        <span class="chip-text">
          <span class="chip-title">${escapeHtml(a.title)}</span>
          <span class="chip-meta">${escapeHtml(a.type)}</span>
        </span>
      </div>`;
    }).join("")}</div>`;
  }

  // For a message bubble built incrementally (streaming), insert its chips
  // after the fact rather than re-rendering the whole bubble from scratch.
  function injectArtifactChips(msgDiv, msgIndex) {
    const chipsHTML = renderArtifactChipsHTML(msgIndex);
    if (!chipsHTML || !msgDiv) return;
    const body = msgDiv.querySelector(".message-body");
    if (body) body.insertAdjacentHTML("afterend", chipsHTML);
  }

  // ─── Inspector / Evidence Drawer ────────────────────────────────────────
  // Stores citations per message: { msgId: ["citation1", ...] }
  window._msgCitations = {};

  window.openInspectorModal = function(type, queryText = "", citations = []) {
    const modal   = document.getElementById("inspector-drawer");
    const title   = document.getElementById("inspector-drawer-title");
    const content = document.getElementById("inspector-drawer-content");
    const workspace = document.getElementById("workspace-body");
    
    if (!modal || !title || !content) return;
    
    // Close artifact drawer if open so they don't overlap awkwardly
    document.getElementById("artifact-drawer").classList.add("hidden");
    workspace.classList.remove("artifact-open");

    if (type === "evidence") {
      title.textContent = "📄 Evidence & Citations";
      if (!citations || citations.length === 0) {
        content.innerHTML = `
          <p style="color:#b4b4b4; font-size:0.85rem; margin-bottom:12px;">Source: Enterprise Knowledge Vault v2.0.0</p>
          <div class="glass-info-box">
            <p style="color:#8e8e8e; font-size:0.85rem; margin:0;">
              ℹ️ This answer was generated using <strong style="color:#ececec;">general knowledge</strong> — no specific company documents were retrieved for this query.
            </p>
          </div>`;
      } else {
        content.innerHTML = `
          <p style="color:#b4b4b4; font-size:0.8rem; margin-bottom:10px;">Source: Enterprise Knowledge Vault v2.0.0 · ${citations.length} document(s) retrieved</p>
          ${citations.map((c, i) => {
            const isWeb = String(c).startsWith("http");
            const icon = isWeb ? "🌐" : "📄";
            const cText = escapeHtml(String(c));
            const cLink = isWeb ? `<a href="${cText}" target="_blank" style="color:#60a5fa; text-decoration:underline;">${cText}</a>` : cText;
            return `
            <div class="glass-card" style="display:flex; gap:10px; align-items:center;">
              <b style="color:#10a37f; min-width:24px;">[${i+1}]</b> 
              <span style="font-size:1.1rem;">${icon}</span>
              <span style="color:#ececec; font-size:0.85rem; word-break:break-all;">${cLink}</span>
            </div>`;
          }).join("")}`;
      }
    } else if (type === "explain") {
      // Real replacement (2026-08-20) for a hardcoded "Grounding: 98.4% / Hallucination
      // Guard: PASSED" shown identically for every answer, whether it was actually
      // grounded or not. Backed by explanation_engine.py's real fix — this turn's
      // actual GroundingGuard/CitationValidator/AIResponseReviewEngine results and
      // real retrieved evidence, captured in window._lastTurnExplanation when the
      // response arrived.
      title.textContent = "❓ Why This Answer?";
      const exp = window._lastTurnExplanation && window._lastTurnExplanation.explanation;
      if (!exp) {
        content.innerHTML = `
          <div class="glass-info-box">
            <p style="color:#8e8e8e; font-size:0.85rem; margin:0;">ℹ️ No explanation captured for this turn yet — ask a question first.</p>
          </div>`;
      } else {
        const statusColor = exp.grounding_status === "VERIFIED_GROUNDED" ? "#10a37f" : exp.grounding_status === "NO_COMPANY_DATA_RETRIEVED" ? "#60a5fa" : "#ef4444";
        const statusLabel = exp.grounding_status === "VERIFIED_GROUNDED" ? "Grounded in your data" : exp.grounding_status === "NO_COMPANY_DATA_RETRIEVED" ? "General knowledge (no company data)" : "Not grounded";
        content.innerHTML = `
          <div class="glass-card">
            <b>Real Reasoning:</b><br>
            <p style="color:#b4b4b4; font-size:0.85rem; margin-top:6px;">${escapeHtml(exp.reasoning_summary || "")}</p>
            <div style="display:flex; gap:8px; margin-top:10px; flex-wrap:wrap;">
              <span style="font-size:0.75rem; background:${statusColor}22; color:${statusColor}; padding:3px 8px; border-radius:4px;">${escapeHtml(statusLabel)}</span>
              <span style="font-size:0.75rem; background:rgba(139,92,246,0.15); color:#a78bfa; padding:3px 8px; border-radius:4px;">Confidence: ${Math.round((exp.confidence_score || 0) * 100)}%</span>
            </div>
          </div>
          ${exp.evidence_used && exp.evidence_used.length ? `
            <p style="color:#b4b4b4; font-size:0.8rem; margin-bottom:8px;">Real evidence used (${exp.evidence_used.length}):</p>
            ${exp.evidence_used.map(e => `
              <div style="background:#212121; padding:10px; border-radius:8px; border:1px solid #383838; margin-bottom:6px;">
                <span style="color:#ececec; font-size:0.85rem;">${escapeHtml(e.doc_title || "Untitled")}</span>
                <span style="color:#8e8e8e; font-size:0.75rem; float:right;">${escapeHtml(e.source_app || "")} · score ${(e.rerank_score || 0).toFixed ? e.rerank_score.toFixed(2) : e.rerank_score}</span>
              </div>`).join("")}
          ` : `<p style="color:#8e8e8e; font-size:0.8rem;">No company documents were used as evidence for this answer.</p>`}
        `;
      }
    } else if (type === "graph") {
      // Real replacement (2026-08-20) for what used to be two hardcoded fake nodes
      // ("Enterprise Knowledge", "Knowledge Context") drawn for every single query
      // regardless of what was actually asked. Now queries the real graph_entities/
      // graph_relationships tables for this tenant via /api/v1/knowledge/graph-context.
      title.textContent = "🕸️ Knowledge Graph";
      content.innerHTML = `<p style="color:#8e8e8e; font-size:0.85rem;">Looking up real graph data for this query…</p>`;
      const gq = queryText || (promptTextarea ? promptTextarea.value : "") || "";
      authFetch(`/api/v1/knowledge/graph-context?tenant_id=${encodeURIComponent(activeTenant)}&query=${encodeURIComponent(gq)}`)
        .then(r => r.json())
        .then(data => {
          if (!data.matched || !data.nodes || data.nodes.length === 0) {
            content.innerHTML = `
              <div class="glass-info-box">
                <p style="color:#8e8e8e; font-size:0.85rem; margin:0;">
                  ℹ️ ${escapeHtml(data.message || "No entity from your knowledge graph matches this query yet.")}
                </p>
              </div>`;
            return;
          }
          content.innerHTML = `
            <p style="color:#b4b4b4; font-size:0.8rem; margin-bottom:8px;">Matched real entity: <strong style="color:#ececec;">${escapeHtml(data.matched_entity)}</strong> — ${data.edges.length} real relationship(s)</p>
            <div style="background:#171717; border-radius:8px; border:1px solid #383838; position:relative; overflow:hidden;">
              <div style="position:absolute; top:8px; left:8px; z-index:10; font-family:monospace; font-size:0.75rem; color:#8e8e8e; background:rgba(0,0,0,0.5); padding:4px 8px; border-radius:4px;">Scroll to zoom, drag to pan</div>
              <canvas id="kg-canvas" width="380" height="300" style="display:block; width:100%; height:300px; cursor:grab;"></canvas>
            </div>`;
          setTimeout(() => renderBasicGraph(document.getElementById("kg-canvas"), data.nodes, data.edges), 50);
        })
        .catch(() => {
          content.innerHTML = `<p style="color:#ef4444; font-size:0.85rem;">Could not reach the knowledge graph service.</p>`;
        });
    } else if (type === "timeline") {
      // Real replacement (2026-08-20) for a fixed 6-step list ("Query Received",
      // "Knowledge Retrieval", ...) shown identically for every turn regardless of
      // what actually happened. Now renders the real per-turn retrieval diagnostics
      // captured when Dev Telemetry Mode was on for that turn (hybrid_retriever's own
      // debug output — candidate counts, latencies, rerank threshold) — nothing here
      // is fabricated, and if no real data was captured, that's stated honestly.
      title.textContent = "⏱️ Execution Timeline";
      const dbg = window._lastTurnDebug;
      if (!dbg || !dbg.debug) {
        content.innerHTML = `
          <div class="glass-info-box">
            <p style="color:#8e8e8e; font-size:0.85rem; margin:0;">
              ℹ️ No real execution data captured yet. Turn on <strong style="color:#ececec;">Dev Telemetry Mode</strong> (⋯ menu) before sending a message to see its real retrieval pipeline stages here.
            </p>
          </div>`;
      } else {
        const d = dbg.debug;
        const rows = [
          ["Query embedded", `${d.embedding_model} (${d.embedding_dimension}d)`],
          ["Vector candidates found", d.vector_candidate_count],
          ["Keyword candidates found", d.keyword_candidate_count],
          ["Fused candidate pool", d.fused_candidate_count],
          ["Reranked", d.reranked_candidate_count],
          ["Accepted (score ≥ threshold)", `${d.selected_count} (threshold ${d.rerank_accept_threshold})`],
          ["Rerank latency", `${d.rerank_latency_ms?.toFixed ? d.rerank_latency_ms.toFixed(1) : d.rerank_latency_ms} ms`],
          ["Total retrieval latency", `${d.total_latency_ms?.toFixed ? d.total_latency_ms.toFixed(1) : d.total_latency_ms} ms`],
        ];
        content.innerHTML = `
          <p style="color:#b4b4b4; font-size:0.8rem; margin-bottom:10px;">Real pipeline stages for: "${escapeHtml(dbg.query || "")}"</p>
          <div style="display:flex; flex-direction:column; gap:8px;">
            ${rows.map(([label, val]) => `
              <div style="display:flex; justify-content:space-between; gap:10px; background:#212121; padding:8px 12px; border-radius:6px; border:1px solid #383838;">
                <span style="font-size:0.82rem; color:#b4b4b4;">${escapeHtml(label)}</span>
                <span style="font-size:0.82rem; color:#ececec; font-family:var(--font-mono);">${escapeHtml(String(val))}</span>
              </div>`).join("")}
          </div>`;
      }
    } else if (type === "decisions") {
      // Real Module 6B panel (2026-08-22) — this data (graph_decisions) already
      // existed and was already populated; it just had no read endpoint or UI
      // surface anywhere before now. RBAC redaction is applied server-side
      // (app/security/content_redaction.py), same policy as decisions surfaced
      // through chat, so a non-admin never sees a restricted figure here either.
      title.textContent = "📊 Decisions";
      content.innerHTML = `<p style="color:#8e8e8e; font-size:0.85rem;">Loading real decisions…</p>`;
      authFetch(`/api/v1/knowledge/decisions?tenant_id=${encodeURIComponent(activeTenant)}`)
        .then(r => r.json())
        .then(data => {
          if (!data.decisions || data.decisions.length === 0) {
            content.innerHTML = `
              <div class="glass-info-box">
                <p style="color:#8e8e8e; font-size:0.85rem; margin:0;">ℹ️ No decisions recorded for your organization yet.</p>
              </div>`;
            return;
          }
          content.innerHTML = data.decisions.map(d => `
            <div class="glass-card">
              <div style="display:flex; justify-content:space-between; align-items:start; gap:8px;">
                <b style="color:#ececec; font-size:0.9rem;">${escapeHtml(d.title || "Untitled decision")}</b>
                <span style="font-size:0.72rem; background:rgba(16,163,127,0.15); color:#10a37f; padding:2px 8px; border-radius:4px; white-space:nowrap;">${escapeHtml(d.state || "unknown")}</span>
              </div>
              <p style="color:#b4b4b4; font-size:0.82rem; margin-top:6px; white-space:pre-wrap;">${escapeHtml(d.rationale || "")}</p>
              ${d.expected_outcome ? `<p style="color:#8e8e8e; font-size:0.78rem; margin-top:4px;">Expected: ${escapeHtml(d.expected_outcome)}</p>` : ""}
            </div>`).join("");
        })
        .catch(() => {
          content.innerHTML = `<p style="color:#ef4444; font-size:0.85rem;">Could not reach the decisions service.</p>`;
        });
    } else if (type === "projects") {
      // Real Module 6B "Project memory" foundation (2026-08-22). Before this,
      // conversation history had no durable server-side storage at all
      // (in-memory only, wiped on restart) and "Projects" had no backend
      // concept — both fixed together (see app/conversation/session/
      // postgres_repo.py and app/api/projects_router.py). This is a real
      // MVP: named containers you can file the current conversation into,
      // revisitable later — not yet the vision's full per-project
      // decisions/docs/artifacts/timeline scope.
      title.textContent = "📁 Projects";
      renderProjectsPanel(content);
    } else if (type === "plugins") {
      // Real Module 6C panel (2026-08-23). Found+built the same way as
      // Library/Admin Dashboard: research first. app/api/connectors_router.py
      // (real AES-256-GCM token encryption, real Redis caching, real Slack
      // token verification via auth.test), app/api/{google,jira,microsoft}
      // _oauth_router.py (real OAuth start/callback flows), and
      // app/api/ingestion_router.py's real /start + /status (which
      // ConnectorRegistry.get_connector() genuinely calls, unlike the
      // orphaned app/graph/extraction/ plugin system) were ALL already real,
      // tested, and registered in main.py — just never called from any
      // frontend. No new backend was needed here at all.
      title.textContent = "🔌 Plugins";
      renderPluginsPanel(content);
    } else if (type === "scheduled") {
      // Real Module 6C panel (2026-08-23) — recurring saved questions,
      // chosen (via a real product decision, not a guess) over Celery-beat
      // sync scheduling or email digests, since it's the smallest fully
      // real, fully testable scope: reuses the existing chat/RAG pipeline
      // directly, no new delivery infrastructure needed.
      title.textContent = "⏱️ Scheduled";
      renderScheduledPanel(content);
    } else if (type === "risks") {
      // Real Module 6B panel (2026-08-22). The vision's "Risks" concept maps
      // onto the real, already-populated graph_conflicts table (sources
      // disagreeing with each other) — an honest proxy for "needs a human to
      // look at it", not a fabricated separate risk-scoring system.
      title.textContent = "⚠️ Risks";
      content.innerHTML = `<p style="color:#8e8e8e; font-size:0.85rem;">Loading real risks…</p>`;
      const severityColor = { critical: "#ef4444", high: "#f59e0b", medium: "#60a5fa", low: "#8e8e8e" };
      authFetch(`/api/v1/knowledge/risks?tenant_id=${encodeURIComponent(activeTenant)}`)
        .then(r => r.json())
        .then(data => {
          if (!data.risks || data.risks.length === 0) {
            content.innerHTML = `
              <div class="glass-info-box">
                <p style="color:#8e8e8e; font-size:0.85rem; margin:0;">ℹ️ No open risks or data conflicts detected for your organization.</p>
              </div>`;
            return;
          }
          content.innerHTML = data.risks.map(r => {
            const color = severityColor[r.severity] || "#8e8e8e";
            return `
            <div class="glass-card">
              <div style="display:flex; justify-content:space-between; align-items:start; gap:8px;">
                <b style="color:#ececec; font-size:0.9rem;">${escapeHtml(r.type || "Unspecified")}</b>
                <span style="font-size:0.72rem; background:${color}22; color:${color}; padding:2px 8px; border-radius:4px; white-space:nowrap;">${escapeHtml(r.severity || "unknown")}</span>
              </div>
              <p style="color:#b4b4b4; font-size:0.82rem; margin-top:6px;">${escapeHtml(r.description || "")}</p>
              <p style="color:#8e8e8e; font-size:0.75rem; margin-top:4px;">Status: ${escapeHtml(r.resolution_status || "open")}</p>
            </div>`;
          }).join("");
        })
        .catch(() => {
          content.innerHTML = `<p style="color:#ef4444; font-size:0.85rem;">Could not reach the risks service.</p>`;
        });
    } else if (type === "people") {
      // Real Module 6B panel (2026-08-23) — the real users table every
      // other endpoint already trusts, surfaced as a directory for the
      // first time. No RBAC redaction: this is organizational directory
      // info, not restricted content.
      title.textContent = "👤 People";
      content.innerHTML = `<p style="color:#8e8e8e; font-size:0.85rem;">Loading real people…</p>`;
      authFetch(`/api/v1/workspace/people?tenant_id=${encodeURIComponent(activeTenant)}`)
        .then(r => r.json())
        .then(data => {
          if (!data.people || data.people.length === 0) {
            content.innerHTML = `<div class="glass-info-box"><p style="color:#8e8e8e; font-size:0.85rem; margin:0;">ℹ️ No team members found.</p></div>`;
            return;
          }
          content.innerHTML = data.people.map(p => `
            <div class="glass-card" style="display:flex; align-items:center; gap:10px;">
              <div style="width:32px; height:32px; border-radius:50%; background:#10a37f22; color:#10a37f; display:flex; align-items:center; justify-content:center; font-weight:600; font-size:0.8rem; flex-shrink:0;">${escapeHtml((p.full_name || p.email || "?").slice(0,2).toUpperCase())}</div>
              <div style="min-width:0;">
                <b style="color:#ececec; font-size:0.88rem;">${escapeHtml(p.full_name || p.email)}</b>
                <div style="color:#8e8e8e; font-size:0.75rem;">${escapeHtml(p.email)} · ${escapeHtml(p.role || "member")}${p.department ? " · " + escapeHtml(p.department) : ""}</div>
              </div>
            </div>`).join("");
        })
        .catch(() => {
          content.innerHTML = `<p style="color:#ef4444; font-size:0.85rem;">Could not reach the people service.</p>`;
        });
    } else if (type === "teams") {
      // Real Module 6B panel (2026-08-23) — teams derived from the real
      // users.department column. The vision's fuller Teams concept
      // (dedicated team entities) doesn't exist as a schema yet, so this is
      // an honest synthesis from real data rather than a separate
      // fabricated concept.
      title.textContent = "👥 Teams";
      content.innerHTML = `<p style="color:#8e8e8e; font-size:0.85rem;">Loading real teams…</p>`;
      authFetch(`/api/v1/workspace/teams?tenant_id=${encodeURIComponent(activeTenant)}`)
        .then(r => r.json())
        .then(data => {
          if (!data.teams || data.teams.length === 0) {
            content.innerHTML = `<div class="glass-info-box"><p style="color:#8e8e8e; font-size:0.85rem; margin:0;">ℹ️ No team members found yet.</p></div>`;
            return;
          }
          content.innerHTML = data.teams.map(t => `
            <div class="glass-card">
              <div style="display:flex; justify-content:space-between; align-items:center;">
                <b style="color:#ececec; font-size:0.9rem;">${escapeHtml(t.team_name)}</b>
                <span style="font-size:0.72rem; color:#8e8e8e;">${t.member_count} member(s)</span>
              </div>
              <p style="color:#b4b4b4; font-size:0.8rem; margin-top:6px;">${t.members.map(m => escapeHtml(m.full_name || m.email)).join(", ")}</p>
            </div>`).join("");
        })
        .catch(() => {
          content.innerHTML = `<p style="color:#ef4444; font-size:0.85rem;">Could not reach the teams service.</p>`;
        });
    } else if (type === "workspace-documents") {
      // Real Module 6B panel (2026-08-23) — the real documents table,
      // filtered by the exact same ACL clause hybrid_retriever.py already
      // uses for retrieval, so this never lists a document this caller
      // couldn't actually search over either.
      title.textContent = "📄 Documents";
      content.innerHTML = `<p style="color:#8e8e8e; font-size:0.85rem;">Loading real documents…</p>`;
      const uid = localStorage.getItem("user_id") || "";
      authFetch(`/api/v1/workspace/documents?tenant_id=${encodeURIComponent(activeTenant)}&user_id=${encodeURIComponent(uid)}`)
        .then(r => r.json())
        .then(data => {
          if (!data.documents || data.documents.length === 0) {
            content.innerHTML = `<div class="glass-info-box"><p style="color:#8e8e8e; font-size:0.85rem; margin:0;">ℹ️ No documents ingested yet.</p></div>`;
            return;
          }
          content.innerHTML = data.documents.map(d => `
            <div class="glass-card" style="display:flex; justify-content:space-between; align-items:flex-start; gap:10px;">
              <div>
                <b style="color:#ececec; font-size:0.88rem;">${escapeHtml(d.title || "Untitled")}</b>
                <div style="color:#8e8e8e; font-size:0.75rem; margin-top:4px;">${escapeHtml(d.source_app || "")} · ${escapeHtml(d.resource_category || "")}${d.created_at ? " · " + new Date(d.created_at).toLocaleDateString() : ""}</div>
              </div>
              <button class="action-btn-sm pin-doc-btn" data-doc-id="${escapeHtml(d.id)}" title="Add to Library" style="white-space:nowrap;">📌 Pin</button>
            </div>`).join("");
          // Real Library wiring (2026-08-23): pins the document via the real
          // /documents/{id}/pin endpoint so it shows up in the Library panel —
          // no fake "saved" state, the button reflects a real DB row.
          content.querySelectorAll(".pin-doc-btn").forEach(btn => {
            btn.addEventListener("click", () => {
              const docId = btn.dataset.docId;
              btn.disabled = true;
              btn.textContent = "Pinning…";
              authFetch(`/api/v1/workspace/documents/${encodeURIComponent(docId)}/pin?tenant_id=${encodeURIComponent(activeTenant)}&user_id=${encodeURIComponent(uid)}`, { method: "POST" })
                .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
                .then(() => {
                  btn.textContent = "✓ Pinned";
                  showToast("Added to Library");
                })
                .catch(() => {
                  btn.disabled = false;
                  btn.textContent = "📌 Pin";
                  showToast("Could not pin this document");
                });
            });
          });
        })
        .catch(() => {
          content.innerHTML = `<p style="color:#ef4444; font-size:0.85rem;">Could not reach the documents service.</p>`;
        });
    } else if (type === "library") {
      // Real Module 6C panel (2026-08-23) — a genuine per-user curated
      // subset of Documents, backed by the real document_pins table. Was
      // honestly marked "Soon" until this pass; now real, reusing the exact
      // same ACL-safe read path as Documents.
      title.textContent = "📚 Library";
      content.innerHTML = `<p style="color:#8e8e8e; font-size:0.85rem;">Loading your library…</p>`;
      const libUid = localStorage.getItem("user_id") || "";
      authFetch(`/api/v1/workspace/library?tenant_id=${encodeURIComponent(activeTenant)}&user_id=${encodeURIComponent(libUid)}`)
        .then(r => r.json())
        .then(data => {
          if (!data.library || data.library.length === 0) {
            content.innerHTML = `<div class="glass-info-box"><p style="color:#8e8e8e; font-size:0.85rem; margin:0;">ℹ️ Nothing pinned yet. Open Documents and pin anything you want to keep close.</p></div>`;
            return;
          }
          content.innerHTML = data.library.map(d => `
            <div class="glass-card" style="display:flex; justify-content:space-between; align-items:flex-start; gap:10px;">
              <div>
                <b style="color:#ececec; font-size:0.88rem;">${escapeHtml(d.title || "Untitled")}</b>
                <div style="color:#8e8e8e; font-size:0.75rem; margin-top:4px;">${escapeHtml(d.source_app || "")} · ${escapeHtml(d.resource_category || "")}${d.pinned_at ? " · pinned " + new Date(d.pinned_at).toLocaleDateString() : ""}</div>
              </div>
              <button class="action-btn-sm unpin-doc-btn" data-doc-id="${escapeHtml(d.id)}" title="Remove from Library">✕ Unpin</button>
            </div>`).join("");
          content.querySelectorAll(".unpin-doc-btn").forEach(btn => {
            btn.addEventListener("click", () => {
              const docId = btn.dataset.docId;
              authFetch(`/api/v1/workspace/documents/${encodeURIComponent(docId)}/pin?tenant_id=${encodeURIComponent(activeTenant)}&user_id=${encodeURIComponent(libUid)}`, { method: "DELETE" })
                .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
                .then(() => openInspectorModal("library"))
                .catch(() => showToast("Could not remove this document"));
            });
          });
        })
        .catch(() => {
          content.innerHTML = `<p style="color:#ef4444; font-size:0.85rem;">Could not reach the library service.</p>`;
        });
    } else if (type === "dashboards") {
      // Real Module 6B panel (2026-08-23) — reuses the already-real,
      // already-computed /api/v1/knowledge/health metrics
      // (organizational_health_engine) rather than building a second,
      // duplicate health computation just to have a "Dashboards" surface.
      title.textContent = "📈 Dashboards";
      content.innerHTML = `<p style="color:#8e8e8e; font-size:0.85rem;">Loading real organizational health…</p>`;
      authFetch(`/api/v1/knowledge/health?tenant_id=${encodeURIComponent(activeTenant)}`)
        .then(r => r.json())
        .then(data => {
          const metrics = [
            ["Knowledge Quality Score", data.quality_score],
            ["Knowledge Freshness", data.knowledge_freshness_pct != null ? data.knowledge_freshness_pct + "%" : undefined],
            ["Documentation Coverage", data.documentation_coverage_pct != null ? data.documentation_coverage_pct + "%" : undefined],
            ["Orphan Projects", data.orphan_projects_count],
            ["Unassigned Tasks", data.unassigned_tasks_count],
            ["Active Conflicts", data.active_conflicts_count],
            ["Knowledge Gaps", data.knowledge_gaps_count],
          ].filter(([, v]) => v !== undefined && v !== null);
          if (!metrics.length) {
            content.innerHTML = `<div class="glass-info-box"><p style="color:#8e8e8e; font-size:0.85rem; margin:0;">ℹ️ No organizational health data yet — ingest some documents first.</p></div>`;
            return;
          }
          content.innerHTML = `<div style="display:flex; flex-direction:column; gap:8px;">${metrics.map(([label, val]) => `
            <div style="display:flex; justify-content:space-between; gap:10px; background:#212121; padding:10px 12px; border-radius:6px; border:1px solid #383838;">
              <span style="font-size:0.82rem; color:#b4b4b4;">${escapeHtml(label)}</span>
              <span style="font-size:0.82rem; color:#ececec; font-family:var(--font-mono);">${escapeHtml(String(val))}</span>
            </div>`).join("")}</div>`;
        })
        .catch(() => {
          content.innerHTML = `<p style="color:#ef4444; font-size:0.85rem;">Could not reach the dashboards service.</p>`;
        });
    } else if (type === "architecture-graph") {
      // Real Module 6B panel (2026-08-23) — a standalone, query-free browse
      // view of the tenant's whole real knowledge graph, using the exact
      // same real backend tables and node/edge shape (and the same
      // renderBasicGraph() canvas renderer) as the chat "Graph" button's
      // /graph-context, which requires a query matching one entity. Shows
      // the most-connected real entities first, not an arbitrary order.
      title.textContent = "🏛️ Architecture Graph";
      content.innerHTML = `<p style="color:#8e8e8e; font-size:0.85rem;">Loading your real knowledge graph…</p>`;
      authFetch(`/api/v1/knowledge/architecture-graph?tenant_id=${encodeURIComponent(activeTenant)}`)
        .then(r => r.json())
        .then(data => {
          if (!data.matched || !data.nodes || data.nodes.length === 0) {
            content.innerHTML = `
              <div class="glass-info-box">
                <p style="color:#8e8e8e; font-size:0.85rem; margin:0;">
                  ℹ️ ${escapeHtml(data.message || "No entities in your knowledge graph yet.")}
                </p>
              </div>`;
            return;
          }
          content.innerHTML = `
            <p style="color:#b4b4b4; font-size:0.8rem; margin-bottom:8px;">${data.nodes.length} real entit${data.nodes.length === 1 ? "y" : "ies"}, ${data.edges.length} real relationship(s)</p>
            <div style="background:#171717; border-radius:8px; border:1px solid #383838; position:relative; overflow:hidden;">
              <div style="position:absolute; top:8px; left:8px; z-index:10; font-family:monospace; font-size:0.75rem; color:#8e8e8e; background:rgba(0,0,0,0.5); padding:4px 8px; border-radius:4px;">Scroll to zoom, drag to pan</div>
              <canvas id="arch-graph-canvas" width="380" height="300" style="display:block; width:100%; height:300px; cursor:grab;"></canvas>
            </div>`;
          setTimeout(() => renderBasicGraph(document.getElementById("arch-graph-canvas"), data.nodes, data.edges), 50);
        })
        .catch(() => {
          content.innerHTML = `<p style="color:#ef4444; font-size:0.85rem;">Could not reach the architecture graph service.</p>`;
        });
    } else if (type === "settings") {
      // Real Settings panel (2026-08-31) — did not exist at all before this;
      // there was no backend endpoint for password change/profile update
      // anywhere in the codebase, not just a missing frontend page. Backed
      // by three new real endpoints in app/api/auth.py: GET /me,
      // PATCH /profile, POST /change-password. Reuses this same
      // openInspectorModal drawer every other panel uses rather than a new,
      // separate UI surface.
      title.textContent = "⚙️ Settings";
      content.innerHTML = `<p style="color:#8e8e8e; font-size:0.85rem;">Loading your profile…</p>`;
      authFetch(`/api/v1/auth/me`)
        .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
        .then(profile => {
          content.innerHTML = `
            <div style="display:flex; flex-direction:column; gap:20px;">
              <div>
                <h4 style="font-size:0.85rem; color:#ececec; margin-bottom:10px;">Profile</h4>
                <div style="display:flex; flex-direction:column; gap:10px;">
                  <label style="font-size:0.78rem; color:#8e8e8e;">Email
                    <input type="text" value="${escapeHtml(profile.email || "")}" disabled
                      style="width:100%; margin-top:4px; background:#171717; color:#6e6e6e; border:1px solid #383838; border-radius:6px; padding:8px 10px; font-size:0.85rem;">
                  </label>
                  <label style="font-size:0.78rem; color:#8e8e8e;">Full name
                    <input type="text" id="settings-full-name" value="${escapeHtml(profile.full_name || "")}"
                      style="width:100%; margin-top:4px; background:#1e1e1e; color:#ececec; border:1px solid #383838; border-radius:6px; padding:8px 10px; font-size:0.85rem;">
                  </label>
                  <label style="font-size:0.78rem; color:#8e8e8e;">Department
                    <input type="text" id="settings-department" value="${escapeHtml(profile.department || "")}"
                      style="width:100%; margin-top:4px; background:#1e1e1e; color:#ececec; border:1px solid #383838; border-radius:6px; padding:8px 10px; font-size:0.85rem;">
                  </label>
                  <label style="font-size:0.78rem; color:#8e8e8e;">Role
                    <input type="text" value="${escapeHtml(profile.role || "")}" disabled
                      style="width:100%; margin-top:4px; background:#171717; color:#6e6e6e; border:1px solid #383838; border-radius:6px; padding:8px 10px; font-size:0.85rem;">
                  </label>
                  <div id="settings-profile-msg" style="font-size:0.78rem; min-height:16px;"></div>
                  <button id="settings-save-profile-btn" class="action-btn-sm" style="align-self:flex-start;">Save profile</button>
                </div>
              </div>
              <div style="border-top:1px solid #383838; padding-top:16px;">
                <h4 style="font-size:0.85rem; color:#ececec; margin-bottom:10px;">Change password</h4>
                <div style="display:flex; flex-direction:column; gap:10px;">
                  <input type="password" id="settings-current-password" placeholder="Current password" autocomplete="current-password"
                    style="width:100%; background:#1e1e1e; color:#ececec; border:1px solid #383838; border-radius:6px; padding:8px 10px; font-size:0.85rem;">
                  <input type="password" id="settings-new-password" placeholder="New password (min 8 characters)" autocomplete="new-password"
                    style="width:100%; background:#1e1e1e; color:#ececec; border:1px solid #383838; border-radius:6px; padding:8px 10px; font-size:0.85rem;">
                  <input type="password" id="settings-confirm-password" placeholder="Confirm new password" autocomplete="new-password"
                    style="width:100%; background:#1e1e1e; color:#ececec; border:1px solid #383838; border-radius:6px; padding:8px 10px; font-size:0.85rem;">
                  <div id="settings-password-msg" style="font-size:0.78rem; min-height:16px;"></div>
                  <button id="settings-change-password-btn" class="action-btn-sm" style="align-self:flex-start;">Change password</button>
                </div>
              </div>
            </div>`;

          const profileMsg = document.getElementById("settings-profile-msg");
          document.getElementById("settings-save-profile-btn").addEventListener("click", (e) => {
            const btn = e.currentTarget;
            const full_name = document.getElementById("settings-full-name").value.trim();
            const department = document.getElementById("settings-department").value.trim();
            profileMsg.textContent = "";
            btn.disabled = true;
            btn.textContent = "Saving…";
            authFetch(`/api/v1/auth/profile`, {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ full_name, department }),
            })
              .then(async (r) => {
                const body = await r.json().catch(() => ({}));
                if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
                profileMsg.style.color = "#22c55e";
                profileMsg.textContent = "✓ Profile updated.";
                showToast("Profile updated");
              })
              .catch((err) => {
                profileMsg.style.color = "#ef4444";
                profileMsg.textContent = "✕ " + (err.message || "Could not update profile.");
              })
              .finally(() => {
                btn.disabled = false;
                btn.textContent = "Save profile";
              });
          });

          const pwMsg = document.getElementById("settings-password-msg");
          document.getElementById("settings-change-password-btn").addEventListener("click", (e) => {
            const btn = e.currentTarget;
            const current_password = document.getElementById("settings-current-password").value;
            const new_password = document.getElementById("settings-new-password").value;
            const confirm_password = document.getElementById("settings-confirm-password").value;
            pwMsg.style.color = "#ef4444";
            if (!current_password || !new_password) {
              pwMsg.textContent = "✕ Fill in both password fields.";
              return;
            }
            if (new_password.length < 8) {
              pwMsg.textContent = "✕ New password must be at least 8 characters.";
              return;
            }
            if (new_password !== confirm_password) {
              pwMsg.textContent = "✕ New password and confirmation don't match.";
              return;
            }
            pwMsg.textContent = "";
            btn.disabled = true;
            btn.textContent = "Changing…";
            authFetch(`/api/v1/auth/change-password`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ current_password, new_password }),
            })
              .then(async (r) => {
                const body = await r.json().catch(() => ({}));
                if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
                pwMsg.style.color = "#22c55e";
                pwMsg.textContent = "✓ Password changed.";
                document.getElementById("settings-current-password").value = "";
                document.getElementById("settings-new-password").value = "";
                document.getElementById("settings-confirm-password").value = "";
                showToast("Password changed");
              })
              .catch((err) => {
                pwMsg.style.color = "#ef4444";
                pwMsg.textContent = "✕ " + (err.message || "Could not change password.");
              })
              .finally(() => {
                btn.disabled = false;
                btn.textContent = "Change password";
              });
          });
        })
        .catch(() => {
          content.innerHTML = `<p style="color:#ef4444; font-size:0.85rem;">Could not load your profile.</p>`;
        });
    }

    modal.classList.remove("hidden");
    workspace.classList.add("inspector-open");
  };

  // Real Module 6B Projects panel (2026-08-22) — create/list projects, view
  // a project's real assigned conversations, and file the current
  // conversation into one. All backed by app/api/projects_router.py.
  async function renderProjectsPanel(content) {
    content.innerHTML = `<p style="color:#8e8e8e; font-size:0.85rem;">Loading real projects…</p>`;
    let data;
    try {
      const resp = await authFetch(`/api/v1/projects?tenant_id=${encodeURIComponent(activeTenant)}`);
      data = await resp.json();
    } catch {
      content.innerHTML = `<p style="color:#ef4444; font-size:0.85rem;">Could not reach the projects service.</p>`;
      return;
    }

    const projects = data.projects || [];
    content.innerHTML = `
      <div style="display:flex; gap:8px; margin-bottom:12px;">
        <input id="new-project-name-input" placeholder="New project name…" style="flex:1; background:#212121; border:1px solid #383838; border-radius:6px; padding:8px 10px; color:#ececec; font-size:0.85rem;">
        <button class="action-btn-sm" id="create-project-btn">+ Create</button>
      </div>
      <div id="projects-list">
        ${projects.length === 0
          ? `<div class="glass-info-box"><p style="color:#8e8e8e; font-size:0.85rem; margin:0;">ℹ️ No projects yet — create one to start grouping conversations.</p></div>`
          : projects.map(p => `
            <div class="project-card glass-card" data-pid="${p.id}" style="cursor:pointer;">
              <div style="display:flex; justify-content:space-between; align-items:center;">
                <b style="color:#ececec; font-size:0.9rem;">${escapeHtml(p.name)}</b>
                <span style="font-size:0.72rem; color:#8e8e8e;">${p.session_count} conversation(s)</span>
              </div>
              ${p.description ? `<p style="color:#b4b4b4; font-size:0.78rem; margin-top:4px;">${escapeHtml(p.description)}</p>` : ""}
              <button class="action-btn-sm add-to-project-btn" data-pid="${p.id}" style="margin-top:8px;">+ Add current chat</button>
            </div>`).join("")
        }
      </div>`;

    document.getElementById("create-project-btn")?.addEventListener("click", async () => {
      const input = document.getElementById("new-project-name-input");
      const name = (input?.value || "").trim();
      if (!name) return;
      try {
        const resp = await authFetch(`/api/v1/projects`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tenant_id: activeTenant, name }),
        });
        if (resp.ok) {
          showToast(`Project "${name}" created`);
          renderProjectsPanel(content);
        } else {
          showToast("Could not create project");
        }
      } catch {
        showToast("Could not create project");
      }
    });

    content.querySelectorAll(".add-to-project-btn").forEach(btn => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const pid = btn.dataset.pid;
        try {
          const resp = await authFetch(`/api/v1/projects/assign-session`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tenant_id: activeTenant, session_id: currentSessionId, project_id: pid }),
          });
          showToast(resp.ok ? "Added to project ✓" : "Could not add to project");
        } catch {
          showToast("Could not add to project");
        }
      });
    });
  }

  // ─── Plugins Panel (real connector management, Module 6C 2026-08-23) ───
  // OAuth-only connectors — these already reject a pasted-token connect
  // attempt server-side (connectors_router.py's real 400 guard) since a
  // stray call there would clobber a real, working refresh_token with an
  // inert placeholder. Real redirect flow instead: navigate the whole page
  // to /connectors/oauth/{app}/start, which itself 503s with a clear,
  // honest message if the server has no client_id/secret configured for it
  // — never a fake "connected" state.
  const OAUTH_ONLY_APPS = new Set(["google_drive", "jira", "sharepoint"]);
  let _pluginsPollTimer = null;

  async function renderPluginsPanel(content) {
    if (_pluginsPollTimer) { clearInterval(_pluginsPollTimer); _pluginsPollTimer = null; }
    content.innerHTML = `<p style="color:#8e8e8e; font-size:0.85rem;">Loading real connector state…</p>`;

    let listData, statusData;
    try {
      const [listResp, statusResp] = await Promise.all([
        authFetch(`/api/v1/connectors/list?tenant_id=${encodeURIComponent(activeTenant)}`),
        authFetch(`/api/v1/ingestion/status?tenant_id=${encodeURIComponent(activeTenant)}`),
      ]);
      listData = await listResp.json();
      statusData = await statusResp.json();
    } catch {
      content.innerHTML = `<p style="color:#ef4444; font-size:0.85rem;">Could not reach the connectors service.</p>`;
      return;
    }

    const statusByApp = {};
    (statusData.apps_status || []).forEach(s => { statusByApp[s.source_app] = s; });
    const connectors = listData.connectors || [];
    const anyConnected = connectors.some(c => c.is_connected);
    const anySyncing = Object.values(statusByApp).some(s => s.status === "syncing");

    const statusBadge = (c) => {
      if (!c.is_connected) return `<span style="font-size:0.72rem; color:#8e8e8e; background:#2a2a2a; padding:2px 8px; border-radius:100px;">Not connected</span>`;
      const s = statusByApp[c.id];
      const st = s?.status || "idle";
      const map = { idle: ["#8e8e8e", "Connected"], syncing: ["#f59e0b", "Syncing…"], error: ["#ef4444", "Sync error"], completed: ["#10a37f", "Synced"] };
      const [clr, label] = map[st] || map.idle;
      return `<span style="font-size:0.72rem; color:${clr}; background:${clr}22; padding:2px 8px; border-radius:100px;">${label}</span>`;
    };

    content.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
        <p style="color:#8e8e8e; font-size:0.78rem; margin:0;">${connectors.filter(c => c.is_connected).length} of ${connectors.length} connected</p>
        <button class="action-btn-sm" id="sync-all-btn" ${anyConnected ? "" : "disabled"} title="${anyConnected ? "Pull the latest data from every connected app" : "Connect an app first"}">↻ Sync All Connected</button>
      </div>
      <div id="connectors-list">
        ${connectors.map(c => {
          const s = statusByApp[c.id];
          const isOAuth = OAUTH_ONLY_APPS.has(c.id);
          return `
          <div class="connector-card glass-card" data-app="${c.id}">
            <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:10px;">
              <div>
                <b style="color:#ececec; font-size:0.92rem;">${escapeHtml(c.name)}</b>
                <span style="color:#666; font-size:0.72rem; margin-left:6px;">${escapeHtml(c.category)}</span>
                <div style="color:#8e8e8e; font-size:0.78rem; margin-top:2px;">${escapeHtml(c.description)}</div>
                ${c.is_connected ? `<div style="color:#666; font-size:0.72rem; margin-top:6px;">
                  ${s?.items_synced ? `${s.items_synced} item(s) synced` : "No items synced yet"}${s?.last_synced_at ? " · last synced " + new Date(s.last_synced_at).toLocaleString() : ""}
                  ${s?.status === "error" && s?.error ? `<div style="color:#ef4444; margin-top:2px;">⚠ ${escapeHtml(s.error)}</div>` : ""}
                </div>` : ""}
              </div>
              <div style="display:flex; flex-direction:column; align-items:flex-end; gap:6px;">
                ${statusBadge(c)}
                ${c.is_connected
                  ? `<button class="action-btn-sm disconnect-btn" data-app="${c.id}">Disconnect</button>`
                  : (isOAuth
                      ? `<button class="action-btn-sm oauth-connect-btn" data-app="${c.id}">Connect via OAuth</button>`
                      : `<button class="action-btn-sm token-connect-toggle-btn" data-app="${c.id}">Connect</button>`)
                }
              </div>
            </div>
            ${(!c.is_connected && !isOAuth) ? `
              <div class="token-connect-form" data-app="${c.id}" style="display:none; margin-top:10px; padding-top:10px; border-top:1px solid #2f2f2f;">
                <input type="password" class="token-input" data-app="${c.id}" placeholder="${c.id === "github" ? "GitHub personal access token" : c.id + " access token"}"
                  style="width:100%; background:#1a1a1a; border:1px solid #383838; border-radius:6px; padding:7px 10px; color:#ececec; font-size:0.82rem; margin-bottom:6px;">
                ${c.id === "github" ? `
                  <div style="display:flex; gap:6px; margin-bottom:6px;">
                    <input class="config-owner-input" data-app="${c.id}" placeholder="Repo owner (e.g. octocat)" style="flex:1; background:#1a1a1a; border:1px solid #383838; border-radius:6px; padding:7px 10px; color:#ececec; font-size:0.82rem;">
                    <input class="config-repo-input" data-app="${c.id}" placeholder="Repo name (e.g. Hello-World)" style="flex:1; background:#1a1a1a; border:1px solid #383838; border-radius:6px; padding:7px 10px; color:#ececec; font-size:0.82rem;">
                  </div>` : ""}
                <button class="action-btn-sm confirm-connect-btn" data-app="${c.id}">Save &amp; Connect</button>
              </div>` : ""}
          </div>`;
        }).join("")}
      </div>`;

    // ── Connect (paste-token) — expand the inline form ──
    content.querySelectorAll(".token-connect-toggle-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const form = content.querySelector(`.token-connect-form[data-app="${btn.dataset.app}"]`);
        if (form) form.style.display = form.style.display === "none" ? "block" : "none";
      });
    });

    // ── Connect (paste-token) — actually submit ──
    content.querySelectorAll(".confirm-connect-btn").forEach(btn => {
      btn.addEventListener("click", async () => {
        const app_ = btn.dataset.app;
        const tokenVal = content.querySelector(`.token-input[data-app="${app_}"]`)?.value?.trim();
        if (!tokenVal) { showToast("Enter a real access token first"); return; }
        const config = {};
        if (app_ === "github") {
          config.owner = content.querySelector(`.config-owner-input[data-app="${app_}"]`)?.value?.trim();
          config.repo = content.querySelector(`.config-repo-input[data-app="${app_}"]`)?.value?.trim();
        }
        btn.disabled = true; btn.textContent = "Connecting…";
        try {
          const resp = await authFetch(`/api/v1/connectors/connect`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tenant_id: activeTenant, source_app: app_, action: "connect", access_token: tokenVal, config }),
          });
          const data = await resp.json().catch(() => ({}));
          if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
          showToast(`✅ ${data.message || "Connected"}`);
          renderPluginsPanel(content);
        } catch (err) {
          btn.disabled = false; btn.textContent = "Save & Connect";
          showToast(`❌ ${err.message}`);
        }
      });
    });

    // ── Connect via real OAuth redirect ──
    content.querySelectorAll(".oauth-connect-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        window.location.href = `/api/v1/connectors/oauth/${encodeURIComponent(btn.dataset.app)}/start?tenant_id=${encodeURIComponent(activeTenant)}`;
      });
    });

    // ── Disconnect ──
    content.querySelectorAll(".disconnect-btn").forEach(btn => {
      btn.addEventListener("click", async () => {
        const app_ = btn.dataset.app;
        btn.disabled = true; btn.textContent = "Disconnecting…";
        try {
          const resp = await authFetch(`/api/v1/connectors/connect`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tenant_id: activeTenant, source_app: app_, action: "disconnect" }),
          });
          if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
          showToast(`Disconnected ${app_}`);
          renderPluginsPanel(content);
        } catch {
          btn.disabled = false; btn.textContent = "Disconnect";
          showToast("Could not disconnect");
        }
      });
    });

    // ── Sync All — triggers the real background pipeline, then polls real
    // status every 3s (matching /ingestion/status's own docstring: "Polled
    // every few seconds by frontend to display real-time counters") until
    // nothing is left syncing. ──
    document.getElementById("sync-all-btn")?.addEventListener("click", async () => {
      try {
        const resp = await authFetch(`/api/v1/ingestion/start`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tenant_id: activeTenant }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        showToast("Sync started");
        renderPluginsPanel(content);
        _pluginsPollTimer = setInterval(async () => {
          try {
            const sResp = await authFetch(`/api/v1/ingestion/status?tenant_id=${encodeURIComponent(activeTenant)}`);
            const sData = await sResp.json();
            const stillSyncing = (sData.apps_status || []).some(s => s.status === "syncing");
            if (!stillSyncing) {
              clearInterval(_pluginsPollTimer);
              _pluginsPollTimer = null;
              showToast("Sync finished");
            }
            // Only re-render if this panel is still the one open.
            if (document.getElementById("connectors-list")) renderPluginsPanel(content);
          } catch { /* transient poll failure — try again next tick */ }
        }, 3000);
      } catch {
        showToast("Could not start sync");
      }
    });

    if (anySyncing && !_pluginsPollTimer) {
      _pluginsPollTimer = setInterval(() => {
        if (document.getElementById("connectors-list")) renderPluginsPanel(content);
        else { clearInterval(_pluginsPollTimer); _pluginsPollTimer = null; }
      }, 3000);
    }
  }

  // ─── Scheduled Panel (real recurring saved questions, Module 6C 2026-08-23) ───
  // Real backend, not Celery — see app/scheduler/query_scheduler.py's
  // module docstring: Redis is confirmed unreachable in this environment,
  // so this runs on a real in-process asyncio loop instead.
  async function renderScheduledPanel(content) {
    content.innerHTML = `<p style="color:#8e8e8e; font-size:0.85rem;">Loading your scheduled questions…</p>`;
    let data;
    try {
      const resp = await authFetch(`/api/v1/scheduled?tenant_id=${encodeURIComponent(activeTenant)}`);
      data = await resp.json();
    } catch {
      content.innerHTML = `<p style="color:#ef4444; font-size:0.85rem;">Could not reach the scheduled-queries service.</p>`;
      return;
    }
    const schedules = data.schedules || [];
    const intervalLabel = (s) => s === 3600 ? "Hourly" : s === 86400 ? "Daily" : s === 604800 ? "Weekly" : `Every ${s}s`;
    const statusBadge = (s) => {
      if (!s.last_status) return `<span style="font-size:0.72rem; color:#8e8e8e; background:#2a2a2a; padding:2px 8px; border-radius:100px;">Never run yet</span>`;
      if (s.last_status === "error") return `<span style="font-size:0.72rem; color:#ef4444; background:#ef444422; padding:2px 8px; border-radius:100px;">Last run failed</span>`;
      return `<span style="font-size:0.72rem; color:#10a37f; background:#10a37f22; padding:2px 8px; border-radius:100px;">Up to date</span>`;
    };

    content.innerHTML = `
      <div class="glass-card" style="margin-bottom:12px;">
        <textarea id="new-schedule-query" placeholder="Question to re-run automatically, e.g. “What changed in our open risks this week?”"
          style="width:100%; min-height:56px; background:#1a1a1a; border:1px solid #383838; border-radius:6px; padding:8px 10px; color:#ececec; font-size:0.85rem; resize:vertical; margin-bottom:8px;"></textarea>
        <div style="display:flex; gap:8px; align-items:center;">
          <select id="new-schedule-interval" style="background:#1a1a1a; border:1px solid #383838; border-radius:6px; padding:7px 10px; color:#ececec; font-size:0.82rem;">
            <option value="hourly">Hourly</option>
            <option value="daily" selected>Daily</option>
            <option value="weekly">Weekly</option>
          </select>
          <button class="action-btn-sm" id="create-schedule-btn" style="margin-left:auto;">+ Schedule</button>
        </div>
      </div>
      <div id="schedules-list">
        ${schedules.length === 0
          ? `<div class="glass-info-box"><p style="color:#8e8e8e; font-size:0.85rem; margin:0;">ℹ️ No scheduled questions yet — add one above and it will keep a fresh, real answer on its own.</p></div>`
          : schedules.map(s => `
            <div class="schedule-card glass-card" data-id="${s.id}">
              <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:10px;">
                <div style="flex:1;">
                  <b style="color:#ececec; font-size:0.88rem;">${escapeHtml(s.query_text)}</b>
                  <div style="color:#8e8e8e; font-size:0.75rem; margin-top:4px;">
                    ${intervalLabel(s.interval_seconds)}${s.last_run_at ? " · last ran " + new Date(s.last_run_at).toLocaleString() : ""}
                  </div>
                </div>
                <div style="display:flex; flex-direction:column; align-items:flex-end; gap:6px;">
                  ${statusBadge(s)}
                  <div style="display:flex; gap:6px;">
                    <button class="action-btn-sm run-now-btn" data-id="${s.id}" title="Run now instead of waiting">▶ Run now</button>
                    <button class="action-btn-sm delete-schedule-btn" data-id="${s.id}" title="Delete">✕</button>
                  </div>
                </div>
              </div>
              ${s.last_status === "error"
                ? `<div style="color:#ef4444; font-size:0.78rem; margin-top:8px; padding-top:8px; border-top:1px solid #2f2f2f;">⚠ ${escapeHtml(s.last_error || "Unknown error")}</div>`
                : s.last_answer
                  ? `<div style="color:#d4d4d4; font-size:0.82rem; margin-top:8px; padding-top:8px; border-top:1px solid #2f2f2f; white-space:pre-wrap;">${escapeHtml(s.last_answer.slice(0, 400))}${s.last_answer.length > 400 ? "…" : ""}</div>`
                  : ""}
            </div>`).join("")
        }
      </div>`;

    document.getElementById("create-schedule-btn")?.addEventListener("click", async () => {
      const textEl = document.getElementById("new-schedule-query");
      const query_text = (textEl?.value || "").trim();
      const interval = document.getElementById("new-schedule-interval")?.value || "daily";
      if (!query_text) { showToast("Enter a question first"); return; }
      try {
        const resp = await authFetch(`/api/v1/scheduled`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tenant_id: activeTenant, query_text, interval }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        showToast("Scheduled");
        renderScheduledPanel(content);
      } catch {
        showToast("Could not create the schedule");
      }
    });

    content.querySelectorAll(".delete-schedule-btn").forEach(btn => {
      btn.addEventListener("click", async () => {
        try {
          const resp = await authFetch(`/api/v1/scheduled/${btn.dataset.id}?tenant_id=${encodeURIComponent(activeTenant)}`, { method: "DELETE" });
          if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
          renderScheduledPanel(content);
        } catch {
          showToast("Could not delete this schedule");
        }
      });
    });

    content.querySelectorAll(".run-now-btn").forEach(btn => {
      btn.addEventListener("click", async () => {
        btn.disabled = true; btn.textContent = "Queued…";
        try {
          const resp = await authFetch(`/api/v1/scheduled/${btn.dataset.id}/run-now?tenant_id=${encodeURIComponent(activeTenant)}`, { method: "POST" });
          if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
          showToast("Running — the real scheduler picks this up within ~10s");
          setTimeout(() => { if (document.getElementById("schedules-list")) renderScheduledPanel(content); }, 12000);
        } catch {
          btn.disabled = false; btn.textContent = "▶ Run now";
          showToast("Could not trigger this schedule");
        }
      });
    });
  }

  // Renders real nodes/edges from /api/v1/knowledge/graph-context — a radial layout
  // computed from however many real entities actually came back (previously this
  // always drew the same two hardcoded fake nodes no matter what).
  const NODE_TYPE_COLORS = { Document: "#60a5fa", Person: "#a78bfa", default: "#10a37f" };

  window.renderBasicGraph = function(canvas, realNodes, realEdges) {
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const width = canvas.width;
    const height = canvas.height;

    const rawNodes = realNodes && realNodes.length ? realNodes : [];
    const centerId = rawNodes[0]?.id;
    const others = rawNodes.slice(1);
    const radius = Math.min(width, height) / 2 - 50;

    const nodes = rawNodes.map((n, i) => {
      let x, y;
      if (n.id === centerId) {
        x = width / 2; y = height / 2;
      } else {
        const idx = others.findIndex(o => o.id === n.id);
        const angle = (idx / Math.max(others.length, 1)) * 2 * Math.PI;
        x = width / 2 + radius * Math.cos(angle);
        y = height / 2 + radius * Math.sin(angle);
      }
      const label = n.label && n.label.length > 22 ? n.label.substring(0, 22) + "..." : (n.label || n.id);
      return { id: n.id, label, x, y, color: NODE_TYPE_COLORS[n.type] || NODE_TYPE_COLORS.default };
    });
    const edges = (realEdges || []).map(e => ({ from: e.from, to: e.to, label: e.label }));

    let scale = 1;
    let offsetX = 0;
    let offsetY = 0;
    let isDragging = false;
    let dragStartX = 0;
    let dragStartY = 0;

    function draw() {
      ctx.clearRect(0, 0, width, height);
      ctx.save();
      ctx.translate(offsetX, offsetY);
      ctx.scale(scale, scale);

      edges.forEach(edge => {
        const fromNode = nodes.find(n => n.id === edge.from);
        const toNode = nodes.find(n => n.id === edge.to);
        if (fromNode && toNode) {
          ctx.beginPath();
          ctx.moveTo(fromNode.x, fromNode.y);
          ctx.lineTo(toNode.x, toNode.y);
          ctx.strokeStyle = "#383838";
          ctx.lineWidth = 2;
          ctx.stroke();

          const midX = (fromNode.x + toNode.x) / 2;
          const midY = (fromNode.y + toNode.y) / 2;
          ctx.fillStyle = "#8e8e8e";
          ctx.font = "10px monospace";
          ctx.textAlign = "center";
          ctx.fillText(edge.label, midX, midY - 4);
        }
      });

      nodes.forEach(node => {
        ctx.beginPath();
        ctx.arc(node.x, node.y, 16, 0, 2 * Math.PI);
        ctx.fillStyle = node.color;
        ctx.fill();
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 1;
        ctx.stroke();

        ctx.fillStyle = "#ececec";
        ctx.font = "12px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText(node.label, node.x, node.y + 28);
      });
      ctx.restore();
    }
    draw();

    canvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      scale += e.deltaY * -0.001;
      scale = Math.min(Math.max(0.5, scale), 3);
      draw();
    });
    canvas.addEventListener('mousedown', (e) => {
      isDragging = true;
      dragStartX = e.clientX - offsetX;
      dragStartY = e.clientY - offsetY;
      canvas.style.cursor = 'grabbing';
    });
    canvas.addEventListener('mousemove', (e) => {
      if (isDragging) {
        offsetX = e.clientX - dragStartX;
        offsetY = e.clientY - dragStartY;
        draw();
      }
    });
    canvas.addEventListener('mouseup', () => { isDragging = false; canvas.style.cursor = 'grab'; });
    canvas.addEventListener('mouseleave', () => { isDragging = false; canvas.style.cursor = 'grab'; });
  };

  // ─── Markdown & Table Renderer (ChatGPT / Claude Standard) ─────────────
  function escapeHtml(text) {
    return (text || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // Real bug found via live testing 2026-08-21: this section was labeled "Table
  // Renderer" but had no actual table logic — the AI answers with a real markdown
  // table constantly (comparisons, summaries, conflict-detection), and every one
  // rendered as literal, garbled pipe-and-dash text ("| Source | Policy |",
  // "|--------|----------------|") instead of a real table. Runs before the
  // paragraph/line-break pass in renderMarkdown() and returns HTML with no bare
  // newlines inside the table itself, so that later pass can't re-mangle it.
  function renderMarkdownTables(text) {
    const lines = text.split("\n");
    const isRowLine = (l) => /^\s*\|.*\|\s*$/.test(l);
    const isSeparatorLine = (l) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(l);
    const splitRow = (l) => l.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(c => c.trim());

    const out = [];
    let i = 0;
    while (i < lines.length) {
      if (isRowLine(lines[i]) && i + 1 < lines.length && isSeparatorLine(lines[i + 1])) {
        const headerCells = splitRow(lines[i]);
        const bodyRows = [];
        let j = i + 2;
        while (j < lines.length && isRowLine(lines[j])) {
          bodyRows.push(splitRow(lines[j]));
          j++;
        }
        const thead = headerCells.map(c => `<th style="text-align:left; padding:6px 12px; border-bottom:1px solid #383838; color:#ececec; font-weight:600;">${formatInlineMarkdown(escapeHtml(c))}</th>`).join("");
        const tbody = bodyRows.map(row =>
          `<tr>${row.map(c => `<td style="padding:6px 12px; border-bottom:1px solid #2f2f2f; color:#d4d4d4;">${formatInlineMarkdown(escapeHtml(c))}</td>`).join("")}</tr>`
        ).join("");
        out.push(`<table style="border-collapse:collapse; margin:10px 0; width:100%; font-size:0.88rem;"><thead><tr>${thead}</tr></thead><tbody>${tbody}</tbody></table>`);
        i = j;
      } else {
        out.push(lines[i]);
        i++;
      }
    }
    return out.join("\n");
  }

  function formatInlineMarkdown(text) {
    if (!text) return "";
    return text
      .replace(/`([^`]+)`/g, '<code style="background:#2d2d2d; color:#10a37f; padding:2px 6px; border-radius:4px; font-size:0.88em; font-family:monospace;">$1</code>')
      .replace(/\*\*(.+?)\*\*/g, '<strong style="color:#ffffff; font-weight:600;">$1</strong>')
      .replace(/\*(.+?)\*/g, '<em style="color:#cccccc;">$1</em>')
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" style="color:#10a37f; text-decoration:none; border-bottom:1px underline;">$1</a>');
  }

  // Real bug found via live testing 2026-08-21: small fenced code blocks (too tiny
  // for the artifact drawer, which only pulls out blocks 60+ chars / 4+ lines) never
  // got real code-block rendering in the chat bubble itself — the fence markers
  // survived as literal stray backticks, the language tag ("python") leaked into the
  // visible code text, and <br> tags corrupted the formatting. Runs before
  // formatInlineMarkdown() (whose single-backtick inline-code regex would otherwise
  // mis-match parts of a triple-backtick fence) and stashes real newlines behind a
  // private-use placeholder, restored only after the later blanket "\n" -> "<br>"
  // pass — a <pre> block needs its own real newlines, not a <br> after each one.
  const _NEWLINE_PLACEHOLDER = "";
  function renderCodeBlocks(text) {
    return text.replace(/```(\w+)?\n([\s\S]*?)```/g, (_match, lang, code) => {
      const trimmed = code.replace(/\n$/, "");
      const escaped = escapeHtml(trimmed).replace(/\n/g, _NEWLINE_PLACEHOLDER);
      const label = lang ? `<div style="color:#8e8e8e; font-size:0.75rem; padding:4px 12px; border-bottom:1px solid #383838;">${escapeHtml(lang)}</div>` : "";
      return `<div style="background:#1a1a1a; border:1px solid #383838; border-radius:8px; margin:10px 0; overflow-x:auto;">${label}<pre style="margin:0; padding:12px; font-family:monospace; font-size:0.85rem; color:#e0e0e0;"><code>${escaped}</code></pre></div>`;
    });
  }

  function renderMarkdown(text) {
    if (!text) return "";
    // Code blocks and tables are extracted and converted to real HTML on the raw
    // text FIRST — their own content gets escapeHtml (and, for tables,
    // formatInlineMarkdown) applied inside their own render functions, so by the
    // time the whole-text formatInlineMarkdown() call below runs, there are no bare
    // "**"/backtick markers left inside them for it to (harmlessly) re-scan.
    // Real bug found via live formatting test 2026-08-23: only a single "# "
    // (h1) was ever matched here, so "## " and "### " headings (which the
    // model produces constantly, e.g. "### Quick Tips") fell straight through
    // to the reader as literal "###" text instead of rendering as headings.
    // Longest-prefix-first ordering (### then ## then #) so "### Foo" is
    // consumed whole by the h3 rule instead of the h1 rule matching its
    // leading "#" and leaving "## Foo" behind.
    let html = formatInlineMarkdown(renderMarkdownTables(renderCodeBlocks(text)))
      .replace(/^### (.+)$/gm, '<h3 style="font-size:1rem;margin:14px 0 8px;color:#fff;">$1</h3>')
      .replace(/^## (.+)$/gm, '<h2 style="font-size:1.1rem;margin:16px 0 9px;color:#fff;">$1</h2>')
      .replace(/^# (.+)$/gm, '<h1 style="font-size:1.2rem;margin:18px 0 10px;color:#fff;">$1</h1>')
      .replace(/^---$/gm, '<hr style="border:none;border-top:1px solid #383838;margin:12px 0;">')
      // Real bug found via live formatting test 2026-08-23: every list line was
      // flattened to the exact same 16px margin regardless of leading
      // whitespace, so a model's common "bullet + indented sub-explanation"
      // pattern (e.g. "* Use print():" followed by "  - In Python, you can
      // use...") rendered as two visually identical top-level bullets with no
      // hierarchy at all — the sub-point read as just another unrelated tip.
      // Indentation now maps to a real nesting depth (2 spaces ≈ one level,
      // capped at 3) reflected as extra left margin and a slightly muted,
      // smaller style so a nested line reads as "detail of the point above it".
      .replace(/^([ \t]*)[-•] (.+)$/gm, (_m, indent, content) => {
        const depth = Math.min(3, Math.floor((indent || "").replace(/\t/g, "  ").length / 2));
        const ml = 16 + depth * 20;
        return `<li style="margin-left:${ml}px;${depth > 0 ? " opacity:0.82; font-size:0.93em;" : ""}">${content}</li>`;
      })
      .replace(/^([ \t]*)\d+\.\s(.+)$/gm, (_m, indent, content) => {
        const depth = Math.min(3, Math.floor((indent || "").replace(/\t/g, "  ").length / 2));
        const ml = 16 + depth * 20;
        return `<li style="margin-left:${ml}px;${depth > 0 ? " opacity:0.82; font-size:0.93em;" : ""}">${content}</li>`;
      })
      .replace(/\n\n/g, '</p><p style="margin:8px 0;">')
      .replace(/\n/g, '<br>')
      // Restore real newlines inside code blocks now that the blanket <br> pass
      // above is done — a <pre> element needs actual "\n" characters to lay out
      // code lines correctly, not <br> tags.
      .replace(new RegExp(_NEWLINE_PLACEHOLDER, "g"), "\n");
    html = html.replace(/(<li.*<\/li>)+/gs, '<ul style="margin:8px 0;">$&</ul>');
    return `<p style="margin:0;">${html}</p>`;
  }

  // ─── Local Storage & Pinning Store ─────────────────────────────────────
  // Real bug found via live testing 2026-08-21: this was keyed on the single global
  // "cb_sessions" localStorage entry, with no tenant scoping at all — now that real
  // per-tenant login exists, two different workspaces logged into from the same
  // browser would see each other's chat history mixed together. Namespaced by
  // activeTenant so each workspace's history is genuinely its own.
  const SESSIONS_KEY = `cb_sessions_${activeTenant}`;
  const Store = {
    save(id, history, pinned = false) {
      const all = this.getAll();
      const existing = all[id] || {};
      all[id] = {
        history,
        updatedAt: Date.now(),
        title: history.find(m => m.role === "user")?.content?.substring(0, 36) || "New Chat",
        pinned: pinned !== undefined ? pinned : (existing.pinned || false)
      };
      localStorage.setItem(SESSIONS_KEY, JSON.stringify(all));
    },
    togglePin(id) {
      const all = this.getAll();
      if (all[id]) {
        all[id].pinned = !all[id].pinned;
        localStorage.setItem(SESSIONS_KEY, JSON.stringify(all));
      }
    },
    getAll() { return JSON.parse(localStorage.getItem(SESSIONS_KEY) || "{}"); },
    load(id)  { return this.getAll()[id]?.history || []; },
    delete(id){
      const all = this.getAll();
      delete all[id];
      localStorage.setItem(SESSIONS_KEY, JSON.stringify(all));
    },
    // Real fix 2026-08-22: moves a session's localStorage entry from a
    // client-guessed id to the real backend-minted one adopted right after
    // the first turn, so the sidebar/pin/Projects-assignment all keep
    // pointing at the same conversation instead of a now-abandoned key.
    rename(oldId, newId) {
      if (oldId === newId) return;
      const all = this.getAll();
      if (all[oldId] && !all[newId]) {
        all[newId] = all[oldId];
        delete all[oldId];
        localStorage.setItem(SESSIONS_KEY, JSON.stringify(all));
      }
    }
  };

  // ─── Render Sidebar History (Pinned & Recents with Search) ───────────────
  function renderSidebarHistory() {
    const sessions = Store.getAll();
    let ids = Object.keys(sessions).sort((a, b) => sessions[b].updatedAt - sessions[a].updatedAt);

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      ids = ids.filter(id => (sessions[id].title || "").toLowerCase().includes(q));
    }

    const pinnedIds = ids.filter(id => sessions[id].pinned);
    const recentIds = ids.filter(id => !sessions[id].pinned);

    // Render Pinned Section
    if (pinnedIds.length > 0) {
      pinnedTitle.classList.remove("hidden");
      pinnedHistory.innerHTML = pinnedIds.map(id => createHistoryItemHTML(id, sessions[id], true)).join("");
    } else {
      pinnedTitle.classList.add("hidden");
      pinnedHistory.innerHTML = "";
    }

    // Render Recents Section
    if (recentIds.length === 0 && pinnedIds.length === 0) {
      sidebarHistory.innerHTML = `<div style="padding:8px 10px;color:#8e8e8e;font-size:0.82rem;">No chats found</div>`;
    } else {
      sidebarHistory.innerHTML = recentIds.map(id => createHistoryItemHTML(id, sessions[id], false)).join("");
    }

    // Event Listeners for Chat Items
    document.querySelectorAll(".chat-history-item[data-sid]").forEach(el => {
      const sid = el.dataset.sid;
      el.addEventListener("click", (e) => {
        if (!e.target.closest(".chat-action-icon")) {
          loadSession(sid);
        }
      });
    });

    // Pin Button Listeners
    document.querySelectorAll(".pin-action-btn").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const sid = btn.dataset.sid;
        Store.togglePin(sid);
        renderSidebarHistory();
        showToast(Store.getAll()[sid]?.pinned ? "Pinned to sidebar" : "Unpinned from sidebar");
      });
    });

    // Delete Button Listeners
    // Real UX gap found via live audit 2026-08-22: this deleted a conversation
    // permanently and immediately with zero confirmation — a single misclick
    // loses a real chat with no undo. A lightweight native confirm is enough
    // friction to prevent an accidental click without being annoying.
    document.querySelectorAll(".delete-action-btn").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const sid = btn.dataset.sid;
        const title = Store.getAll()[sid]?.title || "this conversation";
        if (!window.confirm(`Delete "${title}"? This can't be undone.`)) return;
        Store.delete(sid);
        if (currentSessionId === sid) resetChat();
        else renderSidebarHistory();
        showToast("Conversation deleted");
      });
    });
  }

  function createHistoryItemHTML(id, session, isPinned) {
    const isActive = id === currentSessionId;
    return `
      <div class="chat-history-item ${isActive ? 'active' : ''}" data-sid="${id}">
        <span class="chat-item-title">${escapeHtml(session.title || "New Chat")}</span>
        <div class="chat-item-actions">
          <button class="chat-action-icon pin-action-btn ${isPinned ? 'pinned' : ''}" data-sid="${id}" title="${isPinned ? 'Unpin chat' : 'Pin chat'}">
            📌
          </button>
          <button class="chat-action-icon delete-action-btn" data-sid="${id}" title="Delete chat">
            🗑️
          </button>
        </div>
      </div>
    `;
  }

  // ─── Search Input Listener ─────────────────────────────────────────────
  if (searchInput) {
    searchInput.addEventListener("input", (e) => {
      searchQuery = e.target.value;
      renderSidebarHistory();
    });
  }

  // ─── Load Session ─────────────────────────────────────────────────────
  window.loadSession = function(sid) {
    currentSessionId = sid;
    chatHistory = Store.load(sid);
    welcomeHero.classList.add("hidden");
    messagesContainer.classList.remove("hidden");
    messagesContainer.innerHTML = "";
    refreshArtifacts();

    let lastUserQuery = "";
    chatHistory.forEach((msg, idx) => {
      if (msg.role === "user") {
        lastUserQuery = msg.content;
        appendUserMessage(msg.content);
      } else {
        appendAssistantMessage(msg.content, lastUserQuery, msg.followups, msg.source, idx);
      }
    });
    chatScrollArea.scrollTop = chatScrollArea.scrollHeight;
    renderSidebarHistory();
  };

  // ─── Append User Message ──────────────────────────────────────────────
  function appendUserMessage(text) {
    const div = document.createElement("div");
    div.className = "message user";
    div.innerHTML = `<div class="message-content">${escapeHtml(text)}</div>`;
    messagesContainer.appendChild(div);
  }

  // ─── Append Assistant Message ─────────────────────────────────────────
  function appendAssistantMessage(text, userQuery = "", followups = [], source = null, msgIndex = -1) {
    const div = document.createElement("div");
    div.className = "message assistant";
    
    let sourceHTML = "";
    if (source) {
      sourceHTML = `<div class="source-tag">📍 Source: <a href="${escapeHtml(source.url || '#')}" target="_blank" rel="noopener">${escapeHtml(source.name || 'Web Search')}</a></div>`;
    }
    // Real bug found via live testing 2026-08-21: this used to special-case any
    // message containing the word "nift" (leftover scaffolding from the fake
    // hardcoded "Tell me about NIFT" demo conversation removed elsewhere) and
    // show a fabricated "Source: Live Web Search (DuckDuckGo)" link and a fixed
    // fake follow-up — misfiring on any real, legitimate mention of that word in
    // an actual user's real conversation. Removed along with the demo itself.

    let followupHTML = "";
    const activeFollowups = followups && followups.length > 0 ? followups : [];

    if (activeFollowups.length > 0) {
      followupHTML = `
        <div class="followup-chips-container">
          ${activeFollowups.map(f => `<button class="followup-chip" data-prompt="${escapeHtml(f)}">${escapeHtml(f)}</button>`).join("")}
        </div>
      `;
    }

    div.innerHTML = `
      <div class="message-body">${renderMarkdown(text)}</div>
      ${renderArtifactChipsHTML(msgIndex)}
      ${sourceHTML}
      ${followupHTML}
      <div class="message-actions">
        <button class="action-btn-sm copy-btn" title="Copy">📋 Copy</button>
        <button class="action-btn-sm" onclick="openInspectorModal('evidence','${escapeHtml(userQuery)}')">🔍 Evidence</button>
        <button class="action-btn-sm" onclick="openInspectorModal('explain','${escapeHtml(userQuery)}')">❓ Why?</button>
        <button class="action-btn-sm feedback-btn" data-type="up" title="Good">👍</button>
        <button class="action-btn-sm feedback-btn" data-type="down" title="Bad">👎</button>
      </div>
    `;

    messagesContainer.appendChild(div);

    // Bind Copy Button
    div.querySelector(".copy-btn")?.addEventListener("click", () => {
      navigator.clipboard.writeText(text).then(() => showToast("Copied to clipboard"));
    });

    // Bind Followup Chips
    div.querySelectorAll(".followup-chip").forEach(chip => {
      chip.addEventListener("click", () => {
        promptTextarea.value = chip.dataset.prompt;
        sendBtn.disabled = false;
        handleSend();
      });
    });

    // Bind Feedback Buttons
    div.querySelectorAll(".feedback-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const type = btn.dataset.type;
        submitFeedback("msg_" + Date.now(), type);
        btn.style.opacity = "0.5";
        btn.style.pointerEvents = "none";
      });
    });
  }

  function escapeHtml(t) {
    const d = document.createElement("div");
    d.textContent = t || "";
    return d.innerHTML;
  }

  // ─── Send Message ─────────────────────────────────────────────────────
  async function handleSend() {
    const text = promptTextarea.value.trim();
    if (!text) return;

    promptTextarea.value = "";
    promptTextarea.style.height = "auto";
    sendBtn.disabled = true;
    sendBtn.classList.add("hidden");
    stopBtn.classList.remove("hidden");
    activeAbortController = new AbortController();

    welcomeHero.classList.add("hidden");
    messagesContainer.classList.remove("hidden");

    appendUserMessage(text);
    chatHistory.push({ role: "user", content: text });
    Store.save(currentSessionId, chatHistory);
    renderSidebarHistory();
    chatScrollArea.scrollTop = chatScrollArea.scrollHeight;

    // Typing indicator
    const typingDiv = document.createElement("div");
    typingDiv.className = "message assistant";
    typingDiv.innerHTML = `
      <div style="display:flex;gap:4px;padding:8px 0;">
        <span style="width:6px;height:6px;border-radius:50%;background:#8e8e8e;animation:bounce 1.2s infinite;"></span>
        <span style="width:6px;height:6px;border-radius:50%;background:#8e8e8e;animation:bounce 1.2s .2s infinite;"></span>
        <span style="width:6px;height:6px;border-radius:50%;background:#8e8e8e;animation:bounce 1.2s .4s infinite;"></span>
      </div>`;
    messagesContainer.appendChild(typingDiv);
    chatScrollArea.scrollTop = chatScrollArea.scrollHeight;

    const currentModel = models[currentModelIdx];
    const startTime = performance.now();

    try {
      // ── Build assistant message bubble with streaming cursor ────────────
      // Real bug found via live testing 2026-08-21: this fake client-side
      // "msg_<timestamp>" id was what got submitted as feedback's task_id — real
      // thumbs up/down feedback had zero relationship to the actual conversation
      // turn it was about. A real turn_id now arrives on the SSE "done" event
      // (see chat_router.py); msgId starts as a placeholder and is replaced with
      // the real one the moment it arrives, before any feedback button can fire.
      let msgId    = "msg_" + Date.now();
      const msgDiv = document.createElement("div");
      msgDiv.className = "message assistant";
      msgDiv.dataset.msgId = msgId;
      msgDiv.innerHTML = `
        <div class="message-body"><span class="stream-target"></span><span class="typing-dots"><span class="dot"></span><span class="dot"></span><span class="dot"></span></span></div>
        <span class="confidence-badge" style="display:none;"></span>
        <div class="message-actions" style="opacity:0;">
          <button class="action-btn-sm copy-btn" title="Copy">📋 Copy</button>
          <button class="action-btn-sm evidence-btn">🔍 Evidence</button>
          <button class="action-btn-sm explain-btn">❓ Why?</button>
          <button class="action-btn-sm graph-btn">🕸️ Graph</button>
          <button class="action-btn-sm export-btn" title="Export">⬇ Export</button>
          <button class="action-btn-sm feedback-btn" data-type="up" title="Good">👍</button>
          <button class="action-btn-sm feedback-btn" data-type="down" title="Bad">👎</button>
        </div>
      `;
      typingDiv.remove();
      messagesContainer.appendChild(msgDiv);
      chatScrollArea.scrollTop = chatScrollArea.scrollHeight;

      const streamTarget    = msgDiv.querySelector(".stream-target");
      const cursorEl        = msgDiv.querySelector(".typing-dots");
      const actionsDiv      = msgDiv.querySelector(".message-actions");
      const confidenceBadge = msgDiv.querySelector(".confidence-badge");

      let fullText       = "";
      let msgCitations   = [];
      let finalProvider  = currentModel.provider;

      // ── Real SSE Streaming (with /turn fallback if stream unavailable) ──
      const payload = JSON.stringify({
        tenant_id:          activeTenant,
        // Real bug found via live testing 2026-08-21: this was hardcoded to
        // "user_surabhi" for every user of the app, regardless of who actually
        // logged in — the real user_id captured at login (onAuthSuccess) was
        // sitting in localStorage unused. Every chat turn was misattributed.
        user_id:            localStorage.getItem("user_id") || "unknown_user",
        session_id:         currentSessionId,
        history:            chatHistory.slice(0, -1),
        user_query:         text,
        persona:            "CTO",
        mode:               "ASK",
        preferred_provider: currentModel.provider,
        // Real per-turn retrieval diagnostics, opt-in via Dev Telemetry Mode — feeds
        // the Execution Timeline panel with real data instead of a fixed fake list.
        debug_retrieval:    devModeActive
      });

      const res = await authFetch(STREAM_URL, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body: payload,
        signal: activeAbortController.signal
      });

      // ── Fallback to /turn if stream endpoint not available (405/404) ───
      if (res.status === 405 || res.status === 404) {
        const fallback = await authFetch(API_BASE_URL, {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body: payload,
          signal: activeAbortController.signal
        });
        if (!fallback.ok) throw new Error(`HTTP ${fallback.status}`);
        const data = await fallback.json();
        const raw  = data.response_text || data.response || data.answer || "I processed your request.";
        // Real bug found via live testing 2026-08-23: if `raw` was an object whose
        // own text_content came back empty, this fell back to JSON.stringify(raw)
        // and showed the user the raw internal response envelope as if it were the
        // chat answer, instead of an honest error state.
        fullText   = (typeof raw === "object")
          ? (raw.text_content || "Something went wrong generating a response. Please try asking again.")
          : raw;
        // Same real session_id adoption as the SSE "done" handler above —
        // this /turn fallback path hits it too whenever /stream is
        // unavailable.
        if (data.session_id && data.session_id !== currentSessionId) {
          Store.rename(currentSessionId, data.session_id);
          currentSessionId = data.session_id;
        }

        // Animate with simulated streaming
        cursorEl.remove();
        const rendered = renderMarkdown(fullText);
        let idx = 0;
        await new Promise(resolve => {
          const iv = setInterval(() => {
            idx = Math.min(idx + 5, rendered.length);
            streamTarget.innerHTML = rendered.substring(0, idx);
            chatScrollArea.scrollTop = chatScrollArea.scrollHeight;
            if (idx >= rendered.length) { clearInterval(iv); resolve(); }
          }, 10);
        });
        actionsDiv.style.opacity = "1";
        if (data.retrieval_debug) window._lastTurnDebug = { query: text, debug: data.retrieval_debug };
        if (data.explanation) window._lastTurnExplanation = { query: text, explanation: data.explanation };
        chatHistory.push({ role: "assistant", content: fullText });
        Store.save(currentSessionId, chatHistory);
        refreshArtifacts();
        injectArtifactChips(msgDiv, chatHistory.length - 1);
        renderSidebarHistory();
        sendBtn.classList.remove("hidden");
        stopBtn.classList.add("hidden");
        activeAbortController = null;
        sendBtn.disabled = !promptTextarea.value.trim();
        return; // exit early — already done
      }

      if (!res.ok) throw new Error(`HTTP ${res.status}`);


      const reader  = res.body.getReader();
      const decoder = new TextDecoder();
      let   buf     = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop(); // keep incomplete last chunk

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const evt = JSON.parse(line.slice(6));

            if (evt.type === "token") {
              fullText += evt.content;
              streamTarget.innerHTML = renderMarkdown(fullText);
              chatScrollArea.scrollTop = chatScrollArea.scrollHeight;

            } else if (evt.type === "done") {
              msgCitations  = evt.citations  || [];
              finalProvider = evt.provider   || finalProvider;
              const conf    = evt.confidence || 0;
              if (evt.retrieval_debug) window._lastTurnDebug = { query: text, debug: evt.retrieval_debug };
              if (evt.explanation) window._lastTurnExplanation = { query: text, explanation: evt.explanation };

              cursorEl.remove();
              streamTarget.innerHTML = renderMarkdown(fullText);

              // Confidence badge
              //
              // CRITICAL real bug found via live AI-quality testing 2026-08-23: the
              // message template never actually contained a ".confidence-badge"
              // element, so `confidenceBadge` (queried a few lines up) was always
              // null. Every real, company-data-grounded answer (any turn with
              // conf > 0 — i.e. the app's core, primary RAG path) hit
              // `confidenceBadge.textContent = ...` below and threw a TypeError,
              // silently swallowed by this whole block's surrounding
              // `catch (_) { /* partial JSON — ignore */ }` (meant only for
              // incomplete SSE chunks). That exception aborted the rest of this
              // "done" handler, so `actionsDiv.style.opacity = "1"` a few lines
              // below never ran either — leaving Copy/Evidence/Why?/Graph/Export/
              // feedback invisible (opacity 0, though still technically present
              // and programmatically clickable, which is how this stayed hidden
              // through this session's earlier testing — those turns were mostly
              // confidence=0 world-knowledge fallbacks, the one branch that never
              // hit this line at all) for the single most important answer type in
              // the product. Only found once a real uploaded document put a
              // confidence > 0 answer in front of a real browser. Fixed by giving
              // the template a real element to bind to.
              if (conf > 0) {
                const clr   = conf >= 75 ? "#10a37f" : conf >= 50 ? "#f59e0b" : "#ef4444";
                const icon  = conf >= 75 ? "🟢" : conf >= 50 ? "🟡" : "🔴";
                confidenceBadge.textContent = `${icon} ${conf}% confident`;
                confidenceBadge.style.cssText = `display:inline-block; color:${clr}; font-size:0.72rem; margin:4px 0 0;`;
              }

              actionsDiv.style.opacity = "1";
              // Real turn_id from the backend replaces the temporary client-side
              // placeholder — feedback submitted after this point is correctly
              // attributed to the real conversation turn.
              if (evt.turn_id) {
                msgId = evt.turn_id;
                msgDiv.dataset.msgId = msgId;
              }
              // Real bug found via live testing 2026-08-22: the client's own
              // guessed session_id never matches the real one the backend
              // mints on the first turn of a conversation (see
              // conversation_service.py's SessionManager.create_session) —
              // without adopting the real ID here, every "current chat" the
              // Projects panel tries to file away would point at a session
              // row with zero real turns actually attached to it server-side.
              if (evt.session_id && evt.session_id !== currentSessionId) {
                Store.rename(currentSessionId, evt.session_id);
                currentSessionId = evt.session_id;
              }
              window._msgCitations[msgId] = msgCitations;

              const elapsed = Math.round(performance.now() - startTime);
              if (devModeActive) showToast(`${finalProvider} · ${elapsed}ms`);

            } else if (evt.type === "error") {
              cursorEl.remove();
              streamTarget.innerHTML = renderMarkdown(
                `⚠️ **Error:** ${escapeHtml(evt.message || "Something went wrong. Please try again.")}`
              );
              actionsDiv.style.opacity = "1";
            }
          } catch (_) { /* partial JSON — ignore */ }
        }
      }

      // ── Bind Action Buttons ─────────────────────────────────────────────
      msgDiv.querySelector(".copy-btn")?.addEventListener("click", () => {
        navigator.clipboard.writeText(fullText).then(() => showToast("Copied to clipboard!"));
      });
      msgDiv.querySelector(".evidence-btn")?.addEventListener("click", () => {
        openInspectorModal("evidence", text, window._msgCitations[msgId] || []);
      });
      msgDiv.querySelector(".explain-btn")?.addEventListener("click", () => openInspectorModal("explain", text));
      msgDiv.querySelector(".graph-btn")?.addEventListener("click",   () => openInspectorModal("graph",   text));
      msgDiv.querySelector(".export-btn")?.addEventListener("click", () => exportChatAsTxt());
      
      msgDiv.querySelectorAll(".feedback-btn").forEach(btn => {
        btn.addEventListener("click", () => {
          submitFeedback(msgId, btn.dataset.type);
          btn.style.opacity = "0.5";
          btn.style.pointerEvents = "none";
        });
      });

      // ── Save to history & sidebar ───────────────────────────────────────
      chatHistory.push({ role: "assistant", content: fullText });
      Store.save(currentSessionId, chatHistory);
      refreshArtifacts();
      injectArtifactChips(msgDiv, chatHistory.length - 1);
      renderSidebarHistory();

    } catch (err) {
      typingDiv.remove();
      if (err.name === "AbortError") {
        // Real gap found via live UI audit 2026-08-22: a stopped response used to
        // have no graceful path at all. Leave whatever partial text already
        // streamed in place (it's already in the DOM), just stop the spinner and
        // reveal actions so Copy/Evidence etc. still work on the partial answer.
        const lastMsg = messagesContainer.querySelector(".message.assistant:last-child");
        lastMsg?.querySelector(".typing-dots")?.remove();
        const lastActions = lastMsg?.querySelector(".message-actions");
        if (lastActions) lastActions.style.opacity = "1";
        showToast("Stopped");
      } else {
        const errDiv = document.createElement("div");
        errDiv.className = "message assistant";
        errDiv.innerHTML = `<div class="message-body" style="color:#ef4444;">⚠ Error: ${escapeHtml(err.message)}. Please try again.</div>`;
        messagesContainer.appendChild(errDiv);
        showToast(`Error: ${err.message}`);
      }
    }

    sendBtn.classList.remove("hidden");
    stopBtn.classList.add("hidden");
    activeAbortController = null;
    sendBtn.disabled = !promptTextarea.value.trim();
  }

  stopBtn?.addEventListener("click", () => {
    activeAbortController?.abort();
  });

  // Real accessibility gap found via live keyboard-navigation testing 2026-08-23:
  // none of the three overlay panels (inspector drawer — Decisions/Risks/Projects/
  // People/Teams/Documents/Dashboards/Architecture Graph/Evidence/Explain/Graph/
  // Timeline all render through it — the artifact drawer, and the upload modal)
  // had any Escape-key handling at all; the only keydown listener in the whole app
  // was scoped to the prompt textarea for Enter-to-send. A keyboard-only user could
  // open any of these but had no way to close them without a mouse. Mirrors each
  // overlay's own existing close-button behavior exactly, and only acts on the
  // topmost open one so Escape doesn't blindly close everything at once.
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    const inspectorDrawer = document.getElementById("inspector-drawer");
    const uploadModal = document.getElementById("upload-modal");
    if (inspectorDrawer && !inspectorDrawer.classList.contains("hidden")) {
      inspectorDrawer.classList.add("hidden");
      document.getElementById("workspace-body")?.classList.remove("inspector-open");
    } else if (uploadModal && !uploadModal.classList.contains("hidden")) {
      uploadModal.classList.add("hidden");
    } else if (artifactDrawer && !artifactDrawer.classList.contains("hidden")) {
      artifactDrawer.classList.add("hidden");
    }
  });

  // ─── Keyboard & Button Handlers ───────────────────────────────────────
  sendBtn.addEventListener("click", handleSend);
  promptTextarea.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
  });
  promptTextarea.addEventListener("input", () => {
    promptTextarea.style.height = "auto";
    promptTextarea.style.height = Math.min(promptTextarea.scrollHeight, 200) + "px";
    sendBtn.disabled = !promptTextarea.value.trim();
  });

  // ─── Suggestion Chips ─────────────────────────────────────────────────
  document.querySelectorAll(".chip").forEach(chip => {
    chip.addEventListener("click", () => {
      promptTextarea.value = chip.dataset.prompt;
      sendBtn.disabled = false;
      handleSend();
    });
  });

  // ─── Sidebar Toggle ───────────────────────────────────────────────────
  const newChatBtnCollapsed = document.getElementById("new-chat-btn-collapsed");
  sidebarToggleBtn?.addEventListener("click", () => {
    sidebar.classList.add("collapsed");
    sidebarOpenBtn?.classList.remove("hidden");
    newChatBtnCollapsed?.classList.remove("hidden");
  });
  sidebarOpenBtn?.addEventListener("click", () => {
    sidebar.classList.remove("collapsed");
    sidebarOpenBtn?.classList.add("hidden");
    newChatBtnCollapsed?.classList.add("hidden");
  });

  // ─── New Chat ─────────────────────────────────────────────────────────
  function resetChat() {
    currentSessionId = "sess_" + Date.now();
    chatHistory = [];
    messagesContainer.innerHTML = "";
    messagesContainer.classList.add("hidden");
    welcomeHero.classList.remove("hidden");
    promptTextarea.value = "";
    sendBtn.disabled = true;
    refreshArtifacts();
    renderSidebarHistory();
  }

  window.resetChat = resetChat;
  newChatBtn?.addEventListener("click", resetChat);
  newChatBtnCollapsed?.addEventListener("click", resetChat);

  // ─── Typing Bounce Animation ──────────────────────────────────────────
  const style = document.createElement("style");
  style.textContent = `
    @keyframes bounce {
      0%,80%,100% { transform: translateY(0); opacity:0.4; }
      40%          { transform: translateY(-5px); opacity:1; }
    }
    .art-pane.hidden { display: none !important; }
    .art-tab.active { background: #2f2f2f; color: #fff; }
  `;
  document.head.appendChild(style);

  // ─── Seed Default Chat if Empty for Demo ──────────────────────────────
  
  // ─── Health & Feedback Functions ──────────────────────────────────────────
  window.fetchHealthStatus = async function() {
    try {
      const res = await fetch("/api/v6a/chat/health");
      const data = await res.json();
      const icon = document.getElementById("health-icon");
      const text = document.getElementById("health-status-text");
      if (data.status === "healthy") {
        icon.textContent = "🟢";
        text.textContent = "Online";
      } else {
        icon.textContent = "🟡";
        text.textContent = "Degraded";
      }
      showToast(`Health checked. Database is ${data.database}.`);
    } catch (e) {
      document.getElementById("health-icon").textContent = "🔴";
      document.getElementById("health-status-text").textContent = "Offline";
      showToast("Service is offline or unreachable.");
    }
  };
  
  // Call once on load
  setTimeout(window.fetchHealthStatus, 1000);

  window.submitFeedback = async function(taskId, feedbackType) {
    try {
      await authFetch("/api/v6a/chat/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          task_id: taskId,
          tenant_id: activeTenant,
          feedback: feedbackType,
          comment: ""
        })
      });
      showToast("Thanks for the feedback!");
    } catch (e) {
      console.error("Failed to submit feedback", e);
    }
  };

  // Real bug found via live testing 2026-08-21: every brand-new user with no
  // chat history landed on a hardcoded, entirely unrelated fake "Tell me about
  // NIFT" conversation seeded into their sidebar — content about a fashion
  // institute and an unrelated referral-marketing product, nothing to do with
  // Company Brain, presumably a stray leftover from an unrelated template.
  // A genuinely new user's first impression should be an empty history and the
  // real welcome hero (already handled elsewhere), not a nonsensical demo chat.

  // ─── Export Chat as Text File ─────────────────────────────────────────
  function exportChatAsTxt() {
    if (!chatHistory.length) { showToast("Nothing to export yet."); return; }
    const lines = chatHistory.map(m =>
      `[${m.role.toUpperCase()}]\n${m.content}\n`
    ).join("\n─────────────────────────────────────\n\n");
    const header = `Company Brain — Chat Export\nSession: ${currentSessionId}\nDate: ${new Date().toLocaleString()}\n\n${'═'.repeat(40)}\n\n`;
    const blob = new Blob([header + lines], { type: "text/plain" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href     = url;
    a.download = `company-brain-chat-${Date.now()}.txt`;
    a.click();
    URL.revokeObjectURL(url);
    showToast("Chat exported!");
  }
  window.exportChatAsTxt = exportChatAsTxt;

  // Add Export button to toolbar if present
  const exportGlobalBtn = document.getElementById("export-chat-btn");
  exportGlobalBtn?.addEventListener("click", exportChatAsTxt);

  // ─── Auto-restore last session on load ───────────────────────────────
  (function restoreLastSession() {
    const all = Store.getAll();
    // Kept as a defensive filter for any browser that already had the fake
    // "sess_nift_demo" conversation persisted in localStorage before that seed
    // was removed (2026-08-21) — harmless once storage is clean, but self-heals
    // anyone who hit the bug before the fix shipped.
    const ids = Object.keys(all).filter(k => k !== "sess_nift_demo");
    if (ids.length === 0) return;
    // Sort by last message timestamp (we use session ID which has timestamp)
    ids.sort((a, b) => (b.replace("sess_","") > a.replace("sess_","") ? 1 : -1));
    const lastId = ids[0];
    const hist   = all[lastId]?.history; // was `all[lastId]` (the whole session record, not its
                                          // .history array) — hist.length was always undefined,
                                          // so this silently never restored anything. Fixed.
    if (!hist || !hist.length) return;
    currentSessionId = lastId;
    chatHistory      = hist;
    welcomeHero.classList.add("hidden");
    messagesContainer.classList.remove("hidden");
    refreshArtifacts();
    hist.forEach((m, idx) => {
      if (m.role === "user")      appendUserMessage(m.content);
      else if (m.role === "assistant") {
        const d = document.createElement("div");
        d.className = "message assistant";
        d.innerHTML = `
          <div class="message-body">${renderMarkdown(m.content)}</div>
          ${renderArtifactChipsHTML(idx)}
          <div class="message-actions" style="opacity:1;">
            <button class="action-btn-sm copy-btn">📋 Copy</button>
            <button class="action-btn-sm export-btn">⬇ Export</button>
            <button class="action-btn-sm" title="Good">👍</button>
            <button class="action-btn-sm" title="Bad">👎</button>
          </div>`;
        d.querySelector(".copy-btn")?.addEventListener("click", () => {
          navigator.clipboard.writeText(m.content).then(() => showToast("Copied!"));
        });
        d.querySelector(".export-btn")?.addEventListener("click", exportChatAsTxt);
        messagesContainer.appendChild(d);
      }
    });
    chatScrollArea.scrollTop = chatScrollArea.scrollHeight;
    showToast("Last session restored ✓");
  })();

  // ─── Initialize ───────────────────────────────────────────────────────
  renderSidebarHistory();
}

// ─── File Upload Handler (Global) ────────────────────────────────────────────
window.handleFileUpload = async function(event) {
  const file = event.target.files[0];
  if (!file) return;

  const modal       = document.getElementById("upload-modal");
  const modalIcon   = document.getElementById("upload-modal-icon");
  const modalTitle  = document.getElementById("upload-modal-title");
  const modalMsg    = document.getElementById("upload-modal-msg");
  const progressFill = document.getElementById("upload-progress-fill");

  // Show upload modal
  modalIcon.textContent  = "📎";
  modalTitle.textContent = `Uploading: ${file.name}`;
  modalMsg.textContent   = "Extracting text and creating knowledge embeddings...";
  progressFill.style.width = "0%";
  modal.classList.remove("hidden");

  // Animate progress bar
  let progress = 0;
  const progressInterval = setInterval(() => {
    progress = Math.min(progress + 8, 85);
    progressFill.style.width = progress + "%";
  }, 200);

  try {
    const tenant_id = localStorage.getItem("tenant_id") || "00000000-0000-0000-0000-000000000001";
    const formData  = new FormData();
    formData.append("file", file);
    formData.append("tenant_id", tenant_id);
    formData.append("source_label", "UPLOAD");

    const response = await authFetch("/api/v1/upload/document", {
      method: "POST",
      body: formData
    });

    clearInterval(progressInterval);
    progressFill.style.width = "100%";

    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: "Upload failed" }));
      throw new Error(err.detail || `HTTP ${response.status}`);
    }

    const data = await response.json();
    modalIcon.textContent  = "✅";
    modalTitle.textContent = "Upload Successful!";
    modalMsg.textContent   = data.message || `${file.name} ingested into Company Brain.`;

    // Real bug found via live AI-quality testing 2026-08-23: this notification
    // used to be injected inside the same setTimeout that auto-dismissed the
    // modal, 2.5s after the upload actually finished. Closing the modal early
    // via its own "Close" button (the normal, expected thing to do — nobody
    // waits out an auto-dismiss timer) didn't cancel that pending timeout, so
    // a user who closed the dialog and immediately asked a question about the
    // document they'd just uploaded got a real, correct chat answer — followed
    // a moment later by the "✅ ingested!" notification popping in AFTER it,
    // reading as if the chat had jumped backwards. Inject the notification
    // immediately, synchronously with the real upload completing; keep only
    // the modal's own auto-close (a cosmetic "let the user see the success
    // state for a moment") on its own short timer, fully decoupled from
    // message ordering.
    const messagesContainer = document.getElementById("messages-container");
    const welcomeHero = document.getElementById("welcome-hero");
    welcomeHero.classList.add("hidden");
    messagesContainer.classList.remove("hidden");

    const notif = document.createElement("div");
    notif.className = "message assistant";
    notif.innerHTML = `<div class="message-body"><p style="margin:0;">
      ✅ <strong>${file.name}</strong> has been ingested into Company Brain!<br>
      <span style="color:#8e8e8e; font-size:0.85rem;">${data.chunks_ingested} knowledge chunks created. You can now ask questions about this document.</span>
    </p></div>`;
    messagesContainer.appendChild(notif);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    setTimeout(() => { modal.classList.add("hidden"); }, 2500);

  } catch (err) {
    clearInterval(progressInterval);
    progressFill.style.width = "100%";
    progressFill.style.background = "#ef4444";
    modalIcon.textContent  = "❌";
    modalTitle.textContent = "Upload Failed";
    modalMsg.textContent   = err.message || "Could not upload the file. Please try again.";
  }

  // Reset file input so same file can be re-uploaded
  event.target.value = "";
};
