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
    q = []
    cols = "date,tmax,tmin,source"
    if "id,name,source" in sql or "id, name, source" in sql: cols = "id,name,source,latitude,longitude,elevation"
    if "COUNT(*)" in sql: return [("bom_acorn", 748696)]
    if params:
        date_idx = 0
        for p in params:
            if p in ("bom_acorn", "bom_api", "noaa_ghcn"): q.append(("source", f"eq.{p}"))
            elif isinstance(p, str) and len(p) == 10 and p[4] == "-":
                if "date >= %s" in sql and date_idx == 0: q.append(("date", f"gte.{p}")); date_idx += 1
                elif "date <= %s" in sql: q.append(("date", f"lte.{p}"))
                else: q.append(("date", f"eq.{p}"))
            elif isinstance(p, str) and len(p) == 6 and p.isdigit(): q.append(("station_id", f"eq.{p}"))
    order = "date.asc"
    m = re.search(r"ORDER BY (\w+)\s*(ASC|DESC)?", sql)
    if m: order = m.group(1) + (".desc" if m.group(2) == "DESC" else ".asc")
    limit = 50000
    m = re.search(r"LIMIT (\d+)", sql)
    if m: limit = min(int(m.group(1)), 50000)
    if "SELECT 1" in sql: return [(1,)]
    if "MIN(date)" in sql:
        h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        f = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=h, params=q+[("select","date"),("order","date.asc"),("limit","1")], timeout=10).json()
        l = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=h, params=q+[("select","date"),("order","date.desc"),("limit","1")], timeout=10).json()
        return [(f[0]["date"][:10] if f else None, l[0]["date"][:10] if l else None)]
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=headers, params=q+[("select",cols),("order",order),("limit",str(limit))], timeout=30)
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
        if from_date: clauses.append("date >= %s"); params.append(from_date)
        if to_date: clauses.append("date <= %s"); params.append(to_date)
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
<title>AUSCLIMA</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=Space+Grotesk:wght@500;600&display=swap" rel="stylesheet">
<style>
:root{--accent-cyan:#67e8f9}
body{font-family:'Inter',system-ui,sans-serif;background:#020617;color:white;overflow-x:hidden}
.font-display{font-family:'Space Grotesk','Inter',sans-serif;font-weight:600}
.glass{background:rgba(15,23,42,0.75);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px)}
.data-label{background:rgba(15,23,42,0.85);border:1px solid rgba(103,232,249,0.3);box-shadow:0 0 10px rgba(103,232,249,0.15)}
.nav-item{transition:all 0.2s ease;cursor:pointer}
.nav-item.active{background:rgba(103,232,249,0.1);color:#67e8f9;border-radius:0.5rem}
.metric-row{transition:all 0.2s ease}
.metric-row:hover{background:rgba(103,232,249,0.05);transform:translateX(2px)}
.section-header{font-size:0.75rem;letter-spacing:1.5px;font-weight:600}
.stat-value{font-variant-numeric:tabular-nums}
input[type=range]{-webkit-appearance:none;appearance:none;height:6px;background:rgba(255,255,255,0.1);border-radius:3px;outline:none;width:100%;cursor:pointer}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:20px;height:20px;border-radius:50%;background:#67e8f9;border:2px solid rgba(255,255,255,0.3);cursor:pointer;box-shadow:0 0 12px rgba(103,232,249,0.5)}
table{width:100%;border-collapse:collapse;font-size:14px}
th{text-align:left;padding:12px 16px;font-weight:500;color:#64748b;border-bottom:1px solid rgba(255,255,255,0.05)}
td{padding:8px 16px;border-bottom:1px solid rgba(255,255,255,0.03);font-family:monospace}
tr:hover{background:rgba(255,255,255,0.02)}
.tab{transition:all 0.2s;cursor:pointer;padding:8px 20px;border-radius:12px;font-size:13px;border:1px solid rgba(255,255,255,0.08);color:#64748b}
.tab:hover{background:rgba(103,232,249,0.05)}
.tab-active{background:rgba(103,232,249,0.1);border-color:rgba(103,232,249,0.3);color:#67e8f9}
.pin{animation:pulse 2s ease-in-out infinite;cursor:pointer}.pin:hover{filter:brightness(1.3)}
@keyframes pulse{0%,100%{opacity:0.6}50%{opacity:1}}
</style>
</head>
<body>
<div class="border-b border-white/10 bg-[#020617]/95 backdrop-blur-xl sticky top-0 z-50">
<div class="max-w-[1480px] mx-auto px-8"><div class="flex items-center justify-between h-16">
<div class="flex items-center gap-x-3">
<div class="flex items-center justify-center w-9 h-9 rounded-2xl bg-gradient-to-br from-cyan-400 to-teal-500 p-1.5 shadow-inner">
<svg width="28" height="28" viewBox="0 0 24 24" fill="none"><path d="M12 3L20 7.5V16.5L12 21L4 16.5V7.5L12 3Z" stroke="white" stroke-width="2.5" stroke-linejoin="round"/><path d="M12 21V12M12 12L20 7.5M12 12L4 7.5" stroke="white" stroke-width="2" stroke-linejoin="round"/></svg>
</div>
<div><span class="font-display text-3xl font-semibold tracking-tighter">AUSCLIMA</span>
<div class="text-[10px] text-cyan-400/80 -mt-1 tracking-[2px]">HISTORICAL DATA AGGREGATOR</div></div></div>
<div class="flex items-center gap-x-4">
<select id="stn" class="bg-white/5 border border-white/10 rounded-2xl px-4 py-2 text-sm text-white cursor-pointer" style="min-width:200px"></select>
<button id="load-btn" class="px-5 py-2 rounded-2xl text-sm font-medium bg-gradient-to-r from-cyan-500 to-teal-500 text-white shadow-lg hover:shadow-cyan-500/25 transition-all">Load</button>
<span class="text-xs text-white/60" id="rec-count"></span>
<button id="status-btn" class="flex items-center gap-2 px-3 py-1.5 rounded-2xl text-xs border border-white/10 bg-white/5"><span id="status-dot" class="w-1.5 h-1.5 rounded-full bg-zinc-600"></span><span id="status-text" class="text-white/60">DB</span></button>
</div></div></div></div>

<div class="max-w-[1480px] mx-auto px-8 pt-6 pb-4">
<div class="flex gap-6">
<div class="w-56 flex-shrink-0">
<div class="glass border border-white/10 rounded-3xl p-2">
<div class="nav-item active flex items-center gap-x-3 px-4 py-3 rounded-2xl mb-1"><i class="fa-solid fa-th-large w-4 text-cyan-400"></i><span class="font-medium text-sm">DASHBOARD</span></div>
<div class="nav-item flex items-center gap-x-3 px-4 py-3 rounded-2xl mb-1 hover:bg-white/5"><i class="fa-solid fa-table w-4 text-white/70"></i><span class="font-medium text-sm">DATA TABLE</span></div>
<div class="nav-item flex items-center gap-x-3 px-4 py-3 rounded-2xl mb-1 hover:bg-white/5"><i class="fa-solid fa-calendar w-4 text-white/70"></i><span class="font-medium text-sm">CALENDAR</span></div>
<div class="nav-item flex items-center gap-x-3 px-4 py-3 rounded-2xl mb-1 hover:bg-white/5"><i class="fa-solid fa-chart-line w-4 text-white/70"></i><span class="font-medium text-sm">TRENDS</span></div>
<div class="nav-item flex items-center gap-x-3 px-4 py-3 rounded-2xl mb-1 hover:bg-white/5"><i class="fa-solid fa-temperature-high w-4 text-white/70"></i><span class="font-medium text-sm">RECORDS</span></div>
<div class="nav-item flex items-center gap-x-3 px-4 py-3 rounded-2xl mb-1 hover:bg-white/5"><i class="fa-solid fa-chart-scatter w-4 text-white/70"></i><span class="font-medium text-sm">SCATTER</span></div>
<div class="nav-item flex items-center gap-x-3 px-4 py-3 rounded-2xl hover:bg-white/5"><i class="fa-solid fa-arrows-left-right w-4 text-white/70"></i><span class="font-medium text-sm">COMPARE</span></div>
</div></div>

<div class="flex-1 min-w-0">
<div class="relative border border-white/10 rounded-[2rem] overflow-hidden shadow-2xl" style="height:560px;box-shadow:0 25px 60px -15px rgba(0,0,0,0.5),0 0 0 1px rgba(103,232,249,0.08) inset;background:#050d1a">
<div class="absolute inset-0 bg-[radial-gradient(#1e3a5f_0.6px,transparent_1px)] bg-[length:3px_3px] opacity-60"></div>
<svg id="map-svg" width="100%" height="100%" viewBox="0 0 900 620" class="absolute inset-0">
<defs>
<radialGradient id="globeGrad" cx="45%" cy="35%" r="75%" fx="40%" fy="30%"><stop offset="0%" stop-color="#1e3a5f"/><stop offset="55%" stop-color="#0f172a"/><stop offset="100%" stop-color="#020617"/></radialGradient>
<linearGradient id="ausGrad" x1="30%" y1="20%" x2="75%" y2="85%"><stop offset="0%" stop-color="#f97316"/><stop offset="35%" stop-color="#fb923c"/><stop offset="65%" stop-color="#f43f5e"/><stop offset="100%" stop-color="#e11d48"/></linearGradient>
<filter id="neonGlow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur in="SourceGraphic" stdDeviation="3.5" result="coloredBlur"/><feMerge><feMergeNode in="coloredBlur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
<filter id="softGlow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur in="SourceGraphic" stdDeviation="2" result="coloredBlur"/><feMerge><feMergeNode in="coloredBlur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
</defs>
<ellipse cx="450" cy="310" rx="395" ry="275" fill="none" stroke="#67e8f9" stroke-width="3" opacity="0.12"/>
<ellipse cx="450" cy="310" rx="375" ry="260" fill="none" stroke="#67e8f9" stroke-width="1.5" opacity="0.2"/>
<ellipse cx="450" cy="310" rx="365" ry="255" fill="url(#globeGrad)" stroke="#334155" stroke-width="1"/>
<g id="australia-group" class="australia-glow">
<path id="aus-path" d="M 304 180 L 326 177 L 353 173 L 378 173 L 398 177 L 413 184 L 425 192 L 435 200 L 443 210 L 449 221 L 452 232 L 450 243 L 446 252 L 440 259 L 433 266 L 425 272 L 416 278 L 408 284 L 400 290 L 391 296 L 383 302 L 374 307 L 366 312 L 357 316 L 350 319 L 346 324 L 342 329 L 335 334 L 327 339 L 319 342 L 312 345 L 304 347 L 296 348 L 287 350 L 276 352 L 265 354 L 255 356 L 246 358 L 236 360 L 226 363 L 217 367 L 209 372 L 202 378 L 197 385 L 192 392 L 186 401 L 179 411 L 173 421 L 167 431 L 162 441 L 157 451 L 152 461 L 147 471 L 142 481 L 137 490 L 133 498 L 130 504 L 127 509 L 123 513 L 118 516 L 112 517 L 105 516 L 99 513 L 94 509 L 89 504 L 85 497 L 83 490 L 82 482 L 83 474 L 85 466 L 88 458 L 92 451 L 96 445 L 101 439 L 106 433 L 111 428 L 117 423 L 122 419 L 128 415 L 133 411 L 139 406 L 144 401 L 149 396 L 153 391 L 157 385 L 161 379 L 164 373 L 167 367 L 169 361 L 172 354 L 175 347 L 178 340 L 180 333 L 183 326 L 186 319 L 188 312 L 191 305 L 193 299 L 196 293 L 198 287 L 201 281 L 204 276 L 207 272 L 210 268 L 214 264 L 218 260 L 222 256 L 227 252 L 232 249 L 237 246 L 243 243 L 249 240 L 256 238 L 263 236 L 270 234 L 277 233 L 284 232 L 290 232 L 296 231 L 302 230 L 307 229 L 311 226 L 314 222 L 316 218 L 316 213 L 315 207 L 312 202 L 308 197 L 303 193 L 304 180 Z" fill="url(#ausGrad)" stroke="#bae6fd" stroke-width="2.5" filter="url(#neonGlow)"/>
<ellipse cx="490" cy="550" rx="30" ry="20" fill="#67e8f9" stroke="#bae6fd" stroke-width="1.5" opacity="0.8"/>
</g>
<g id="pins-group"></g>
</svg>
<div id="map-loading" class="absolute inset-0 flex items-center justify-center text-white/40 text-sm">Loading stations...</div>
</div></div>

<div class="w-72 flex-shrink-0 space-y-3">
<div class="glass border border-white/10 rounded-3xl p-4">
<div class="flex items-center justify-between mb-3"><div class="section-header text-white/70">STATION DATA</div></div>
<div id="station-metrics" class="space-y-2 text-sm">
<div class="metric-row flex justify-between items-center px-1 py-1 rounded-xl"><span class="text-white/60">TEMPERATURE</span><span class="font-mono text-cyan-400 font-semibold stat-value" id="metric-temp">-</span></div>
<div class="metric-row flex justify-between items-center px-1 py-1 rounded-xl"><span class="text-white/60">RECORDS</span><span class="font-mono text-cyan-400 font-semibold stat-value" id="metric-records">-</span></div>
<div class="metric-row flex justify-between items-center px-1 py-1 rounded-xl"><span class="text-white/60">YEAR RANGE</span><span class="font-mono text-cyan-400 font-semibold stat-value" id="metric-years">-</span></div>
<div class="metric-row flex justify-between items-center px-1 py-1 rounded-xl"><span class="text-white/60">BASELINE</span><span class="font-mono text-cyan-400 font-semibold stat-value">1961-1990</span></div>
</div></div>
<div class="glass border border-white/10 rounded-3xl p-4">
<div class="section-header text-white/70 mb-3">YEAR RANGE</div>
<div class="px-1 pt-2 pb-1">
<input type="range" id="yr-s" min="1910" max="2024" value="2014" oninput="updateSlider()">
<input type="range" id="yr-e" min="1910" max="2024" value="2024" oninput="updateSlider()" style="margin-top:2px">
<div class="flex justify-between text-[10px] text-white/40 px-1 mt-1 font-mono"><span id="yl">1910</span><span id="yr-range" class="text-cyan-400">2014-2024</span><span id="yr">2024</span></div>
</div></div>
<div class="glass border border-white/10 rounded-3xl p-4">
<div class="section-header text-white/70 mb-3">DATABASE STATUS</div>
<div class="flex items-center justify-between text-xs bg-white/5 border border-white/10 rounded-2xl px-3 py-2"><div class="flex items-center gap-x-2"><i class="fa-solid fa-check-circle text-emerald-400"></i><span class="text-emerald-400 text-xs" id="db-status">Checking...</span></div></div>
</div></div></div>

<div class="mt-6"><div class="glass border border-white/10 rounded-3xl overflow-hidden">
<div class="flex items-center justify-between px-6 py-4 border-b border-white/10">
<div><h3 class="font-display text-lg" id="table-title">Temperature Readings</h3><p class="text-xs text-white/50" id="table-sub">Select a station</p></div>
<div class="flex gap-2" id="tabs">
<button class="tab tab-active" data-view="table">Table</button>
<button class="tab" data-view="anomaly">Anomaly</button>
<button class="tab" data-view="calendar">Calendar</button>
<button class="tab" data-view="monthly">Monthly</button>
<button class="tab" data-view="records">Records</button>
</div>
<div class="flex items-center gap-2"><button id="pp" class="px-3 py-1.5 rounded-xl bg-white/5 text-white/50 disabled:opacity-30 text-xs border border-white/10">&larr;</button><span id="pi" class="text-xs text-white/50 font-mono w-12 text-center">0</span><button id="np" class="px-3 py-1.5 rounded-xl bg-white/5 text-white/50 disabled:opacity-30 text-xs border border-white/10">&rarr;</button></div></div>
<div id="views"><div id="v-table"><div id="tbl" class="overflow-x-auto"><div class="text-center py-16 text-white/30 text-sm">Click Load to view data</div></div></div>
<div id="v-anomaly" class="hidden" style="height:350px"><canvas id="chart-anomaly"></canvas></div>
<div id="v-calendar" class="hidden" style="height:350px"><canvas id="chart-cal"></canvas></div>
<div id="v-monthly" class="hidden" style="height:350px"><canvas id="chart-monthly"></canvas></div>
<div id="v-records" class="hidden"><div class="grid grid-cols-4 gap-4 p-4"><div style="height:180px"><canvas id="chart-rec-high"></canvas></div><div style="height:180px"><canvas id="chart-rec-low"></canvas></div><div style="height:180px"><canvas id="chart-rec-range"></canvas></div><div style="height:180px"><canvas id="chart-rec-hotdays"></canvas></div></div></div>
</div></div></div></div>

<script>
const PAGE=100;let raw=[],pg=0,stns=[],CH={};const $=id=>document.getElementById(id);
const DATA_STNS=["066214","086338","040842","009021","031011","014015","023000","094029","070351"];
const PIN_POS={066214:{x:578,y:226},086338:{x:505,y:244},040842:{x:590,y:178},009021:{x:345,y:217},031011:{x:555,y:120},014015:{x:420,y:60},023000:{x:470,y:230},094029:{x:525,y:273},070351:{x:545,y:235},004032:{x:365,y:130},032040:{x:565,y:145},076031:{x:510,y:225},037010:{x:485,y:140},072150:{x:545,y:238},015590:{x:440,y:160},091311:{x:530,y:265},039083:{x:570,y:175},003003:{x:385,y:115},012038:{x:395,y:200},068072:{x:570,y:230}};

function drawMap(){
  const svg=$('map-svg');const ns='http://www.w3.org/2000/svg';
  const g=svg.querySelector('#pins-group');if(!g)return;
  g.innerHTML='';
  stns.forEach(s=>{
    const pin=PIN_POS[s.id];if(!pin)return;
    const has=DATA_STNS.includes(s.id);
    const c=document.createElementNS(ns,'circle');
    c.setAttribute('cx',pin.x);c.setAttribute('cy',pin.y);
    c.setAttribute('r',has?'5':'3.5');
    c.setAttribute('fill',has?'#67e8f9':'#64748b');
    c.setAttribute('stroke','rgba(255,255,255,0.3)');
    c.setAttribute('stroke-width','1.5');
    c.setAttribute('class','pin');
    c.dataset.id=s.id;
    c.addEventListener('click',()=>selectStation(s.id));
    g.appendChild(c);
    const t=document.createElementNS(ns,'text');
    t.setAttribute('x',pin.x);t.setAttribute('y',pin.y-10);
    t.setAttribute('fill','#94a3b8');t.setAttribute('font-size','9');
    t.setAttribute('text-anchor','middle');
    t.textContent=s.name.split('(')[0].trim();
    g.appendChild(t);
  });
  [{n:'Sydney',x:578,y:244},{n:'Perth',x:345,y:235},{n:'Melbourne',x:505,y:262},{n:'Darwin',x:420,y:78},{n:'Brisbane',x:590,y:196},{n:'Adelaide',x:470,y:248},{n:'Hobart',x:525,y:290}].forEach(c=>{
    const t=document.createElementNS(ns,'text');
    t.setAttribute('x',c.x);t.setAttribute('y',c.y);
    t.setAttribute('fill','rgba(255,255,255,0.08)');t.setAttribute('font-size','10');
    t.setAttribute('text-anchor','middle');t.textContent=c.n;
    g.appendChild(t);
  });
  $('map-loading').classList.add('hidden');
}

async function selectStation(id){
  $('stn').value=id;
  const f=$('yr-s').value+'-01-01',t=$('yr-e').value+'-12-31';
  try{
    const r=await fetch(`/api/data/${id}?from=${f}&to=${t}&limit=50000`);
    if(!r.ok)throw new Error((await r.json().catch(()=>({}))).error||`HTTP ${r.status}`);
    raw=await r.json();if(raw.error)throw new Error(raw.error);pg=0;
    const name=$('stn').selectedOptions[0]?.text||id;
    $('table-title').textContent=name;$('table-sub').textContent=raw.length?`${raw.length.toLocaleString()} readings`:'No data';
    const mn=raw.reduce((a,b)=>Math.max(a,b.tmax||0),0);
    $('metric-temp').textContent=mn?mn.toFixed(1)+'\u00b0C max':'-';
    $('metric-records').textContent=raw.length.toLocaleString();
    if(raw[0])$('metric-years').textContent=raw[0].d.slice(0,4)+'-'+raw[raw.length-1].d.slice(0,4);
    renderAll();
  }catch(e){$('error')&&($('error').textContent=e.message)};
}

function renderAll(){
  Object.values(CH).forEach(c=>{try{c.destroy()}catch(e){}});
  if(!raw.length)return;
  renderTable();renderAnomaly();renderCalendar();renderMonthly();renderRecords();
}

function updateSlider(){
  const s=parseInt($('yr-s').value),e=parseInt($('yr-e').value);
  if(s>e){$('yr-s').value=e;$('yr-e').value=s;}
  $('yl').textContent=$('yr-s').value;$('yr').textContent=$('yr-e').value;
  $('yr-range').textContent=$('yr-s').value+'-'+$('yr-e').value;
}

function renderTable(){
  if(!raw.length){$('tbl').innerHTML='<div class="text-center py-16 text-white/30 text-sm">No data</div>';$('pp').disabled=true;$('np').disabled=true;$('pi').textContent='0';return}
  const tp=Math.ceil(raw.length/PAGE),s=pg*PAGE,e=Math.min(s+PAGE,raw.length),p=raw.slice(s,e);
  $('pp').disabled=pg<=0;$('np').disabled=pg>=tp-1;$('pi').textContent=`${pg+1}/${tp}`;
  $('tbl').innerHTML=`<table><thead><tr><th>Date</th><th style="text-align:right">Max</th><th style="text-align:right">Min</th></tr></thead><tbody>${p.map(d=>`<tr><td>${d.d}</td><td style="text-align:right;color:${d.tmax!=null?'#fb923c':'#333'}">${d.tmax!=null?d.tmax.toFixed(1)+'\u00b0':'-'}</td><td style="text-align:right;color:${d.tmin!=null?'#67e8f9':'#333'}">${d.tmin!=null?d.tmin.toFixed(1)+'\u00b0':'-'}</td></tr>`).join('')}</tbody></table><div style="text-align:center;color:#64748b;padding:12px;font-family:monospace;font-size:12px">${s+1}\u2013${e} of ${raw.length.toLocaleString()}</div>`;
}

function renderAnomaly(){
  const mode='tmax',years={};
  raw.forEach(d=>{const y=d.d.slice(0,4);years[y]=years[y]||[];if(d[mode]!=null)years[y].push(d[mode])});
  const ys=Object.keys(years).sort(),annual=ys.map(y=>years[y].reduce((a,b)=>a+b,0)/years[y].length);
  const bs=ys.filter(y=>y>='1961'&&y<='1990');
  const bv=bs.length?bs.reduce((s,y)=>s+annual[ys.indexOf(y)],0)/bs.length:annual.reduce((a,b)=>a+b,0)/annual.length;
  const anom=annual.map(v=>v-bv),mx=Math.max(...anom.map(Math.abs))||1;
  const colors=anom.map(v=>v>=0?`rgba(239,68,68,${Math.min(1,v/mx*1.5)})`:`rgba(59,130,246,${Math.min(1,Math.abs(v)/mx*1.5)})`);
  CH.anomaly=new Chart($('chart-anomaly'),{type:'bar',data:{labels:ys,datasets:[{data:anom,backgroundColor:colors,borderRadius:2}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{backgroundColor:'rgba(15,23,42,0.95)',titleColor:'#e4e4e7',bodyColor:'#a1a1aa',padding:12,cornerRadius:8,displayColors:false,callbacks:{label:ctx=>`${ctx.parsed.y>0?'+':''}${ctx.parsed.y.toFixed(2)}\u00b0C`}}},scales:{x:{grid:{display:false},ticks:{color:'#64748b',font:{size:11},maxTicksLimit:20}},y:{grid:{color:'rgba(255,255,255,0.03)'},ticks:{color:'#64748b',font:{size:11},callback:v=>v+'\u00b0'}}}}});
}

function renderCalendar(){
  const byMonth={};
  raw.forEach(d=>{if(d.tmax==null)return;const m=d.d.slice(0,7);byMonth[m]=byMonth[m]||[];byMonth[m].push(d.tmax)});
  const allMonths=Object.keys(byMonth).sort().slice(-36);
  const data=allMonths.map(m=>byMonth[m].reduce((a,b)=>a+b,0)/byMonth[m].length);
  const labels=allMonths.map(m=>{const d=new Date(m+'-01');return d.toLocaleString('default',{month:'short'})+" '"+m.slice(2,4)});
  const cmax=Math.max(...data),cmin=Math.min(...data);
  CH.cal=new Chart($('chart-cal'),{type:'bar',data:{labels,datasets:[{data,backgroundColor:data.map(v=>{const t=(v-cmin)/(cmax-cmin||1);return`rgb(${Math.round(26+t*170)},${Math.round(109+t*(-109+150))},${Math.round(93+t*(-93+60))})`}),borderRadius:2}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{display:false},ticks:{color:'#64748b',font:{size:10},maxTicksLimit:36}},y:{display:false,grid:{display:false}}}}});
}

function renderMonthly(){
  const byMonth={};
  raw.forEach(d=>{if(d.tmax==null)return;const m=parseInt(d.d.slice(5,7)),y=parseInt(d.d.slice(0,4));byMonth[m]=byMonth[m]||{years:{}};byMonth[m].years[y]=byMonth[m].years[y]||[];byMonth[m].years[y].push(d.tmax)});
  const mnths=Array.from({length:12},(_,i)=>new Date(2000,i).toLocaleString('default',{month:'short'}));
  const means=mnths.map((_,i)=>{const v=Object.values(byMonth[i+1]?.years||{}).flatMap(v=>v.reduce((a,b)=>a+b,0)/v.length);return v.reduce((a,b)=>a+b,0)/v.length});
  const maxes=mnths.map((_,i)=>{const v=Object.entries(byMonth[i+1]?.years||{}).map(([y,v])=>({y,avg:v.reduce((a,b)=>a+b,0)/v.length}));return Math.max(...v.map(a=>a.avg))});
  const mins=mnths.map((_,i)=>{const v=Object.entries(byMonth[i+1]?.years||{}).map(([y,v])=>({y,avg:v.reduce((a,b)=>a+b,0)/v.length}));return Math.min(...v.map(a=>a.avg))});
  CH.monthly=new Chart($('chart-monthly'),{type:'line',data:{labels:mnths,datasets:[{label:'Avg',data:means,borderColor:'#67e8f9',backgroundColor:'rgba(103,232,249,0.06)',fill:true,tension:0.4,pointRadius:3,pointBackgroundColor:'#67e8f9'},{label:'Max',data:maxes,borderColor:'#fb923c',borderDash:[4,3],pointRadius:0,tension:0.4},{label:'Min',data:mins,borderColor:'#38bdf8',borderDash:[4,3],pointRadius:0,tension:0.4}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{color:'#a1a1aa',font:{size:11},usePointStyle:true}}},scales:{x:{grid:{display:false},ticks:{color:'#64748b',font:{size:11}}},y:{grid:{color:'rgba(255,255,255,0.03)'},ticks:{color:'#64748b',font:{size:11}}}}}});
}

function renderRecords(){
  const byYear={};
  raw.forEach(d=>{const y=d.d.slice(0,4);if(d.tmax==null)return;byYear[y]=byYear[y]||[];byYear[y].push(d.tmax)});
  const decades={};
  Object.entries(byYear).forEach(([y,vals])=>{const d=Math.floor(parseInt(y)/10)*10;decades[d]=decades[d]||{years:{}};decades[d].years[y]=vals});
  const dk=Object.keys(decades).sort(),dl=dk.map(d=>`${d}s`);
  CH.recH=new Chart($('chart-rec-high'),{type:'bar',data:{labels:dl,datasets:[{data:dk.map(dk=>Math.max(...Object.values(decades[dk].years).flat())),backgroundColor:'rgba(239,68,68,0.5)',borderRadius:4}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{display:false},ticks:{color:'#64748b',font:{size:10}}},y:{grid:{color:'rgba(255,255,255,0.03)'},ticks:{color:'#64748b',font:{size:10}}}}}});
  CH.recL=new Chart($('chart-rec-low'),{type:'bar',data:{labels:dl,datasets:[{data:dk.map(dk=>Math.min(...Object.values(decades[dk].years).flat())),backgroundColor:'rgba(59,130,246,0.5)',borderRadius:4}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{display:false},ticks:{color:'#64748b',font:{size:10}}},y:{grid:{color:'rgba(255,255,255,0.03)'},ticks:{color:'#64748b',font:{size:10}}}}}});
  CH.recR=new Chart($('chart-rec-range'),{type:'bar',data:{labels:dl,datasets:[{data:dk.map((dk,i)=>Math.max(...Object.values(decades[dk].years).flat())-Math.min(...Object.values(decades[dk].years).flat())),backgroundColor:'rgba(168,85,247,0.5)',borderRadius:4}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{display:false},ticks:{color:'#64748b',font:{size:10}}},y:{grid:{color:'rgba(255,255,255,0.03)'},ticks:{color:'#64748b',font:{size:10}}}}}});
  const hotDays={};
  Object.entries(byYear).forEach(([y,vals])=>{hotDays[y]=vals.filter(v=>v>35).length});
  const hd=Object.entries(hotDays).sort((a,b)=>a[0]-b[0]);
  CH.hotD=new Chart($('chart-rec-hotdays'),{type:'line',data:{labels:hd.map(h=>h[0]),datasets:[{data:hd.map(h=>h[1]),borderColor:'#ef4444',backgroundColor:'rgba(239,68,68,0.06)',fill:true,pointRadius:0,tension:0.3}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{grid:{display:false},ticks:{color:'#64748b',font:{size:10},maxTicksLimit:15}},y:{grid:{color:'rgba(255,255,255,0.03)'},ticks:{color:'#64748b',font:{size:10}}}}}});
}

