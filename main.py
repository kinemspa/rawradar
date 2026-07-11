from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
import os, traceback
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="RawRadar")

# --- Database helpers ---

def get_db():
    import psycopg2
    url = os.getenv("DATABASE_URL")
    if not url:
        raise Exception("DATABASE_URL not set. Add it to Vercel Environment Variables.")
    return psycopg2.connect(url, connect_timeout=5)


def query(sql, params=None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(sql, params or [])
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def check_db():
    try:
        rows = query("SELECT 1 AS ok")
        return {"connected": True, "detail": "OK"}
    except Exception as e:
        return {"connected": False, "detail": str(e)}


# --- API ---

@app.get("/api/health")
def api_health():
    db = check_db()
    return {
        "status": "ok" if db["connected"] else "error",
        "database": db,
        "python": os.environ.get("PYTHON_VERSION", "unknown"),
    }


@app.get("/api/stations")
def api_stations():
    try:
        rows = query("SELECT id, name, source, latitude, longitude, elevation FROM stations ORDER BY name")
        return [{"id": r[0], "name": r[1], "source": r[2],
                 "lat": float(r[3]) if r[3] else None,
                 "lon": float(r[4]) if r[4] else None,
                 "elev": float(r[5]) if r[5] else None} for r in rows]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e), "traceback": traceback.format_exc()})


@app.get("/api/counts")
def api_counts():
    try:
        rows = query("SELECT source, COUNT(*) FROM temperature_readings GROUP BY source")
        return {r[0]: r[1] for r in rows}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/years/{station_id}")
def api_years(station_id: str, source: str = None):
    try:
        params = [station_id]
        src_clause = ""
        if source:
            src_clause = "AND source = %s"
            params.append(source)
        rows = query(f"SELECT MIN(date), MAX(date) FROM temperature_readings WHERE station_id = %s {src_clause}", params)
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
        rows = query(f"SELECT date, tmax, tmin, source FROM temperature_readings WHERE {where} ORDER BY date LIMIT %s", (*params, limit))
        return [{"date": str(r[0]), "tmax": float(r[1]) if r[1] else None,
                 "tmin": float(r[2]) if r[2] else None, "source": r[3]} for r in rows]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/compare/{station_id}")
def api_compare(station_id: str, from_date: str = Query(None, alias="from"), to_date: str = Query(None, alias="to")):
    try:
        params = [station_id, station_id, station_id]
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


# --- Frontend ---

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
code{font-family:monospace;font-size:11px}
</style>
</head>
<body>
<div class="min-h-screen flex flex-col">
  <header class="bg-zinc-900/80 border-b border-white/5 px-6 py-4 flex items-center justify-between sticky top-0 z-50 backdrop-blur">
    <div class="flex items-center gap-3">
      <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center text-white font-bold text-sm">RR</div>
      <h1 class="text-lg font-bold">RawRadar</h1>
    </div>
    <div class="flex items-center gap-2 text-xs" id="status-bar">
      <span class="w-2 h-2 rounded-full bg-zinc-600" id="status-dot"></span>
      <span class="text-zinc-500" id="status-text">Checking...</span>
    </div>
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
        <button id="load-btn" class="bg-blue-600 hover:bg-blue-500 text-white px-6 py-2.5 rounded-xl text-sm font-medium transition disabled:opacity-50">Load</button>
      </div>
      <div id="range-info" class="mt-2 text-xs text-zinc-600 hidden"></div>
    </div>

    <div class="bg-zinc-900 rounded-2xl border border-white/5 overflow-hidden">
      <div class="flex items-center justify-between px-4 lg:px-6 py-4 border-b border-white/5">
        <div>
          <h2 class="text-base font-semibold" id="table-title">Temperature Readings</h2>
          <p class="text-xs text-zinc-500" id="table-subtitle"></p>
        </div>
        <div class="flex items-center gap-2 text-sm">
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
  try {
    const r = await fetch('/api/health');
    const h = await r.json();
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');
    if (h.database?.connected) {
      dot.className = 'w-2 h-2 rounded-full bg-emerald-500';
      text.textContent = 'DB Connected';
      document.getElementById('load-btn').disabled = false;
    } else {
      dot.className = 'w-2 h-2 rounded-full bg-red-500';
      text.textContent = 'DB Error: ' + (h.database?.detail || 'unknown');
      showError('Database connection failed. ' + (h.database?.detail || '') + '. Add DATABASE_URL to Vercel Environment Variables.');
      document.getElementById('load-btn').disabled = true;
    }
  } catch (e) {
    document.getElementById('status-dot').className = 'w-2 h-2 rounded-full bg-red-500';
    document.getElementById('status-text').textContent = 'Server Error';
  }
}

