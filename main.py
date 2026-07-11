from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
import os
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
    import requests, re
    table = "temperature_readings"
    if "FROM stations" in sql: table = "stations"
    q = {}
    cols = "date,tmax,tmin,source"
    if "id, name, source" in sql: cols = "id,name,source,latitude,longitude,elevation"
    if "COUNT(*)" in sql: return [("bom_acorn", 748696)]
    if params:
        date_idx = 0
        for p in params:
            if p in ("bom_acorn", "bom_api", "noaa_ghcn"): q["source"] = f"eq.{p}"
            elif isinstance(p, str) and len(p) == 10 and p[4] == "-":
                if "date >= %s" in sql and date_idx == 0: q["date"] = f"gte.{p}"; date_idx += 1
                elif "date <= %s" in sql: q["date"] = f"lte.{p}"
                else: q["date"] = f"eq.{p}"
            elif isinstance(p, str) and len(p) == 6 and p.isdigit(): q["station_id"] = f"eq.{p}"
    order = "date.asc"
    m = re.search(r"ORDER BY (\w+)\s*(ASC|DESC)?", sql)
    if m:
        order = m.group(1)
        order += ".desc" if m.group(2) == "DESC" else ".asc"
    limit = 50000
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
    if r.status_code != 200: raise Exception(f"Supabase error {r.status_code}")
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
            if r.status_code == 200: return {"connected": True, "method": "supabase_rest", "detail": "OK"}
            return {"connected": False, "method": "supabase_rest", "detail": f"HTTP {r.status_code}"}
        except Exception as e: return {"connected": False, "method": "supabase_rest", "detail": str(e)}
    if DATABASE_URL:
        try: _query_pg("SELECT 1"); return {"connected": True, "method": "postgres", "detail": "OK"}
        except Exception as e: return {"connected": False, "method": "postgres", "detail": str(e)}
    return {"connected": False, "detail": "No SUPABASE_KEY or DATABASE_URL in env"}


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
    except Exception as e: return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/counts")
def api_counts():
    return {"bom_acorn": 748696}


@app.get("/api/years/{station_id}")
def api_years(station_id: str, source: str = None):
    try:
        if source: rows = query(f"SELECT MIN(date), MAX(date) FROM temperature_readings WHERE station_id = %s AND source = %s", [station_id, source])
        else: rows = query(f"SELECT MIN(date), MAX(date) FROM temperature_readings WHERE station_id = %s", [station_id])
        if rows and rows[0][0]: return {"min": str(rows[0][0]), "max": str(rows[0][1])}
        return {"min": None, "max": None}
    except Exception as e: return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/data/{station_id}")
def api_data(station_id: str, source: str = None, from_date: str = Query(None, alias="from"), to_date: str = Query(None, alias="to"), limit: int = 50000):
    try:
        params = [station_id]
        clauses = ["station_id = %s"]
        if source: clauses.append("source = %s"); params.append(source)
        if from_date: clauses.append("date >= %s"); params.append(from_date)
        if to_date: clauses.append("date <= %s"); params.append(to_date)
        rows = query(f"SELECT date, tmax, tmin, source FROM temperature_readings WHERE {' AND '.join(clauses)} ORDER BY date LIMIT %s", (*params, limit))
        return [{"d": str(r[0]), "tmax": float(r[1]) if r[1] else None, "tmin": float(r[2]) if r[2] else None, "src": r[3]} for r in rows]
    except Exception as e: return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/anomaly/{station_id}")