$('load-btn').addEventListener('click',()=>{const sid=$('stn').value;if(sid)selectStation(sid)});
$('pp').addEventListener('click',()=>{if(pg>0){pg--;renderTable()}});
$('np').addEventListener('click',()=>{if((pg+1)*PAGE<raw.length){pg++;renderTable()}});
document.querySelectorAll('.tab').forEach(t=>t.addEventListener('click',function(){
  document.querySelectorAll('.tab').forEach(x=>{x.classList.remove('tab-active')});
  this.classList.add('tab-active');
  document.querySelectorAll('#views>div').forEach(v=>v.classList.add('hidden'));
  const target=document.getElementById('v-'+this.dataset.view);
  if(target)target.classList.remove('hidden');
  setTimeout(()=>renderAll(),100);
}));
document.querySelectorAll('.nav-item').forEach((item,idx)=>{
  item.addEventListener('click',function(){
    document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));
    this.classList.add('active');
    const views=['table','table','calendar','monthly','records','scatter','compare'];
    const t=document.querySelector(`.tab[data-view="${views[idx]}"]`);
    if(t)t.click();
  });
});

async function checkHealth(){
  try{
    const h=await(await fetch('/api/health')).json();
    if(h.database?.connected){
      $('status-dot').className='w-1.5 h-1.5 rounded-full bg-emerald-500';$('status-text').textContent='Connected';
      $('db-status').textContent='All systems nominal';
      const c=await(await fetch('/api/counts')).json();
      $('rec-count').textContent=Object.values(c).reduce((a,b)=>a+b,0).toLocaleString()+' records';
    }
  }catch(e){}
}

async function init(){
  $('yr-s').value=2014;$('yr-e').value=2024;updateSlider();
  checkHealth();
  try{
    stns=await(await fetch('/api/stations')).json();
    if(stns.error)throw new Error(stns.error);
    const sel=$('stn');sel.innerHTML=stns.map(s=>`<option value="${s.id}">${s.name}</option>`).join('');
    const gs=stns.find(s=>DATA_STNS.includes(s.id));if(gs)sel.value=gs.id;
    drawMap();
  }catch(e){$('error')&&($('error').textContent=e.message)}
}
init();
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def homepage(): return HOME

@app.get("/data", response_class=HTMLResponse)
def data_page(): return HOME
