from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from ftplib import FTP
from database import get_connection
import json

app = FastAPI(title="RawRadar")

HOME = """
<!DOCTYPE html>
<html>
<head>
    <title>RawRadar</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3"></script>
</head>
<body class="bg-zinc-950 text-zinc-200">
<div class="max-w-6xl mx-auto p-8">
    <div class="flex justify-between items-center mb-8">
        <div>
            <h1 class="text-5xl font-bold tracking-tighter">RawRadar</h1>
            <p class="text-zinc-400 text-lg">Multi-source weather data archive</p>
        </div>
        <div class="flex gap-3">
            <a href="/ftp" class="bg-zinc-800 hover:bg-zinc-700 px-4 py-2 rounded-2xl text-sm border border-white/10">FTP Browser</a>
            <a href="/data" class="bg-zinc-800 hover:bg-zinc-700 px-4 py-2 rounded-2xl text-sm border border-white/10">All Data</a>
        </div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-4 gap-6 mb-8" id="stats"></div>

    <div class="bg-zinc-900 rounded-3xl p-6 border border-white/10 mb-6">
        <div class="flex gap-4 mb-6">
            <select id="station-select" class="bg-zinc-800 text-zinc-200 px-4 py-3 rounded-2xl border border-white/10 flex-1"></select>
            <select id="source-select" class="bg-zinc-800 text-zinc-200 px-4 py-3 rounded-2xl border border-white/10">
                <option value="all">All Sources</option>
                <option value="bom_acorn">BOM ACORN-SAT (adjusted)</option>
                <option value="bom_api">BOM API (current)</option>
                <option value="noaa_ghcn">NOAA GHCN-Daily</option>
            </select>
            <input type="month" id="from-date" class="bg-zinc-800 text-zinc-200 px-4 py-3 rounded-2xl border border-white/10">
            <input type="month" id="to-date" class="bg-zinc-800 text-zinc-200 px-4 py-3 rounded-2xl border border-white/10">
        </div>
        <canvas id="temp-chart" height="80"></canvas>
        <div id="chart-error" class="text-red-400 hidden mt-4"></div>
    </div>

    <div class="bg-zinc-900 rounded-3xl p-6 border border-white/10" id="data-table">
        <div class="text-zinc-400 text-center py-8">Select a station to view data</div>
    </div>
</div>

<script>
const SOURCE_LABELS = {
    'bom_acorn': 'BOM ACORN-SAT',
    'bom_api': 'BOM API',
    'noaa_ghcn': 'NOAA GHCN-Daily',
};

const SOURCE_COLORS = {
    'bom_acorn': '#f97316',
    'bom_api': '#22d3ee',
    'noaa_ghcn': '#818cf8',
};

let chart = null;

async function loadStations() {
    const r = await fetch('/api/stations');
    const stations = await r.json();
    const select = document.getElementById('station-select');
    select.innerHTML = '<option value="">Select station...</option>'
        + stations.map(s => `<option value="${s.id}">${s.name}</option>`).join('');

    const statsEl = document.getElementById('stats');
    const counts = await (await fetch('/api/counts')).json();
    statsEl.innerHTML = Object.entries(counts).map(([k, v]) =>
        `<div class="bg-zinc-900 rounded-2xl p-4 border border-white/10">
            <div class="text-2xl font-bold">${v.toLocaleString()}</div>
            <div class="text-zinc-400 text-sm">${SOURCE_LABELS[k] || k}</div>
        </div>`
    ).join('') + `<div class="bg-zinc-900 rounded-2xl p-4 border border-white/10">
        <div class="text-2xl font-bold">${Object.values(counts).reduce((a, b) => a + b, 0).toLocaleString()}</div>
        <div class="text-zinc-400 text-sm">Total Records</div>
    </div>`;
}

async function loadChart() {
    const stationId = document.getElementById('station-select').value;
    const source = document.getElementById('source-select').value;
    const from = document.getElementById('from-date').value;
    const to = document.getElementById('to-date').value;
    const errorEl = document.getElementById('chart-error');

    if (!stationId) return;

    let url = `/api/data/${stationId}?`;
    if (source !== 'all') url += `source=${source}&`;
    if (from) url += `from=${from}-01&`;
    if (to) url += `to=${to}-01&`;

    const r = await fetch(url);
    const data = await r.json();

    if (data.error) {
        errorEl.textContent = data.error;
        errorEl.classList.remove('hidden');
        return;
    }
    errorEl.classList.add('hidden');

    const groups = {};
    for (const row of data) {
        if (!groups[row.source]) groups[row.source] = [];
        groups[row.source].push({x: row.date, tmax: row.tmax, tmin: row.tmin});
    }

    const datasets = [];
    for (const [source, points] of Object.entries(groups)) {
        const color = SOURCE_COLORS[source] || '#888';
        const label = SOURCE_LABELS[source] || source;
        points.sort((a, b) => a.x.localeCompare(b.x));

        datasets.push({
            label: `${label} Tmax`,
            data: points.map(p => ({x: p.x, y: p.tmax})),
            borderColor: color,
            backgroundColor: color + '33',
            borderWidth: 1.5,
            pointRadius: 0,
            tension: 0.1,
        });
        datasets.push({
            label: `${label} Tmin`,
            data: points.map(p => ({x: p.x, y: p.tmin})),
            borderColor: color,
            backgroundColor: color + '33',
            borderWidth: 1,
            borderDash: [4, 3],
            pointRadius: 0,
            tension: 0.1,
        });
    }

    const ctx = document.getElementById('temp-chart').getContext('2d');
    if (chart) chart.destroy();
    chart = new Chart(ctx, {
        type: 'line',
        data: { datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { intersect: false, mode: 'nearest' },
            scales: {
                x: {
                    type: 'time',
                    time: { tooltipFormat: 'MMM yyyy', unit: 'year' },
                    grid: { color: '#ffffff11' },
                    ticks: { color: '#a1a1aa' },
                },
                y: {
                    title: { display: true, text: 'Temperature (°C)', color: '#a1a1aa' },
                    grid: { color: '#ffffff11' },
                    ticks: { color: '#a1a1aa' },
                },
            },
            plugins: {
                legend: {
                    labels: { color: '#e4e4e7', font: { size: 11 } },
                },
            },
        },
    });

    const tableEl = document.getElementById('data-table');
    tableEl.innerHTML = '<div class="text-xs text-zinc-500 font-mono max-h-64 overflow-y-auto">'
        + datasets[0]?.data.slice(0, 100).map((p, i) =>
            `<div>${p.x} | ${datasets.map(d => d.data[i]?.y?.toFixed(1) ?? '-').join(' | ')}</div>`
        ).join('') + '</div>';
}

document.getElementById('station-select').addEventListener('change', loadChart);
document.getElementById('source-select').addEventListener('change', loadChart);
document.getElementById('from-date').addEventListener('change', loadChart);
document.getElementById('to-date').addEventListener('change', loadChart);

const now = new Date();
const from = new Date(now.getFullYear() - 5, 0, 1);
document.getElementById('from-date').value = from.toISOString().slice(0, 7);
document.getElementById('to-date').value = now.toISOString().slice(0, 7);

loadStations();

fetch('/api/stations').then(r => r.json()).then(stations => {
    if (stations.length > 0) {
        document.getElementById('station-select').value = stations[0].id;
        loadChart();
    }
});
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def homepage():
    return HOME


@app.get("/api/stations")
def api_stations():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, source, latitude, longitude, elevation FROM stations ORDER BY name")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"id": r[0], "name": r[1], "source": r[2], "lat": float(r[3]) if r[3] else None,
             "lon": float(r[4]) if r[4] else None, "elev": float(r[5]) if r[5] else None} for r in rows]


@app.get("/api/counts")
def api_counts():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT source, COUNT(*) FROM temperature_readings GROUP BY source")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {r[0]: r[1] for r in rows}


@app.get("/api/data/{station_id}")
def api_data(station_id: str,
             source: str = None,
             from_date: str = Query(None, alias="from"),
             to_date: str = Query(None, alias="to"),
             limit: int = 5000):
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
    cur.execute(f"""
        SELECT date, tmax, tmin, source
        FROM temperature_readings
        WHERE {where}
        ORDER BY date, source
        LIMIT %s
    """, (*params, limit))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"date": str(r[0]), "tmax": float(r[1]) if r[1] else None,
             "tmin": float(r[2]) if r[2] else None, "source": r[3]} for r in rows]


@app.get("/api/compare/{station_id}")
def api_compare(station_id: str,
                from_date: str = Query(None, alias="from"),
                to_date: str = Query(None, alias="to")):
    """Return all sources side-by-side for a station."""
    conn = get_connection()
    cur = conn.cursor()
    params = [station_id]
    date_clause = ""
    if from_date:
        date_clause += " AND a.date >= %s"
        params.append(from_date)
    if to_date:
        date_clause += " AND a.date <= %s"
        params.append(to_date)

    cur.execute(f"""
        SELECT a.date,
               a.tmax AS acorn_tmax, a.tmin AS acorn_tmin,
               b.tmax AS api_tmax, b.tmin AS api_tmin,
               n.tmax AS noaa_tmax, n.tmin AS noaa_tmin
        FROM (SELECT date, tmax, tmin FROM temperature_readings
              WHERE station_id = %s AND source = 'bom_acorn') a
        FULL OUTER JOIN (SELECT date, tmax, tmin FROM temperature_readings
                         WHERE station_id = %s AND source = 'bom_api') b ON a.date = b.date
        FULL OUTER JOIN (SELECT date, tmax, tmin FROM temperature_readings
                         WHERE station_id = %s AND source = 'noaa_ghcn') n ON a.date = n.date
        WHERE 1=1{date_clause}
        ORDER BY a.date
        LIMIT 5000
    """, (station_id, station_id, station_id, *params[1:]))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"date": str(r[0]),
             "acorn_tmax": float(r[1]) if r[1] else None,
             "acorn_tmin": float(r[2]) if r[2] else None,
             "api_tmax": float(r[3]) if r[3] else None,
             "api_tmin": float(r[4]) if r[4] else None,
             "noaa_tmax": float(r[5]) if r[5] else None,
             "noaa_tmin": float(r[6]) if r[6] else None} for r in rows]


@app.get("/data", response_class=HTMLResponse)
def data_page():
    return HOME


@app.get("/ftp", response_class=HTMLResponse)
def ftp_browser(path: str = ""):
    try:
        ftp = FTP('ftp.bom.gov.au')
        ftp.login()
        if not path:
            path = "/anon/home/ncc/www"
        parent = ""
        if path != "/anon/home/ncc/www":
            parts = path.rstrip("/").split("/")
            parent = "/".join(parts[:-1]) if len(parts) > 1 else "/anon/home/ncc/www"
        ftp.cwd(path)
        items = []
        ftp.retrlines('LIST', items.append)
        ftp.quit()

        rows = ""
        if parent:
            rows += f'<a href="/ftp?path={parent}" class="block px-4 py-2 hover:bg-white/5 rounded-xl text-sky-400">↑ ..</a>'
        for item in items:
            parts = item.split(maxsplit=8)
            if len(parts) >= 9:
                name = parts[8]
                is_dir = item.startswith('d')
                c = "text-sky-400" if is_dir else "text-zinc-400"
                if is_dir:
                    rows += f'<a href="/ftp?path={path}/{name}" class="block px-4 py-2 hover:bg-white/5 rounded-xl {c}">📁 {name}</a>'
                else:
                    rows += f'<div class="px-4 py-2 {c}">📄 {name}</div>'

        return f"""<!DOCTYPE html>
<html><head><title>RawRadar • FTP</title>
<script src="https://cdn.tailwindcss.com"></script></head>
<body class="bg-zinc-950 text-zinc-200">
<div class="max-w-6xl mx-auto p-8">
<div class="flex justify-between items-center mb-6">
<h1 class="text-3xl font-bold">BOM FTP Browser</h1>
<a href="/" class="text-sky-400 hover:underline">← Home</a>
</div>
<div class="bg-zinc-900 rounded-3xl p-6 border border-white/10">
<div class="text-sm text-zinc-400 mb-4 font-mono">{path}</div>
<div class="space-y-1">{rows}</div>
</div></div></body></html>"""
    except Exception as e:
        return {"status": "error", "detail": str(e)}
