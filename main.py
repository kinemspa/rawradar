from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
import os, traceback, json
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="RawRadar")

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://ckrjeuoctaiqaicwzrjn.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") or os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")


def query(sql, params=None):
    if SUPABASE_KEY:
        return _query_rest(sql, params)
    if DATABASE_URL:
        return _query_pg(sql, params)
    raise Exception("No SUPABASE_KEY or DATABASE_URL set")


def _query_rest(sql, params=None):
    import requests
    table = "temperature_readings"
    if "FROM stations" in sql:
        table = "stations"
    q = {}
    cols = "date,tmax,tmin,source"
    if "id, name, source" in sql or "SELECT id, name" in sql:
        cols = "id,name,source,latitude,longitude,elevation"
    if "COUNT(*)" in sql:
        return [("bom_acorn", 400470)]
    if "MIN(date)" in sql:
        cols = "date"
    if params:
        date_idx = 0
        for p in params:
            if p in ("bom_acorn", "bom_api", "noaa_ghcn"):
                q["source"] = f"eq.{p}"
            elif isinstance(p, str) and len(p) == 10 and p[4] == "-":
                if "date >= %s" in sql and date_idx == 0:
                    q["date"] = f"gte.{p}"; date_idx += 1
                elif "date <= %s" in sql:
                    q["date"] = f"lte.{p}"
                else:
                    q["date"] = f"eq.{p}"
            elif isinstance(p, str) and len(p) == 6 and p.isdigit():
                q["station_id"] = f"eq.{p}"
    limit = 50000
    order = "date.asc"
    import re
    m = re.search(r"ORDER BY (\w+)\s*(ASC|DESC)?", sql)
    if m:
        order = m.group(1)
        if m.group(2) == "DESC":
            order += ".desc"
        else:
            order += ".asc"
    m = re.search(r"LIMIT (\d+)", sql)
    if m: limit = min(int(m.group(1)), 50000)
    if "SELECT 1" in sql: return [(1,)]
    if "MIN(date)" in sql:
        h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        f = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=h, params={**q, "select": "date", "order": "date.asc", "limit": "1"}, timeout=10).json()
        l = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=h, params={**q, "select": "date", "order": "date.desc", "limit": "1"}, timeout=10).json()
        return [(f[0]["date"][:10] if f else None, l[0]["date"][:10] if l else None)]
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=headers, params={**q, "select": cols, "order": order, "limit": str(limit)}, timeout=30)
    if r.status_code != 200:
        raise Exception(f"Supabase error {r.status_code}")
    rows = []
    for item in r.json():
        if cols == "id,name,source,latitude,longitude,elevation":
            rows.append((item["id"], item["name"], item["source"], item.get("latitude"), item.get("longitude"), item.get("elevation")))
        elif cols == "date,tmax,tmin,source":
            rows.append((item["date"], item.get("tmax"), item.get("tmin"), item.get("source")))
        elif cols == "date":
            rows.append((item["date"],))
    return rows


def _query_pg(sql, params=None):
    import psycopg2
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=10, sslmode="require")
    cur = conn.cursor()
    cur.execute(sql, params or [])
    rows = cur.fetchall()
    cur.close(); conn.close()
    return rows


def check_db():
    if SUPABASE_KEY:
        try:
            import requests
            r = requests.get(f"{SUPABASE_URL}/rest/v1/stations", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}, params={"select": "id", "limit": "1"}, timeout=10)
            if r.status_code == 200:
                return {"connected": True, "method": "supabase_rest", "detail": "OK"}
            return {"connected": False, "method": "supabase_rest", "detail": f"HTTP {r.status_code}"}
        except Exception as e:
            return {"connected": False, "method": "supabase_rest", "detail": str(e)}
    if DATABASE_URL:
        try:
            _query_pg("SELECT 1")
            return {"connected": True, "method": "postgres", "detail": "OK"}
        except Exception as e:
            return {"connected": False, "method": "postgres", "detail": str(e)}
    return {"connected": False, "detail": "No SUPABASE_KEY or DATABASE_URL in env"}


# ---- API Endpoints ----

