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
    if SUPABASE_KEY: return _query_rest(sql, params)
    if DATABASE_URL: return _query_pg(sql, params)
    raise Exception("No SUPABASE_KEY or DATABASE_URL set")

def _query_rest(sql, params=None):
    import requests, re
    table = "temperature_readings"
    if "FROM stations" in sql: table = "stations"
    q = {}
    cols = "date,tmax,tmin,source"
    if "id,name,source" in sql or "id, name, source" in sql: cols = "id,name,source,latitude,longitude,elevation"
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
    if m: order = m.group(1) + (".desc" if m.group(2) == "DESC" else ".asc")
    limit = 50000
    m = re.search(r"LIMIT (\d+)", sql)
    if m: limit = min(int(m.group(1)), 50000)
    if "SELECT 1" in sql: return [(1,)]
    if "MIN(date)" in sql:
        h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        f = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=h, params={**q, "select":"date","order":"date.asc","limit":"1"}, timeout=10).json()
        l = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=h, params={**q, "select":"date","order":"date.desc","limit":"1"}, timeout=10).json()
        return [(f[0]["date"][:10] if f else None, l[0]["date"][:10] if l else None)]
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=headers, params={**q, "select":cols, "order":order, "limit":str(limit)}, timeout=30)
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
            r = requests.get(f"{SUPABASE_URL}/rest/v1/stations", headers={"apikey":SUPABASE_KEY,"Authorization":f"Bearer {SUPABASE_KEY}"}, params={"select":"id","limit":"1"}, timeout=10)
            if r.status_code == 200: return {"connected":True,"method":"supabase_rest","detail":"OK"}
            return {"connected":False,"method":"supabase_rest","detail":f"HTTP {r.status_code}"}
        except Exception as e: return {"connected":False,"method":"supabase_rest","detail":str(e)}
    if DATABASE_URL:
        try: _query_pg("SELECT 1"); return {"connected":True,"method":"postgres","detail":"OK"}
        except Exception as e: return {"connected":False,"method":"postgres","detail":str(e)}
    return {"connected":False,"detail":"No SUPABASE_KEY or DATABASE_URL in env"}

@app.get("/api/health")
def api_health():
    db = check_db()
    return {"status":"ok" if db["connected"] else "error","database":db,"method":db.get("method","none")}

@app.get("/api/stations")
def api_stations():
    try:
        rows = query("SELECT id,name,source,latitude,longitude,elevation FROM stations ORDER BY name")
        return [{"id":r[0],"name":r[1],"s":r[2],"lat":float(r[3]) if r[3] else None,"lon":float(r[4]) if r[4] else None,"elev":float(r[5]) if r[5] else None} for r in rows]
    except Exception as e: return JSONResponse(status_code=500,content={"error":str(e)})

@app.get("/api/counts")
def api_counts(): return {"bom_acorn":748696}

@app.get("/api/years/{station_id}")
def api_years(station_id:str,source:str=None):
    try:
        if source: rows = query(f"SELECT MIN(date),MAX(date) FROM temperature_readings WHERE station_id=%s AND source=%s",[station_id,source])
        else: rows = query(f"SELECT MIN(date),MAX(date) FROM temperature_readings WHERE station_id=%s",[station_id])
        if rows and rows[0][0]: return {"min":str(rows[0][0]),"max":str(rows[0][1])}
        return {"min":None,"max":None}
    except Exception as e: return JSONResponse(status_code=500,content={"error":str(e)})

@app.get("/api/data/{station_id}")
def api_data(station_id:str,source:str=None,from_date:str=Query(None,alias="from"),to_date:str=Query(None,alias="to"),limit:int=50000):
    try:
        params=[station_id]; clauses=["station_id=%s"]
        if source: clauses.append("source=%s"); params.append(source)
        if from_date: clauses.append("date>=%s"); params.append(from_date)
        if to_date: clauses.append("date<=%s"); params.append(to_date)
        rows = query(f"SELECT date,tmax,tmin,source FROM temperature_readings WHERE {' AND '.join(clauses)} ORDER BY date LIMIT %s",(*params,limit))
        return [{"d":str(r[0]),"tmax":float(r[1]) if r[1] else None,"tmin":float(r[2]) if r[2] else None,"src":r[3]} for r in rows]
    except Exception as e: return JSONResponse(status_code=500,content={"error":str(e)})

@app.get("/api/anomaly/{station_id}")
def api_anomaly(station_id:str,source:str="bom_acorn"):
    try:
        rows = query(f"SELECT date,tmax,tmin FROM temperature_readings WHERE station_id=%s AND source=%s ORDER BY date",[station_id,source])
        annual={}
        for r in rows:
            y=r[0][:4]
            if y not in annual: annual[y]={"tmax":[],"tmin":[]}
            if r[1] is not None: annual[y]["tmax"].append(r[1])
            if r[2] is not None: annual[y]["tmin"].append(r[2])
        years=sorted(annual.keys())
        means={y:{"tmax":sum(d["tmax"])/len(d["tmax"]) if d["tmax"] else None,"tmin":sum(d["tmin"])/len(d["tmin"]) if d["tmin"] else None} for y,d in annual.items()}
        bt=[means[y]["tmax"] for y in years if "1961"<=y<="1990" and means[y]["tmax"] is not None]
        bn=[means[y]["tmin"] for y in years if "1961"<=y<="1990" and means[y]["tmin"] is not None]
        b_tmax=sum(bt)/len(bt) if bt else None; b_tmin=sum(bn)/len(bn) if bn else None
        result=[{"year":y,"tmax":m["tmax"],"tmin":m["tmin"],"anomaly_tmax":round(m["tmax"]-b_tmax,2) if(m["tmax"] and b_tmax) else None,"anomaly_tmin":round(m["tmin"]-b_tmin,2) if(m["tmin"] and b_tmin) else None} for y,m in means.items()]
        return {"station_id":station_id,"baseline":"1961-1990","baseline_tmax":round(b_tmax,2) if b_tmax else None,"baseline_tmin":round(b_tmin,2) if b_tmin else None,"years":result}
    except Exception as e: return JSONResponse(status_code=500,content={"error":str(e)})

