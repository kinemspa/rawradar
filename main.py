from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
import os
import psycopg2
import psycopg2.extras
import requests

load_dotenv()

app = FastAPI(title="RawRadar")

DATABASE_URL = os.getenv("DATABASE_URL")

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "http://www.bom.gov.au/"
}

# ==================== HOMEPAGE ====================
@app.get("/", response_class=HTMLResponse)
def homepage():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>RawRadar</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-zinc-950 text-zinc-200">
        <div class="max-w-6xl mx-auto p-8">
            <h1 class="text-6xl font-bold tracking-tighter mb-2">RawRadar</h1>
            <p class="text-xl text-zinc-400 mb-10">Raw weather observations • No adjustments</p>

            <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                <button onclick="window.location.href='/setup'" 
                        class="bg-zinc-900 hover:bg-zinc-800 border border-white/10 rounded-3xl p-8 text-left transition">
                    <div class="text-3xl mb-4">🛠️</div>
                    <div class="text-2xl font-semibold">Setup Database</div>
                    <div class="text-zinc-400 mt-1">Create the raw observations table</div>
                </button>

                <button onclick="window.location.href='/ingest/station/95936'" 
                        class="bg-zinc-900 hover:bg-zinc-800 border border-white/10 rounded-3xl p-8 text-left transition">
                    <div class="text-3xl mb-4">📥</div>
                    <div class="text-2xl font-semibold">Fetch Melbourne Data</div>
                    <div class="text-zinc-400 mt-1">Station 95936 • Raw JSON</div>
                </button>

                <button onclick="window.location.href='/data'" 
                        class="bg-zinc-900 hover:bg-zinc-800 border border-white/10 rounded-3xl p-8 text-left transition">
                    <div class="text-3xl mb-4">📊</div>
                    <div class="text-2xl font-semibold">View Stored Data</div>
                    <div class="text-zinc-400 mt-1">Browse all raw observations</div>
                </button>
            </div>
        </div>
    </body>
    </html>
    """

# ==================== HEALTH ====================
@app.get("/health")
def health():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.close()
        return {"status": "healthy", "db": "connected"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

# ==================== SETUP ====================
@app.get("/setup")
def setup_db():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS raw_observations (
                id SERIAL PRIMARY KEY,
                station_wmo INTEGER,
                timestamp TIMESTAMPTZ,
                air_temp DOUBLE PRECISION,
                apparent_t DOUBLE PRECISION,
                gust_kmh DOUBLE PRECISION,
                rain_trace DOUBLE PRECISION,
                raw_json JSONB,
                fetched_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "table created"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

# ==================== INGEST ====================
@app.get("/ingest/station/{wmo_id}")
def ingest_station(wmo_id: int):
    try:
        url = f"http://www.bom.gov.au/fwo/IDV60901/IDV60901.{wmo_id}.json"
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            return {"status": "error", "detail": f"BOM returned {response.status_code}"}
        
        data = response.json()
        
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO raw_observations (station_wmo, raw_json)
            VALUES (%s, %s)
        """, (wmo_id, psycopg2.extras.Json(data)))
        conn.commit()
        cur.close()
        conn.close()
        
        return {"status": "success", "station": wmo_id, "records": len(data.get('observations', {}).get('data', []))}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

# ==================== DATA PAGE ====================
@app.get("/data", response_class=HTMLResponse)
def view_data():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT id, station_wmo, fetched_at,
                   raw_json->'observations'->'data'->0->>'local_date_time_full' as local_time,
                   raw_json->'observations'->'data'->0->>'air_temp' as air_temp,
                   raw_json->'observations'->'data'->0->>'apparent_t' as apparent_t,
                   raw_json->'observations'->'data'->0->>'gust_kmh' as gust_kmh,
                   raw_json->'observations'->'data'->0->>'rain_trace' as rain_trace
            FROM raw_observations
            ORDER BY fetched_at DESC
            LIMIT 100
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>RawRadar • Data</title>
            <script src="https://cdn.tailwindcss.com"></script>
        </head>
        <body class="bg-zinc-950 text-zinc-200">
            <div class="max-w-7xl mx-auto p-8">
                <div class="flex justify-between items-center mb-8">
                    <h1 class="text-4xl font-bold">Stored Raw Data</h1>
                    <a href="/" class="text-sky-400 hover:underline">← Back to Home</a>
                </div>

                <div class="bg-zinc-900 rounded-3xl overflow-hidden border border-white/10">
                    <table class="w-full text-sm">
                        <thead class="bg-zinc-800">
                            <tr>
                                <th class="px-6 py-4 text-left">ID</th>
                                <th class="px-6 py-4 text-left">Station</th>
                                <th class="px-6 py-4 text-left">Fetched At</th>
                                <th class="px-6 py-4 text-right">Air Temp</th>
                                <th class="px-6 py-4 text-right">Apparent</th>
                                <th class="px-6 py-4 text-right">Gust</th>
                                <th class="px-6 py-4 text-right">Rain</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-white/10">
        """

        for row in rows:
            html += f"""
                <tr>
                    <td class="px-6 py-4">{row['id']}</td>
                    <td class="px-6 py-4 font-medium">{row['station_wmo']}</td>
                    <td class="px-6 py-4 text-xs text-zinc-400">{row['fetched_at']}</td>
                    <td class="px-6 py-4 text-right">{row.get('air_temp', '—')}°C</td>
                    <td class="px-6 py-4 text-right text-emerald-400">{row.get('apparent_t', '—')}°C</td>
                    <td class="px-6 py-4 text-right">{row.get('gust_kmh', '—')} km/h</td>
                    <td class="px-6 py-4 text-right text-amber-400">{row.get('rain_trace', '—')} mm</td>
                </tr>
            """

        html += """
                        </tbody>
                    </table>
                </div>
            </div>
        </body>
        </html>
        """
        return html
    except Exception as e:
        return {"status": "error", "detail": str(e)}
