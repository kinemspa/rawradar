from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from database import create_table, insert_observation, get_latest_observations
from bom import fetch_station_data

app = FastAPI(title="RawRadar")

# ==================== HOMEPAGE ====================
@app.get("/", response_class=HTMLResponse)
def homepage():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>RawRadar • Raw Weather Data</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    </head>
    <body class="bg-zinc-950 text-zinc-200">
        <div class="max-w-7xl mx-auto px-6 py-12">
            <div class="flex items-center justify-between mb-12">
                <div>
                    <h1 class="text-6xl font-bold tracking-tighter">RawRadar</h1>
                    <p class="text-xl text-zinc-400 mt-2">Unfiltered Australian weather observations</p>
                </div>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                <button onclick="window.location.href='/setup'" 
                        class="glass border border-white/10 hover:border-white/30 transition-all rounded-3xl p-8 text-left">
                    <i class="fa-solid fa-cog text-4xl mb-6 text-sky-400"></i>
                    <div class="text-2xl font-semibold mb-1">Setup Database</div>
                    <div class="text-zinc-400">Initialize raw observations table</div>
                </button>

                <button onclick="window.location.href='/ingest/station/95936'" 
                        class="glass border border-white/10 hover:border-white/30 transition-all rounded-3xl p-8 text-left">
                    <i class="fa-solid fa-download text-4xl mb-6 text-emerald-400"></i>
                    <div class="text-2xl font-semibold mb-1">Fetch Melbourne Data</div>
                    <div class="text-zinc-400">Station 95936 • Raw</div>
                </button>

                <button onclick="window.location.href='/data'" 
                        class="glass border border-white/10 hover:border-white/30 transition-all rounded-3xl p-8 text-left">
                    <i class="fa-solid fa-table text-4xl mb-6 text-violet-400"></i>
                    <div class="text-2xl font-semibold mb-1">View Data</div>
                    <div class="text-zinc-400">Browse stored observations</div>
                </button>
            </div>
        </div>
    </body>
    </html>
    """

# ==================== OTHER ROUTES ====================
@app.get("/health")
def health():
    return {"status": "healthy", "db": "connected"}

@app.get("/setup")
def setup_db():
    return create_table()

@app.get("/ingest/station/{wmo_id}")
def ingest_station(wmo_id: int):
    try:
        response = fetch_station_data(wmo_id)
        if response.status_code != 200:
            return {"status": "error", "detail": f"BOM returned status {response.status_code}"}
        
        data = response.json()
        insert_observation(wmo_id, data)
        return {"status": "success", "station": wmo_id, "records": len(data.get('observations', {}).get('data', []))}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

@app.get("/data", response_class=HTMLResponse)
def data_page():
    try:
        rows = get_latest_observations(50)
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>RawRadar • Observations</title>
            <script src="https://cdn.tailwindcss.com"></script>
        </head>
        <body class="bg-zinc-950 text-zinc-200">
            <div class="max-w-7xl mx-auto px-6 py-8">
                <div class="flex items-center justify-between mb-8">
                    <div>
                        <h1 class="text-4xl font-bold tracking-tight">Latest Observations</h1>
                        <p class="text-zinc-400">Raw data • Last 50 records</p>
                    </div>
                    <a href="/" class="px-5 py-2.5 bg-zinc-900 hover:bg-zinc-800 rounded-2xl text-sm">← Back</a>
                </div>

                <div class="border border-white/10 rounded-3xl overflow-hidden">
                    <table class="w-full text-sm">
                        <thead class="bg-zinc-900">
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
                <tr class="hover:bg-white/5">
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