@app.get("/api/export/{station_id}")
def api_export(station_id:str,source:str=None,from_date:str=Query(None,alias="from"),to_date:str=Query(None,alias="to")):
    try:
        data=api_data(station_id,source,from_date,to_date,50000)
        if isinstance(data,JSONResponse): return data
        lines=["date,tmax,tmin,source"]
        for r in data: lines.append(f"{r['d']},{r['tmax'] or ''},{r['tmin'] or ''},{r['src']}")
        return PlainTextResponse("\n".join(lines),media_type="text/csv",headers={"Content-Disposition":f"attachment; filename={station_id}.csv"})
    except Exception as e: return JSONResponse(status_code=500,content={"error":str(e)})


HOME = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RawRadar</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@200;300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<script>tailwind.config={theme:{extend:{fontFamily:{sans:['Inter','system-ui','sans-serif']}}}}</script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',system-ui,sans-serif;background:#06060e;color:#e4e4e7;overflow-x:hidden}
::-webkit-scrollbar{width:4px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.1);border-radius:2px}
.glass{background:rgba(18,18,30,0.7);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);border:1px solid rgba(255,255,255,0.05)}
.tab{transition:all 0.3s ease}.tab:hover{background:rgba(255,255,255,0.04)}
.tab-active{background:linear-gradient(135deg,rgba(59,130,246,0.2),rgba(139,92,246,0.1));border-color:rgba(59,130,246,0.3);color:#93c5fd}
.pin{animation:pulse 2s ease-in-out infinite;cursor:pointer;transition:r 0.2s}.pin:hover{r:8;filter:brightness(1.3)}
input[type=range]{-webkit-appearance:none;appearance:none;height:4px;background:rgba(255,255,255,0.1);border-radius:2px;outline:none;width:100%}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:16px;height:16px;border-radius:50%;background:#3b82f6;border:2px solid rgba(255,255,255,0.2);cursor:pointer;box-shadow:0 0 10px rgba(59,130,246,0.3)}
</style>
</head>
<body>
<div class="relative min-h-screen flex flex-col">
<header class="glass border-b border-white/[0.03] px-6 lg:px-10 py-4 flex items-center justify-between sticky top-0 z-50 backdrop-blur-2xl" style="background:rgba(6,6,14,0.8)">
<a href="/" class="flex items-center gap-3 group"><div class="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-500 via-indigo-500 to-purple-600 flex items-center justify-center text-white font-bold text-sm group-hover:scale-105 transition-transform" style="box-shadow:0 0 20px rgba(59,130,246,0.2)">RR</div><div><h1 class="text-lg font-bold tracking-tight" style="background:linear-gradient(135deg,#e4e4e7 0%,#a1a1aa 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent">RawRadar</h1><p class="text-[10px] text-zinc-600 -mt-0.5 tracking-wider uppercase font-medium">Australian Climate Data</p></div></a>
<div class="flex items-center gap-4"><span class="text-xs text-zinc-600" id="rec-count"></span><button id="status-btn" class="flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-medium border border-zinc-800" style="background:rgba(24,24,27,0.5)"><span class="w-1.5 h-1.5 rounded-full bg-zinc-600" id="status-dot"></span><span id="status-text" class="text-zinc-400">DB</span></button></div>
</header>

<div class="flex-1 p-6 lg:p-10 max-w-[1600px] mx-auto w-full">
<div id="error" class="hidden bg-red-900/30 border border-red-500/20 rounded-3xl p-4 mb-6 text-sm text-red-300"></div>

<div id="map-section" class="glass rounded-3xl p-6 lg:p-8 mb-6" style="background:linear-gradient(135deg,rgba(6,6,20,0.9),rgba(10,10,30,0.9))">
<div class="flex items-center justify-between mb-4"><div><h2 class="text-base font-semibold text-zinc-100">Explore Stations</h2><p class="text-xs text-zinc-600 mt-0.5">Click a marker to view climate data</p></div>
<div class="flex items-center gap-2 text-xs text-zinc-500"><span class="flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-full bg-orange-500"></span> Has data</span><span class="flex items-center gap-1"><span class="w-2.5 h-2.5 rounded-full bg-zinc-600"></span> Limited</span></div></div>
<div id="map-container" class="relative w-full" style="height:min(60vh,540px)"><svg id="map-svg" class="w-full h-full" viewBox="0 0 820 680" preserveAspectRatio="xMidYMid meet"></svg><div id="map-loading" class="absolute inset-0 flex items-center justify-center text-zinc-600 text-sm">Loading stations...</div></div>
</div>

<div class="glass rounded-3xl p-5 lg:p-6 mb-6">
<div class="flex flex-wrap items-end gap-4">
<div class="flex-1 min-w-[200px]"><label class="text-[10px] text-zinc-600 mb-1.5 block uppercase tracking-wider font-medium">Station</label>
<select id="stn" class="w-full bg-zinc-800/50 text-zinc-200 px-4 py-3 rounded-2xl text-sm border border-white/5"></select></div>
<div class="flex-1 min-w-[260px]"><label class="text-[10px] text-zinc-600 mb-1.5 block uppercase tracking-wider font-medium">Year Range</label>
<div class="flex items-center gap-3"><span class="text-xs text-zinc-500 w-7 text-center font-mono" id="yl">1910</span>
<div class="flex-1 relative" style="height:24px"><input type="range" id="yr-s" class="absolute" min="1910" max="2024" value="2014" style="top:10px"><input type="range" id="yr-e" class="absolute" min="1910" max="2024" value="2024" style="top:10px;background:transparent"></div>
<span class="text-xs text-zinc-500 w-7 text-center font-mono" id="yr">2024</span></div></div>
<button id="load-btn" class="px-6 py-3 rounded-2xl text-sm font-semibold text-white border-0 cursor-pointer" style="background:linear-gradient(135deg,#3b82f6,#6366f1);box-shadow:0 0 30px rgba(59,130,246,0.2)">Load</button>
<a id="dl-btn" class="px-5 py-3 rounded-2xl text-sm font-medium text-zinc-300 no-underline hidden cursor-pointer border border-white/5" style="background:rgba(24,24,27,0.4)">CSV</a>
</div></div>

<div class="flex gap-1.5 mb-6 flex-wrap" id="tabs">
<button class="tab tab-active px-5 py-2.5 rounded-2xl text-xs font-medium border border-white/5" data-tab="anomaly">Anomaly</button>
<button class="tab px-5 py-2.5 rounded-2xl text-xs font-medium border border-white/5 text-zinc-500" data-tab="calendar">Calendar</button>
<button class="tab px-5 py-2.5 rounded-2xl text-xs font-medium border border-white/5 text-zinc-500" data-tab="monthly">Monthly</button>
<button class="tab px-5 py-2.5 rounded-2xl text-xs font-medium border border-white/5 text-zinc-500" data-tab="records">Records</button>
<button class="tab px-5 py-2.5 rounded-2xl text-xs font-medium border border-white/5 text-zinc-500" data-tab="scatter">Scatter</button>
<button class="tab px-5 py-2.5 rounded-2xl text-xs font-medium border border-white/5 text-zinc-500" data-tab="compare">Compare</button>
</div>

<div id="views">
<div class="view" id="v-anomaly"><div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
<div class="lg:col-span-2 glass rounded-3xl p-6 lg:p-8"><div class="flex justify-between mb-5"><div><h2 class="text-base font-semibold text-zinc-100" id="anomaly-title">Temperature Anomaly</h2><p class="text-xs text-zinc-600 mt-0.5">Annual deviation from 1961-1990 baseline</p></div><div class="flex items-center gap-1 text-xs"><span class="w-3 h-3 rounded-sm" style="background:rgba(239,68,68,0.7)"></span><span class="text-zinc-500 ml-1">Warm</span><span class="w-3 h-3 rounded-sm ml-2" style="background:rgba(59,130,246,0.7)"></span><span class="text-zinc-500 ml-1">Cool</span></div></div><div style="height:280px"><canvas id="chart-anomaly"></canvas></div></div>
<div class="glass rounded-3xl p-6 lg:p-8"><h3 class="text-sm font-semibold text-zinc-100 mb-4">Climate Stripes</h3><div id="stripes" class="flex h-[240px] rounded-2xl overflow-hidden"></div><div class="flex justify-between text-xs text-zinc-600 mt-2"><span id="s-start"></span><span id="s-end"></span></div><div class="flex items-center gap-3 mt-3 text-xs text-zinc-500"><span class="flex items-center gap-1"><span class="w-3 h-3 rounded-sm" style="background:#1e3a5f"></span>Colder</span><span class="flex items-center gap-1"><span class="w-3 h-3 rounded-sm" style="background:#8b1a1a"></span>Warmer</span></div></div>
</div></div>

<div class="view hidden" id="v-calendar"><div class="grid grid-cols-1 lg:grid-cols-5 gap-6">
<div class="lg:col-span-3 glass rounded-3xl p-6 lg:p-8"><h2 class="text-base font-semibold text-zinc-100 mb-4">Calendar Heatmap</h2><div style="height:300px"><canvas id="chart-cal"></canvas></div><div class="flex justify-center gap-3 mt-4 text-xs text-zinc-500"><span class="flex items-center gap-1"><span class="w-4 h-4 rounded" style="background:#1e3a5f"></span></span><span class="flex items-center gap-1"><span class="w-4 h-4 rounded" style="background:#2b6cb0"></span></span><span class="flex items-center gap-1"><span class="w-4 h-4 rounded" style="background:#63b3ed"></span></span><span class="flex items-center gap-1"><span class="w-4 h-4 rounded" style="background:#fbd38d"></span></span><span class="flex items-center gap-1"><span class="w-4 h-4 rounded" style="background:#ed8936"></span></span><span class="flex items-center gap-1"><span class="w-4 h-4 rounded" style="background:#c53030"></span><span class="ml-1">Hot</span></span></div></div>
<div class="lg:col-span-2 glass rounded-3xl p-6 lg:p-8"><h2 class="text-base font-semibold text-zinc-100 mb-4">Temperature Spiral</h2><div style="height:350px"><canvas id="chart-spiral"></canvas></div></div>
</div></div>

<div class="view hidden" id="v-monthly"><div class="glass rounded-3xl p-6 lg:p-8 mb-6"><h2 class="text-base font-semibold text-zinc-100 mb-4">Monthly Temperature Cycle</h2><div style="height:300px"><canvas id="chart-monthly"></canvas></div></div>
<div class="grid grid-cols-1 lg:grid-cols-2 gap-6"><div class="glass rounded-3xl p-6 lg:p-8"><h3 class="text-sm font-semibold text-zinc-100 mb-3">January <span class="text-zinc-500 font-normal">— summer</span></h3><div style="height:180px"><canvas id="chart-month-jan"></canvas></div></div><div class="glass rounded-3xl p-6 lg:p-8"><h3 class="text-sm font-semibold text-zinc-100 mb-3">July <span class="text-zinc-500 font-normal">— winter</span></h3><div style="height:180px"><canvas id="chart-month-jul"></canvas></div></div></div></div>

<div class="view hidden" id="v-records"><div class="grid grid-cols-1 lg:grid-cols-4 gap-6">
<div class="glass rounded-3xl p-6 lg:p-8"><h3 class="text-xs font-semibold text-zinc-100 mb-3 uppercase tracking-wider">Record Highs</h3><div style="height:200px"><canvas id="chart-rec-high"></canvas></div></div>
<div class="glass rounded-3xl p-6 lg:p-8"><h3 class="text-xs font-semibold text-zinc-100 mb-3 uppercase tracking-wider">Record Lows</h3><div style="height:200px"><canvas id="chart-rec-low"></canvas></div></div>
<div class="glass rounded-3xl p-6 lg:p-8"><h3 class="text-xs font-semibold text-zinc-100 mb-3 uppercase tracking-wider">Extreme Range</h3><div style="height:200px"><canvas id="chart-rec-range"></canvas></div></div>
<div class="glass rounded-3xl p-6 lg:p-8"><h3 class="text-xs font-semibold text-zinc-100 mb-3 uppercase tracking-wider">Days &gt;35&deg;C</h3><div style="height:200px"><canvas id="chart-rec-hotdays"></canvas></div></div>
</div></div>

<div class="view hidden" id="v-scatter"><div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
<div class="glass rounded-3xl p-6 lg:p-8"><h3 class="text-sm font-semibold text-zinc-100 mb-4">Max vs Min Temp</h3><div style="height:300px"><canvas id="chart-scatter"></canvas></div></div>
<div class="glass rounded-3xl p-6 lg:p-8"><h3 class="text-sm font-semibold text-zinc-100 mb-4">Distribution</h3><div style="height:300px"><canvas id="chart-dist"></canvas></div></div>
</div></div>

<div class="view hidden" id="v-compare"><div class="glass rounded-3xl p-6 lg:p-8"><h2 class="text-base font-semibold text-zinc-100 mb-4">Station Comparison</h2><div class="flex gap-2 mb-4 flex-wrap" id="compare-stns"></div><div style="height:300px"><canvas id="chart-compare"></canvas></div></div></div>
</div>

<div class="mt-6 glass rounded-3xl overflow-hidden">
<div class="flex items-center justify-between px-6 lg:px-8 py-5 border-b border-white/5"><div><h3 class="text-sm font-semibold text-zinc-100" id="tbl-title">Daily Readings</h3><p class="text-xs text-zinc-600 mt-0.5" id="tbl-sub"></p></div>
<div class="flex items-center gap-3"><button id="pp" class="px-3 py-1.5 rounded-xl bg-zinc-800/50 text-zinc-400 disabled:opacity-30 text-xs border border-white/5" disabled>&larr;</button><span id="pi" class="text-xs text-zinc-600 w-10 text-center font-mono">0</span><button id="np" class="px-3 py-1.5 rounded-xl bg-zinc-800/50 text-zinc-400 disabled:opacity-30 text-xs border border-white/5" disabled>&rarr;</button></div></div>
<div id="tbl" class="overflow-x-auto"><div class="text-center py-16 text-zinc-700 text-sm">Click a station on the map or select from the dropdown</div></div>
</div>
</div>
<footer class="glass border-t border-white/[0.03] px-6 lg:px-10 py-4 text-xs text-zinc-700 flex items-center justify-between" style="background:rgba(6,6,14,0.8)"><span>RawRadar</span><span>Weather Data Transparency Project</span></footer>
</div>

<script>
const PAGE=100,W=window;let raw=[],pg=0,stns=[],CH={};const $=id=>document.getElementById(id);
const SRC_LABELS={'bom_acorn':'BOM ACORN-SAT','bom_api':'BOM API','noaa_ghcn':'NOAA GHCN'};
const AUS="M 606.7 29.7 L 625.9 27.4 L 647.2 25.0 L 668.5 25.0 L 689.8 27.4 L 711.1 33.3 L 728.1 41.6 L 743.0 51.1 L 753.7 60.5 L 764.3 72.4 L 770.7 84.2 L 775.0 98.4 L 770.7 110.3 L 764.3 119.7 L 753.7 128.0 L 743.0 136.3 L 732.4 143.4 L 721.7 151.7 L 711.1 160.0 L 700.4 169.5 L 689.8 178.9 L 679.1 187.2 L 668.5 195.5 L 657.8 202.6 L 647.2 207.4 L 642.9 214.5 L 636.5 222.8 L 625.9 231.1 L 615.2 238.2 L 604.5 242.9 L 593.9 246.4 L 583.2 250.0 L 572.6 252.4 L 557.7 254.7 L 540.6 258.3 L 523.6 261.8 L 508.7 264.2 L 493.8 266.6 L 476.7 270.1 L 459.7 273.7 L 444.7 278.4 L 429.8 285.5 L 417.0 293.8 L 408.5 302.1 L 402.1 311.6 L 395.7 321.1 L 391.5 329.3 L 387.2 337.6 L 380.8 344.7 L 370.2 353.0 L 359.5 361.3 L 344.6 368.4 L 327.6 373.2 L 310.5 376.7 L 295.6 380.3 L 280.7 382.6 L 263.6 385.0 L 246.6 388.6 L 231.7 394.5 L 216.8 403.9 L 204.0 415.8 L 195.5 427.6 L 189.1 439.5 L 182.7 451.3 L 178.4 463.2 L 174.1 475.0 L 167.8 486.8 L 161.4 498.7 L 152.8 510.5 L 146.4 522.4 L 140.1 534.2 L 135.8 546.1 L 131.5 557.9 L 125.1 569.7 L 118.8 581.6 L 114.5 593.4 L 110.2 605.3 L 103.8 617.1 L 97.4 628.9 L 93.2 637.2 L 88.9 643.2 L 82.5 649.1 L 76.1 652.6 L 67.6 655.0 L 54.8 652.6 L 46.3 649.1 L 39.9 643.2 L 33.5 637.2 L 29.3 628.9 L 25.0 619.5 L 25.0 607.6 L 29.3 595.8 L 33.5 583.9 L 39.9 572.1 L 46.3 562.6 L 54.8 554.3 L 61.2 546.1 L 67.6 536.6 L 76.1 527.1 L 82.5 518.8 L 88.9 510.5 L 93.2 501.1 L 97.4 491.6 L 103.8 486.8 L 110.2 483.3 L 118.8 479.7 L 125.1 475.0 L 131.5 467.9 L 135.8 459.6 L 140.1 451.3 L 146.4 441.8 L 152.8 432.4 L 157.1 424.1 L 161.4 415.8 L 167.8 406.3 L 174.1 396.8 L 178.4 388.6 L 182.7 380.3 L 189.1 370.8 L 195.5 361.3 L 199.7 353.0 L 204.0 344.7 L 210.4 335.3 L 216.8 325.8 L 221.0 317.5 L 225.3 309.2 L 231.7 302.1 L 238.1 297.4 L 246.6 293.8 L 259.4 290.3 L 267.9 287.9 L 280.7 285.5 L 289.2 282.0 L 302.0 278.4 L 310.5 276.1 L 323.3 273.7 L 331.8 270.1 L 344.6 266.6 L 353.1 261.8 L 359.5 254.7 L 365.9 246.4 L 370.2 238.2 L 370.2 228.7 L 365.9 219.2 L 359.5 210.9 L 348.9 202.6 L 338.2 195.5 L 327.6 190.8 L 316.9 187.2 L 306.2 183.7 L 295.6 178.9 L 284.9 171.8 L 280.7 163.6 L 274.3 155.3 L 267.9 145.8 L 263.6 136.3 L 259.4 128.0 L 253.0 119.7 L 246.6 110.3 L 238.1 100.8 L 231.7 92.5 L 225.3 84.2 L 221.0 77.1 L 216.8 68.8 L 210.4 60.5 L 204.0 53.4 L 199.7 48.7 L 195.5 45.1 L 199.7 41.6 L 210.4 39.2 L 225.3 36.8 L 242.3 34.5 L 259.4 33.3 L 274.3 32.1 L 289.2 30.9 L 302.0 29.7 L 316.9 29.7 L 331.8 30.9 L 344.6 33.3 L 359.5 36.8 L 374.4 41.6 L 387.2 48.7 L 402.1 57.0 L 417.0 65.3 L 434.1 72.4 L 451.1 77.1 L 466.1 80.7 L 481.0 84.2 L 493.8 86.6 L 508.7 88.9 L 523.6 92.5 L 536.4 96.1 L 544.9 100.8 L 551.3 107.9 L 557.7 116.2 L 561.9 124.5 L 566.2 131.6 L 572.6 136.3 L 579.0 139.9 L 587.5 143.4 L 593.9 145.8 L 600.3 148.2 Z";
const TAS="M 619.0 613.9 L 638.1 623.3 L 647.6 642.2 L 657.1 661.1 L 666.7 670.6 L 685.7 670.6 L 695.2 661.1 L 685.7 642.2 L 676.2 623.3 L 657.1 613.9 L 638.1 613.9 L 619.0 613.9 Z";
const PINS={023000:{x:505,y:513},015590:{x:415,y:305},040842:{x:783,y:376},003003:{x:195,y:192},031011:{x:648,y:172},037010:{x:480,y:225},070351:{x:715,y:522},014015:{x:360,y:88},094029:{x:680,y:662},012038:{x:260,y:435},091311:{x:658,y:635},086338:{x:635,y:568},076031:{x:600,y:520},068072:{x:740,y:530},009021:{x:78,y:458},004032:{x:230,y:305},039083:{x:760,y:315},066214:{x:755,y:495},032040:{x:710,y:245},072150:{x:680,y:540}};
const DATA_STNS=["066214","086338","040842","009021","031011","014015","023000","094029","070351"];

function drawMap(){
  const svg=$('map-svg');svg.innerHTML='';const ns='http://www.w3.org/2000/svg';
  const d=document.createElementNS(ns,'defs');
  d.innerHTML='<linearGradient id="sg" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#0a1628"/><stop offset="100%" stop-color="#0d1f3c"/></linearGradient><filter id="gl"><feGaussianBlur stdDeviation="2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>';
  svg.appendChild(d);
  const bg=document.createElementNS(ns,'rect');bg.setAttribute('width','820');bg.setAttribute('height','680');bg.setAttribute('fill','url(#sg)');bg.setAttribute('rx','16');svg.appendChild(bg);
  [AUS,TAS].forEach((p,i)=>{const e=document.createElementNS(ns,'path');e.setAttribute('d',p);e.setAttribute('fill','rgba(20,30,50,0.6)');e.setAttribute('stroke','rgba(59,130,246,0.2)');e.setAttribute('stroke-width',i?'1':'1.5');svg.appendChild(e);});
  stns.forEach(s=>{const pin=PINS[s.id];if(!pin)return;const has=DATA_STNS.includes(s.id);const g=document.createElementNS(ns,'g');const c=document.createElementNS(ns,'circle');c.setAttribute('cx',pin.x);c.setAttribute('cy',pin.y);c.setAttribute('r',has?'6':'4');c.setAttribute('fill',has?'#f97316':'#52525b');c.setAttribute('stroke','rgba(255,255,255,0.2)');c.setAttribute('stroke-width',has?'1.5':'1');c.setAttribute('filter','url(#gl)');c.setAttribute('class','pin');c.dataset.id=s.id;c.addEventListener('click',()=>selectStation(s.id));g.appendChild(c);const t=document.createElementNS(ns,'text');t.setAttribute('x',pin.x);t.setAttribute('y',pin.y-12);t.setAttribute('font-size','9');t.setAttribute('fill','#a1a1aa');t.setAttribute('text-anchor','middle');t.textContent=s.name.split('(')[0].trim();g.appendChild(t);svg.appendChild(g);});
  [{n:'Sydney',x:755,y:513},{n:'Perth',x:78,y:476},{n:'Melbourne',x:635,y:586},{n:'Darwin',x:360,y:106},{n:'Brisbane',x:783,y:394},{n:'Adelaide',x:505,y:531},{n:'Hobart',x:680,y:680},{n:'Cairns',x:648,y:190}].forEach(c=>{const t=document.createElementNS(ns,'text');t.setAttribute('x',c.x);t.setAttribute('y',c.y);t.setAttribute('fill','rgba(255,255,255,0.12)');t.setAttribute('font-size','9');t.setAttribute('text-anchor','middle');t.textContent=c.n;svg.appendChild(t);});
  $('map-loading').classList.add('hidden');
}

async function selectStation(id){
  $('stn').value=id;$('error').classList.add('hidden');
  const f=$('yr-s').value+'-01-01',t=$('yr-e').value+'-12-31';
  try{
    const r=await fetch(`/api/data/${id}?from=${f}&to=${t}&limit=50000`);
    if(!r.ok)throw new Error((await r.json().catch(()=>({}))).error||`HTTP ${r.status}`);
    raw=await r.json();if(raw.error)throw new Error(raw.error);pg=0;
    const name=$('stn').selectedOptions[0]?.text||id;
    $('tbl-title').textContent=name;$('tbl-sub').textContent=raw.length?`${raw.length.toLocaleString()} readings`:'No data';
    $('dl-btn').href=`/api/export/${id}?from=${f}&to=${t}`;$('dl-btn').classList.remove('hidden');
    renderAll();
  }catch(e){$('error').textContent=e.message;$('error').classList.remove('hidden')}
}

function renderAll(){
  Object.values(CH).forEach(c=>{try{c.destroy()}catch(e){}});
  if(!raw.length)return;
  ['anomaly','calendar','monthly','records','scatter'].forEach(v=>{try{W['render'+v[0].toUpperCase()+v.slice(1)]()}catch(e){console.error(v,e)}});
  renderTable();renderCompare();
}

function renderAnomaly(){
  const mode='tmax',years={};
  raw.forEach(d=>{const y=d.d.slice(0,4);years[y]=years[y]||[];if(d[mode]!=null)years[y].push(d[mode])});
  const ys=Object.keys(years).sort(),annual=ys.map(y=>years[y].reduce((a,b)=>a+b,0)/years[y].length);
  const bs=ys.filter(y=>y>='1961'&&y<='1990');
  const bv=bs.length?bs.reduce((s,y)=>s+annual[ys.indexOf(y)],0)/bs.length:annual.reduce((a,b)=>a+b,0)/annual.length;
  const anom=annual.map(v=>v-bv),mx=Math.max(...anom.map(Math.abs))||1;
  const colors=anom.map(v=>v>=0?`rgba(239,68,68,${Math.min(1,v/mx*1.5)})`:`rgba(59,130,246,${Math.min(1,Math.abs(v)/mx*1.5)})`);
  CH.anomaly=new Chart($('chart-anomaly'),{type:'bar',data:{labels:ys,datasets:[{data:anom,backgroundColor:colors,borderRadius:2}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{backgroundColor:'rgba(6,6,14,0.95)',titleColor:'#e4e4e7',bodyColor:'#a1a1aa',padding:12,cornerRadius:12,displayColors:false,callbacks:{label:ctx=>`${ctx.parsed.y>0?'+':''}${ctx.parsed.y.toFixed(2)}°C`}}},scales:{x:{grid:{display:false},ticks:{color:'#52525b',font:{size:10},maxTicksLimit:20}},y:{grid:{color:'rgba(255,255,255,0.03)'},ticks:{color:'#52525b',font:{size:10},callback:v=>v+'°'}}}}});
  const byYear={};
  raw.forEach(d=>{const y=d.d.slice(0,4);if(d.tmax==null)return;byYear[y]=byYear[y]||[];byYear[y].push(d.tmax)});
  const ys2=Object.keys(byYear).filter(y=>byYear[y].length>20).sort();
  if(ys2.length<2)return;
  const means=ys2.map(y=>byYear[y].reduce((a,b)=>a+b,0)/byYear[y].length);
  const bl=means.reduce((a,b)=>a+b,0)/means.length,mx2=Math.max(...means.map(m=>Math.abs(m-bl)))||1;
  $('s-start').textContent=ys2[0];$('s-end').textContent=ys2[ys2.length-1];
  $('stripes').innerHTML=ys2.map(y=>{
    const m=byYear[y].reduce((a,b)=>a+b,0)/byYear[y].length,d=(m-bl)/mx2,c=Math.max(-1,Math.min(1,d));
    const r=c>0?Math.round(180*c+70):30,b=c<0?Math.round(180*Math.abs(c)+70):30,g=Math.round(40+40*(1-Math.abs(c)));
    return `<div class="flex-1 hover:opacity-80 transition-opacity cursor-pointer" style="background:rgb(${r},${g},${b})" title="${y}: ${m.toFixed(1)}°C"></div>`;
  }).join('');
}

function renderCalendar(){
  const byMonth={};
  raw.forEach(d=>{if(d.tmax==null)return;const m=d.d.slice(0,7);byMonth[m]=byMonth[m]||[];byMonth[m].push(d.tmax)});
  const months=Object.keys(byMonth).sort().slice(-36),labels=months,data=months.map(m=>byMonth[m].reduce((a,b)=>a+b,0)/byMonth[m].length);
  const cmax=Math.max(...data),cmin=Math.min(...data);
  CH.cal=new Chart($('chart-cal'),{type:'bar',data:{labels,datasets:[{data,backgroundColor:data.map(v=>{const t=(v-cmin)/(cmax-cmin||1);return`rgb(${Math.round(26+t*170)},${Math.round(109+t*(-109+150))},${Math.round(93+t*(-93+60))})`}),borderRadius:2}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{display:false},ticks:{color:'#52525b',font:{size:9},maxTicksLimit:36}},y:{display:false,grid:{display:false}}}}});
  const md={};
  raw.forEach(d=>{if(d.tmax==null)return;const m=parseInt(d.d.slice(5,7)),y=d.d.slice(0,4);md[y]=md[y]||{};md[y][m]=md[y][m]||[];md[y][m].push(d.tmax)});
  const yrs=Object.keys(md).sort(),sd=yrs.flatMap(y=>Array.from({length:12},(_,i)=>{const av=md[y]?.[i+1];return av?av.reduce((a,b)=>a+b,0)/av.length:null})).filter(v=>v!=null);
  const rmx=Math.max(...sd),rmn=Math.min(...sd);
  CH.spiral=new Chart($('chart-spiral'),{type:'polarArea',data:{labels:yrs.flatMap(y=>Array.from({length:12},(_,i)=>`${y}-${String(i+1).padStart(2,'0')}`)),datasets:[{data:yrs.flatMap(y=>Array.from({length:12},(_,i)=>{const av=md[y]?.[i+1];const v=av?av.reduce((a,b)=>a+b,0)/av.length:null;return v?v-rmn+1:null})).filter(v=>v!=null),backgroundColor:sd.map(v=>{const t=(v-rmn)/(rmx-rmn||1);return`rgba(${Math.round(59+t*180)},${Math.round(130-t*60)},${Math.round(246-t*180)},0.7)`}),borderWidth:0.1}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{r:{display:false,grid:{display:false}}}}});
}

function renderMonthly(){
  const byMonth={};
  raw.forEach(d=>{if(d.tmax==null)return;const m=parseInt(d.d.slice(5,7)),y=parseInt(d.d.slice(0,4));byMonth[m]=byMonth[m]||{years:{}};byMonth[m].years[y]=byMonth[m].years[y]||[];byMonth[m].years[y].push(d.tmax)});
  const mnths=Array.from({length:12},(_,i)=>new Date(2000,i).toLocaleString('default',{month:'short'}));
  const means=mnths.map((_,i)=>{const v=Object.values(byMonth[i+1]?.years||{}).flatMap(v=>v.reduce((a,b)=>a+b,0)/v.length);return v.reduce((a,b)=>a+b,0)/v.length});
  const maxes=mnths.map((_,i)=>{const v=Object.entries(byMonth[i+1]?.years||{}).map(([y,v])=>({y,avg:v.reduce((a,b)=>a+b,0)/v.length}));return Math.max(...v.map(a=>a.avg))});
  const mins=mnths.map((_,i)=>{const v=Object.entries(byMonth[i+1]?.years||{}).map(([y,v])=>({y,avg:v.reduce((a,b)=>a+b,0)/v.length}));return Math.min(...v.map(a=>a.avg))});
  CH.monthly=new Chart($('chart-monthly'),{type:'line',data:{labels:mnths,datasets:[{label:'Avg',data:means,borderColor:'#f97316',backgroundColor:'rgba(249,115,22,0.08)',fill:true,tension:0.4,pointRadius:3,pointBackgroundColor:'#f97316'},{label:'Max',data:maxes,borderColor:'#ef4444',borderDash:[4,3],pointRadius:0,tension:0.4},{label:'Min',data:mins,borderColor:'#3b82f6',borderDash:[4,3],pointRadius:0,tension:0.4}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{color:'#a1a1aa',font:{size:10},usePointStyle:true}}},scales:{x:{grid:{display:false},ticks:{color:'#52525b',font:{size:10}}},y:{grid:{color:'rgba(255,255,255,0.03)'},ticks:{color:'#52525b',font:{size:10}}}}}});
  ['jan','jul'].forEach((m,mi)=>{const month=mi===0?1:7;
    const years=Object.entries(byMonth[month]?.years||{}).map(([y,vals])=>({y,avg:vals.reduce((a,b)=>a+b,0)/vals.length})).sort((a,b)=>a.y-b.y);
    const ll=years.map(y=>y.avg),trend=ll.map((_,i,a)=>a.slice(Math.max(0,i-10),i+1).reduce((s,v)=>s+v,0)/Math.min(11,i+1));
    CH[`month-${m}`]=new Chart($(`chart-month-${m}`),{type:'line',data:{labels:years.map(y=>y.y),datasets:[{label:'Annual',data:ll,borderColor:'#22d3ee',backgroundColor:'rgba(34,211,238,0.06)',fill:true,pointRadius:0.5,tension:0.2},{label:'10yr avg',data:trend,borderColor:'#f97316',borderWidth:2,pointRadius:0,tension:0.3}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{color:'#a1a1aa',font:{size:9},usePointStyle:true}}},scales:{x:{grid:{display:false},ticks:{color:'#52525b',font:{size:9}}},y:{grid:{color:'rgba(255,255,255,0.03)'},ticks:{color:'#52525b',font:{size:9}}}}}})});
}