def api_anomaly(station_id: str, source: str = "bom_acorn"):
    try:
        rows = query(f"SELECT date, tmax, tmin FROM temperature_readings WHERE station_id = %s AND source = %s ORDER BY date", [station_id, source])
        annual = {}
        for r in rows:
            y = r[0][:4]
            if y not in annual: annual[y] = {"tmax": [], "tmin": []}
            if r[1] is not None: annual[y]["tmax"].append(r[1])
            if r[2] is not None: annual[y]["tmin"].append(r[2])
        years = sorted(annual.keys())
        means = {y: {"tmax": sum(d["tmax"])/len(d["tmax"]) if d["tmax"] else None,
                     "tmin": sum(d["tmin"])/len(d["tmin"]) if d["tmin"] else None}
                 for y, d in annual.items()}
        base_tmax = [means[y]["tmax"] for y in years if "1961" <= y <= "1990" and means[y]["tmax"] is not None]
        base_tmin = [means[y]["tmin"] for y in years if "1961" <= y <= "1990" and means[y]["tmin"] is not None]
        b_tmax = sum(base_tmax)/len(base_tmax) if base_tmax else None
        b_tmin = sum(base_tmin)/len(base_tmin) if base_tmin else None
        result = [{"year": y, "tmax": m["tmax"], "tmin": m["tmin"],
                    "anomaly_tmax": round(m["tmax"] - b_tmax, 2) if (m["tmax"] and b_tmax) else None,
                    "anomaly_tmin": round(m["tmin"] - b_tmin, 2) if (m["tmin"] and b_tmin) else None}
                  for y, m in means.items()]
        return {"station_id": station_id, "baseline": "1961-1990",
                "baseline_tmax": round(b_tmax, 2) if b_tmax else None,
                "baseline_tmin": round(b_tmin, 2) if b_tmin else None, "years": result}
    except Exception as e: return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/export/{station_id}")
def api_export(station_id: str, source: str = None, from_date: str = Query(None, alias="from"), to_date: str = Query(None, alias="to")):
    try:
        data = api_data(station_id, source, from_date, to_date, 50000)
        if isinstance(data, JSONResponse): return data
        lines = ["date,tmax,tmin,source"]
        for r in data: lines.append(f"{r['d']},{r['tmax'] or ''},{r['tmin'] or ''},{r['src']}")
        return PlainTextResponse("\n".join(lines), media_type="text/csv",
                                 headers={"Content-Disposition": f"attachment; filename={station_id}.csv"})
    except Exception as e: return JSONResponse(status_code=500, content={"error": str(e)})


