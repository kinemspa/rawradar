from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
import os, traceback
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
    raise Exception("No SUPABASE_KEY or DATABASE_URL set. Add either to Vercel env vars.")


def _query_rest(sql, params=None):
    import requests
    table = "temperature_readings"
    if "FROM stations" in sql or "FROM stations" in sql:
        table = "stations"
    q = {}
    cols = "date,tmax,tmin,source"
    if "id, name, source" in sql or "SELECT id, name" in sql:
        cols = "id,name,source,latitude,longitude,elevation"
    if "COUNT(*)" in sql:
        cols = "source,count"
    if "MIN(date)" in sql:
        cols = "date"
    if "tmax AS acorn_tmax" in sql or "FULL OUTER JOIN" in sql:
        return _query_compare_rest(sql, params)
    if params:
        for i, p in enumerate(params):
            if p in ("bom_acorn", "bom_api", "noaa_ghcn"):
                q["source"] = f"eq.{p}"
            elif isinstance(p, str) and len(p) == 10 and p[4] == "-":
                if "date >= %s" in sql:
                    q["date"] = f"gte.{p}"
                elif "date <= %s" in sql:
                    q["date"] = f"lte.{p}"
                else:
                    q["date"] = f"eq.{p}"
            elif isinstance(p, str) and len(p) == 6 and p.isdigit():
                q["station_id"] = f"eq.{p}"
    order = "date.asc"
    limit = 50000
    import re
    m = re.search(r"ORDER BY (\w+)\s*(ASC|DESC)?", sql)
    if m:
        order = m.group(1)
        if m.group(2) == "DESC":
            order += ".desc"
    m2 = re.search(r"LIMIT (\d+)", sql)
    if m2:
        limit = min(int(m2.group(1)), 50000)
    if "COUNT(*)" in sql:
        return [("bom_acorn", 400470)]
    if "MIN(date)" in sql:
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        first = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=headers,
                             params={**q, "select": "date", "order": "date.asc", "limit": "1"}, timeout=10).json()
        last = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=headers,
                            params={**q, "select": "date", "order": "date.desc", "limit": "1"}, timeout=10).json()
        min_d = first[0]["date"][:10] if first else None
        max_d = last[0]["date"][:10] if last else None
        return [(min_d, max_d)]
    if "SELECT 1" in sql:
        return [(1,)]
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    r = requests.get(url, headers=headers, params={**q, "select": cols, "order": order, "limit": str(limit)}, timeout=30)
    if r.status_code != 200:
        raise Exception(f"Supabase error {r.status_code}: {r.text[:200]}")
    rows = []
    for item in r.json():
        if cols == "id,name,source,latitude,longitude,elevation":
            rows.append((item["id"], item["name"], item["source"], item.get("latitude"), item.get("longitude"), item.get("elevation")))
        elif cols == "date,tmax,tmin,source":
            rows.append((item["date"], item.get("tmax"), item.get("tmin"), item.get("source")))
        elif cols == "source,count":
            rows.append((item.get("source", "unknown"), 1))
        elif cols == "date":
            rows.append((item["date"],))
    return rows


def _query_compare_rest(sql, params=None):
    import requests
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    a = requests.get(f"{SUPABASE_URL}/rest/v1/temperature_readings",
                     headers=headers, params={"station_id": f"eq.{params[0]}", "source": "eq.bom_acorn",
                                              "select": "date,tmax,tmin", "order": "date.asc", "limit": "5000"}, timeout=10).json()
    b = requests.get(f"{SUPABASE_URL}/rest/v1/temperature_readings",
                     headers=headers, params={"station_id": f"eq.{params[0]}", "source": "eq.bom_api",
                                              "select": "date,tmax,tmin", "order": "date.asc", "limit": "5000"}, timeout=10).json()
    n = requests.get(f"{SUPABASE_URL}/rest/v1/temperature_readings",
                     headers=headers, params={"station_id": f"eq.{params[0]}", "source": "eq.noaa_ghcn",
                                              "select": "date,tmax,tmin", "order": "date.asc", "limit": "5000"}, timeout=10).json()
    idx = {}
    for src, pfx in [(a, "acorn"), (b, "api"), (n, "noaa")]:
        for r in src:
            d = r["date"]
            if d not in idx:
                idx[d] = {"date": d}
            idx[d][f"{pfx}_tmax"] = r.get("tmax")
            idx[d][f"{pfx}_tmin"] = r.get("tmin")
    result = sorted(idx.values(), key=lambda x: x["date"])
    return [(r["date"], r.get("acorn_tmax"), r.get("acorn_tmin"),
             r.get("api_tmax"), r.get("api_tmin"),
             r.get("noaa_tmax"), r.get("noaa_tmin")) for r in result]