function renderRecords(){
  const byYear={};
  raw.forEach(d=>{const y=d.d.slice(0,4);if(d.tmax==null)return;byYear[y]=byYear[y]||[];byYear[y].push(d.tmax)});
  const decades={};
  Object.entries(byYear).forEach(([y,vals])=>{const d=Math.floor(parseInt(y)/10)*10;decades[d]=decades[d]||{years:{}};decades[d].years[y]=vals});
  const dk=Object.keys(decades).sort(),dl=dk.map(d=>`${d}s`);
  CH.recH=new Chart($('chart-rec-high'),{type:'bar',data:{labels:dl,datasets:[{data:dk.map(dk=>Math.max(...Object.values(decades[dk].years).flat())),backgroundColor:'rgba(239,68,68,0.6)',borderRadius:4}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{display:false},ticks:{color:'#52525b',font:{size:9}}},y:{grid:{color:'rgba(255,255,255,0.03)'},ticks:{color:'#52525b',font:{size:9}}}}}});
  CH.recL=new Chart($('chart-rec-low'),{type:'bar',data:{labels:dl,datasets:[{data:dk.map(dk=>Math.min(...Object.values(decades[dk].years).flat())),backgroundColor:'rgba(59,130,246,0.6)',borderRadius:4}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{display:false},ticks:{color:'#52525b',font:{size:9}}},y:{grid:{color:'rgba(255,255,255,0.03)'},ticks:{color:'#52525b',font:{size:9}}}}}});
  CH.recR=new Chart($('chart-rec-range'),{type:'bar',data:{labels:dl,datasets:[{data:dk.map((dk,i)=>Math.max(...Object.values(decades[dk].years).flat())-Math.min(...Object.values(decades[dk].years).flat())),backgroundColor:'rgba(168,85,247,0.6)',borderRadius:4}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{display:false},ticks:{color:'#52525b',font:{size:9}}},y:{grid:{color:'rgba(255,255,255,0.03)'},ticks:{color:'#52525b',font:{size:9}}}}}});
  const hotDays={};
  Object.entries(byYear).forEach(([y,vals])=>{hotDays[y]=vals.filter(v=>v>35).length});
  const hd=Object.entries(hotDays).sort((a,b)=>a[0]-b[0]);
  CH.hotD=new Chart($('chart-rec-hotdays'),{type:'line',data:{labels:hd.map(h=>h[0]),datasets:[{data:hd.map(h=>h[1]),borderColor:'#ef4444',backgroundColor:'rgba(239,68,68,0.06)',fill:true,pointRadius:0,tension:0.3}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{display:false},ticks:{color:'#52525b',font:{size:9},maxTicksLimit:15}},y:{grid:{color:'rgba(255,255,255,0.03)'},ticks:{color:'#52525b',font:{size:9}}}}}});
}

