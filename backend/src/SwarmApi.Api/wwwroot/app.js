// Polls GET /api/swarm/state and renders it — M4's acceptance criterion ("obejrzeć
// trwającą misję i odczytać status każdego drona bez zaglądania w terminal") — and is the
// person's side of the agent write gate (docs/adr/0009): mission plans are approved or
// rejected here, and an approval shows its single-use code once. Stopping (abort, land
// all) is never gated. The demo-mission button is a convenience, not the integration point.

const POLL_INTERVAL_MS = 1000;
const PLAN_POLL_INTERVAL_MS = 2000;
const OPEN_PLAN_STATUSES = ["PendingApproval", "Conflicted", "Approved"];

const bridgeModeEl = document.getElementById("bridge-mode");
const tableBody = document.querySelector("#drone-table tbody");
const emptyStateEl = document.getElementById("empty-state");
const canvas = document.getElementById("plot");
const ctx = canvas.getContext("2d");
const demoBtn = document.getElementById("demo-mission-btn");
const demoStatusEl = document.getElementById("demo-status");
const activeMissionEl = document.getElementById("active-mission");
const abortBtn = document.getElementById("abort-btn");
const landAllBtn = document.getElementById("land-all-btn");
const stopStatusEl = document.getElementById("stop-status");
const plansEl = document.getElementById("plans");
const noPlansEl = document.getElementById("no-plans");

let activeMissionId = null;
// Approval codes live only in this page's memory: the API shows each one once, in the
// approve response, and never again — reloading the page forgets them, by design.
const approvalCodes = new Map();
let renderedPlans = "";

async function pollState() {
  try {
    const response = await fetch("/api/swarm/state", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`GET /api/swarm/state -> ${response.status}`);
    }
    const state = await response.json();
    renderBridgeMode(state.bridgeMode);
    renderTable(state.drones ?? []);
    renderPlot(state.drones ?? []);
    await renderActiveMission(state.activeMissionId);
  } catch (err) {
    bridgeModeEl.textContent = "unreachable";
    bridgeModeEl.className = "badge error";
    console.error(err);
  }
}

// The three bridge modes (docs/adr/0003): a live swarm, a configured swarm whose
// connection is down (positions below are the last ones received), or the stand-in.
const BRIDGE_BADGES = {
  Connected: { text: "connected", css: "connected" },
  Disconnected: { text: "disconnected — reconnecting; positions are stale", css: "error" },
  Simulated: { text: "simulated (degraded)", css: "simulated" },
};

function renderBridgeMode(mode) {
  const badge = BRIDGE_BADGES[mode] ?? { text: `unknown mode: ${mode}`, css: "error" };
  bridgeModeEl.textContent = badge.text;
  bridgeModeEl.className = `badge ${badge.css}`;
}

function renderTable(drones) {
  emptyStateEl.hidden = drones.length > 0;
  tableBody.innerHTML = "";

  for (const drone of drones) {
    const row = document.createElement("tr");
    const updated = drone.lastUpdatedUtc ? new Date(drone.lastUpdatedUtc).toLocaleTimeString() : "—";
    row.innerHTML = `
      <td>${escapeHtml(drone.id)}</td>
      <td class="status-${escapeHtml(drone.status)}">${escapeHtml(drone.status)}</td>
      <td>${fmt(drone.position?.x)}, ${fmt(drone.position?.y)}, ${fmt(drone.position?.z)}</td>
      <td>${drone.batteryPercent == null ? "—" : `${fmt(drone.batteryPercent, 0)}%`}</td>
      <td>${drone.currentWaypointIndex ?? "—"}</td>
      <td>${updated}</td>
    `;
    tableBody.appendChild(row);
  }
}

