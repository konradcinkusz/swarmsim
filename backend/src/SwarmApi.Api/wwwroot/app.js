// Polls GET /api/swarm/state and renders it — the read-only half of M4's acceptance
// criterion ("obejrzeć trwającą misję i odczytać status każdego drona bez zaglądania w
// terminal"). The demo-mission button below is a convenience for trying this without a
// terminal at all, not a substitute for POST /api/missions as the real integration point.

const POLL_INTERVAL_MS = 1000;

const bridgeModeEl = document.getElementById("bridge-mode");
const tableBody = document.querySelector("#drone-table tbody");
const emptyStateEl = document.getElementById("empty-state");
const canvas = document.getElementById("plot");
const ctx = canvas.getContext("2d");
const demoBtn = document.getElementById("demo-mission-btn");
const demoStatusEl = document.getElementById("demo-status");

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

pollState();
setInterval(pollState, POLL_INTERVAL_MS);