function renderScatter(){
  const pts=raw.filter(d=>d.tmax!=null&&d.tmin!=null).map(d=>({x:d.tmin,y:d.tmax}));
  CH.scatter=new Chart($('chart-scatter'),{type:'scatter',data:{datasets:[{data:pts,backgroundColor:'rgba(59,130,246,0.12)',pointRadius:2,borderColor:'rgba(59,130,246,0.3)'}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{title:{display:true,text:'Min Temp (\u00b0C)',color:'#71717a',font:{size:10}},grid:{color:'rgba(255,255,255,0.03)'},ticks:{color:'#52525b',font:{size:9}}},y:{title:{display:true,text:'Max Temp (\u00b0C)',color:'#71717a',font:{size:10}},grid:{color:'rgba(255,255,255,0.03)'},ticks:{color:'#52525b',font:{size:9}}}}}});
  const bins={};raw.forEach(d=>{if(d.tmax==null)return;const b=Math.floor(d.tmax/2)*2;bins[b]=bins[b]||[];bins[b].push(d.tmax)});
  const bl=Object.keys(bins).sort((a,b)=>a-b);
  CH.dist=new Chart($('chart-dist'),{type:'bar',data:{labels:bl.map(b=>b+'\u00b0'),datasets:[{data:bl.map(b=>bins[b].length),backgroundColor:'rgba(139,92,246,0.4)',borderRadius:2}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{display:false},ticks:{color:'#52525b',font:{size:9}}},y:{grid:{color:'rgba(255,255,255,0.03)'},ticks:{color:'#52525b',font:{size:9}}}}}});
}

