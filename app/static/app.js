let currentTenant = null;
let currentStep = 1;
let pollTimer = null;

// On Page Load
document.addEventListener("DOMContentLoaded", () => {
  setupFormListeners();
});

function switchAuthTab(tab) {
  const signupForm = document.getElementById("signup-form");
  const loginForm = document.getElementById("login-form");
  const tabBtns = document.querySelectorAll(".tab-btn");

  if (tab === "signup") {
    signupForm.classList.remove("hidden");
    loginForm.classList.add("hidden");
    tabBtns[0].classList.add("active");
    tabBtns[1].classList.remove("active");
  } else {
    signupForm.classList.add("hidden");
    loginForm.classList.remove("hidden");
    tabBtns[0].classList.remove("active");
    tabBtns[1].classList.add("active");
  }
}

function setupFormListeners() {
  document.getElementById("signup-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      company_name: document.getElementById("signup-company").value,
      company_domain: document.getElementById("signup-domain").value,
      email: document.getElementById("signup-email").value,
      password: document.getElementById("signup-password").value,
    };
    await handleAuth("/api/v1/auth/signup", payload);
  });

  document.getElementById("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      email: document.getElementById("login-email").value,
      password: document.getElementById("login-password").value,
    };
    await handleAuth("/api/v1/auth/login", payload);
  });
}

async function handleAuth(endpoint, payload) {
  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    let data;
    const contentType = res.headers.get("content-type");
    if (contentType && contentType.includes("application/json")) {
      data = await res.json();
    } else {
      const textErr = await res.text();
      throw new Error(textErr || "Authentication request failed");
    }

    if (!res.ok) throw new Error(data.detail || "Authentication failed");

    currentTenant = data;
    updateTenantBadge(data);
    goToStep(2);
    await loadConnectorsHub();
  } catch (err) {
    alert("Error: " + err.message);
  }
}

function updateTenantBadge(data) {
  document.getElementById("tenant-badge").classList.remove("hidden");
  document.getElementById("badge-company-name").innerText = data.company_name;
  document.getElementById("badge-tenant-id").innerText = data.tenant_id.slice(0, 8) + "...";
  document.getElementById("sync-company-display").innerText = data.company_name;
}

function goToStep(stepNum) {
  currentStep = stepNum;
  for (let i = 1; i <= 5; i++) {
    const view = document.getElementById(`view-step-${i}`);
    const nav = document.getElementById(`step-nav-${i}`);
    if (!view || !nav) continue;

    if (i === stepNum) {
      view.classList.remove("hidden");
      nav.classList.add("active");
    } else {
      view.classList.add("hidden");
      nav.classList.remove("active");
    }

    if (i < stepNum) {
      nav.classList.add("completed");
    }
  }

  if (stepNum === 4) {
    startTelemetryPolling();
  } else if (pollTimer) {
    clearInterval(pollTimer);
  }
}

async function loadConnectorsHub() {
  if (!currentTenant) return;
  try {
    const res = await fetch(`/api/v1/connectors/list?tenant_id=${currentTenant.tenant_id}`);
    const data = await res.json();
    renderConnectorsGrid(data.connectors);
  } catch (err) {
    console.error("Failed to load connectors", err);
  }
}

function renderConnectorsGrid(connectors) {
  const container = document.getElementById("connectors-grid");
  container.innerHTML = "";

  connectors.forEach((app) => {
    const card = document.createElement("div");
    card.className = `connector-card ${app.is_connected ? "connected" : ""}`;
    card.innerHTML = `
      <div class="connector-top">
        <span class="connector-title">${app.name}</span>
        <span class="connector-cat">${app.category}</span>
      </div>
      <p class="connector-desc">${app.description}</p>
      <div class="connector-action">
        <button class="btn-connect" onclick="toggleAppConnection('${app.id}', ${app.is_connected})">
          ${app.is_connected ? "Disconnect App" : "+ Connect " + app.name}
        </button>
      </div>
    `;
    container.appendChild(card);
  });
}

async function toggleAppConnection(appId, isConnected) {
  if (!currentTenant) return;
  const action = isConnected ? "disconnect" : "connect";
  try {
    const res = await fetch("/api/v1/connectors/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tenant_id: currentTenant.tenant_id,
        source_app: appId,
        action: action,
      }),
    });
    const data = await res.json();
    if (res.ok) {
      await loadConnectorsHub();
    }
  } catch (err) {
    alert("Connection toggle failed");
  }
}

