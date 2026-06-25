// Front-end for the System Health Monitor web dashboard.
// Polls the JSON API and updates gauges, tables, the history chart,
// anomalies and alerts.

const REFRESH_MS = 2000;
let lastHistory = { metric: "cpu_percent", points: [] };

// ---- helpers ---------------------------------------------------------------

function humanBytes(n) {
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  let i = 0;
  while (Math.abs(n) >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(1)} ${units[i]}`;
}

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

function statusClass(value, warn, crit) {
  if (value >= crit) return "critical";
  if (value >= warn) return "warning";
  return "";
}

function setGauge(prefix, value, warn, crit, unit = "%") {
  const fill = document.getElementById(`${prefix}-fill`);
  const val = document.getElementById(`${prefix}-val`);
  const cls = statusClass(value, warn, crit);
  if (fill) {
    fill.style.width = Math.min(value, 100) + "%";
    fill.className = "fill " + cls;
  }
  if (val) val.textContent = value.toFixed(1) + unit;
}

// ---- snapshot rendering ----------------------------------------------------

async function refreshSnapshot() {
  let data;
  try {
    data = await (await fetch("/api/snapshot")).json();
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

  document.getElementById("hostname").textContent = sys.hostname;
  document.getElementById("osinfo").textContent = sys.os;
  document.getElementById("uptime").textContent = "up " + humanDuration(sys.uptime_seconds);

  // Score + overall badge
  const score = document.getElementById("score");
  score.textContent = data.health.score + "/100";
  const badge = document.getElementById("overall");
  badge.textContent = data.health.overall;
  badge.className = "status-badge status-" + data.health.overall;

  // Gauges
  setGauge("cpu", s.cpu.percent, 70, 90);
  const load = s.cpu.load_avg;
  document.getElementById("cpu-sub").textContent =
    `load ${load["1m"].toFixed(2)} / ${load["5m"].toFixed(2)} / ${load["15m"].toFixed(2)} · ${s.cpu.core_count} cores` +
    (s.cpu.temperature != null ? ` · ${s.cpu.temperature.toFixed(0)}°C` : "");

  setGauge("mem", s.memory.percent, 75, 90);
  document.getElementById("mem-sub").textContent =
    `${humanBytes(s.memory.used)} / ${humanBytes(s.memory.total)}` +
    (s.memory.swap_total > 0 ? ` · swap ${s.memory.swap_percent.toFixed(0)}%` : "");

  setGauge("disk", s.disk.max_percent, 80, 95);
  document.getElementById("disk-sub").textContent =
    `${s.disk.partitions.length} partition(s)`;

  document.getElementById("net-val").textContent =
    `↑ ${humanBytes(s.network.bytes_sent)}  ↓ ${humanBytes(s.network.bytes_recv)}`;
  document.getElementById("net-sub").textContent =
    `${s.network.connections != null ? s.network.connections : "?"} conns · ` +
    `${s.network.errin + s.network.errout} errors`;

  renderDiskTable(s.disk.partitions);
  renderProcTable(s.processes.top_cpu);
  renderChecks(data.health.checks);
  renderAnomalies(data.anomalies);
}

function renderDiskTable(parts) {
  const tb = document.querySelector("#disk-table tbody");
  tb.innerHTML = parts.map(p => `
    <tr>
      <td>${p.mountpoint}</td>
      <td class="num">${p.percent.toFixed(0)}%</td>
      <td class="num dim">${humanBytes(p.free)} free</td>
    </tr>`).join("");
}

function renderProcTable(procs) {
  const tb = document.querySelector("#proc-table tbody");
  tb.innerHTML = procs.slice(0, 6).map(p => `
    <tr>
      <td class="dim">${p.pid}</td>
      <td>${(p.name || "?").slice(0, 22)}</td>
      <td class="num">${(p.cpu_percent || 0).toFixed(1)}</td>
      <td class="num">${(p.memory_percent || 0).toFixed(1)}</td>
    </tr>`).join("");
}

function renderChecks(checks) {
  const colors = { HEALTHY: "var(--green)", WARNING: "var(--yellow)", CRITICAL: "var(--red)" };
  const tb = document.querySelector("#checks-table tbody");
  tb.innerHTML = checks.map(c => `
    <tr>
      <td><span class="pill status-${c.status}" style="color:${colors[c.status]}">${c.status}</span></td>
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
      <strong>${a.metric}</strong> = ${a.value.toFixed(1)}
      (${a.zscore >= 0 ? "+" : ""}${a.zscore.toFixed(1)}σ from mean ${a.mean.toFixed(1)})
    </div>`).join("");
}

async function refreshAlerts() {
  try {
    const alerts = await (await fetch("/api/alerts")).json();
    const box = document.getElementById("alerts");
    if (!alerts.length) { box.innerHTML = '<span class="dim">None</span>'; return; }
    box.innerHTML = alerts.slice(0, 8).map(a => {
      const time = new Date(a.timestamp * 1000).toLocaleTimeString();
      return `<div class="alert-item ${a.severity}">
        <span class="dim">${time}</span> [${a.source}] ${a.message}</div>`;
    }).join("");
  } catch (e) { /* ignore */ }
}

// ---- history chart ---------------------------------------------------------

async function setupMetricSelect() {
  const metrics = await (await fetch("/api/metrics")).json();
  const sel = document.getElementById("metric-select");
  sel.innerHTML = metrics.map(m => `<option value="${m}">${m}</option>`).join("");
  sel.addEventListener("change", refreshChart);
  document.getElementById("range-select").addEventListener("change", refreshChart);
}

async function refreshChart() {
  const metric = document.getElementById("metric-select").value;
  const minutes = document.getElementById("range-select").value;
  try {
    lastHistory = await (await fetch(`/api/history?metric=${metric}&minutes=${minutes}`)).json();
  } catch (e) { return; }
  drawChart();
}

// Self-contained canvas line chart (no external libraries).
function drawChart() {
  const canvas = document.getElementById("history-chart");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  // Match the canvas backing store to its displayed size for crisp lines.
  const cssW = canvas.clientWidth || 800;
  const cssH = 220;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = cssW * dpr;
  canvas.height = cssH * dpr;
  canvas.style.height = cssH + "px";
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  const pad = { l: 50, r: 12, t: 12, b: 24 };
  const W = cssW - pad.l - pad.r;
  const H = cssH - pad.t - pad.b;
  const pts = lastHistory.points || [];

  // Axes / grid
  ctx.strokeStyle = "#2d3743";
  ctx.fillStyle = "#8b97a6";
  ctx.font = "11px system-ui, sans-serif";
  ctx.lineWidth = 1;

  if (pts.length < 2) {
    ctx.fillText("Collecting data…", pad.l, pad.t + H / 2);
    return;
  }

  const vals = pts.map(p => p.v);
  let min = Math.min(...vals), max = Math.max(...vals);
  if (min === max) { max = min + 1; }            // avoid flat-line div-by-zero
  const range = max - min;
  min = Math.max(0, min - range * 0.1);
  max = max + range * 0.1;

  const x = i => pad.l + (i / (pts.length - 1)) * W;
  const y = v => pad.t + H - ((v - min) / (max - min)) * H;

  // Horizontal grid + y labels (4 lines)
  for (let g = 0; g <= 4; g++) {
    const gv = min + (max - min) * (g / 4);
    const gy = y(gv);
    ctx.beginPath(); ctx.moveTo(pad.l, gy); ctx.lineTo(pad.l + W, gy); ctx.stroke();
    ctx.fillText(gv.toFixed(0), 6, gy + 3);
  }

  // Area fill
  ctx.beginPath();
  ctx.moveTo(x(0), y(vals[0]));
  pts.forEach((p, i) => ctx.lineTo(x(i), y(p.v)));
  ctx.lineTo(x(pts.length - 1), pad.t + H);
  ctx.lineTo(x(0), pad.t + H);
  ctx.closePath();
  ctx.fillStyle = "rgba(88,166,255,0.12)";
  ctx.fill();

  // Line
  ctx.beginPath();
  pts.forEach((p, i) => i === 0 ? ctx.moveTo(x(i), y(p.v)) : ctx.lineTo(x(i), y(p.v)));
  ctx.strokeStyle = "#58a6ff";
  ctx.lineWidth = 2;
  ctx.stroke();

  // X labels (first, middle, last)
  ctx.fillStyle = "#8b97a6";
  [0, Math.floor(pts.length / 2), pts.length - 1].forEach(i => {
    const t = new Date(pts[i].t * 1000).toLocaleTimeString();
    ctx.fillText(t, Math.min(x(i), cssW - 60), cssH - 6);
  });

  // Title
  ctx.fillStyle = "#e6edf3";
  ctx.fillText(lastHistory.metric, pad.l, pad.t - 1);
}

window.addEventListener("resize", drawChart);

// ---- boot ------------------------------------------------------------------

async function boot() {
  await setupMetricSelect();
  await refreshSnapshot();
  await refreshChart();
  await refreshAlerts();
  setInterval(refreshSnapshot, REFRESH_MS);
  setInterval(refreshChart, REFRESH_MS * 2);
  setInterval(refreshAlerts, REFRESH_MS * 2);
}

boot();