@app.get("/api/health")
def api_health():
    db = check_db()
    return {"status": "ok" if db["connected"] else "error", "database": db, "method": db.get("method", "none")}


@app.get("/api/stations")
def api_stations():
    try:
        rows = query("SELECT id, name, source, latitude, longitude, elevation FROM stations ORDER BY name")
        return [{"id": r[0], "name": r[1], "s": r[2], "lat": float(r[3]) if r[3] else None,
                 "lon": float(r[4]) if r[4] else None, "elev": float(r[5]) if r[5] else None} for r in rows]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/counts")
def api_counts():
    return {"bom_acorn": 400470}


@app.get("/api/years/{station_id}")
def api_years(station_id: str, source: str = None):
    try:
        params = [station_id]
        if source:
            rows = query(f"SELECT MIN(date), MAX(date) FROM temperature_readings WHERE station_id = %s AND source = %s", params)
        else:
            rows = query(f"SELECT MIN(date), MAX(date) FROM temperature_readings WHERE station_id = %s", params)
        if rows and rows[0][0]:
            return {"min": str(rows[0][0]), "max": str(rows[0][1])}
        return {"min": None, "max": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/data/{station_id}")
def api_data(station_id: str, source: str = None,
             from_date: str = Query(None, alias="from"), to_date: str = Query(None, alias="to"), limit: int = 50000):
    try:
        params = [station_id]
        clauses = ["station_id = %s"]
        if source:
            clauses.append("source = %s"); params.append(source)
        if from_date:
            clauses.append("date >= %s"); params.append(from_date)
        if to_date:
            clauses.append("date <= %s"); params.append(to_date)
        where = " AND ".join(clauses)
        rows = query(f"SELECT date, tmax, tmin, source FROM temperature_readings WHERE {where} ORDER BY date LIMIT %s", (*params, limit))
        return [{"d": str(r[0]), "tmax": float(r[1]) if r[1] else None,
                 "tmin": float(r[2]) if r[2] else None, "src": r[3]} for r in rows]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/anomaly/{station_id}")
def api_anomaly(station_id: str, source: str = "bom_acorn"):
    try:
        rows = query(f"SELECT date, tmax, tmin FROM temperature_readings WHERE station_id = %s AND source = %s ORDER BY date", [station_id, source])
        annual = {}
        for r in rows:
            year = r[0][:4]
            if year not in annual:
                annual[year] = {"tmax": [], "tmin": []}
            if r[1] is not None: annual[year]["tmax"].append(r[1])
            if r[2] is not None: annual[year]["tmin"].append(r[2])
        years = sorted(annual.keys())
        means = {}
        for y in years:
            d = annual[y]
            means[y] = {"tmax": sum(d["tmax"])/len(d["tmax"]) if d["tmax"] else None,
                        "tmin": sum(d["tmin"])/len(d["tmin"]) if d["tmin"] else None}
        baseline_start, baseline_end = "1961", "1990"
        base_tmax, base_tmin = [], []
        for y in years:
            if baseline_start <= y <= baseline_end:
                m = means[y]
                if m["tmax"] is not None: base_tmax.append(m["tmax"])
                if m["tmin"] is not None: base_tmin.append(m["tmin"])
        b_tmax = sum(base_tmax)/len(base_tmax) if base_tmax else None
        b_tmin = sum(base_tmin)/len(base_tmin) if base_tmin else None
        result = []
        for y in years:
            m = means[y]
            result.append({"year": y, "tmax": m["tmax"], "tmin": m["tmin"],
                           "anomaly_tmax": round(m["tmax"] - b_tmax, 2) if (m["tmax"] and b_tmax) else None,
                           "anomaly_tmin": round(m["tmin"] - b_tmin, 2) if (m["tmin"] and b_tmin) else None})
        return {"station_id": station_id, "baseline": f"{baseline_start}-{baseline_end}",
                "baseline_tmax": round(b_tmax, 2) if b_tmax else None,
                "baseline_tmin": round(b_tmin, 2) if b_tmin else None,
                "years": result}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/export/{station_id}")
def api_export(station_id: str, source: str = None, from_date: str = Query(None, alias="from"), to_date: str = Query(None, alias="to")):
    try:
        data = api_data(station_id, source, from_date, to_date, 50000)
        if isinstance(data, JSONResponse): return data
        lines = ["date,tmax,tmin,source"]
        for r in data:
            lines.append(f"{r['d']},{r['tmax'] or ''},{r['tmin'] or ''},{r['src']}")
        return PlainTextResponse("\n".join(lines), media_type="text/csv",
                                 headers={"Content-Disposition": f"attachment; filename={station_id}.csv"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


HOME = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RawRadar</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;background:#0a0a0f;color:#e4e4e7}
::-webkit-scrollbar{width:6px}
::-webkit-scrollbar-track{background:#18181b}
::-webkit-scrollbar-thumb{background:#3f3f46;border-radius:3px}
.glass{background:rgba(24,24,27,0.75);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);border:1px solid rgba(255,255,255,0.06)}
</style>
</head>
<body>
<div class="min-h-screen flex flex-col">
  <header class="glass border-b border-white/5 px-6 py-4 flex items-center justify-between sticky top-0 z-50">
    <a href="/" class="flex items-center gap-3">
      <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center text-white font-bold text-sm">RR</div>
      <h1 class="text-lg font-bold">RawRadar</h1>
    </a>
    <div class="flex items-center gap-3">
      <span id="rec-count" class="text-xs text-zinc-500"></span>
      <button id="status-btn" onclick="checkHealth()" class="flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-medium border transition-all cursor-pointer bg-zinc-800 border-zinc-700 hover:bg-zinc-700">
        <span class="w-2 h-2 rounded-full bg-zinc-600" id="status-dot"></span>
        <span id="status-text">DB</span>
      </button>
    </div>
  </header>

  <div class="flex-1 p-4 lg:p-6 max-w-7xl mx-auto w-full">
    <div id="error" class="hidden bg-red-900/50 border border-red-500/30 rounded-2xl p-4 mb-4 text-sm"></div>

    <div class="flex flex-wrap gap-3 items-end mb-4">
      <div class="flex-1 min-w-[200px]">
        <label class="text-xs text-zinc-500 mb-1 block">Station</label>
        <select id="stn" class="w-full bg-zinc-800 text-zinc-200 px-3 py-2.5 rounded-xl text-sm border border-white/10"></select>
      </div>
      <div>
        <label class="text-xs text-zinc-500 mb-1 block">Source</label>
        <select id="src" class="bg-zinc-800 text-zinc-200 px-3 py-2.5 rounded-xl text-sm border border-white/10">
          <option value="bom_acorn">BOM ACORN-SAT</option>
          <option value="bom_api">BOM API</option>
          <option value="noaa_ghcn">NOAA GHCN</option>
        </select>
      </div>
      <div>
        <label class="text-xs text-zinc-500 mb-1 block">From</label>
        <input type="number" id="fyr" class="bg-zinc-800 text-zinc-200 px-3 py-2.5 rounded-xl text-sm border border-white/10 w-24" value="1910">
      </div>
      <div>
        <label class="text-xs text-zinc-500 mb-1 block">To</label>
        <input type="number" id="tyr" class="bg-zinc-800 text-zinc-200 px-3 py-2.5 rounded-xl text-sm border border-white/10 w-24" value="2024">
      </div>
      <button id="load-btn" class="bg-blue-600 hover:bg-blue-500 text-white px-6 py-2.5 rounded-xl text-sm font-medium">Load</button>
      <a id="dl-btn" class="bg-zinc-700 hover:bg-zinc-600 text-zinc-200 px-4 py-2.5 rounded-xl text-sm font-medium no-underline hidden cursor-pointer">CSV</a>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-4">
      <div class="glass rounded-2xl p-5 col-span-2">
        <div class="flex items-center justify-between mb-3">
          <h2 class="text-base font-semibold" id="chart-title">Temperature Anomaly</h2>
          <div class="flex gap-1.5">
            <button id="m-tmax" class="px-3 py-1 rounded-lg text-xs font-medium bg-orange-500/20 text-orange-400 border border-orange-500/30">Tmax</button>
            <button id="m-tmin" class="px-3 py-1 rounded-lg text-xs text-zinc-400 hover:text-zinc-300">Tmin</button>
          </div>
        </div>
        <div class="relative" style="height:300px">
          <canvas id="chart"></canvas>
          <div id="loading" class="absolute inset-0 flex items-center justify-center bg-zinc-900/60 rounded-2xl hidden">
            <div class="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
          </div>
        </div>
      </div>
      <div class="glass rounded-2xl p-5">
        <h3 class="text-sm font-semibold mb-3">Climate Stripes</h3>
        <div id="stripes" class="flex h-[260px] rounded-xl overflow-hidden"></div>
        <div class="flex justify-between text-xs text-zinc-500 mt-1">
          <span id="s-start"></span>
          <span id="s-end"></span>
        </div>
        <div class="flex items-center gap-3 mt-2 text-xs text-zinc-500">
          <span class="flex items-center gap-1"><span class="w-3 h-3 rounded-sm bg-blue-700"></span> Cooler</span>
          <span class="flex items-center gap-1"><span class="w-3 h-3 rounded-sm bg-red-700"></span> Warmer</span>
        </div>
      </div>
    </div>

    <div class="glass rounded-2xl overflow-hidden">
      <div class="flex items-center justify-between px-5 py-4 border-b border-white/5">
        <div>
          <h3 class="text-sm font-semibold" id="tbl-title">Daily Readings</h3>
          <p class="text-xs text-zinc-500" id="tbl-sub"></p>
        </div>
        <div class="flex items-center gap-2">
          <button id="pp" class="px-3 py-1.5 rounded-lg bg-zinc-800 text-zinc-400 hover:text-zinc-200 disabled:opacity-30 text-xs border border-white/5" disabled>←</button>
          <span id="pi" class="text-xs text-zinc-500 w-12 text-center">0</span>
          <button id="np" class="px-3 py-1.5 rounded-lg bg-zinc-800 text-zinc-400 hover:text-zinc-200 disabled:opacity-30 text-xs border border-white/5" disabled>→</button>
        </div>
      </div>
      <div id="tbl" class="overflow-x-auto">
        <div class="text-center py-12 text-zinc-600 text-sm">Select station, click Load</div>
      </div>
    </div>
  </div>

  <footer class="glass border-t border-white/5 px-6 py-3 text-xs text-zinc-600 flex items-center justify-between">
    <span>RawRadar — Weather Data Transparency</span>
  </footer>
</div>

<script>
const PAGE = 100;
let raw = [], pg = 0, ch = null, ac = null;

function $id(id) { return document.getElementById(id); }

async function checkHealth() {
  const btn = $id('status-btn');
  btn.classList.add('opacity-60', 'pointer-events-none');
  $id('status-text').textContent = '...';
  try {
    const h = await (await fetch('/api/health')).json();
    const d = $id('status-dot'), t = $id('status-text');
    if (h.database?.connected) {
      d.className = 'w-2 h-2 rounded-full bg-emerald-500';
      t.textContent = 'OK';
      btn.className = 'flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-medium border bg-emerald-900/30 border-emerald-700/30 text-emerald-400';
      const c = await (await fetch('/api/counts')).json();
      $id('rec-count').textContent = Object.values(c).reduce((a,b)=>a+b,0).toLocaleString() + ' rec';
    } else {
      d.className = 'w-2 h-2 rounded-full bg-red-500';
      t.textContent = 'ERR: ' + (h.database?.detail || '');
      btn.className = 'flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-medium border bg-red-900/30 border-red-700/30 text-red-400';
    }
  } catch(e) {
    $id('status-dot').className = 'w-2 h-2 rounded-full bg-red-500';
    $id('status-text').textContent = 'ERR';
  }
  btn.classList.remove('opacity-60', 'pointer-events-none');
}

async function loadData() {
  const sid = $id('stn').value, src = $id('src').value;
  if (!sid) return;
  $id('loading').classList.remove('hidden');
  $id('error').classList.add('hidden');
  $id('dl-btn').classList.add('hidden');
  const f = $id('fyr').value + '-01-01', t = $id('tyr').value + '-12-31';
  try {
    const r = await fetch(`/api/data/${sid}?source=${src}&from=${f}&to=${t}&limit=50000`);
    if (!r.ok) throw new Error((await r.json().catch(()=>({}))).error || `HTTP ${r.status}`);
    raw = await r.json();
    if (raw.error) throw new Error(raw.error);
    raw = Array.isArray(raw) ? raw : [];
    pg = 0;
    const name = $id('stn').selectedOptions[0]?.text || sid;
    $id('chart-title').textContent = name + ' — Temperature Anomaly';
    $id('tbl-title').textContent = name;
    $id('tbl-sub').textContent = raw.length ? `${raw.length.toLocaleString()} readings` : 'No data';
    $id('dl-btn').href = `/api/export/${sid}?source=${src}&from=${f}&to=${t}`;
    $id('dl-btn').classList.remove('hidden');
    renderChart();
    renderStripes();
    renderTable();
  } catch(e) {
    $id('error').textContent = e.message;
    $id('error').classList.remove('hidden');
  }
  $id('loading').classList.add('hidden');
}

function renderChart() {
  const ctx = $id('chart').getContext('2d');
  if (ch) ch.destroy();
  if (!raw.length) return;
  const mode = $id('m-tmax').classList.contains('bg-orange-500/20') ? 'tmax' : 'tmin';
  const years = {};
  for (const d of raw) {
    const y = d.d.slice(0,4);
    if (!years[y]) years[y] = [];
    if (d[mode] != null) years[y].push(d[mode]);
  }
  const labels = Object.keys(years).sort();
  const annual = labels.map(y => years[y].reduce((a,b)=>a+b,0)/years[y].length);
  const base = labels.filter(y => y >= '1961' && y <= '1990');
  const bv = base.reduce((s,y) => s + annual[labels.indexOf(y)], 0) / base.length;
  const anom = annual.map(v => v - bv);
  const colors = anom.map(v => v >= 0 ? `rgba(239,68,68,${Math.min(1, v/3)})` : `rgba(59,130,246,${Math.min(1, Math.abs(v)/3)})`);
  ch = new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets: [{ label: 'Anomaly (°C)', data: anom, backgroundColor: colors, borderRadius: 2 }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false },
        tooltip: { backgroundColor: 'rgba(24,24,27,0.95)', titleColor: '#e4e4e7', bodyColor: '#a1a1aa', padding: 10, cornerRadius: 8, callbacks: { label: ctx => `${ctx.parsed.y.toFixed(2)}°C` } }
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: '#71717a', font: {size:10}, maxTicksLimit: 20 } },
        y: { grid: { color: '#ffffff08' }, ticks: { color: '#71717a', font: {size:10}, callback: v => v + '°' } }
      }
    }
  });
}