function showError(msg) {
  const el = document.getElementById('error-banner');
  el.textContent = msg;
  el.classList.remove('hidden');
}

function hideError() {
  document.getElementById('error-banner').classList.add('hidden');
}

async function loadData() {
  const station = document.getElementById('station-select').value;
  const source = document.getElementById('source-select').value;
  const from = document.getElementById('from-year').value + '-01-01';
  const to = document.getElementById('to-year').value + '-12-31';
  if (!station) return;

  hideError();
  document.getElementById('loading').classList.remove('hidden');
  document.getElementById('table-container').innerHTML = '';
  document.getElementById('load-btn').disabled = true;

  try {
    const r = await fetch(`/api/data/${station}?source=${source}&from=${from}&to=${to}&limit=50000`);
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${r.status}`);
    }
    const data = await r.json();
    if (data.error) throw new Error(data.error);

    currentData = Array.isArray(data) ? data : [];
    currentPage = 0;

    const name = document.getElementById('station-select').selectedOptions[0]?.text || station;
    document.getElementById('table-title').textContent = name;
    if (currentData.length === 0) {
      document.getElementById('table-subtitle').textContent = 'No data for this period. Try different years or source.';
    } else {
      document.getElementById('table-subtitle').textContent =
        `${currentData.length.toLocaleString()} readings — ${currentData[0].date} to ${currentData[currentData.length-1].date}`;
    }
    document.getElementById('record-count').textContent =
      currentData.length > 0 ? `${currentData.length.toLocaleString()} records` : '';
    renderTable();

    // Show available date range for this station
    const yr = await fetch(`/api/years/${station}?source=${source}`);
    const yrData = await yr.json();
    if (yrData.min) {
      document.getElementById('range-info').classList.remove('hidden');
      document.getElementById('range-info').textContent =
        `Data available: ${yrData.min} to ${yrData.max} for ${source}`;
    }
  } catch (e) {
    showError(e.message);
    document.getElementById('table-title').textContent = 'Error';
    document.getElementById('table-subtitle').textContent = '';
  }
  document.getElementById('loading').classList.add('hidden');
  document.getElementById('load-btn').disabled = false;
}

function renderTable() {
  if (!currentData.length) {
    document.getElementById('table-container').innerHTML =
      '<div class="text-center py-12 text-zinc-500 text-sm">No data for this period</div>';
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
      <thead>
        <tr class="text-zinc-500 border-b border-white/5">
          <th class="text-left py-2.5 px-4 font-medium">Date</th>
          <th class="text-right py-2.5 px-4 font-medium">Max Temp</th>
          <th class="text-right py-2.5 px-4 font-medium">Min Temp</th>
          <th class="text-right py-2.5 px-4 font-medium">Range</th>
        </tr>
      </thead>
      <tbody>
        ${page.map(d => {
          const range = d.tmax != null && d.tmin != null ? (d.tmax - d.tmin).toFixed(1) : '-';
          return `<tr class="border-b border-white/5 hover:bg-white/[0.02]">
            <td class="py-2 px-4 text-zinc-300 font-medium">${d.date}</td>
            <td class="py-2 px-4 text-right ${d.tmax != null ? 'text-orange-400' : 'text-zinc-700'}">${d.tmax != null ? d.tmax.toFixed(1) + '\u00b0' : '-'}</td>
            <td class="py-2 px-4 text-right ${d.tmin != null ? 'text-blue-400' : 'text-zinc-700'}">${d.tmin != null ? d.tmin.toFixed(1) + '\u00b0' : '-'}</td>
            <td class="py-2 px-4 text-right text-zinc-500">${range}</td>
          </tr>`;
        }).join('')}
      </tbody>
    </table>
    <div class="text-center text-xs text-zinc-600 py-3">
      ${start + 1}\u2013${Math.min(end, currentData.length)} of ${currentData.length.toLocaleString()}
    </div>`;
}

async function init() {
  await checkHealth();
  try {
    const r = await fetch('/api/stations');
    const stations = await r.json();
    if (stations.error) throw new Error(stations.error);
    const select = document.getElementById('station-select');
    select.innerHTML = stations.map(s => `<option value="${s.id}">${s.name}</option>`).join('');
    if (stations.length > 0) loadData();
  } catch (e) {
    showError('Failed to load stations: ' + e.message);
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