async function renderCompare(){
  const sel=$('compare-stns');sel.innerHTML='';
  const sts=await(await fetch('/api/stations')).json();
  if(sts.error)return;
  const act=['066214','086338','009021'];
  sts.forEach(s=>{
    const btn=document.createElement('button');
    btn.className=`px-3 py-1.5 rounded-xl text-xs font-medium border transition-all ${act.includes(s.id)?'border-blue-500/30 text-blue-400':'border-white/5 text-zinc-500'}`;
    btn.textContent=s.name.split('(')[0].trim();
    if(act.includes(s.id))btn.style.background='rgba(59,130,246,0.1)';
    btn.onclick=async()=>{
      btn.classList.toggle('border-blue-500/30');btn.classList.toggle('text-blue-400');
      if(!btn.style.background||btn.style.background==='none')btn.style.background='rgba(59,130,246,0.1)';else btn.style.background='none';
      await renderCompareChart();
    };
    sel.appendChild(btn);
  });
  await renderCompareChart();
}

async function renderCompareChart(){
  const btns=document.querySelectorAll('#compare-stns button');
  const active=[];btns.forEach((b,i)=>{if(b.style.background&&b.style.background!=='none')active.push(i)});
  const sts=await(await fetch('/api/stations')).json();
  if(sts.error)return;
  const colors=['#f97316','#22d3ee','#818cf8','#34d399','#f472b6','#fbbf24','#a78bfa','#fb923c'];
  const datasets=[];
  for(let idx of active){
    const s=sts[idx];if(!s)continue;
    try{
      const r=await(await fetch(`/api/anomaly/${s.id}?source=bom_acorn`)).json();
      if(r.years){
        const anomalyData=r.years.filter(y=>y.anomaly_tmax!=null).map(y=>({x:y.year,y:y.anomaly_tmax}));
        datasets.push({label:s.name.split('(')[0].trim(),data:anomalyData,borderColor:colors[datasets.length%colors.length],backgroundColor:colors[datasets.length%colors.length]+'11',fill:true,pointRadius:0,tension:0.3});
      }
    }catch(e){}
  }
  if(CH.compare)CH.compare.destroy();
  CH.compare=new Chart($('chart-compare'),{type:'line',data:{datasets},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{color:'#a1a1aa',font:{size:10},usePointStyle:true}}},scales:{x:{type:'category',grid:{color:'rgba(255,255,255,0.03)'},ticks:{color:'#52525b',font:{size:9}}},y:{title:{display:true,text:'Anomaly (\u00b0C)',color:'#71717a',font:{size:10}},grid:{color:'rgba(255,255,255,0.03)'},ticks:{color:'#52525b',font:{size:9}}}}}});
}