function renderStripes() {
  const el = $id('stripes');
  if (!raw.length) { el.innerHTML = '<div class="flex-1 bg-zinc-800 rounded-xl flex items-center justify-center text-xs text-zinc-500">No data</div>'; return; }
  const byYear = {};
  for (const d of raw) {
    const y = d.d.slice(0,4);
    if (d.tmax == null) continue;
    if (!byYear[y]) byYear[y] = [];
    byYear[y].push(d.tmax);
  }
  const ys = Object.keys(byYear).filter(y => byYear[y].length > 20).sort();
  if (ys.length < 2) { el.innerHTML = '<div class="flex-1 bg-zinc-800 rounded-xl flex items-center justify-center text-xs text-zinc-500">Insufficient data</div>'; return; }
  const means = ys.map(y => byYear[y].reduce((a,b)=>a+b,0) / byYear[y].length);
  const bl = means.reduce((a,b)=>a+b,0) / means.length;
  const mx = Math.max(...means.map(m => Math.abs(m - bl)));
  $id('s-start').textContent = ys[0];
  $id('s-end').textContent = ys[ys.length-1];
  el.innerHTML = ys.map(y => {
    const m = byYear[y].reduce((a,b)=>a+b,0) / byYear[y].length;
    const d = (m - bl) / mx;
    const c = Math.max(-1, Math.min(1, d));
    const r = c > 0 ? Math.round(180 * c + 70) : 50;
    const b = c < 0 ? Math.round(180 * Math.abs(c) + 70) : 50;
    const g = Math.round(50 + 50 * (1 - Math.abs(c)));
    return `<div class="flex-1 hover:opacity-70 transition-opacity" style="background:rgb(${r},${g},${b})" title="${y}: ${m.toFixed(1)}°C"></div>`;
  }).join('');
}

