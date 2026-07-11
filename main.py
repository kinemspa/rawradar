from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from database import get_connection

app = FastAPI(title="RawRadar")

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
::-webkit-scrollbar{width:6px}
::-webkit-scrollbar-track{background:#18181b}
::-webkit-scrollbar-thumb{background:#3f3f46;border-radius:3px}
.glass{background:rgba(24,24,27,0.8);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,0.06)}
</style>
</head>
<body>
<div class="min-h-screen flex flex-col">
  <header class="glass border-b border-white/5 px-6 py-4 flex items-center justify-between sticky top-0 z-50">
    <div class="flex items-center gap-3">
      <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center text-white font-bold text-sm">RR</div>
      <h1 class="text-lg font-bold tracking-tight">RawRadar</h1>
    </div>
    <div class="text-xs text-zinc-500"><span id="live-dot" class="inline-block w-2 h-2 rounded-full bg-zinc-600 mr-1"></span><span id="live-label">Loading...</span></div>
  </header>

  <div class="flex-1 p-4 lg:p-6">
    <div class="glass rounded-2xl p-4 lg:p-6 mb-4">
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
          <label class="text-xs text-zinc-500 mb-1 block">Year From</label>
          <input type="number" id="from-year" class="bg-zinc-800 text-zinc-200 px-3 py-2.5 rounded-xl text-sm border border-white/10 w-24" value="2010">
        </div>
        <div>
          <label class="text-xs text-zinc-500 mb-1 block">Year To</label>
          <input type="number" id="to-year" class="bg-zinc-800 text-zinc-200 px-3 py-2.5 rounded-xl text-sm border border-white/10 w-24" value="2025">
        </div>
        <button id="load-btn" class="bg-blue-600 hover:bg-blue-500 text-white px-6 py-2.5 rounded-xl text-sm font-medium transition">Load</button>
      </div>
    </div>

    <div class="glass rounded-2xl p-4 lg:p-6 overflow-hidden">
      <div class="flex items-center justify-between mb-4">
        <div>
          <h2 class="text-base font-semibold" id="table-title">Temperature Readings</h2>
          <p class="text-xs text-zinc-500" id="table-subtitle">Select filters and click Load</p>
        </div>
        <div class="flex items-center gap-2 text-sm">
          <button id="prev-btn" class="px-3 py-1.5 rounded-lg bg-zinc-800 text-zinc-400 hover:text-zinc-200 disabled:opacity-30 text-xs" disabled>←</button>
          <span id="page-info" class="text-xs text-zinc-500">0</span>
          <button id="next-btn" class="px-3 py-1.5 rounded-lg bg-zinc-800 text-zinc-400 hover:text-zinc-200 disabled:opacity-30 text-xs" disabled>→</button>
        </div>
      </div>
      <div id="loading" class="hidden text-center py-8 text-zinc-500 text-sm">Loading...</div>
      <div id="error" class="hidden text-center py-8 text-red-400 text-sm"></div>
      <div id="table-container" class="overflow-x-auto">
        <div class="text-center py-16 text-zinc-600">
          <div class="text-5xl mb-4 opacity-20">🌡</div>
          <p class="text-sm">Select a station and click Load</p>
        </div>
      </div>
    </div>
  </div>

  <footer class="glass border-t border-white/5 px-6 py-3 text-xs text-zinc-600 flex items-center justify-between">
    <span>RawRadar — Weather Data Transparency</span>
    <span id="record-count"></span>
  </footer>
</div>

<script>
const PAGE_SIZE = 100;
let currentData = [];
let currentPage = 0;

async function loadData() {
  const station = document.getElementById('station-select').value;
  const source = document.getElementById('source-select').value;
  const from = document.getElementById('from-year').value + '-01-01';
  const to = document.getElementById('to-year').value + '-12-31';
  if (!station) return;

  document.getElementById('loading').classList.remove('hidden');
  document.getElementById('error').classList.add('hidden');
  document.getElementById('table-container').innerHTML = '';

  try {
    const r = await fetch(`/api/data/${station}?source=${source}&from=${from}&to=${to}&limit=50000`);
    if (!r.ok) throw new Error('Server error: ' + r.statusText);
    const data = await r.json();
    if (data.error) throw new Error(data.error);

    currentData = data;
    currentPage = 0;

    const name = document.getElementById('station-select').selectedOptions[0]?.text || station;
    document.getElementById('table-title').textContent = name;
    document.getElementById('table-subtitle').textContent = `${data.length.toLocaleString()} readings from ${source}`;
    document.getElementById('record-count').textContent = `${data.length.toLocaleString()} records`;

    renderTable();
  } catch (e) {
    document.getElementById('error').textContent = e.message;
    document.getElementById('error').classList.remove('hidden');
    document.getElementById('table-title').textContent = 'Error';
    document.getElementById('table-subtitle').textContent = e.message;
  }
  document.getElementById('loading').classList.add('hidden');
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
  document.getElementById('page-info').textContent = `${currentPage + 1} / ${totalPages}`;

  document.getElementById('table-container').innerHTML = `
    <table class="w-full text-xs">
      <thead>
        <tr class="text-zinc-500 border-b border-white/5">
          <th class="text-left py-2.5 px-3 font-medium">Date</th>
          <th class="text-right py-2.5 px-3 font-medium">Max Temp</th>
          <th class="text-right py-2.5 px-3 font-medium">Min Temp</th>
          <th class="text-right py-2.5 px-3 font-medium">Range</th>
          <th class="text-right py-2.5 px-3 font-medium">Source</th>
        </tr>
      </thead>
      <tbody>
        ${page.map(d => {
          const range = d.tmax != null && d.tmin != null ? (d.tmax - d.tmin).toFixed(1) : '-';
          const tmaxClass = d.tmax != null ? 'text-orange-400' : 'text-zinc-700';
          const tminClass = d.tmin != null ? 'text-blue-400' : 'text-zinc-700';
          return `<tr class="border-b border-white/5 hover:bg-white/[0.02] transition-colors">
            <td class="py-2 px-3 text-zinc-300 font-medium">${d.date}</td>
            <td class="py-2 px-3 text-right ${tmaxClass}">${d.tmax != null ? d.tmax.toFixed(1) + '°' : '-'}</td>
            <td class="py-2 px-3 text-right ${tminClass}">${d.tmin != null ? d.tmin.toFixed(1) + '°' : '-'}</td>
            <td class="py-2 px-3 text-right text-zinc-500">${range}</td>
            <td class="py-2 px-3 text-right text-zinc-500">${d.source}</td>
          </tr>`;
        }).join('')}
      </tbody>
    </table>
    <div class="text-center text-xs text-zinc-600 py-3">
      ${start + 1}–${Math.min(end, currentData.length)} of ${currentData.length.toLocaleString()}
    </div>`;
}

// Init
async function init() {
  try {
    const r = await fetch('/api/stations');
    const stations = await r.json();
    const select = document.getElementById('station-select');
    select.innerHTML = stations.map(s => `<option value="${s.id}">${s.name}</option>`).join('');
    if (stations.length > 0) {
      select.value = stations[0].id;
      document.getElementById('live-dot').className = 'inline-block w-2 h-2 rounded-full bg-emerald-500 mr-1';
      document.getElementById('live-label').textContent = 'Connected';
    }
  } catch (e) {
    document.getElementById('live-dot').className = 'inline-block w-2 h-2 rounded-full bg-red-500 mr-1';
    document.getElementById('live-label').textContent = 'DB Error';
    document.getElementById('table-title').textContent = 'Connection Error';
    document.getElementById('table-subtitle').textContent = 'Set DATABASE_URL in Vercel env vars';
  }
}

document.getElementById('load-btn').addEventListener('click', loadData);
document.getElementById('prev-btn').addEventListener('click', () => { if (currentPage > 0) { currentPage--; renderTable(); }});
document.getElementById('next-btn').addEventListener('click', () => { if ((currentPage + 1) * PAGE_SIZE < currentData.length) { currentPage++; renderTable(); }});
document.getElementById('station-select').addEventListener('keydown', e => { if (e.key === 'Enter') loadData(); });
document.getElementById('from-year').addEventListener('keydown', e => { if (e.key === 'Enter') loadData(); });
document.getElementById('to-year').addEventListener('keydown', e => { if (e.key === 'Enter') loadData(); });

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


@app.get("/api/stations")
def api_stations():
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, name, source, latitude, longitude, elevation FROM stations ORDER BY name")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [{"id": r[0], "name": r[1], "source": r[2],
                 "lat": float(r[3]) if r[3] else None,
                 "lon": float(r[4]) if r[4] else None,
                 "elev": float(r[5]) if r[5] else None} for r in rows]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/counts")