function renderPlot(drones) {
  const { width, height } = canvas;
  ctx.clearRect(0, 0, width, height);

  ctx.strokeStyle = "color-mix(in srgb, currentColor 15%, transparent)";
  ctx.strokeRect(0, 0, width, height);

  if (drones.length === 0) {
    return;
  }

  const xs = drones.map((d) => d.position?.x ?? 0);
  const ys = drones.map((d) => d.position?.y ?? 0);
  const margin = 3;
  const minX = Math.min(...xs) - margin;
  const maxX = Math.max(...xs) + margin;
  const minY = Math.min(...ys) - margin;
  const maxY = Math.max(...ys) + margin;
  const spanX = Math.max(maxX - minX, 1);
  const spanY = Math.max(maxY - minY, 1);

  const toCanvas = (x, y) => [
    ((x - minX) / spanX) * width,
    height - ((y - minY) / spanY) * height, // flip Y so "up" on screen is +Y
  ];

  for (const drone of drones) {
    const [cx, cy] = toCanvas(drone.position?.x ?? 0, drone.position?.y ?? 0);
    ctx.beginPath();
    ctx.arc(cx, cy, 6, 0, Math.PI * 2);
    ctx.fillStyle = statusColor(drone.status);
    ctx.fill();
    ctx.fillStyle = "currentColor";
    ctx.font = "11px system-ui, sans-serif";
    ctx.fillText(drone.id, cx + 8, cy - 8);
  }
}

function statusColor(status) {
  switch (status) {
    case "InFlight": return "#3b82f6";
    case "Landed": return "#22c55e";
    case "Landing":
    case "TakingOff":
    case "Returning": return "#f59e0b";
    case "Holding": return "#a855f7";
    case "Error": return "#ef4444";
    default: return "#9ca3af"; // Idle, Unknown
  }
}

function fmt(value, digits = 2) {
  return typeof value === "number" ? value.toFixed(digits) : "—";
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value ?? "";
  return div.innerHTML;
}

demoBtn.addEventListener("click", async () => {
  const droneCount = Number(document.getElementById("demo-drone-count").value) || 3;
  const mode = document.getElementById("demo-mode").value;

  demoBtn.disabled = true;
  demoStatusEl.textContent = "Dispatching…";

  try {
    const response = await fetch("/api/missions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: `Demo mission (${mode})`,
        type: mode,
        waypoints: [
          { x: 0, y: 0, z: 5 },
          { x: 10, y: 0, z: 5 },
          { x: 10, y: 10, z: 5 },
          { x: 0, y: 10, z: 5 },
        ],
        droneCount,
        spacingMeters: 2.0,
      }),
    });

    if (!response.ok) {
      const problem = await response.json().catch(() => null);
      throw new Error(problem?.errors ? JSON.stringify(problem.errors) : `HTTP ${response.status}`);
    }

    const mission = await response.json();
    demoStatusEl.textContent = `Mission "${mission.name}" dispatched (id ${mission.id}).`;
  } catch (err) {
    demoStatusEl.textContent = `Failed to dispatch mission: ${err.message}`;
  } finally {
    demoBtn.disabled = false;
  }
});

async function renderActiveMission(missionId) {
  activeMissionId = missionId ?? null;
  abortBtn.disabled = activeMissionId === null;
  if (activeMissionId === null) {
    activeMissionEl.textContent = "No mission is flying.";
    return;
  }
  const response = await fetch(`/api/missions/${activeMissionId}`, { cache: "no-store" });
  const mission = response.ok ? await response.json() : null;
  activeMissionEl.textContent = mission
    ? `"${mission.name}" — ${mission.status} (${mission.droneCount} drones, id ${mission.id})`
    : `Mission ${activeMissionId}`;
}