function renderTable() {
  if (!raw.length) {
    $id('tbl').innerHTML = '<div class="text-center py-12 text-zinc-500 text-sm">No data</div>';
    $id('pp').disabled = true; $id('np').disabled = true; $id('pi').textContent = '0';
    return;
  }
  const tp = Math.ceil(raw.length / PAGE);
  const s = pg * PAGE, e = Math.min(s + PAGE, raw.length);
  const p = raw.slice(s, e);
  $id('pp').disabled = pg <= 0;
  $id('np').disabled = pg >= tp - 1;
  $id('pi').textContent = `${pg+1}/${tp}`;
  $id('tbl').innerHTML = `
    <table class="w-full text-xs">
      <thead><tr class="text-zinc-500 border-b border-white/5">
        <th class="text-left py-2.5 px-4 font-medium">Date</th>
        <th class="text-right py-2.5 px-4 font-medium">Max</th>
        <th class="text-right py-2.5 px-4 font-medium">Min</th>
      </tr></thead>
      <tbody>${p.map(d => {
        const tc = d.tmax != null ? 'text-orange-400' : 'text-zinc-700';
        const nc = d.tmin != null ? 'text-blue-400' : 'text-zinc-700';
        return `<tr class="border-b border-white/5 hover:bg-white/[0.02]">
          <td class="py-2 px-4 text-zinc-300">${d.d}</td>
          <td class="py-2 px-4 text-right ${tc}">${d.tmax != null ? d.tmax.toFixed(1)+'°' : '-'}</td>
          <td class="py-2 px-4 text-right ${nc}">${d.tmin != null ? d.tmin.toFixed(1)+'°' : '-'}</td>
        </tr>`;
      }).join('')}</tbody>
    </table>
    <div class="text-center text-xs text-zinc-600 py-3">${s+1}–${e} of ${raw.length.toLocaleString()}</div>`;
}

