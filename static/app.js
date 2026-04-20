const REFRESH_MS = 5 * 60 * 1000;

let gexChart = null;
let historyChart = null;
let lastData = null;

const fmtMoney = (v) => {
  const abs = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(1)}M`;
  return `${sign}$${abs.toFixed(0)}`;
};
const fmtStrike = (v) => v == null ? "—" : Math.round(v).toLocaleString();
const fmtPct = (v) => v == null ? "—" : `${v.toFixed(0)}th pct`;

async function loadSnapshot(overrideShort, overrideLong) {
  const params = new URLSearchParams();
  if (overrideShort) params.set("short_expiry", overrideShort);
  if (overrideLong) params.set("long_expiry", overrideLong);
  const qs = params.toString() ? `?${params}` : "";
  const res = await fetch(`/api/snapshot${qs}`);
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}

async function loadHistory() {
  const res = await fetch("/api/history");
  if (!res.ok) return { rows: [] };
  return res.json();
}

function renderVerdict(data) {
  const sec = document.getElementById("verdict");
  const pill = document.getElementById("verdict-pill");
  const head = document.getElementById("verdict-headline");
  const reasons = document.getElementById("verdict-reasons");

  sec.classList.remove("loading", "enter", "wait", "avoid");
  sec.classList.add(data.signal.verdict.toLowerCase());
  pill.textContent = data.signal.verdict;
  head.textContent = data.signal.headline;
  reasons.innerHTML = "";
  for (const r of data.signal.reasons) {
    const li = document.createElement("li");
    li.textContent = r;
    reasons.appendChild(li);
  }
}

function renderTiles(data) {
  document.getElementById("tile-spot").textContent = data.spot.toFixed(2);
  const flipStr = data.gex.flip_strike != null
    ? `flip: ${fmtStrike(data.gex.flip_strike)} (${(data.spot - data.gex.flip_strike).toFixed(0).replace(/^-/, "-")} pts ${data.spot >= data.gex.flip_strike ? "above" : "below"})`
    : "flip: —";
  document.getElementById("tile-flip").textContent = flipStr;

  const gexEl = document.getElementById("tile-gex");
  gexEl.textContent = fmtMoney(data.gex.total);
  gexEl.classList.toggle("pos", data.gex.total >= 0);
  gexEl.classList.toggle("neg", data.gex.total < 0);
  document.getElementById("tile-gex-pct").textContent = data.gex.percentile != null
    ? `${fmtPct(data.gex.percentile)} vs last 20d`
    : "percentile: insufficient history";

  const ivEl = document.getElementById("tile-iv");
  if (data.iv_diff) {
    ivEl.textContent = `${data.iv_diff.diff_pts >= 0 ? "+" : ""}${data.iv_diff.diff_pts.toFixed(2)} pts`;
    ivEl.classList.toggle("pos", data.iv_diff.diff_pts >= 0);
    ivEl.classList.toggle("neg", data.iv_diff.diff_pts < 0);
    document.getElementById("tile-iv-detail").textContent =
      `ATM ${fmtStrike(data.iv_diff.atm_strike)}: ${(data.iv_diff.short_iv * 100).toFixed(1)}% @ ${data.iv_diff.short_dte}d vs ${(data.iv_diff.long_iv * 100).toFixed(1)}% @ ${data.iv_diff.long_dte}d  (${data.iv_diff.percentile != null ? fmtPct(data.iv_diff.percentile) : "insufficient history"})`;
  } else {
    ivEl.textContent = "—";
    document.getElementById("tile-iv-detail").textContent = "no ATM quotes";
  }

  const walls = [];
  if (data.gex.call_wall) walls.push(`call ${fmtStrike(data.gex.call_wall)}`);
  if (data.gex.put_wall) walls.push(`put ${fmtStrike(data.gex.put_wall)}`);
  document.getElementById("tile-walls").textContent = walls.length ? walls.join(" / ") : "—";
}

function nearestBinIndex(bins, target) {
  let best = 0, bestDist = Infinity;
  bins.forEach((b, i) => {
    const d = Math.abs(b.strike - target);
    if (d < bestDist) { bestDist = d; best = i; }
  });
  return best;
}

function renderGexChart(data) {
  const ctx = document.getElementById("gex-chart").getContext("2d");
  const bins = data.gex.by_strike;
  const labels = bins.map(p => fmtStrike(p.strike));
  const values = bins.map(p => p.net / 1e9);   // $B per 1%
  const colors = values.map(v => v >= 0 ? "rgba(46,160,67,0.75)" : "rgba(208,69,63,0.75)");

  const spotIdx = nearestBinIndex(bins, data.spot);
  const annos = {
    spot: {
      type: "line", xMin: spotIdx, xMax: spotIdx,
      borderColor: "#4493f8", borderWidth: 2,
      label: { display: true, content: `spot ${data.spot.toFixed(0)}`, position: "start",
               color: "#4493f8", backgroundColor: "rgba(14,17,22,0.8)", font: { size: 11 } },
    },
  };
  if (data.gex.flip_strike) {
    const flipIdx = nearestBinIndex(bins, data.gex.flip_strike);
    annos.flip = {
      type: "line", xMin: flipIdx, xMax: flipIdx,
      borderColor: "#d1a13a", borderWidth: 2, borderDash: [6, 4],
      label: { display: true, content: `flip ${fmtStrike(data.gex.flip_strike)}`, position: "end",
               color: "#d1a13a", backgroundColor: "rgba(14,17,22,0.8)", font: { size: 11 } },
    };
  }

  if (gexChart) gexChart.destroy();
  gexChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [{ label: "Net GEX ($B / 1%)", data: values, backgroundColor: colors, borderWidth: 0 }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      categoryPercentage: 0.95, barPercentage: 0.95,
      scales: {
        x: { title: { display: true, text: `strike (binned ${data.gex.bin_width}pt)`, color: "#8b949e" },
             grid: { display: false }, ticks: { color: "#8b949e", maxRotation: 0, autoSkip: true, maxTicksLimit: 14 } },
        y: { title: { display: true, text: "$B net gamma / 1% move", color: "#8b949e" },
             grid: { color: "#222932" }, ticks: { color: "#8b949e" } },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (items) => `strike bin ${items[0].label}`,
            label: (item) => {
              const p = bins[item.dataIndex];
              return [
                `net: ${fmtMoney(p.net)}`,
                `calls: ${fmtMoney(p.calls)}`,
                `puts: ${fmtMoney(p.puts)}`,
              ];
            },
          },
        },
        annotation: { annotations: annos },
      },
    },
  });
}

function populateExpiryPickers(data) {
  const shortSel = document.getElementById("short-select");
  const longSel = document.getElementById("long-select");
  shortSel.innerHTML = ""; longSel.innerHTML = "";
  for (const e of data.expiry_options.short) {
    const o = document.createElement("option"); o.value = e; o.textContent = e;
    shortSel.appendChild(o);
  }
  for (const e of data.expiry_options.long) {
    const o = document.createElement("option"); o.value = e; o.textContent = e;
    longSel.appendChild(o);
  }
  shortSel.value = data.suggested_trade.short_expiry;
  longSel.value = data.suggested_trade.long_expiry;
  document.getElementById("trade-desc").textContent = data.suggested_trade.description || "—";
}

function renderHistoryChart(rows) {
  const canvas = document.getElementById("history-chart");
  const ctx = canvas.getContext("2d");
  const placeholder = document.getElementById("history-placeholder");
  if (historyChart) { historyChart.destroy(); historyChart = null; }
  if (rows.length < 2) {
    canvas.style.display = "none";
    placeholder.style.display = "block";
    placeholder.textContent = `Need at least 2 daily snapshots for a trend line (have ${rows.length}). Come back tomorrow.`;
    return;
  }
  canvas.style.display = "";
  placeholder.style.display = "none";

  const labels = rows.map(r => r.asof_date);
  const gex = rows.map(r => r.gex_total / 1e9);
  const ivDiff = rows.map(r => r.iv_diff != null ? r.iv_diff * 100 : null);
  historyChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "Net GEX ($B/1%)", data: gex, borderColor: "#4493f8", backgroundColor: "rgba(68,147,248,0.15)", yAxisID: "y", tension: 0.25, pointRadius: 3 },
        { label: "IV diff (pts)", data: ivDiff, borderColor: "#d1a13a", backgroundColor: "rgba(209,161,58,0.15)", yAxisID: "y1", tension: 0.25, pointRadius: 3, spanGaps: true },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { grid: { color: "#222932" }, ticks: { color: "#8b949e" } },
        y: { position: "left", grid: { color: "#222932" }, ticks: { color: "#4493f8" }, title: { display: true, text: "GEX $B", color: "#4493f8" } },
        y1: { position: "right", grid: { drawOnChartArea: false }, ticks: { color: "#d1a13a" }, title: { display: true, text: "IV diff pts", color: "#d1a13a" } },
      },
      plugins: { legend: { labels: { color: "#e6edf3" } } },
    },
  });
}

async function refresh(overrideShort, overrideLong) {
  const btn = document.getElementById("refresh-btn");
  btn.disabled = true; btn.textContent = "Loading…";
  try {
    const data = await loadSnapshot(overrideShort, overrideLong);
    lastData = data;
    document.getElementById("asof").textContent = `as of ${new Date(data.asof).toLocaleString()}`;
    renderVerdict(data);
    renderTiles(data);
    renderGexChart(data);
    populateExpiryPickers(data);

    const hist = await loadHistory();
    renderHistoryChart(hist.rows.slice(-20));
  } catch (e) {
    console.error(e);
    document.getElementById("verdict-headline").textContent = `Error: ${e.message}`;
  } finally {
    btn.disabled = false; btn.textContent = "Refresh";
  }
}

document.getElementById("refresh-btn").addEventListener("click", () => refresh());
document.getElementById("short-select").addEventListener("change", () => {
  const s = document.getElementById("short-select").value;
  const l = document.getElementById("long-select").value;
  refresh(s, l);
});
document.getElementById("long-select").addEventListener("change", () => {
  const s = document.getElementById("short-select").value;
  const l = document.getElementById("long-select").value;
  refresh(s, l);
});

refresh();
setInterval(() => refresh(
  document.getElementById("short-select").value || null,
  document.getElementById("long-select").value || null
), REFRESH_MS);
