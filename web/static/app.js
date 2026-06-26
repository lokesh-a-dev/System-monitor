// Front-end for the System Health Monitor web dashboard.

const REFRESH_MS = 2000;
let lastHistory = { metric: "cpu_percent", points: [] };

// When served by the central hub, window.MONITOR_HOST names which remote host
// to view; on the local dashboard it is empty and api() is a no-op.
const HOST = (window.MONITOR_HOST || "").trim();
function api(path) {
  if (!HOST) return path;
  return path + (path.includes("?") ? "&" : "?") + "host=" + encodeURIComponent(HOST);
}

// Tracks previous network counters for rate calculation.
let prevNet = null;
let prevNetTime = null;

// Current process sort tab.
let procTab = "cpu";

// ---- helpers ---------------------------------------------------------------

function humanBytes(n) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (Math.abs(n) >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(1)} ${units[i]}`;
}

function humanRate(bytesPerSec) {
  return humanBytes(bytesPerSec) + "/s";
}

function humanDuration(sec) {
  sec = Math.floor(sec);
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  const parts = [];
  if (d) parts.push(d + "d");
  if (h || d) parts.push(h + "h");
  if (m || h || d) parts.push(m + "m");
  parts.push(s + "s");
  return parts.join(" ");
}

function statusClass(value, warn, crit) {
  if (value >= crit) return "critical";
  if (value >= warn) return "warning";
  return "";
}

function setGauge(prefix, value, warn, crit) {
  const fill = document.getElementById(`${prefix}-fill`);
  const val = document.getElementById(`${prefix}-val`);
  const cls = statusClass(value, warn, crit);
  if (fill) {
    fill.style.width = Math.min(value, 100) + "%";
    fill.className = "fill " + cls;
  }
  if (val) val.textContent = value.toFixed(1) + "%";
}

// ---- process tab toggle ----------------------------------------------------

window.switchProcTab = function(tab) {
  procTab = tab;
  document.getElementById("tab-cpu").className = "tab-btn" + (tab === "cpu" ? " active" : "");
  document.getElementById("tab-mem").className = "tab-btn" + (tab === "mem" ? " active" : "");
};

// ---- snapshot rendering ----------------------------------------------------

async function refreshSnapshot() {
  let data;
  try {
    data = await (await fetch(api("/api/snapshot"))).json();
    document.getElementById("conn-status").textContent = "live";
  } catch (e) {
    document.getElementById("conn-status").textContent = "disconnected";
    return;
  }
  if (!data.ready) {
    document.getElementById("conn-status").textContent = "warming up…";
    return;
  }

  const s = data.snapshot;
  const sys = s.system;
  const now = Date.now() / 1000;

  // ---- Header ----
  document.getElementById("hostname").textContent = sys.hostname;
  document.getElementById("osinfo").textContent = sys.os;
  document.getElementById("uptime").textContent = "up " + humanDuration(sys.uptime_seconds);
  const users = sys.users || [];
  document.getElementById("users-row").textContent =
    users.length ? "Logged in: " + users.join(", ") : "";

  document.getElementById("score").textContent = data.health.score + "/100";
  const badge = document.getElementById("overall");
  badge.textContent = data.health.overall;
  badge.className = "status-badge status-" + data.health.overall;

  // ---- CPU gauge ----
  const cpu = s.cpu;
  setGauge("cpu", cpu.percent, 70, 90);
  const load = cpu.load_avg;
  document.getElementById("cpu-sub").textContent =
    `load ${load["1m"].toFixed(2)} / ${load["5m"].toFixed(2)} / ${load["15m"].toFixed(2)}` +
    ` · ${cpu.core_count} cores` +
    (cpu.frequency_mhz ? ` · ${cpu.frequency_mhz.toFixed(0)} MHz` : "") +
    (cpu.temperature != null ? ` · ${cpu.temperature.toFixed(0)}°C` : "");
  renderCoreBars(cpu.per_core || []);

  // ---- Memory gauge ----
  const mem = s.memory;
  setGauge("mem", mem.percent, 75, 90);
  document.getElementById("mem-sub").textContent =
    `${humanBytes(mem.used)} used / ${humanBytes(mem.total)} total` +
    ` · ${humanBytes(mem.available)} free`;
  if (mem.swap_total > 0) {
    const swapRow = document.getElementById("swap-row");
    swapRow.style.display = "flex";
    const sf = document.getElementById("swap-fill");
    sf.style.width = Math.min(mem.swap_percent, 100) + "%";
    sf.className = "fill " + statusClass(mem.swap_percent, 50, 80);
    document.getElementById("swap-val").textContent =
      `${mem.swap_percent.toFixed(0)}% (${humanBytes(mem.swap_used)}/${humanBytes(mem.swap_total)})`;
  }

  // ---- Disk gauge ----
  const disk = s.disk;
  setGauge("disk", disk.max_percent, 80, 95);
  const busiest = disk.partitions.reduce(
    (best, p) => p.percent > best.percent ? p : best,
    { percent: 0, mountpoint: "" }
  );
  document.getElementById("disk-sub").textContent =
    `${disk.partitions.length} partition(s)` +
    (busiest.mountpoint ? ` · busiest: ${busiest.mountpoint}` : "");
  document.getElementById("disk-io").textContent =
    `↑ ${humanBytes(disk.write_bytes)} written · ↓ ${humanBytes(disk.read_bytes)} read`;

  // ---- Network gauge ----
  const net = s.network;
  let upRate = 0, dnRate = 0;
  if (prevNet && prevNetTime && now > prevNetTime) {
    const dt = now - prevNetTime;
    upRate = Math.max(0, (net.bytes_sent - prevNet.bytes_sent) / dt);
    dnRate = Math.max(0, (net.bytes_recv - prevNet.bytes_recv) / dt);
  }
  prevNet = { bytes_sent: net.bytes_sent, bytes_recv: net.bytes_recv };
  prevNetTime = now;

  document.getElementById("net-up-rate").textContent = humanRate(upRate);
  document.getElementById("net-dn-rate").textContent = humanRate(dnRate);
  document.getElementById("net-totals").textContent =
    `Total ↑ ${humanBytes(net.bytes_sent)} · ↓ ${humanBytes(net.bytes_recv)}`;
  document.getElementById("net-conns").textContent =
    `${net.connections != null ? net.connections + " connections" : "connections n/a"}` +
    ` · ${net.errin + net.errout} errors`;

  // ---- Detail tables ----
  renderDiskTable(disk.partitions);
  renderNetInterfaces(net);
  renderProcTable(s.processes);
  renderSysInfo(sys, cpu);
  renderChecks(data.health.checks);
  renderAnomalies(data.anomalies);
}

function renderCoreBars(perCore) {
  const box = document.getElementById("core-bars");
  box.innerHTML = perCore.map((v, i) => {
    const h = Math.min(Math.max(v, 2), 100);
    const cls = statusClass(v, 70, 90);
    const color = cls === "critical" ? "var(--red)" : cls === "warning" ? "var(--yellow)" : "var(--blue)";
    return `<div class="core-wrap">
      <div class="core-bar">
        <div class="core-fill" style="height:${h}%;background:${color}"></div>
      </div>
      <span class="core-label">${i}</span>
    </div>`;
  }).join("");
}

function renderDiskTable(parts) {
  const tb = document.querySelector("#disk-table tbody");
  tb.innerHTML = parts.map(p => {
    const cls = statusClass(p.percent, 80, 95);
    return `<tr>
      <td>${p.mountpoint}</td>
      <td class="dim">${p.fstype}</td>
      <td class="num ${cls}">${p.percent.toFixed(0)}%</td>
      <td class="num dim">${humanBytes(p.free)}</td>
      <td class="num dim">${humanBytes(p.total)}</td>
    </tr>`;
  }).join("");
}

function renderNetInterfaces(net) {
  const ifaces = net.interfaces || {};
  const tb = document.querySelector("#net-iface-table tbody");
  const rows = Object.entries(ifaces).map(([name, c]) => `
    <tr>
      <td>${name}</td>
      <td class="num dim">${humanBytes(c.bytes_sent)}</td>
      <td class="num dim">${humanBytes(c.bytes_recv)}</td>
      <td class="num ${(c.errin + c.errout) > 0 ? "critical" : "dim"}">${c.errin + c.errout}</td>
    </tr>`).join("");
  tb.innerHTML = rows || `<tr><td colspan="4" class="dim">No interfaces</td></tr>`;

  // Extra stats block
  const extra = document.getElementById("net-stats-extra");
  const statsHtml = [
    ["Packets sent", net.packets_sent.toLocaleString()],
    ["Packets recv", net.packets_recv.toLocaleString()],
    ["Errors in", net.errin],
    ["Errors out", net.errout],
    ["Connections", net.connections != null ? net.connections : "n/a"],
  ].map(([k, v]) => `<div class="stat-line"><span class="dim">${k}</span><span>${v}</span></div>`).join("");
  extra.innerHTML = statsHtml;
}

function renderProcTable(procs) {
  const statuses = procs.statuses || {};
  document.getElementById("proc-status-row").textContent =
    `Total ${procs.count} · ` +
    `running ${statuses.running || 0} · ` +
    `sleeping ${statuses.sleeping || 0} · ` +
    `zombie ${statuses.zombie || 0}`;

  const list = procTab === "cpu" ? (procs.top_cpu || []) : (procs.top_memory || []);
  const tb = document.querySelector("#proc-table tbody");
  tb.innerHTML = list.slice(0, 8).map(p => `
    <tr>
      <td class="dim">${p.pid}</td>
      <td>${(p.name || "?").slice(0, 20)}</td>
      <td class="num ${statusClass(p.cpu_percent || 0, 50, 80)}">${(p.cpu_percent || 0).toFixed(1)}</td>
      <td class="num ${statusClass(p.memory_percent || 0, 30, 60)}">${(p.memory_percent || 0).toFixed(1)}</td>
    </tr>`).join("");
}

function renderSysInfo(sys, cpu) {
  const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
  set("si-hostname", sys.hostname);
  set("si-os", sys.os);
  set("si-platform", sys.platform);
  set("si-uptime", humanDuration(sys.uptime_seconds));
  set("si-boot", new Date(sys.boot_time * 1000).toLocaleString());
  set("si-users", (sys.users || []).join(", ") || "none");
  set("si-cores", `${cpu.physical_cores} physical / ${cpu.core_count} logical`);
  set("si-freq", cpu.frequency_mhz ? `${cpu.frequency_mhz.toFixed(0)} MHz` : "n/a");
  set("si-temp", cpu.temperature != null ? `${cpu.temperature.toFixed(1)}°C` : "n/a");
}

function renderChecks(checks) {
  const colors = { HEALTHY: "var(--green)", WARNING: "var(--yellow)", CRITICAL: "var(--red)" };
  const tb = document.querySelector("#checks-table tbody");
  tb.innerHTML = checks.map(c => `
    <tr>
      <td><span class="pill status-${c.status}" style="color:${colors[c.status]}">${c.status}</span></td>
      <td class="dim">${c.metric}</td>
      <td>${c.message}</td>
    </tr>`).join("");
}

function renderAnomalies(anoms) {
  const box = document.getElementById("anomalies");
  if (!anoms.length) {
    box.innerHTML = '<span class="dim">None — all metrics within baseline.</span>';
    return;
  }
  box.innerHTML = anoms.map(a => `
    <div class="anomaly-item ${a.severity}">
      <strong>${a.metric}</strong> = ${a.value.toFixed(2)}
      <span class="dim">(${a.zscore >= 0 ? "+" : ""}${a.zscore.toFixed(1)}σ from mean ${a.mean.toFixed(2)})</span>
    </div>`).join("");
}

async function refreshAlerts() {
  try {
    const alerts = await (await fetch(api("/api/alerts"))).json();
    const box = document.getElementById("alerts");
    if (!alerts.length) { box.innerHTML = '<span class="dim">None</span>'; return; }
    box.innerHTML = alerts.slice(0, 10).map(a => {
      const time = new Date(a.timestamp * 1000).toLocaleTimeString();
      return `<div class="alert-item ${a.severity}">
        <span class="dim">${time}</span> <strong>[${a.source}]</strong> ${a.message}</div>`;
    }).join("");
  } catch (e) { /* ignore */ }
}

// ---- history chart ---------------------------------------------------------

async function setupMetricSelect() {
  const metrics = await (await fetch(api("/api/metrics"))).json();
  const sel = document.getElementById("metric-select");
  sel.innerHTML = metrics.map(m => `<option value="${m}">${m}</option>`).join("");
  sel.addEventListener("change", refreshChart);
  document.getElementById("range-select").addEventListener("change", refreshChart);
}

async function refreshChart() {
  const metric = document.getElementById("metric-select").value;
  const minutes = document.getElementById("range-select").value;
  try {
    lastHistory = await (await fetch(api(`/api/history?metric=${metric}&minutes=${minutes}`))).json();
  } catch (e) { return; }
  drawChart();
}

function drawChart() {
  const canvas = document.getElementById("history-chart");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const cssW = canvas.clientWidth || 800;
  const cssH = 220;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = cssW * dpr;
  canvas.height = cssH * dpr;
  canvas.style.height = cssH + "px";
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  const pad = { l: 55, r: 12, t: 16, b: 26 };
  const W = cssW - pad.l - pad.r;
  const H = cssH - pad.t - pad.b;
  const pts = lastHistory.points || [];

  ctx.strokeStyle = "#2d3743";
  ctx.fillStyle = "#8b97a6";
  ctx.font = "11px system-ui, sans-serif";
  ctx.lineWidth = 1;

  if (pts.length < 2) {
    ctx.fillText("Collecting data…", pad.l + W / 2 - 40, pad.t + H / 2);
    return;
  }

  const vals = pts.map(p => p.v);
  let min = Math.min(...vals), max = Math.max(...vals);
  if (min === max) { max = min + 1; }
  const range = max - min;
  min = Math.max(0, min - range * 0.08);
  max = max + range * 0.08;

  const x = i => pad.l + (i / (pts.length - 1)) * W;
  const y = v => pad.t + H - ((v - min) / (max - min)) * H;

  // Grid + y labels
  for (let g = 0; g <= 4; g++) {
    const gv = min + (max - min) * (g / 4);
    const gy = y(gv);
    ctx.beginPath(); ctx.moveTo(pad.l, gy); ctx.lineTo(pad.l + W, gy); ctx.stroke();
    ctx.fillText(gv.toFixed(1), 4, gy + 3);
  }

  // Area fill
  ctx.beginPath();
  ctx.moveTo(x(0), y(vals[0]));
  pts.forEach((p, i) => ctx.lineTo(x(i), y(p.v)));
  ctx.lineTo(x(pts.length - 1), pad.t + H);
  ctx.lineTo(x(0), pad.t + H);
  ctx.closePath();
  ctx.fillStyle = "rgba(88,166,255,0.10)";
  ctx.fill();

  // Line
  ctx.beginPath();
  pts.forEach((p, i) => i === 0 ? ctx.moveTo(x(i), y(p.v)) : ctx.lineTo(x(i), y(p.v)));
  ctx.strokeStyle = "#58a6ff";
  ctx.lineWidth = 2;
  ctx.stroke();

  // X labels
  [0, Math.floor(pts.length / 2), pts.length - 1].forEach(i => {
    const t = new Date(pts[i].t * 1000).toLocaleTimeString();
    ctx.fillStyle = "#8b97a6";
    ctx.fillText(t, Math.min(x(i), cssW - 62), cssH - 6);
  });

  // Title
  ctx.fillStyle = "#e6edf3";
  ctx.fillText(lastHistory.metric, pad.l, pad.t - 3);
}

window.addEventListener("resize", drawChart);

// ---- boot ------------------------------------------------------------------

async function boot() {
  await setupMetricSelect();
  await refreshSnapshot();
  await refreshChart();
  await refreshAlerts();
  setInterval(refreshSnapshot, REFRESH_MS);
  setInterval(refreshChart, REFRESH_MS * 3);
  setInterval(refreshAlerts, REFRESH_MS * 2);
}

boot();