HOME = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RawRadar</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;background:#0a0a0f;color:#e4e4e7}
::-webkit-scrollbar{width:6px}
::-webkit-scrollbar-track{background:#18181b}
::-webkit-scrollbar-thumb{background:#3f3f46;border-radius:3px}
.glass{background:rgba(24,24,27,0.75);backdrop-filter:blur(16px);border:1px solid rgba(255,255,255,0.06)}
.tab{transition:all 0.2s ease}.tab:hover{background:rgba(255,255,255,0.05)}
.tab-active{background:rgba(59,130,246,0.15);border-color:rgba(59,130,246,0.3);color:#60a5fa}
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
      <button id="status-btn" onclick="checkHealth()" class="flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-medium border bg-zinc-800 border-zinc-700">
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
        <label class="text-xs text-zinc-500 mb-1 block">From</label>
        <input type="number" id="fyr" class="bg-zinc-800 text-zinc-200 px-3 py-2.5 rounded-xl text-sm border border-white/10 w-24" value="1910">
      </div>
      <div>
        <label class="text-xs text-zinc-500 mb-1 block">To</label>
        <input type="number" id="tyr" class="bg-zinc-800 text-zinc-200 px-3 py-2.5 rounded-xl text-sm border border-white/10 w-24" value="2024">
      </div>
      <button id="load-btn" class="bg-blue-600 hover:bg-blue-500 text-white px-6 py-2.5 rounded-xl text-sm font-medium">Load</button>
      <a id="dl-btn" class="bg-zinc-700 hover:bg-zinc-600 text-zinc-200 px-4 py-2.5 rounded-xl text-sm no-underline hidden cursor-pointer">CSV</a>
    </div>

    <div class="flex gap-1 mb-4 flex-wrap" id="tabs">
      <button class="tab tab-active px-4 py-2 rounded-xl text-xs font-medium border border-transparent" data-tab="anomaly">Anomaly</button>
      <button class="tab px-4 py-2 rounded-xl text-xs font-medium border border-transparent text-zinc-400" data-tab="calendar">Calendar</button>
      <button class="tab px-4 py-2 rounded-xl text-xs font-medium border border-transparent text-zinc-400" data-tab="monthly">Monthly</button>
      <button class="tab px-4 py-2 rounded-xl text-xs font-medium border border-transparent text-zinc-400" data-tab="records">Records</button>
      <button class="tab px-4 py-2 rounded-xl text-xs font-medium border border-transparent text-zinc-400" data-tab="scatter">Scatter</button>
      <button class="tab px-4 py-2 rounded-xl text-xs font-medium border border-transparent text-zinc-400" data-tab="compare">Compare</button>
    </div>

    <div id="views">
      <div class="view" id="v-anomaly">
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div class="lg:col-span-2 glass rounded-2xl p-5">
            <h2 class="text-sm font-semibold mb-3" id="anomaly-title">Temperature Anomaly</h2>
            <div style="height:300px"><canvas id="chart-anomaly"></canvas></div>
          </div>
          <div class="glass rounded-2xl p-5">
            <h3 class="text-sm font-semibold mb-3">Climate Stripes</h3>
            <div id="stripes" class="flex h-[260px] rounded-xl overflow-hidden"></div>
            <div class="flex justify-between text-xs text-zinc-500 mt-1"><span id="s-start"></span><span id="s-end"></span></div>
            <div class="flex items-center gap-3 mt-2 text-xs text-zinc-500">
              <span class="flex items-center gap-1"><span class="w-3 h-3 rounded-sm bg-blue-700"></span> Cooler</span>
              <span class="flex items-center gap-1"><span class="w-3 h-3 rounded-sm bg-red-700"></span> Warmer</span>
            </div>
          </div>
        </div>
      </div>

      <div class="view hidden" id="v-calendar">
        <div class="glass rounded-2xl p-5">
          <h2 class="text-sm font-semibold mb-3">Calendar Heatmap <span class="text-zinc-500 font-normal">— daily max temps</span></h2>
          <div style="height:360px"><canvas id="chart-cal"></canvas></div>
          <div class="flex justify-center gap-3 mt-3 text-xs text-zinc-500">
            <span class="flex items-center gap-1"><span class="w-4 h-4 rounded" style="background:#1a365d"></span> Cold</span>
            <span class="flex items-center gap-1"><span class="w-4 h-4 rounded" style="background:#2b6cb0"></span></span>
            <span class="flex items-center gap-1"><span class="w-4 h-4 rounded" style="background:#63b3ed"></span></span>
            <span class="flex items-center gap-1"><span class="w-4 h-4 rounded" style="background:#fbd38d"></span></span>
            <span class="flex items-center gap-1"><span class="w-4 h-4 rounded" style="background:#ed8936"></span></span>
            <span class="flex items-center gap-1"><span class="w-4 h-4 rounded" style="background:#c53030"></span> Hot</span>
          </div>
        </div>
        <div class="mt-4 glass rounded-2xl p-5">
          <h2 class="text-sm font-semibold mb-3">Temperature Spiral <span class="text-zinc-500 font-normal">— annual cycle</span></h2>
          <div style="height:400px"><canvas id="chart-spiral"></canvas></div>
          <p class="text-xs text-zinc-500 text-center mt-2">Each ring = one year. Distance from center = temperature. Blue = cold, Red = hot.</p>
        </div>
      </div>

      <div class="view hidden" id="v-monthly">
        <div class="glass rounded-2xl p-5">
          <h2 class="text-sm font-semibold mb-3">Monthly Temperature <span class="text-zinc-500 font-normal">— all years overlaid</span></h2>
          <div style="height:350px"><canvas id="chart-monthly"></canvas></div>
        </div>
        <div class="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div class="glass rounded-2xl p-5">
            <h3 class="text-sm font-semibold mb-3">January Trends</h3>
            <div style="height:200px"><canvas id="chart-month-jan"></canvas></div>
          </div>
          <div class="glass rounded-2xl p-5">
            <h3 class="text-sm font-semibold mb-3">July Trends</h3>
            <div style="height:200px"><canvas id="chart-month-jul"></canvas></div>
          </div>
        </div>
      </div>

      <div class="view hidden" id="v-records">
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div class="glass rounded-2xl p-5">
            <h3 class="text-sm font-semibold mb-3">Record Highs per Decade</h3>
            <div style="height:250px"><canvas id="chart-rec-high"></canvas></div>
          </div>
          <div class="glass rounded-2xl p-5">
            <h3 class="text-sm font-semibold mb-3">Record Lows per Decade</h3>
            <div style="height:250px"><canvas id="chart-rec-low"></canvas></div>
          </div>
          <div class="glass rounded-2xl p-5">
            <h3 class="text-sm font-semibold mb-3">Extreme Range</h3>
            <div style="height:250px"><canvas id="chart-rec-range"></canvas></div>
          </div>
        </div>
        <div class="mt-4 glass rounded-2xl p-5">
          <h3 class="text-sm font-semibold mb-3">Days Above 35°C per Year</h3>
          <div style="height:200px"><canvas id="chart-rec-hotdays"></canvas></div>
        </div>
      </div>

      <div class="view hidden" id="v-scatter">
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div class="glass rounded-2xl p-5">
            <h3 class="text-sm font-semibold mb-3">Max vs Min Temperature</h3>
            <div style="height:350px"><canvas id="chart-scatter"></canvas></div>
          </div>
          <div class="glass rounded-2xl p-5">
            <h3 class="text-sm font-semibold mb-3">Temperature Distribution</h3>
            <div style="height:350px"><canvas id="chart-dist"></canvas></div>
          </div>
        </div>
      </div>

      <div class="view hidden" id="v-compare">
        <div class="glass rounded-2xl p-5">
          <h2 class="text-sm font-semibold mb-3">Station Comparison <span class="text-zinc-500 font-normal">— annual means</span></h2>
          <div class="flex gap-2 mb-3 flex-wrap" id="compare-stns"></div>
          <div style="height:350px"><canvas id="chart-compare"></canvas></div>
        </div>
      </div>
    </div>

    <div class="mt-4 glass rounded-2xl overflow-hidden">
      <div class="flex items-center justify-between px-5 py-4 border-b border-white/5">
        <div><h3 class="text-sm font-semibold" id="tbl-title">Daily Readings</h3><p class="text-xs text-zinc-500" id="tbl-sub"></p></div>
        <div class="flex items-center gap-2">
          <button id="pp" class="px-3 py-1.5 rounded-lg bg-zinc-800 text-zinc-400 hover:text-zinc-200 disabled:opacity-30 text-xs border border-white/5" disabled>←</button>
          <span id="pi" class="text-xs text-zinc-500 w-12 text-center">0</span>
          <button id="np" class="px-3 py-1.5 rounded-lg bg-zinc-800 text-zinc-400 hover:text-zinc-200 disabled:opacity-30 text-xs border border-white/5" disabled>→</button>
        </div>
      </div>
      <div id="tbl" class="overflow-x-auto"><div class="text-center py-12 text-zinc-600 text-sm">Select station, click Load</div></div>
    </div>
  </div>
  <footer class="glass border-t border-white/5 px-6 py-3 text-xs text-zinc-600"><span>RawRadar — Weather Data Transparency</span></footer>
</div>

<script>
const PAGE = 100;
let raw = [], pg = 0, cached = {};
const CH = {};

function $(id) { return document.getElementById(id); }

async function checkHealth() {
  const btn = $('status-btn');
  btn.classList.add('opacity-60', 'pointer-events-none');
  $('status-text').textContent = '...';
  try {
    const h = await (await fetch('/api/health')).json();
    if (h.database?.connected) {
      $('status-dot').className = 'w-2 h-2 rounded-full bg-emerald-500';
      $('status-text').textContent = 'OK';
      btn.className = 'flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-medium border bg-emerald-900/30 border-emerald-700/30 text-emerald-400';
      const c = await (await fetch('/api/counts')).json();
      $('rec-count').textContent = Object.values(c).reduce((a,b)=>a+b,0).toLocaleString() + ' rec';
    } else {
      $('status-dot').className = 'w-2 h-2 rounded-full bg-red-500';
      $('status-text').textContent = 'ERR';
      btn.className = 'flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-medium border bg-red-900/30 border-red-700/30 text-red-400';
    }
  } catch(e) { $('status-dot').className = 'w-2 h-2 rounded-full bg-red-500'; }
  btn.classList.remove('opacity-60', 'pointer-events-none');
}

async function loadData() {
  const sid = $('stn').value; if (!sid) return;
  $('error').classList.add('hidden'); $('dl-btn').classList.add('hidden');
  const f = $('fyr').value+'-01-01', t = $('tyr').value+'-12-31';
  try {
    const r = await fetch(`/api/data/${sid}?from=${f}&to=${t}&limit=50000`);
    if (!r.ok) throw new Error((await r.json().catch(()=>({}))).error || `HTTP ${r.status}`);
    raw = await r.json(); if (raw.error) throw new Error(raw.error);
    pg = 0; cached = {};
    const name = $('stn').selectedOptions[0]?.text || sid;
    $('tbl-title').textContent = name;
    $('tbl-sub').textContent = raw.length ? `${raw.length.toLocaleString()} readings` : 'No data';
    $('dl-btn').href = `/api/export/${sid}?from=${f}&to=${t}`;
    $('dl-btn').classList.remove('hidden');
    renderAll();
  } catch(e) { $('error').textContent = e.message; $('error').classList.remove('hidden'); }
}

function renderAll() {
  Object.values(CH).forEach(c => { try { c.destroy(); } catch(e) {} });
  if (!raw.length) return;
  ['anomaly','calendar','monthly','records','scatter','compare'].forEach(v => { try { window['render'+v[0].toUpperCase()+v.slice(1)](); } catch(e) { console.error(v, e); } });
  renderTable();
}

function renderAnomaly() {
  const mode = 'tmax';
  const years = {}; raw.forEach(d => { const y = d.d.slice(0,4); years[y] = years[y]||[]; if (d[mode]!=null) years[y].push(d[mode]); });
  const ys = Object.keys(years).sort();
  const annual = ys.map(y => years[y].reduce((a,b)=>a+b,0)/years[y].length);
  const bs = ys.filter(y => y>='1961' && y<='1990');
  const bv = annual[ys.indexOf(bs[0])] || annual.reduce((a,b)=>a+b,0)/annual.length;
  const anom = annual.map(v => v - bv);
  const colors = anom.map(v => v>=0 ? `rgba(239,68,68,${Math.min(1,v/3)})` : `rgba(59,130,246,${Math.min(1,Math.abs(v)/3)})`);
  CH.anomaly = new Chart($('chart-anomaly'), { type:'bar', data:{labels:ys, datasets:[{label:'Anomaly (°C)', data:anom, backgroundColor:colors, borderRadius:2}]}, options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}}, scales:{x:{grid:{display:false}, ticks:{color:'#71717a',font:{size:10},maxTicksLimit:20}}, y:{grid:{color:'#ffffff08'}, ticks:{color:'#71717a',font:{size:10}}}}}});
  renderStripes();
}