function newKey() {
  // randomUUID needs a secure context (https or localhost); a key only has to be unique.
  return crypto.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

async function send(method, url, body) {
  const response = await fetch(url, {
    method,
    headers: {
      "Content-Type": "application/json",
      // One key per click: a retried click replays the first answer instead of acting twice.
      "Idempotency-Key": newKey(),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const reason = payload?.detail ?? payload?.title ?? `HTTP ${response.status}`;
    throw new Error(reason);
  }
  return payload;
}

abortBtn.addEventListener("click", async () => {
  if (activeMissionId === null) {
    return;
  }
  try {
    await send("POST", `/api/missions/${activeMissionId}/abort`, { action: "rtl" });
    stopStatusEl.textContent = "Mission aborted: every drone is returning to its pad.";
  } catch (err) {
    stopStatusEl.textContent = `Abort failed: ${err.message}`;
  }
  pollState();
});

landAllBtn.addEventListener("click", async () => {
  try {
    await send("POST", "/api/swarm/land");
    stopStatusEl.textContent = "Land all sent: every drone is landing where it is.";
  } catch (err) {
    stopStatusEl.textContent = `Land all failed: ${err.message}`;
  }
  pollState();
});

async function pollPlans() {
  try {
    const response = await fetch("/api/mission-plans?limit=20", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`GET /api/mission-plans -> ${response.status}`);
    }
    const plans = (await response.json()).filter((p) => OPEN_PLAN_STATUSES.includes(p.status));
    const snapshot = JSON.stringify([plans, [...approvalCodes]]);
    if (snapshot !== renderedPlans) {
      renderedPlans = snapshot;
      renderPlans(plans);
    }
  } catch (err) {
    console.error(err);
  }
}

function renderPlans(plans) {
  noPlansEl.hidden = plans.length > 0;
  plansEl.innerHTML = "";
  for (const plan of plans) {
    const card = document.createElement("article");
    card.className = `plan plan-${plan.status}`;
    card.setAttribute("aria-labelledby", `plan-${plan.id}`);
    const preview = plan.preview ?? {};
    const conflicts = (preview.conflicts ?? [])
      .map((c) => `<li>${escapeHtml(c.droneA)} and ${escapeHtml(c.droneB)} within ${fmt(c.distanceMeters)} m at ${fmt(c.atSeconds, 1)} s</li>`)
      .join("");
    const code = approvalCodes.get(plan.id);
    card.innerHTML = `
      <h3 id="plan-${plan.id}">${escapeHtml(plan.name)}</h3>
      <p>${escapeHtml(plan.type)}${plan.type === "LeaderFollowerFormation" ? ` (${escapeHtml(plan.formation)})` : ""},
         ${plan.droneCount} drones, ${plan.waypoints.length} waypoints,
         about ${fmt(preview.estimatedDurationSeconds, 0)} s,
         closest approach ${preview.minSeparationMeters == null ? "—" : `${fmt(preview.minSeparationMeters)} m`}.
         Status: <strong>${escapeHtml(plan.status)}</strong></p>
      ${conflicts ? `<p>Conflicts — this plan cannot be approved:</p><ul>${conflicts}</ul>` : ""}
      ${code ? `<p>Approval code (single use, shown once): <code class="approval-code" aria-label="Approval code">${escapeHtml(code)}</code></p>` : ""}
      <div class="controls"></div>
      <p class="plan-status" role="status"></p>
    `;
    const controls = card.querySelector(".controls");
    const status = card.querySelector(".plan-status");
    if (plan.status === "PendingApproval" || plan.status === "Conflicted") {
      controls.append(button("Approve", plan.status === "Conflicted", async () => {
        const approval = await send("POST", `/api/mission-plans/${plan.id}/approve`);
        approvalCodes.set(plan.id, approval.approvalCode);
      }, status));
    }
    if (plan.status === "Approved" && code) {
      controls.append(button("Dispatch now", false, async () => {
        await send("POST", `/api/mission-plans/${plan.id}/dispatch`, { approvalCode: code });
        approvalCodes.delete(plan.id);
      }, status));
    }
    controls.append(button("Reject", false, async () => {
      await send("POST", `/api/mission-plans/${plan.id}/reject`);
      approvalCodes.delete(plan.id);
    }, status));
    plansEl.appendChild(card);
  }
}

function button(label, disabled, action, statusEl) {
  const el = document.createElement("button");
  el.type = "button";
  el.textContent = label;
  el.disabled = disabled;
  el.addEventListener("click", async () => {
    el.disabled = true;
    try {
      await action();
    } catch (err) {
      statusEl.textContent = `${label} failed: ${err.message}`;
      el.disabled = false;
      return;
    }
    await pollPlans();
    pollState();
  });
  return el;
}

pollState();
setInterval(pollState, POLL_INTERVAL_MS);
pollPlans();
setInterval(pollPlans, PLAN_POLL_INTERVAL_MS);