def api_counts():
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT source, COUNT(*) FROM temperature_readings GROUP BY source")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return {r[0]: r[1] for r in rows}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/data/{station_id}")
def api_data(station_id: str,
             source: str = None,
             from_date: str = Query(None, alias="from"),
             to_date: str = Query(None, alias="to"),
             limit: int = 50000):
    try:
        conn = get_connection()
        cur = conn.cursor()
        params = [station_id]
        clauses = ["station_id = %s"]
        if source:
            clauses.append("source = %s")
            params.append(source)
        if from_date:
            clauses.append("date >= %s")
            params.append(from_date)
        if to_date:
            clauses.append("date <= %s")
            params.append(to_date)
        where = " AND ".join(clauses)
        cur.execute(f"SELECT date, tmax, tmin, source FROM temperature_readings WHERE {where} ORDER BY date LIMIT %s", (*params, limit))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [{"date": str(r[0]), "tmax": float(r[1]) if r[1] else None,
                 "tmin": float(r[2]) if r[2] else None, "source": r[3]} for r in rows]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/compare/{station_id}")
def api_compare(station_id: str,
                from_date: str = Query(None, alias="from"),
                to_date: str = Query(None, alias="to")):
    try:
        conn = get_connection()
        cur = conn.cursor()
        params = [station_id]
        dc = ""
        if from_date:
            dc += " AND COALESCE(a.date, b.date, n.date) >= %s"; params.append(from_date)
        if to_date:
            dc += " AND COALESCE(a.date, b.date, n.date) <= %s"; params.append(to_date)
        cur.execute(f"""
            SELECT COALESCE(a.date, b.date, n.date),
                   a.tmax, a.tmin, b.tmax, b.tmin, n.tmax, n.tmin
            FROM (SELECT date,tmax,tmin FROM temperature_readings WHERE station_id=%s AND source='bom_acorn') a
            FULL OUTER JOIN (SELECT date,tmax,tmin FROM temperature_readings WHERE station_id=%s AND source='bom_api') b ON a.date=b.date
            FULL OUTER JOIN (SELECT date,tmax,tmin FROM temperature_readings WHERE station_id=%s AND source='noaa_ghcn') n ON a.date=n.date OR b.date=n.date
            WHERE 1=1{dc} ORDER BY 1 LIMIT 5000
        """, (station_id, station_id, station_id, *params[1:]))
        rows = cur.fetchall(); cur.close(); conn.close()
        return [{"date": str(r[0]), "acorn_tmax": float(r[1]) if r[1] else None, "acorn_tmin": float(r[2]) if r[2] else None,
                 "api_tmax": float(r[3]) if r[3] else None, "api_tmin": float(r[4]) if r[4] else None,
                 "noaa_tmax": float(r[5]) if r[5] else None, "noaa_tmin": float(r[6]) if r[6] else None} for r in rows]
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