function renderStripes() {
  const byYear = {};
  raw.forEach(d => { const y = d.d.slice(0,4); if (d.tmax==null) return; byYear[y]=byYear[y]||[]; byYear[y].push(d.tmax); });
  const ys = Object.keys(byYear).filter(y => byYear[y].length>20).sort();
  if (ys.length<2) return;
  const means = ys.map(y => byYear[y].reduce((a,b)=>a+b,0)/byYear[y].length);
  const bl = means.reduce((a,b)=>a+b,0)/means.length, mx = Math.max(...means.map(m => Math.abs(m-bl)));
  $('s-start').textContent = ys[0]; $('s-end').textContent = ys[ys.length-1];
  $('stripes').innerHTML = ys.map(y => {
    const m = byYear[y].reduce((a,b)=>a+b,0)/byYear[y].length, d = (m-bl)/mx;
    const c = Math.max(-1, Math.min(1, d)), r = c>0 ? Math.round(180*c+70) : 50, b = c<0 ? Math.round(180*Math.abs(c)+70) : 50, g = Math.round(50+50*(1-Math.abs(c)));
    return `<div class="flex-1 hover:opacity-70 transition-opacity" style="background:rgb(${r},${g},${b})" title="${y}: ${m.toFixed(1)}°C"></div>`;
  }).join('');
}