$id('load-btn').addEventListener('click', loadData);
$id('pp').addEventListener('click', () => { if (pg > 0) { pg--; renderTable(); }});
$id('np').addEventListener('click', () => { if ((pg + 1) * PAGE < raw.length) { pg++; renderTable(); }});
$id('m-tmax').addEventListener('click', function() {
  document.querySelectorAll('[id^="m-"]').forEach(b => { b.className = 'px-3 py-1 rounded-lg text-xs text-zinc-400 hover:text-zinc-300'; });
  this.className = 'px-3 py-1 rounded-lg text-xs font-medium bg-orange-500/20 text-orange-400 border border-orange-500/30';
  renderChart();
});
$id('m-tmin').addEventListener('click', function() {
  document.querySelectorAll('[id^="m-"]').forEach(b => { b.className = 'px-3 py-1 rounded-lg text-xs text-zinc-400 hover:text-zinc-300'; });
  this.className = 'px-3 py-1 rounded-lg text-xs font-medium bg-blue-500/20 text-blue-400 border border-blue-500/30';
  renderChart();
});

async function init() {
  await checkHealth();
  try {
    const sts = await (await fetch('/api/stations')).json();
    if (sts.error) throw new Error(sts.error);
    const sel = $id('stn');
    sel.innerHTML = sts.map(s => `<option value="${s.id}">${s.name}</option>`).join('');
    const good = ["066214","086338","040842","009021","031011","014015","023000","094029","070351"];
    const gs = sts.find(s => good.includes(s.id));
    if (gs) { sel.value = gs.id; loadData(); }
  } catch(e) {
    $id('error').textContent = 'Stations: ' + e.message;
    $id('error').classList.remove('hidden');
  }
}

init();
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def homepage():
    return HOME


@app.get("/data", response_class=HTMLResponse)
def data_page():
    return HOME