async function startDataIngestion() {
  if (!currentTenant) return;
  try {
    const res = await fetch("/api/v1/ingestion/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tenant_id: currentTenant.tenant_id }),
    });
    if (res.ok) {
      goToStep(4);
    }
  } catch (err) {
    alert("Failed to start ingestion pipeline");
  }
}

function startTelemetryPolling() {
  fetchTelemetry();
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(fetchTelemetry, 2000);
}

async function fetchTelemetry() {
  if (!currentTenant) return;
  try {
    const res = await fetch(`/api/v1/ingestion/status?tenant_id=${currentTenant.tenant_id}`);
    const data = await res.json();

    document.getElementById("stat-total-docs").innerText = data.total_documents_synced;
    document.getElementById("stat-s3-bytes").innerText = formatBytes(data.total_s3_bytes);

    renderAppsStatusList(data.apps_status);
    renderActivityLogs(data.recent_activity);
  } catch (err) {
    console.error("Telemetry fetch error", err);
  }
}

function renderAppsStatusList(apps) {
  const container = document.getElementById("apps-status-list");
  container.innerHTML = "";

  if (!apps || apps.length === 0) {
    container.innerHTML = `<div class="log-line">No apps connected yet.</div>`;
    return;
  }

  apps.forEach((app) => {
    const row = document.createElement("div");
    row.className = "app-status-row";
    row.innerHTML = `
      <span><strong>${app.source_app.toUpperCase()}</strong> (${app.items_synced} items)</span>
      <span class="status-badge ${app.status}">${app.status.toUpperCase()}</span>
    `;
    container.appendChild(row);
  });
}

function renderActivityLogs(logs) {
  const container = document.getElementById("activity-log-stream");
  container.innerHTML = "";

  if (!logs || logs.length === 0) {
    container.innerHTML = `<div class="log-line">Pipeline active... Processing incoming events.</div>`;
    return;
  }

  logs.forEach((log) => {
    const line = document.createElement("div");
    line.className = "log-line";
    line.innerText = `[${log.app.toUpperCase()}] Uploaded to S3: ${log.title} (${log.bytes} B)`;
    container.appendChild(line);
  });
}

function formatBytes(bytes) {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}

async function sendChatTurn() {
  const inputEl = document.getElementById("chat-user-input");
  const query = inputEl.value.trim();
  if (!query) return;

  const persona = document.getElementById("chat-persona-select").value;
  const mode = document.getElementById("chat-mode-select").value;
  const container = document.getElementById("chat-messages-container");

  // Render User Message
  const userMsg = document.createElement("div");
  userMsg.style.marginBottom = "1rem";
  userMsg.innerHTML = `<span style="font-size: 0.75rem; color: #94a3b8; font-weight: 600;">YOU</span>
    <p style="background: #1e293b; padding: 0.75rem; border-radius: 0.375rem; margin-top: 0.25rem;">${query}</p>`;
  container.appendChild(userMsg);

  inputEl.value = "";
  container.scrollTop = container.scrollHeight;

  const tenantId = (currentTenant && currentTenant.tenant_id) ? currentTenant.tenant_id : "4c132476-d47c-4e43-8fbf-4685c560ea49";
  const userId = (currentTenant && currentTenant.user_id) ? currentTenant.user_id : "user_default";

  try {
    const res = await fetch("/api/v6a/chat/turn", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tenant_id: tenantId,
        user_id: userId,
        user_query: query,
        persona: persona,
        mode: mode,
      }),
    });

    const data = await res.json();
    
    // Render AI Response
    const aiMsg = document.createElement("div");
    aiMsg.style.marginBottom = "1rem";
    let textContent = "No response text";
    if (data.response_text) {
      if (typeof data.response_text === "object" && data.response_text.text_content) {
        textContent = data.response_text.text_content;
      } else {
        textContent = String(data.response_text);
      }
    } else if (data.response && data.response.text_content) {
      textContent = data.response.text_content;
    }
    
    aiMsg.innerHTML = `<span style="font-size: 0.75rem; color: #3b82f6; font-weight: 600;">COMPANY BRAIN (${persona})</span>
      <div style="background: #1e293b; padding: 0.75rem; border-radius: 0.375rem; margin-top: 0.25rem; border-left: 4px solid #3b82f6;">
        <p style="white-space: pre-wrap;">${textContent}</p>
      </div>`;
    container.appendChild(aiMsg);
    container.scrollTop = container.scrollHeight;

    document.getElementById("chat-meta-latency").innerText = (data.latency_ms || 120).toFixed(1) + " ms";
    document.getElementById("chat-meta-cost").innerText = "$" + (data.cost_usd || 0.004).toFixed(4);
  } catch (err) {
    alert("Chat error: " + err.message);
  }
}
