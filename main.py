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
        <style>
            body { background-color: #0a0a0a; }
            .glass { background: rgba(255,255,255,0.05); backdrop-filter: blur(12px); }
            .metric { transition: all 0.2s ease; }
            .metric:hover { transform: translateY(-2px); box-shadow: 0 10px 15px -3px rgb(0 0 0 / 0.3); }
        </style>
    </head>
    <body class="bg-zinc-950 text-zinc-200">
        <div class="max-w-7xl mx-auto px-6 py-12">
            <!-- Header -->
            <div class="flex items-center justify-between mb-12">
                <div>
                    <h1 class="text-6xl font-bold tracking-tighter">RawRadar</h1>
                    <p class="text-xl text-zinc-400 mt-2">Unfiltered Australian weather observations</p>
                </div>
                <div class="flex items-center gap-x-4">
                    <div class="px-4 py-2 bg-zinc-900 rounded-2xl text-sm flex items-center gap-x-2">
                        <div class="w-2 h-2 bg-emerald-400 rounded-full animate-pulse"></div>
                        <span>Live • Raw Data</span>
                    </div>
                </div>
            </div>

            <!-- Hero Stats -->
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-12">
                <div class="glass border border-white/10 rounded-3xl p-6">
                    <div class="flex items-center gap-x-4">
                        <i class="fa-solid fa-database text-3xl text-sky-400"></i>
                        <div>
                            <div class="text-sm text-zinc-400">Total Records</div>
                            <div class="text-4xl font-semibold">152+</div>
                        </div>
                    </div>
                </div>
                <div class="glass border border-white/10 rounded-3xl p-6">
                    <div class="flex items-center gap-x-4">
                        <i class="fa-solid fa-map-marker-alt text-3xl text-emerald-400"></i>
                        <div>
                            <div class="text-sm text-zinc-400">Stations Tracked</div>
                            <div class="text-4xl font-semibold">1</div>
                        </div>
                    </div>
                </div>
                <div class="glass border border-white/10 rounded-3xl p-6">
                    <div class="flex items-center gap-x-4">
                        <i class="fa-solid fa-clock text-3xl text-amber-400"></i>
                        <div>
                            <div class="text-sm text-zinc-400">Last Update</div>
                            <div class="text-4xl font-semibold">Just now</div>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Actions -->
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                <button onclick="window.location.href='/setup'" 
                        class="glass border border-white/10 hover:border-white/30 transition-all rounded-3xl p-8 text-left group">
                    <i class="fa-solid fa-cog text-4xl mb-6 text-sky-400 group-hover:rotate-45 transition-transform"></i>
                    <div class="text-2xl font-semibold mb-1">Setup Database</div>
                    <div class="text-zinc-400">Initialize raw observations table</div>
                </button>

                <button onclick="window.location.href='/ingest/station/95936'" 
                        class="glass border border-white/10 hover:border-white/30 transition-all rounded-3xl p-8 text-left group">
                    <i class="fa-solid fa-download text-4xl mb-6 text-emerald-400"></i>
                    <div class="text-2xl font-semibold mb-1">Fetch Latest Data</div>
                    <div class="text-zinc-400">Melbourne (95936) • Raw JSON</div>
                </button>

                <button onclick="window.location.href='/data'" 
                        class="glass border border-white/10 hover:border-white/30 transition-all rounded-3xl p-8 text-left group">
                    <i class="fa-solid fa-table text-4xl mb-6 text-violet-400"></i>
                    <div class="text-2xl font-semibold mb-1">View All Data</div>
                    <div class="text-zinc-400">Browse & explore raw observations</div>
                </button>

                <button onclick="window.location.href='/data'" 
                        class="glass border border-white/10 hover:border-white/30 transition-all rounded-3xl p-8 text-left group">
                    <i class="fa-solid fa-chart-line text-4xl mb-6 text-rose-400"></i>
                    <div class="text-2xl font-semibold mb-1">Analytics</div>
                    <div class="text-zinc-400">Coming soon • Charts & trends</div>
                </button>
            </div>
        </div>
    </body>
    </html>
    """

# ==================== DATA PAGE ====================
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
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
            <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        </head>
        <body class="bg-zinc-950 text-zinc-200">
            <div class="max-w-7xl mx-auto px-6 py-8">
                <!-- Header -->
                <div class="flex items-center justify-between mb-8">
                    <div>
                        <h1 class="text-4xl font-bold tracking-tight">Latest Observations</h1>
                        <p class="text-zinc-400 mt-1">Raw data from station 95936 • Melbourne</p>
                    </div>
                    <a href="/" class="flex items-center gap-x-2 px-5 py-2.5 bg-zinc-900 hover:bg-zinc-800 transition rounded-2xl text-sm">
                        <i class="fa-solid fa-arrow-left"></i>
                        <span>Back to Dashboard</span>
                    </a>
                </div>

                <!-- Stats -->
                <div class="flex items-center gap-x-6 mb-6">
                    <div class="px-4 py-2 bg-zinc-900 rounded-2xl text-sm flex items-center gap-x-2">
                        <i class="fa-solid fa-database text-emerald-400"></i>
                        <span>{len(rows)} records shown</span>
                    </div>
                    <div class="px-4 py-2 bg-zinc-900 rounded-2xl text-sm flex items-center gap-x-2">
                        <i class="fa-solid fa-sync text-sky-400"></i>
                        <span>Last updated just now</span>
                    </div>
                </div>

                <!-- Table -->
                <div class="glass border border-white/10 rounded-3xl overflow-hidden">
                    <table class="w-full">
                        <thead class="bg-zinc-900">
                            <tr>
                                <th class="px-6 py-4 text-left text-xs font-medium text-zinc-400">ID</th>
                                <th class="px-6 py-4 text-left text-xs font-medium text-zinc-400">Station</th>
                                <th class="px-6 py-4 text-left text-xs font-medium text-zinc-400">Fetched At</th>
                                <th class="px-6 py-4 text-left text-xs font-medium text-zinc-400">Local Time</th>
                                <th class="px-6 py-4 text-right text-xs font-medium text-zinc-400">Air Temp</th>
                                <th class="px-6 py-4 text-right text-xs font-medium text-zinc-400">Apparent</th>
                                <th class="px-6 py-4 text-right text-xs font-medium text-zinc-400">Gust</th>
                                <th class="px-6 py-4 text-right text-xs font-medium text-zinc-400">Rain</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-white/10 text-sm">
        """

        for row in rows:
            html += f"""
                <tr class="hover:bg-white/5 transition-colors">
                    <td class="px-6 py-4 font-mono text-xs text-zinc-400">{row['id']}</td>
                    <td class="px-6 py-4 font-medium">{row['station_wmo']}</td>
                    <td class="px-6 py-4 text-xs text-zinc-400">{row['fetched_at']}</td>
                    <td class="px-6 py-4 text-xs">{row.get('local_time', '—')}</td>
                    <td class="px-6 py-4 text-right font-medium">{row.get('air_temp', '—')}°C</td>
                    <td class="px-6 py-4 text-right text-emerald-400">{row.get('apparent_t', '—')}°C</td>
                    <td class="px-6 py-4 text-right">{row.get('gust_kmh', '—')} km/h</td>
                    <td class="px-6 py-4 text-right text-amber-400">{row.get('rain_trace', '—')} mm</td>
                </tr>
            """

        html += """
                        </tbody>
                    </table>
                </div>

                <div class="mt-4 text-xs text-zinc-500 text-center">
                    Data is stored exactly as published by the Bureau of Meteorology • No adjustments applied
                </div>
            </div>
        </body>
        </html>
        """
        return html

    except Exception as e:
        return {"status": "error", "detail": str(e)}


# Keep other routes (setup, ingest, health) the same as before...
# (You can copy the rest from the previous version if needed)