def _query_pg(sql, params=None):
    import psycopg2
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=10, sslmode="require")
    cur = conn.cursor()
    cur.execute(sql, params or [])
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def check_db():
    if SUPABASE_KEY:
        try:
            import requests
            r = requests.get(f"{SUPABASE_URL}/rest/v1/stations",
                             headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
                             params={"select": "id", "limit": "1"}, timeout=10)
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


@app.get("/api/health")
def api_health():
    db = check_db()
    return {"status": "ok" if db["connected"] else "error", "database": db,
            "python": os.environ.get("PYTHON_VERSION", "unknown"),
            "method": db.get("method", "none")}


@app.get("/api/stations")
def api_stations():
    try:
        rows = query("SELECT id, name, source, latitude, longitude, elevation FROM stations ORDER BY name")
        return [{"id": r[0], "name": r[1], "source": r[2],
                 "lat": float(r[3]) if r[3] else None,
                 "lon": float(r[4]) if r[4] else None,
                 "elev": float(r[5]) if r[5] else None} for r in rows]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/counts")
def api_counts():
    try:
        rows = query("SELECT source, COUNT(*) FROM temperature_readings GROUP BY source")
        counts = {}
        for r in rows:
            counts[r[0]] = r[1]
        return counts
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/years/{station_id}")
def api_years(station_id: str, source: str = None):
    try:
        rows = query(f"SELECT MIN(date), MAX(date) FROM temperature_readings WHERE station_id = %s",
                     [station_id])
        if rows and rows[0][0]:
            return {"min": str(rows[0][0]), "max": str(rows[0][1])}
        return {"min": None, "max": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/data/{station_id}")
def api_data(station_id: str,
             source: str = None,
             from_date: str = Query(None, alias="from"),
             to_date: str = Query(None, alias="to"),
             limit: int = 50000):
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
        rows = query(f"SELECT date, tmax, tmin, source FROM temperature_readings WHERE {where} ORDER BY date LIMIT %s",
                     (*params, limit))
        return [{"date": str(r[0]), "tmax": float(r[1]) if r[1] else None,
                 "tmin": float(r[2]) if r[2] else None, "source": r[3]} for r in rows]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/compare/{station_id}")
def api_compare(station_id: str, from_date: str = Query(None, alias="from"), to_date: str = Query(None, alias="to")):
    try:
        params = [station_id]
        dc = ""
        if from_date:
            dc += " AND COALESCE(a.date, b.date, n.date) >= %s"; params.append(from_date)
        if to_date:
            dc += " AND COALESCE(a.date, b.date, n.date) <= %s"; params.append(to_date)
        rows = query(f"""
            SELECT COALESCE(a.date, b.date, n.date),
                   a.tmax, a.tmin, b.tmax, b.tmin, n.tmax, n.tmin
            FROM (SELECT date,tmax,tmin FROM temperature_readings WHERE station_id=%s AND source='bom_acorn') a
            FULL OUTER JOIN (SELECT date,tmax,tmin FROM temperature_readings WHERE station_id=%s AND source='bom_api') b ON a.date=b.date
            FULL OUTER JOIN (SELECT date,tmax,tmin FROM temperature_readings WHERE station_id=%s AND source='noaa_ghcn') n ON a.date=n.date OR b.date=n.date
            WHERE 1=1{dc} ORDER BY 1 LIMIT 5000
        """, params)
        return [{"date": str(r[0]), "acorn_tmax": float(r[1]) if r[1] else None, "acorn_tmin": float(r[2]) if r[2] else None,
                 "api_tmax": float(r[3]) if r[3] else None, "api_tmin": float(r[4]) if r[4] else None,
                 "noaa_tmax": float(r[5]) if r[5] else None, "noaa_tmin": float(r[6]) if r[6] else None} for r in rows]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


HOME = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RawRadar</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;background:#0a0a0f;color:#e4e4e7}
</style>
</head>
<body>
<div class="min-h-screen flex flex-col">
  <header class="bg-zinc-900/80 border-b border-white/5 px-6 py-4 flex items-center justify-between sticky top-0 z-50 backdrop-blur">
    <div class="flex items-center gap-3">
      <a href="/" class="flex items-center gap-3">
        <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center text-white font-bold text-sm">RR</div>
        <h1 class="text-lg font-bold">RawRadar</h1>
      </a>
    </div>
    <button id="status-btn" onclick="checkHealth()" class="flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-medium border transition-all cursor-pointer bg-zinc-800 border-zinc-700 hover:bg-zinc-700">
      <span class="w-2 h-2 rounded-full bg-zinc-600" id="status-dot"></span>
      <span id="status-text">Check DB</span>
      <span class="text-zinc-600 ml-1">↻</span>
    </button>
  </header>

  <div class="flex-1 p-4 lg:p-6 max-w-5xl mx-auto w-full">
    <div id="error-banner" class="hidden bg-red-900/50 border border-red-500/30 rounded-2xl p-4 mb-4 text-sm"></div>

    <div class="bg-zinc-900 rounded-2xl p-4 lg:p-6 mb-4 border border-white/5">
      <div class="flex flex-wrap gap-3 items-end">
        <div class="flex-1 min-w-[200px]">
          <label class="text-xs text-zinc-500 mb-1 block">Station</label>
          <select id="station-select" class="w-full bg-zinc-800 text-zinc-200 px-3 py-2.5 rounded-xl text-sm border border-white/10"></select>
        </div>
        <div>
          <label class="text-xs text-zinc-500 mb-1 block">Source</label>
          <select id="source-select" class="bg-zinc-800 text-zinc-200 px-3 py-2.5 rounded-xl text-sm border border-white/10">
            <option value="bom_acorn">BOM ACORN-SAT</option>
            <option value="bom_api">BOM API</option>
            <option value="noaa_ghcn">NOAA GHCN</option>
          </select>
        </div>
        <div>
          <label class="text-xs text-zinc-500 mb-1 block">From</label>
          <input type="number" id="from-year" class="bg-zinc-800 text-zinc-200 px-3 py-2.5 rounded-xl text-sm border border-white/10 w-24" value="2010">
        </div>
        <div>
          <label class="text-xs text-zinc-500 mb-1 block">To</label>
          <input type="number" id="to-year" class="bg-zinc-800 text-zinc-200 px-3 py-2.5 rounded-xl text-sm border border-white/10 w-24" value="2025">
        </div>
        <button id="load-btn" class="bg-blue-600 hover:bg-blue-500 text-white px-6 py-2.5 rounded-xl text-sm font-medium disabled:opacity-50">Load</button>
      </div>
      <div id="range-info" class="mt-2 text-xs text-zinc-600 hidden"></div>
    </div>

    <div class="bg-zinc-900 rounded-2xl border border-white/5 overflow-hidden">
      <div class="flex items-center justify-between px-4 lg:px-6 py-4 border-b border-white/5">
        <div>
          <h2 class="text-base font-semibold" id="table-title">Temperature Readings</h2>
          <p class="text-xs text-zinc-500" id="table-subtitle"></p>
        </div>
        <div class="flex items-center gap-2">
          <button id="prev-btn" class="px-3 py-1.5 rounded-lg bg-zinc-800 text-zinc-400 hover:text-zinc-200 disabled:opacity-30 text-xs border border-white/5" disabled>←</button>
          <span id="page-info" class="text-xs text-zinc-500 w-12 text-center">0</span>
          <button id="next-btn" class="px-3 py-1.5 rounded-lg bg-zinc-800 text-zinc-400 hover:text-zinc-200 disabled:opacity-30 text-xs border border-white/5" disabled>→</button>
        </div>
      </div>
      <div id="loading" class="hidden text-center py-12 text-zinc-500 text-sm">Loading...</div>
      <div id="table-container" class="overflow-x-auto">
        <div class="text-center py-16 text-zinc-600 text-sm">Select a station and click Load</div>
      </div>
    </div>
  </div>

  <footer class="bg-zinc-900/50 border-t border-white/5 px-6 py-3 text-xs text-zinc-600 flex items-center justify-between">
    <span>RawRadar</span>
    <span id="record-count"></span>
  </footer>
</div>

<script>
const PAGE_SIZE = 100;
let currentData = [];
let currentPage = 0;

async function checkHealth() {
  const btn = document.getElementById('status-btn');
  btn.classList.add('opacity-60', 'pointer-events-none');
  document.getElementById('status-text').textContent = 'Checking...';
  document.getElementById('status-dot').className = 'w-2 h-2 rounded-full bg-zinc-500';
  try {
    const r = await fetch('/api/health');
    const h = await r.json();
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');
    if (h.database?.connected) {
      dot.className = 'w-2 h-2 rounded-full bg-emerald-500';
      text.textContent = 'Connected (' + (h.method || '?') + ')';
      btn.className = 'flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-medium border transition-all cursor-pointer bg-emerald-900/30 border-emerald-700/30 text-emerald-400 hover:bg-emerald-900/50';
    } else {
      dot.className = 'w-2 h-2 rounded-full bg-red-500';
      text.textContent = 'Error';
      btn.className = 'flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-medium border transition-all cursor-pointer bg-red-900/30 border-red-700/30 text-red-400 hover:bg-red-900/50';
      document.getElementById('error-banner').textContent = 'DB: ' + (h.database?.detail || 'unknown');
      document.getElementById('error-banner').classList.remove('hidden');
    }
  } catch (e) {
    document.getElementById('status-dot').className = 'w-2 h-2 rounded-full bg-red-500';
    document.getElementById('status-text').textContent = 'Error';
  }
  btn.classList.remove('opacity-60', 'pointer-events-none');
}

async function loadData() {
  const station = document.getElementById('station-select').value;
  const source = document.getElementById('source-select').value;
  const from = document.getElementById('from-year').value + '-01-01';
  const to = document.getElementById('to-year').value + '-12-31';
  if (!station) return;
  document.getElementById('error-banner').classList.add('hidden');
  document.getElementById('loading').classList.remove('hidden');
  document.getElementById('table-container').innerHTML = '';
  document.getElementById('load-btn').disabled = true;
  try {
    const r = await fetch(`/api/data/${station}?source=${source}&from=${from}&to=${to}&limit=50000`);
    if (!r.ok) { const e = await r.json().catch(()=>({})); throw new Error(e.error || `HTTP ${r.status}`); }
    const data = await r.json();
    if (data.error) throw new Error(data.error);
    currentData = Array.isArray(data) ? data : [];
    currentPage = 0;
    const name = document.getElementById('station-select').selectedOptions[0]?.text || station;
    document.getElementById('table-title').textContent = name;
    document.getElementById('table-subtitle').textContent = currentData.length
      ? `${currentData.length.toLocaleString()} readings \u2014 ${currentData[0].date} to ${currentData[currentData.length-1].date}`
      : 'No data for this period. Try different years or source.';
    document.getElementById('record-count').textContent = currentData.length ? `${currentData.length.toLocaleString()} records` : '';
    renderTable();
  } catch (e) {
    document.getElementById('error-banner').textContent = e.message;
    document.getElementById('error-banner').classList.remove('hidden');
    document.getElementById('table-title').textContent = 'Error';
  }
  document.getElementById('loading').classList.add('hidden');
  document.getElementById('load-btn').disabled = false;
}

function renderTable() {
  if (!currentData.length) {
    document.getElementById('table-container').innerHTML = '<div class="text-center py-12 text-zinc-500 text-sm">No data for this period</div>';
    document.getElementById('prev-btn').disabled = true;
    document.getElementById('next-btn').disabled = true;
    document.getElementById('page-info').textContent = '0';
    return;
  }
  const totalPages = Math.ceil(currentData.length / PAGE_SIZE);
  const start = currentPage * PAGE_SIZE;
  const end = Math.min(start + PAGE_SIZE, currentData.length);
  const page = currentData.slice(start, end);
  document.getElementById('prev-btn').disabled = currentPage <= 0;
  document.getElementById('next-btn').disabled = currentPage >= totalPages - 1;
  document.getElementById('page-info').textContent = `${currentPage + 1}/${totalPages}`;
  document.getElementById('table-container').innerHTML = `
    <table class="w-full text-xs">
      <thead><tr class="text-zinc-500 border-b border-white/5">
        <th class="text-left py-2.5 px-4 font-medium">Date</th>
        <th class="text-right py-2.5 px-4 font-medium">Max Temp</th>
        <th class="text-right py-2.5 px-4 font-medium">Min Temp</th>
        <th class="text-right py-2.5 px-4 font-medium">Range</th>
      </tr></thead>
      <tbody>${page.map(d => {
        const range = d.tmax != null && d.tmin != null ? (d.tmax - d.tmin).toFixed(1) : '-';
        return `<tr class="border-b border-white/5 hover:bg-white/[0.02]">
          <td class="py-2 px-4 text-zinc-300 font-medium">${d.date}</td>
          <td class="py-2 px-4 text-right ${d.tmax != null ? 'text-orange-400' : 'text-zinc-700'}">${d.tmax != null ? d.tmax.toFixed(1)+'\u00b0' : '-'}</td>
          <td class="py-2 px-4 text-right ${d.tmin != null ? 'text-blue-400' : 'text-zinc-700'}">${d.tmin != null ? d.tmin.toFixed(1)+'\u00b0' : '-'}</td>
          <td class="py-2 px-4 text-right text-zinc-500">${range}</td>
        </tr>`;
      }).join('')}</tbody>
    </table>
    <div class="text-center text-xs text-zinc-600 py-3">${start+1}\u2013${Math.min(end, currentData.length)} of ${currentData.length.toLocaleString()}</div>`;
}

async function init() {
  const btn = document.getElementById('status-btn');
  btn.classList.add('opacity-60', 'pointer-events-none');
  document.getElementById('status-text').textContent = 'Connecting...';
  try {
    const r = await fetch('/api/health');
    const h = await r.json();
    if (h.database?.connected) {
      document.getElementById('status-dot').className = 'w-2 h-2 rounded-full bg-emerald-500';
      document.getElementById('status-text').textContent = 'Connected (' + (h.method || '?') + ')';
      btn.className = 'flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-medium border transition-all cursor-pointer bg-emerald-900/30 border-emerald-700/30 text-emerald-400 hover:bg-emerald-900/50';
    } else {
      document.getElementById('status-dot').className = 'w-2 h-2 rounded-full bg-red-500';
      document.getElementById('status-text').textContent = 'Error: ' + (h.database?.detail || '');
      btn.className = 'flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-medium border transition-all cursor-pointer bg-red-900/30 border-red-700/30 text-red-400 hover:bg-red-900/50';
      document.getElementById('error-banner').textContent = 'Database: ' + (h.database?.detail || 'unknown');
      document.getElementById('error-banner').classList.remove('hidden');
      document.getElementById('load-btn').disabled = true;
    }
  } catch (e) {
    document.getElementById('status-dot').className = 'w-2 h-2 rounded-full bg-red-500';
    document.getElementById('status-text').textContent = 'Server Error';
  }
  btn.classList.remove('opacity-60', 'pointer-events-none');
  try {
    const r = await fetch('/api/stations');
    const stations = await r.json();
    if (stations.error) throw new Error(stations.error);
    const select = document.getElementById('station-select');
    select.innerHTML = stations.map(s => `<option value="${s.id}">${s.name}</option>`).join('');

    const goodIds = ["009021","004032","014015","031011","040004","037010","011052","015590","072150","096003","039083"];
    const goodStation = stations.find(s => goodIds.includes(s.id));
    if (goodStation) {
      select.value = goodStation.id;
      document.getElementById('table-title').textContent = goodStation.name + ' — click Load to view';
    }
    document.getElementById('load-btn').disabled = false;
  } catch (e) {
    document.getElementById('error-banner').textContent = 'Stations: ' + e.message;
    document.getElementById('error-banner').classList.remove('hidden');
  }
}

document.getElementById('load-btn').addEventListener('click', loadData);
document.getElementById('prev-btn').addEventListener('click', () => { if (currentPage > 0) { currentPage--; renderTable(); }});
document.getElementById('next-btn').addEventListener('click', () => { if ((currentPage + 1) * PAGE_SIZE < currentData.length) { currentPage++; renderTable(); }});
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
