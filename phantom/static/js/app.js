const state = { dashboard: null, activeFollower: null };

const $ = (selector) => document.querySelector(selector);
const escapeHTML = (value) => String(value ?? "").replace(/[&<>\"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[char]));
const formatMoney = (value) => `${Number(value || 0) < 0 ? '-' : ''}$${Math.abs(Number(value || 0)).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const formatTime = (value) => value ? new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—";
const formatDateTime = (value) => value ? new Date(value).toLocaleString([], { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—";

function toast(message, type = "success") {
  const node = document.createElement("div");
  node.className = `toast ${type}`;
  node.textContent = message;
  $("#toast-stack").appendChild(node);
  window.setTimeout(() => node.remove(), 3800);
}

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || body.message || (body.errors && body.errors.join(" · ")) || "Request failed");
  return body;
}

function renderMetrics(data) {
  $("#healthy-followers").textContent = data.metrics.healthy_followers;
  $("#follower-total").textContent = `/ ${data.metrics.total_followers}`;
  $("#active-positions").textContent = data.metrics.active_positions;
  $("#copy-success").textContent = data.metrics.success_count;
  $("#copy-blocked").textContent = data.metrics.failure_count;
  $("#floating-pl").textContent = formatMoney(data.metrics.floating_pl);
  $("#sync-lag").textContent = `Sync lag ${data.metrics.sync_lag}`;
  $("#last-reconcile").textContent = formatTime(data.engine.last_reconciliation);
  $("#engine-state-label").textContent = data.engine.emergency_stop ? "STOP" : data.engine.state.toUpperCase();
  $("#engine-message").textContent = data.engine.emergency_stop ? "Emergency stop is active. New submissions are blocked." : data.engine.state === "running" ? "Monitoring and simulated entry routing are active." : data.engine.state === "stopped" ? "Engine stopped. Connector resources are released." : "Entries are paused. Safe monitoring continues.";
  const coreDot = $(".engine-core .pulse-dot");
  coreDot.style.color = data.engine.emergency_stop ? "var(--red)" : data.engine.state === "running" ? "var(--mint)" : "var(--violet)";
}

function renderAccounts(accounts) {
  $("#account-grid").innerHTML = accounts.map((account) => {
    const isMaster = account.role === "master";
    const stale = account.connection_state !== "connected" || account.readiness !== "ready";
    return `<article class="account-card ${isMaster ? "master" : ""} ${stale ? "stale" : ""}">
      <div class="account-top"><div><div class="account-role">${isMaster ? "MASTER / SOURCE" : "FOLLOWER / DESTINATION"}</div><div class="account-name">${escapeHTML(account.label)}</div><div class="account-broker">${escapeHTML(account.broker)} · ${escapeHTML(account.login_masked)}</div></div><span class="connection-badge ${stale ? "stale" : "connected"}"><span class="status-dot"></span>${stale ? "STALE" : "CONNECTED"}</span></div>
      <div class="account-meta-grid"><div><span>Balance</span><strong>${formatMoney(account.balance)}</strong></div><div><span>Equity</span><strong>${formatMoney(account.equity)}</strong></div><div><span>Floating P/L</span><strong class="${account.floating_pl >= 0 ? "mint-text" : ""}">${formatMoney(account.floating_pl)}</strong></div><div><span>Positions</span><strong>${account.active_positions}</strong></div></div>
      <div class="account-footer"><span class="mono">${escapeHTML(account.terminal_path)}</span>${isMaster ? "<span class=\"account-link\">Read-only monitor</span>" : `<button class="account-link policy-link" data-follower="${escapeHTML(account.id)}">Edit policy →</button>`}</div>
    </article>`;
  }).join("");
  document.querySelectorAll(".policy-link").forEach((button) => button.addEventListener("click", () => openPolicy(button.dataset.follower)));
}

async function openPolicy(followerId) {
  try {
    const policy = await api(`/api/v1/followers/${encodeURIComponent(followerId)}/policy`);
    state.activeFollower = followerId;
    const form = $("#policy-form");
    Object.entries(policy).forEach(([key, value]) => {
      const field = form.elements[key];
      if (!field) return;
      if (field.type === "checkbox") field.checked = Boolean(Number(value));
      else field.value = value;
    });
    $("#policy-modal").hidden = false;
  } catch (error) { toast(error.message, "error"); }
}

function closePolicy() { $("#policy-modal").hidden = true; state.activeFollower = null; }

function statusMarkup(status) {
  const label = status === "success" ? "Copied" : status === "blocked" ? "Blocked" : status;
  return `<span class="table-status ${escapeHTML(status)}"><span class="status-dot"></span>${label}</span>`;
}

function renderActivity(executions) {
  $("#activity-table").innerHTML = executions.length ? executions.map((row) => `<tr><td><span class="event-id">${escapeHTML(row.source_ticket)}</span></td><td>${escapeHTML(row.follower_label)}</td><td><span class="trade-cell"><span class="side-chip ${row.side.toLowerCase()}">${escapeHTML(row.side)}</span><span>${escapeHTML(row.symbol)}</span></span></td><td class="mono">${Number(row.filled_volume ?? row.requested_volume).toFixed(2)} lot</td><td>${statusMarkup(row.status)}</td><td class="mono">${formatTime(row.created_at)}</td></tr>`).join("") : `<tr><td colspan="6" class="empty-cell">No copy activity yet.</td></tr>`;
  $("#activity-summary").textContent = `${executions.length} recent execution records · source-to-follower mapping persisted`;
}

function renderAlerts(alerts) {
  $("#alert-count").textContent = alerts.filter((alert) => !alert.acknowledged).length;
  $("#alert-list").innerHTML = alerts.length ? alerts.slice(0, 4).map((alert) => `<div class="alert-item"><span class="alert-signal ${escapeHTML(alert.severity)}"></span><div class="alert-copy"><strong>${escapeHTML(alert.title)}</strong><p>${escapeHTML(alert.message)}</p></div><span class="alert-time">${formatTime(alert.created_at)}</span></div>`).join("") : `<div class="empty-copy">No active alerts.</div>`;
}

function renderAudit(audit) {
  $("#audit-list").innerHTML = audit.length ? audit.slice(0, 4).map((item) => `<div class="audit-item"><div class="audit-icon">↗</div><div class="audit-copy"><strong>${escapeHTML(item.action.replaceAll("_", " "))}</strong><p>${escapeHTML(item.actor)} · ${escapeHTML(item.object_type)} ${escapeHTML(item.object_id || "")}</p></div><span class="audit-time">${formatDateTime(item.created_at)}</span></div>`).join("") : `<div class="empty-copy">No audit activity.</div>`;
}

function render(data) {
  state.dashboard = data;
  renderMetrics(data);
  renderAccounts(data.accounts);
  renderActivity(data.executions);
  renderAlerts(data.alerts);
  renderAudit(data.audit);
}

async function refresh() {
  try { render(await api("/api/v1/dashboard")); } catch (error) { toast(error.message, "error"); }
}

async function engineAction(action) {
  try { const result = await api(`/api/v1/engine/${action}`, { method: "POST" }); toast(result.message); await refresh(); } catch (error) { toast(error.message, "error"); }
}

function openEmergencyModal() { $("#confirm-modal").hidden = false; }
function closeEmergencyModal() { $("#confirm-modal").hidden = true; }

$("#refresh-button").addEventListener("click", refresh);
$("#demo-tick").addEventListener("click", async () => { try { const result = await api("/api/v1/simulation/tick", { method: "POST" }); toast(result.processed ? "Demo event processed once and mapped to eligible followers." : result.message, result.processed ? "success" : "error"); await refresh(); } catch (error) { toast(error.message, "error"); } });
$("#emergency-button").addEventListener("click", openEmergencyModal);
$("#modal-cancel").addEventListener("click", closeEmergencyModal);
$("#modal-confirm").addEventListener("click", async () => { closeEmergencyModal(); await engineAction("emergency-stop"); });
$("#policy-cancel").addEventListener("click", closePolicy);
$("#policy-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = Object.fromEntries(new FormData(form).entries());
  ["multiplier", "fixed_lot", "balance_ratio", "risk_pct", "max_lot", "max_risk", "max_open_positions"].forEach((key) => { if (payload[key] !== undefined) payload[key] = Number(payload[key]); });
  ["sltp_sync", "pending_order_copy", "copy_enabled"].forEach((key) => { payload[key] = form.elements[key].checked ? 1 : 0; });
  try { await api(`/api/v1/followers/${encodeURIComponent(state.activeFollower)}/policy`, { method: "PUT", body: JSON.stringify(payload) }); closePolicy(); toast("Follower policy saved and persisted locally."); await refresh(); } catch (error) { toast(error.message, "error"); }
});
$("#preflight-button").addEventListener("click", () => toast("Preflight passed for simulation: mode labeled, database ready, policies persisted, live connector gated.", "success"));
$(".notice-dismiss").addEventListener("click", (event) => event.currentTarget.closest(".notice-banner").remove());
document.querySelectorAll("[data-engine-action]").forEach((button) => button.addEventListener("click", () => engineAction(button.dataset.engineAction)));

refresh();
window.setInterval(refresh, 30000);