function renderTable(){
  if(!raw.length){$('tbl').innerHTML='<div class="text-center py-16 text-zinc-700 text-sm">No data</div>';$('pp').disabled=true;$('np').disabled=true;$('pi').textContent='0';return}
  const tp=Math.ceil(raw.length/PAGE),s=pg*PAGE,e=Math.min(s+PAGE,raw.length),p=raw.slice(s,e);
  $('pp').disabled=pg<=0;$('np').disabled=pg>=tp-1;$('pi').textContent=`${pg+1}/${tp}`;
  $('tbl').innerHTML=`<table class="w-full text-xs"><thead><tr class="text-zinc-600 border-b border-white/5"><th class="text-left py-3 px-6 font-medium">Date</th><th class="text-right py-3 px-6 font-medium">Max</th><th class="text-right py-3 px-6 font-medium">Min</th></tr></thead><tbody>${p.map(d=>`<tr class="border-b border-white/5 hover:bg-white/[0.01]"><td class="py-2.5 px-6 text-zinc-300 font-mono text-[11px]">${d.d}</td><td class="py-2.5 px-6 text-right font-mono text-[11px] ${d.tmax!=null?'text-orange-400':'text-zinc-700'}">${d.tmax!=null?d.tmax.toFixed(1)+'\u00b0':'-'}</td><td class="py-2.5 px-6 text-right font-mono text-[11px] ${d.tmin!=null?'text-blue-400':'text-zinc-700'}">${d.tmin!=null?d.tmin.toFixed(1)+'\u00b0':'-'}</td></tr>`).join('')}</tbody></table><div class="text-center text-xs text-zinc-700 py-4 font-mono">${s+1}\u2013${e} of ${raw.length.toLocaleString()}</div>`;
}