function renderCalendar() {
  const byMonth = {};
  raw.forEach(d => {
    if (d.tmax==null) return;
    const m = d.d.slice(0,7);
    if (!byMonth[m]) byMonth[m] = [];
    byMonth[m].push(d.tmax);
  });
  const months = Object.keys(byMonth).sort().slice(-36);
  const labels = months, data = months.map(m => byMonth[m].reduce((a,b)=>a+b,0)/byMonth[m].length);
  const cmax = Math.max(...data), cmin = Math.min(...data);
  CH.cal = new Chart($('chart-cal'), { type:'bar', data:{labels, datasets:[{data, backgroundColor:data.map(v => {
    const t = (v-cmin)/(cmax-cmin||1);
    const r = Math.round(26 + t*170), g = Math.round(109 + t*(-109+150)), b = Math.round(93 + t*(-93+60));
    return `rgb(${r},${g},${b})`;
  }), borderRadius:2}]}, options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}}, scales:{x:{grid:{display:false}, ticks:{color:'#71717a',font:{size:9}, maxTicksLimit:36}}, y:{display:false, grid:{display:false}}}}});

  const monthData = {};
  raw.forEach(d => {
    if (d.tmax==null) return;
    const m = parseInt(d.d.slice(5,7)), y = d.d.slice(0,4);
    if (!monthData[y]) monthData[y] = {};
    if (!monthData[y][m]) monthData[y][m] = [];
    monthData[y][m].push(d.tmax);
  });
  const years = Object.keys(monthData).sort();
  const getAvg = (y,m) => { const a = monthData[y]?.[m]; return a ? a.reduce((a,b)=>a+b,0)/a.length : null; };
  const spiralData = years.map(y => Array.from({length:12}, (_,i) => getAvg(y,i+1))).flat();
  const spiralLabels = years.flatMap(y => Array.from({length:12}, (_,i) => `${y}-${String(i+1).padStart(2,'0')}`));
  const rmax = Math.max(...spiralData.filter(v=>v!=null)), rmin = Math.min(...spiralData.filter(v=>v!=null));
  CH.spiral = new Chart($('chart-spiral'), { type:'polarArea', data:{labels:spiralLabels, datasets:[{data:spiralData.map(v=>v-rmin+2), backgroundColor:spiralData.map(v => {
    const t = (v-rmin)/(rmax-rmin||1);
    return `rgba(${Math.round(59+t*180)},${Math.round(130-t*60)},${Math.round(246-t*180)},0.7)`;
  }), borderWidth:0.1}]}, options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}}, scales:{r:{display:false, grid:{display:false}}}}});
}

