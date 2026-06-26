// Fleet overview: polls /api/hosts and renders one card per monitored host.

const REFRESH_MS = 3000;

function humanDuration(sec) {
  sec = Math.floor(sec);
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const parts = [];
  if (d) parts.push(d + "d");
  if (h || d) parts.push(h + "h");
  parts.push(m + "m");
  return parts.join(" ");
}

function agoText(sec) {
  if (sec < 0) sec = 0;
  if (sec < 60) return Math.round(sec) + "s ago";
  if (sec < 3600) return Math.round(sec / 60) + "m ago";
  return Math.round(sec / 3600) + "h ago";
}

function miniBar(label, value, warn, crit) {
  const cls = value >= crit ? "critical" : value >= warn ? "warning" : "";
  return `<div class="mini">
      <span class="mini-label">${label}</span>
      <div class="mini-track"><div class="mini-fill ${cls}" style="width:${Math.min(value, 100)}%"></div></div>
      <span class="mini-val">${value.toFixed(0)}%</span>
    </div>`;
}

function hostCard(h) {
  const offline = !h.online;
  const overall = offline ? "OFFLINE" : (h.overall || "—");
  const dotCls = offline ? "offline" : "status-" + overall;
  const score = (h.score != null && !offline) ? `${h.score}/100` : "—";

  const body = (h.cpu != null) ? `
    ${miniBar("CPU", h.cpu, 70, 90)}
    ${miniBar("MEM", h.memory, 75, 90)}
    ${miniBar("DISK", h.disk, 80, 95)}
    <div class="card-meta dim">${h.os || ""} · up ${humanDuration(h.uptime_seconds || 0)}</div>
  ` : `<div class="dim" style="padding:0.5rem 0">No data yet</div>`;

  return `<a class="host-card ${offline ? "is-offline" : ""}" href="/host/${encodeURIComponent(h.host)}">
      <div class="card-head">
        <span class="dot ${dotCls}"></span>
        <span class="card-name">${h.label}</span>
        <span class="status-badge status-${offline ? "OFFLINE" : overall}">${overall}</span>
      </div>
      <div class="card-score">${score}</div>
      ${body}
      <div class="card-foot dim">${agoText(h.seconds_ago)}</div>
    </a>`;
}

async function refresh() {
  let data;
  try {
    data = await (await fetch("/api/hosts")).json();
    document.getElementById("conn-status").textContent = "live";
  } catch (e) {
    document.getElementById("conn-status").textContent = "disconnected";
    return;
  }
  const hosts = data.hosts || [];
  const grid = document.getElementById("host-grid");

  if (!hosts.length) {
    grid.innerHTML = '<div class="dim" style="padding:2rem">Waiting for agents to report…</div>';
  } else {
    grid.innerHTML = hosts.map(hostCard).join("");
  }

  const online = hosts.filter(h => h.online).length;
  const critical = hosts.filter(h => h.online && h.overall === "CRITICAL").length;
  document.getElementById("fleet-summary").textContent =
    `${hosts.length} host(s) · ${online} online · ${hosts.length - online} offline`;

  const status = document.getElementById("fleet-status");
  if (critical > 0) {
    status.textContent = `${critical} CRITICAL`;
    status.className = "status-badge status-CRITICAL";
  } else if (online < hosts.length) {
    status.textContent = "DEGRADED";
    status.className = "status-badge status-WARNING";
  } else {
    status.textContent = "ALL HEALTHY";
    status.className = "status-badge status-HEALTHY";
  }
}

refresh();
setInterval(refresh, REFRESH_MS);