$('load-btn').addEventListener('click',()=>{const sid=$('stn').value;if(sid)selectStation(sid)});
$('pp').addEventListener('click',()=>{if(pg>0){pg--;renderTable()}});
$('np').addEventListener('click',()=>{if((pg+1)*PAGE<raw.length){pg++;renderTable()}});
document.querySelectorAll('.tab').forEach(t=>t.addEventListener('click',function(){
  document.querySelectorAll('.tab').forEach(x=>{x.classList.remove('tab-active');x.classList.add('text-zinc-500')});
  this.classList.add('tab-active');this.classList.remove('text-zinc-500');
  document.querySelectorAll('.view').forEach(v=>v.classList.add('hidden'));
  $(`v-${this.dataset.tab}`).classList.remove('hidden');
  setTimeout(()=>renderAll(),50);
}));

['yr-s','yr-e'].forEach(id=>{
  const el=$(id);
  el.addEventListener('input',function(){
    const s=parseInt($('yr-s').value),e=parseInt($('yr-e').value);
    if(s>e){if(this.id==='yr-s')$('yr-e').value=s;else $('yr-s').value=e;}
    $('yl').textContent=$('yr-s').value;
    $('yr').textContent=$('yr-e').value;
  });
});

async function checkHealth(){
  try{
    const h=await(await fetch('/api/health')).json();
    if(h.database?.connected){
      $('status-dot').className='w-1.5 h-1.5 rounded-full bg-emerald-500';$('status-text').textContent='Connected';
      const c=await(await fetch('/api/counts')).json();
      $('rec-count').textContent=Object.values(c).reduce((a,b)=>a+b,0).toLocaleString()+' records';
    }
  }catch(e){}
}

async function init(){
  $('yr-s').value=2014;$('yr-e').value=2024;$('yl').textContent='2014';$('yr').textContent='2024';
  checkHealth();
  try{
    stns=await(await fetch('/api/stations')).json();
    if(stns.error)throw new Error(stns.error);
    const sel=$('stn');sel.innerHTML=stns.map(s=>`<option value="${s.id}">${s.name}</option>`).join('');
    const gs=stns.find(s=>DATA_STNS.includes(s.id));if(gs)sel.value=gs.id;
    drawMap();
  }catch(e){$('error').textContent=e.message;$('error').classList.remove('hidden')}
}
init();
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def homepage(): return HOME

@app.get("/data", response_class=HTMLResponse)
def data_page(): return HOME