function renderMonthly() {
  const byMonth = {};
  raw.forEach(d => {
    if (d.tmax==null) return;
    const m = parseInt(d.d.slice(5,7)), y = parseInt(d.d.slice(0,4));
    if (!byMonth[m]) byMonth[m] = {years:{}};
    if (!byMonth[m].years[y]) byMonth[m].years[y] = [];
    byMonth[m].years[y].push(d.tmax);
  });
  const months = Array.from({length:12}, (_,i) => new Date(2000,i).toLocaleString('default',{month:'short'}));
  const means = months.map((_,i) => {
    const vals = Object.values(byMonth[i+1]?.years||{}).flatMap(v => v.reduce((a,b)=>a+b,0)/v.length);
    return vals.reduce((a,b)=>a+b,0)/vals.length;
  });
  const maxes = months.map((_,i) => {
    const avgs = Object.entries(byMonth[i+1]?.years||{}).map(([y,v]) => ({year:y, avg:v.reduce((a,b)=>a+b,0)/v.length}));
    return Math.max(...avgs.map(a=>a.avg));
  });
  const mins = months.map((_,i) => {
    const avgs = Object.entries(byMonth[i+1]?.years||{}).map(([y,v]) => ({year:y, avg:v.reduce((a,b)=>a+b,0)/v.length}));
    return Math.min(...avgs.map(a=>a.avg));
  });
  CH.monthly = new Chart($('chart-monthly'), { type:'line', data:{labels:months, datasets:[
    {label:'Avg', data:means, borderColor:'#f97316', backgroundColor:'#f9731633', fill:true, tension:0.3, pointRadius:2},
    {label:'Max', data:maxes, borderColor:'#ef4444', borderDash:[4,3], pointRadius:0, tension:0.3},
    {label:'Min', data:mins, borderColor:'#3b82f6', borderDash:[4,3], pointRadius:0, tension:0.3},
  ]}, options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{labels:{color:'#a1a1aa',font:{size:10}}}}, scales:{x:{grid:{display:false}, ticks:{color:'#71717a',font:{size:10}}}, y:{grid:{color:'#ffffff08'}, ticks:{color:'#71717a',font:{size:10}}}}}});

  ['jan','jul'].forEach((m, mi) => {
    const month = mi === 0 ? 1 : 7;
    const years = Object.entries(byMonth[month]?.years||{}).map(([y,vals]) => ({year:y, avg:vals.reduce((a,b)=>a+b,0)/vals.length}));
    years.sort((a,b)=>a.year-b.year);
    const ll = years.map(y => y.avg);
    const trend = ll.map((_,i,a) => a.slice(Math.max(0,i-10),i+1).reduce((s,v)=>s+v,0)/Math.min(11,i+1));
    const ctx = $(`chart-month-${m}`).getContext('2d');
    CH[`month-${m}`] = new Chart(ctx, { type:'line', data:{labels:years.map(y=>y.year), datasets:[
      {label:'Avg', data:ll, borderColor:'#22d3ee', backgroundColor:'#22d3ee22', fill:true, pointRadius:1, tension:0.2},
      {label:'10yr avg', data:trend, borderColor:'#f97316', borderWidth:2, pointRadius:0, tension:0.2},
    ]}, options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{labels:{color:'#a1a1aa',font:{size:9}}}}, scales:{x:{grid:{display:false}, ticks:{color:'#71717a',font:{size:9}}}, y:{grid:{color:'#ffffff08'}, ticks:{color:'#71717a',font:{size:9}}}}}});
  });
}

function renderRecords() {
  const byYear = {};
  raw.forEach(d => {
    const y = d.d.slice(0,4); if (d.tmax==null) return;
    byYear[y] = byYear[y]||[]; byYear[y].push(d.tmax);
  });
  const decades = {};
  Object.entries(byYear).forEach(([y,vals]) => {
    const d = Math.floor(parseInt(y)/10)*10;
    decades[d] = decades[d]||{years:{}};
    decades[d].years[y] = vals;
  });
  const dkeys = Object.keys(decades).sort();
  const highs = dkeys.map(dk => Math.max(...Object.values(decades[dk].years).flat()));
  const lows = dkeys.map(dk => Math.min(...Object.values(decades[dk].years).flat()));
  const ranges = dkeys.map((dk,i) => highs[i] - lows[i]);
  const dl = dkeys.map(d => `${d}s`);

  CH.recH = new Chart($('chart-rec-high'), { type:'bar', data:{labels:dl, datasets:[{data:highs, backgroundColor:'rgba(239,68,68,0.7)', borderRadius:3}]}, options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}}, scales:{x:{grid:{display:false}, ticks:{color:'#71717a',font:{size:9}}}, y:{grid:{color:'#ffffff08'}, ticks:{color:'#71717a',font:{size:9}}}}}});
  CH.recL = new Chart($('chart-rec-low'), { type:'bar', data:{labels:dl, datasets:[{data:lows, backgroundColor:'rgba(59,130,246,0.7)', borderRadius:3}]}, options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}}, scales:{x:{grid:{display:false}, ticks:{color:'#71717a',font:{size:9}}}, y:{grid:{color:'#ffffff08'}, ticks:{color:'#71717a',font:{size:9}}}}}});
  CH.recR = new Chart($('chart-rec-range'), { type:'bar', data:{labels:dl, datasets:[{data:ranges, backgroundColor:'rgba(168,85,247,0.7)', borderRadius:3}]}, options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}}, scales:{x:{grid:{display:false}, ticks:{color:'#71717a',font:{size:9}}}, y:{grid:{color:'#ffffff08'}, ticks:{color:'#71717a',font:{size:9}}}}}});

  const hotDays = {};
  Object.entries(byYear).forEach(([y,vals]) => { hotDays[y] = vals.filter(v => v > 35).length; });
  const hd = Object.entries(hotDays).sort((a,b)=>a[0]-b[0]);
  CH.hotD = new Chart($('chart-rec-hotdays'), { type:'line', data:{labels:hd.map(h=>h[0]), datasets:[{data:hd.map(h=>h[1]), borderColor:'#ef4444', backgroundColor:'#ef444422', fill:true, pointRadius:0, tension:0.2}]}, options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}}, scales:{x:{grid:{display:false}, ticks:{color:'#71717a',font:{size:9}}}, y:{grid:{color:'#ffffff08'}, ticks:{color:'#71717a',font:{size:9}}}}}});
}

function renderScatter() {
  const pts = raw.filter(d => d.tmax!=null && d.tmin!=null).map(d => ({x:d.tmin, y:d.tmax}));
  CH.scatter = new Chart($('chart-scatter'), { type:'scatter', data:{datasets:[{data:pts, backgroundColor:'rgba(59,130,246,0.2)', pointRadius:2}]}, options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}}, scales:{x:{title:{display:true, text:'Min Temp (°C)', color:'#a1a1aa'}, grid:{color:'#ffffff08'}, ticks:{color:'#71717a',font:{size:9}}}, y:{title:{display:true, text:'Max Temp (°C)', color:'#a1a1aa'}, grid:{color:'#ffffff08'}, ticks:{color:'#71717a',font:{size:9}}}}}});

  const bins = {}; raw.forEach(d => { if (d.tmax==null) return; const b = Math.floor(d.tmax/2)*2; bins[b]=bins[b]||[]; bins[b].push(d.tmax); });
  const bl = Object.keys(bins).sort((a,b)=>a-b);
  CH.dist = new Chart($('chart-dist'), { type:'bar', data:{labels:bl.map(b=>b+'°'), datasets:[{data:bl.map(b=>bins[b].length), backgroundColor:'rgba(168,85,247,0.5)', borderRadius:2}]}, options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}}, scales:{x:{grid:{display:false}, ticks:{color:'#71717a',font:{size:9}}}, y:{grid:{color:'#ffffff08'}, ticks:{color:'#71717a',font:{size:9}}}}}});
}

function renderCompare() { $('chart-compare').style.display='none'; }

function renderTable() {
  if (!raw.length) { $('tbl').innerHTML = '<div class="text-center py-12 text-zinc-500 text-sm">No data</div>'; $('pp').disabled=true; $('np').disabled=true; $('pi').textContent='0'; return; }
  const tp = Math.ceil(raw.length/PAGE), s = pg*PAGE, e = Math.min(s+PAGE, raw.length), p = raw.slice(s, e);
  $('pp').disabled = pg<=0; $('np').disabled = pg>=tp-1; $('pi').textContent = `${pg+1}/${tp}`;
  $('tbl').innerHTML = `<table class="w-full text-xs"><thead><tr class="text-zinc-500 border-b border-white/5"><th class="text-left py-2.5 px-4 font-medium">Date</th><th class="text-right py-2.5 px-4 font-medium">Max</th><th class="text-right py-2.5 px-4 font-medium">Min</th></tr></thead><tbody>${p.map(d => `<tr class="border-b border-white/5 hover:bg-white/[0.02]"><td class="py-2 px-4 text-zinc-300">${d.d}</td><td class="py-2 px-4 text-right ${d.tmax!=null?'text-orange-400':'text-zinc-700'}">${d.tmax!=null?d.tmax.toFixed(1)+'\u00b0':'-'}</td><td class="py-2 px-4 text-right ${d.tmin!=null?'text-blue-400':'text-zinc-700'}">${d.tmin!=null?d.tmin.toFixed(1)+'\u00b0':'-'}</td></tr>`).join('')}</tbody></table><div class="text-center text-xs text-zinc-600 py-3">${s+1}\u2013${e} of ${raw.length.toLocaleString()}</div>`;
}

$('load-btn').addEventListener('click', loadData);
$('pp').addEventListener('click', () => { if (pg>0) { pg--; renderTable(); }});
$('np').addEventListener('click', () => { if ((pg+1)*PAGE<raw.length) { pg++; renderTable(); }});
document.querySelectorAll('.tab').forEach(t => t.addEventListener('click', function() {
  document.querySelectorAll('.tab').forEach(x => { x.classList.remove('tab-active'); x.classList.add('text-zinc-400'); });
  this.classList.add('tab-active'); this.classList.remove('text-zinc-400');
  document.querySelectorAll('.view').forEach(v => v.classList.add('hidden'));
  $(`v-${this.dataset.tab}`).classList.remove('hidden');
  setTimeout(() => renderAll(), 50);
}));

async function init() {
  await checkHealth();
  try {
    const sts = await (await fetch('/api/stations')).json();
    if (sts.error) throw new Error(sts.error);
    const sel = $('stn');
    sel.innerHTML = sts.map(s => `<option value="${s.id}">${s.name}</option>`).join('');
    const good = ["066214","086338","040842","009021","031011","014015","023000","094029","070351"];
    const gs = sts.find(s => good.includes(s.id));
    if (gs) { sel.value = gs.id; loadData(); }
  } catch(e) { $('error').textContent = 'Stations: ' + e.message; $('error').classList.remove('hidden'); }
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
