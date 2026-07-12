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
    limit = 100000
    m = re.search(r"LIMIT (\d+)", sql)
    if m: limit = min(int(m.group(1)), 100000)
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
def api_data(station_id:str,source:str=None,from_date:str=Query(None,alias="from"),to_date:str=Query(None,alias="to"),limit:int=100000):
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
        data=api_data(station_id,source,from_date,to_date,100000)
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
.glass{background:rgba(15,23,42,0.75);backdrop-filter:blur(16px)}
.data-label{background:rgba(15,23,42,0.85);border:1px solid rgba(103,232,249,0.3);box-shadow:0 0 10px rgba(103,232,249,0.15)}
.nav-item{transition:all 0.2s;cursor:pointer;border-radius:0.5rem;padding:12px 16px}
.nav-item:hover{background:rgba(255,255,255,0.04)}
.nav-item.active{background:rgba(103,232,249,0.1);color:#67e8f9}
.metric-row{transition:all 0.2s;padding:4px 4px;border-radius:12px}
.metric-row:hover{background:rgba(103,232,249,0.05);transform:translateX(2px)}
.section-header{font-size:0.75rem;letter-spacing:1.5px;font-weight:600;color:rgba(255,255,255,0.7)}
.stat-value{font-variant-numeric:tabular-nums}
input[type=range]{-webkit-appearance:none;appearance:none;height:4px;background:rgba(255,255,255,0.1);border-radius:2px;outline:none;width:100%;cursor:pointer}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:18px;height:18px;border-radius:50%;background:#67e8f9;border:2px solid rgba(255,255,255,0.3);cursor:pointer;box-shadow:0 0 10px rgba(103,232,249,0.4)}
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
<div><span class="font-display text-3xl font-semibold tracking-tighter">AUSCLIMA</span><div class="text-[10px] text-cyan-400/80 -mt-1 tracking-[2px]">HISTORICAL DATA AGGREGATOR</div></div></div>
<div class="flex items-center gap-x-2 bg-white/5 border border-white/10 rounded-3xl px-1.5 py-1.5">
<button onclick="adjustTimeline(-1)" class="w-8 h-8 flex items-center justify-center text-cyan-400 hover:bg-white/10 rounded-2xl transition-colors"><i class="fa-solid fa-chevron-left text-sm"></i></button>
<div class="px-5 text-center"><div class="text-xs text-white/60 tracking-widest">TIME HORIZON</div><div id="time-horizon" class="font-mono text-xl font-semibold tracking-tighter">1889 &mdash; 2024+</div></div>
<button onclick="adjustTimeline(1)" class="w-8 h-8 flex items-center justify-center text-cyan-400 hover:bg-white/10 rounded-2xl transition-colors"><i class="fa-solid fa-chevron-right text-sm"></i></button>
</div>
<div class="flex items-center gap-x-3 bg-white/5 border border-white/10 rounded-3xl px-4 py-2">
<div><div class="flex items-center gap-x-2"><span class="text-xs text-white/60 tracking-widest">DATABASE</span><span class="px-2 py-px rounded bg-emerald-500/10 text-emerald-400 text-[10px] font-mono" id="db-status-badge">LIVE</span></div></div>
<div class="ml-3 pl-3 border-l border-white/10"><span class="text-xs text-white/60 tracking-widest">RECORDS</span><div class="font-mono text-sm text-cyan-400" id="rec-count">748K</div></div>
</div>
</div></div></div>

<div class="max-w-[1480px] mx-auto px-8 pt-6 pb-4">
<div class="flex gap-6">
<div class="w-56 flex-shrink-0">
<div class="glass border border-white/10 rounded-3xl p-2">
<div class="nav-item active flex items-center gap-x-3" onclick="showView('dashboard')"><i class="fa-solid fa-th-large w-4 text-cyan-400"></i><span class="font-medium text-sm">DASHBOARD</span></div>
<div class="nav-item flex items-center gap-x-3" onclick="showView('observations')"><i class="fa-solid fa-satellite w-4 text-white/70"></i><span class="font-medium text-sm">OBSERVATIONS</span></div>
<div class="nav-item flex items-center gap-x-3" onclick="showView('extremes')"><i class="fa-solid fa-temperature-high w-4 text-white/70"></i><span class="font-medium text-sm">EXTREMES</span></div>
<div class="nav-item flex items-center gap-x-3" onclick="showView('trends')"><i class="fa-solid fa-chart-line w-4 text-white/70"></i><span class="font-medium text-sm">TRENDS</span></div>
<div class="nav-item flex items-center gap-x-3" onclick="showView('models')"><i class="fa-solid fa-brain w-4 text-white/70"></i><span class="font-medium text-sm">MODELS</span></div>
<div class="nav-item flex items-center gap-x-3" onclick="showView('alerts')"><i class="fa-solid fa-bell w-4 text-white/70"></i><span class="font-medium text-sm">ALERTS</span></div>
<div class="nav-item flex items-center gap-x-3" onclick="showView('datavault')"><i class="fa-solid fa-database w-4 text-white/70"></i><span class="font-medium text-sm">DATA VAULT</span></div>
</div>
<div class="mt-4 px-4"><div class="text-[10px] text-white/40 tracking-widest mb-2 px-1">SYSTEM STATUS</div>
<div class="flex items-center justify-between text-xs bg-white/5 border border-white/10 rounded-2xl px-3 py-2"><div class="flex items-center gap-x-2"><i class="fa-solid fa-check-circle text-emerald-400"></i><span class="text-emerald-400 text-xs" id="sys-status">All systems nominal</span></div></div>
</div></div>

<div class="flex-1 min-w-0">
<div class="relative border border-white/10 rounded-[2rem] overflow-hidden shadow-2xl" style="height:560px;box-shadow:0 25px 60px -15px rgba(0,0,0,0.5),0 0 0 1px rgba(103,232,249,0.08) inset;background:#050d1a">
<div class="absolute inset-0 bg-[radial-gradient(#1e3a5f_0.6px,transparent_1px)] bg-[length:3px_3px] opacity-60"></div>
<svg id="map-svg" width="100%" height="100%" viewBox="0 0 900 620" class="absolute inset-0">
<defs><radialGradient id="globeGrad" cx="45%" cy="35%" r="75%" fx="40%" fy="30%"><stop offset="0%" stop-color="#1e3a5f"/><stop offset="55%" stop-color="#0f172a"/><stop offset="100%" stop-color="#020617"/></radialGradient><linearGradient id="ausGrad" x1="30%" y1="20%" x2="75%" y2="85%"><stop offset="0%" stop-color="#f97316"/><stop offset="35%" stop-color="#fb923c"/><stop offset="65%" stop-color="#f43f5e"/><stop offset="100%" stop-color="#e11d48"/></linearGradient><filter id="neonGlow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur in="SourceGraphic" stdDeviation="3.5" result="coloredBlur"/><feMerge><feMergeNode in="coloredBlur"/><feMergeNode in="SourceGraphic"/></feMerge></filter><filter id="softGlow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur in="SourceGraphic" stdDeviation="2" result="coloredBlur"/><feMerge><feMergeNode in="coloredBlur"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
<ellipse cx="450" cy="310" rx="395" ry="275" fill="none" stroke="#67e8f9" stroke-width="3" opacity="0.12"/><ellipse cx="450" cy="310" rx="375" ry="260" fill="none" stroke="#67e8f9" stroke-width="1.5" opacity="0.2"/>
<ellipse cx="450" cy="310" rx="365" ry="255" fill="url(#globeGrad)" stroke="#334155" stroke-width="1"/>
<g id="aus-group"><path d="M 269.5 457.4 L 232.8 471.5 L 222.1 489.0 L 194.0 491.2 L 163.5 489.8 L 139.0 500.7 L 123.9 505.2 L 100.8 510.5 L 67.9 498.4 L 58.1 484.0 L 70.7 477.1 L 72.4 457.2 L 60.2 426.9 L 57.9 405.4 L 49.8 387.5 L 39.0 365.2 L 25.5 342.2 L 27.5 332.8 L 42.6 345.6 L 32.8 321.1 L 26.5 309.5 L 32.5 293.9 L 33.1 273.4 L 42.4 274.2 L 65.9 254.9 L 89.7 239.9 L 103.7 240.8 L 130.2 231.6 L 138.2 225.8 L 168.7 220.7 L 183.9 202.2 L 196.0 185.1 L 209.7 158.8 L 225.9 171.3 L 225.1 153.2 L 235.8 142.9 L 250.8 126.2 L 260.7 117.7 L 269.4 115.2 L 287.0 109.9 L 311.6 129.7 L 335.6 131.7 L 340.7 106.1 L 346.3 96.5 L 366.2 79.0 L 391.9 77.7 L 377.6 61.8 L 400.4 63.8 L 426.6 76.3 L 443.8 80.2 L 462.1 76.5 L 475.3 82.2 L 463.0 99.9 L 458.6 108.1 L 446.2 126.9 L 462.8 142.6 L 487.3 155.2 L 506.4 166.3 L 519.3 177.0 L 550.0 177.0 L 557.6 158.4 L 565.8 133.1 L 564.5 118.5 L 564.8 93.4 L 565.5 83.3 L 573.7 62.9 L 581.3 50.4 L 587.9 71.5 L 593.5 81.7 L 601.8 102.0 L 608.0 123.7 L 626.6 124.6 L 633.7 140.3 L 640.7 165.9 L 650.7 184.4 L 655.0 207.0 L 689.1 225.8 L 699.3 238.6 L 717.7 270.9 L 733.0 274.9 L 741.0 292.1 L 763.3 310.9 L 783.6 341.4 L 782.7 363.8 L 790.7 396.6 L 782.3 422.2 L 778.9 446.5 L 756.4 473.0 L 743.0 497.0 L 730.1 522.7 L 722.8 549.8 L 712.9 562.4 L 673.9 570.8 L 653.7 586.2 L 626.2 574.5 L 618.8 568.3 L 585.7 576.8 L 563.9 572.5 L 533.2 555.4 L 525.2 531.5 L 497.5 521.6 L 499.2 498.4 L 472.9 514.9 L 485.8 493.6 L 491.6 470.3 L 464.2 492.9 L 442.1 500.2 L 430.7 476.4 L 424.2 465.0 L 386.5 453.0 L 334.0 445.6 L 287.6 458.7 Z" fill="url(#ausGrad)" stroke="#bae6fd" stroke-width="2.5" filter="url(#neonGlow)"/></g>
<g id="tas-group"><ellipse cx="520" cy="530" rx="28" ry="18" fill="#67e8f9" stroke="#bae6fd" stroke-width="1.5" opacity="0.7"/></g>
<g id="pins-group"></g>
</svg>
<div id="map-loading" class="absolute inset-0 flex items-center justify-center text-white/40 text-sm">Mapping 20 stations...</div>
</div></div>

<div class="w-72 flex-shrink-0 space-y-3">
<div class="glass border border-white/10 rounded-3xl p-4">
<div class="flex items-center justify-between mb-3"><div class="section-header">AGGREGATED INSIGHTS</div><i class="fa-solid fa-sync-alt text-xs text-white/40 cursor-pointer hover:text-white/70" onclick="refreshInsights()"></i></div>
<div class="space-y-2 text-sm">
<div class="metric-row flex justify-between items-center px-1 py-1 rounded-xl"><span class="text-white/70">TEMPERATURE</span><span class="font-mono text-emerald-400 font-semibold stat-value" id="insight-temp">+1.48&deg;C</span></div>
<div class="metric-row flex justify-between items-center px-1 py-1 rounded-xl"><span class="text-white/70">RECORDS LOADED</span><span class="font-mono text-cyan-400 font-semibold stat-value" id="insight-records">0</span></div>
<div class="metric-row flex justify-between items-center px-1 py-1 rounded-xl"><span class="text-white/70">DATA RANGE</span><span class="font-mono text-amber-400 font-semibold stat-value" id="insight-range">-</span></div>
<div class="metric-row flex justify-between items-center px-1 py-1 rounded-xl"><span class="text-white/70">STATION</span><span class="font-mono text-cyan-400 font-semibold stat-value" id="insight-station">-</span></div>
</div></div>
<div class="glass border border-white/10 rounded-3xl p-4">
<div class="section-header mb-3">DATA RESOLUTION</div>
<div class="text-xs flex items-center gap-x-2 flex-wrap"><span class="px-3 py-1 bg-white/5 rounded-2xl border border-white/10">Daily</span><span class="px-3 py-1 bg-cyan-400/10 text-cyan-400 rounded-2xl border border-cyan-400/30">ACORN-SAT</span><span class="px-3 py-1 bg-white/5 rounded-2xl border border-white/10">BOM</span></div>
</div>
<div class="glass border border-white/10 rounded-3xl p-4">
<div class="section-header mb-3">TEMPORAL NAVIGATOR</div>
<div class="px-1 pt-2 pb-1">
<div class="flex justify-between text-xs text-white/60 mb-1"><span>1910</span><span id="tl-range" class="text-cyan-400 font-mono">2014-2024</span><span>2024</span></div>
<div class="relative" style="height:36px">
<input type="range" id="tl-s" min="1910" max="2024" value="2014" class="absolute top-0" style="z-index:2">
<input type="range" id="tl-e" min="1910" max="2024" value="2024" class="absolute top-0" style="background:transparent;z-index:3">
</div>
<div class="flex justify-between text-[10px] text-white/40 px-1 mt-1 font-mono"><div>1910s</div><div>1960s</div><div>2000s</div></div>
</div></div>
<div class="glass border border-white/10 rounded-3xl p-4">
<div class="section-header mb-3">SENSOR FUSION FEED</div>
<div class="flex justify-center"><svg width="160" height="62" viewBox="0 0 160 62"><g fill="none" stroke="#64748b" stroke-width="1.25"><circle cx="25" cy="18" r="6" fill="#0f172a" stroke="#67e8f9"/><circle cx="80" cy="18" r="6" fill="#0f172a" stroke="#67e8f9"/><circle cx="135" cy="18" r="6" fill="#0f172a" stroke="#67e8f9"/><circle cx="52" cy="44" r="5.5" fill="#0f172a" stroke="#67e8f9"/><circle cx="108" cy="44" r="5.5" fill="#0f172a" stroke="#67e8f9"/><path d="M31 18 L74 18"/><path d="M86 18 L129 18"/><path d="M31 22 L46 39"/><path d="M129 22 L114 39"/><path d="M58 44 L102 44"/></g><text x="25" y="55" fill="#64748b" font-size="7" text-anchor="middle">STATIONS</text><text x="80" y="55" fill="#64748b" font-size="7" text-anchor="middle">SATELLITES</text><text x="135" y="55" fill="#64748b" font-size="7" text-anchor="middle">PROBES</text></svg></div>
</div>
<div class="glass border border-white/10 rounded-3xl p-4">
<div class="section-header mb-3">PREDICTIVE PATTERN ENGINE</div>
<div class="flex justify-center items-center h-[92px]"><svg width="92" height="92" viewBox="0 0 92 92"><defs><radialGradient id="coreGrad" cx="50%" cy="50%" r="50%"><stop offset="0%" stop-color="#67e8f9"/><stop offset="100%" stop-color="#0e7490"/></radialGradient></defs><g fill="#67e8f9" opacity="0.9"><path d="M46 12 Q58 28 46 44 Q34 28 46 12"/><path d="M72 24 Q78 40 64 50 Q58 34 72 24"/><path d="M72 68 Q78 52 64 42 Q58 58 72 68"/><path d="M46 80 Q34 64 46 48 Q58 64 46 80"/><path d="M20 68 Q14 52 28 42 Q34 58 20 68"/><path d="M20 24 Q14 40 28 50 Q34 34 20 24"/></g><circle cx="46" cy="46" r="11" fill="url(#coreGrad)"/><circle cx="46" cy="46" r="5.5" fill="#fff"/></svg></div>
<div class="text-center text-[10px] text-cyan-400/70 mt-1 tracking-widest">PATTERN RECOGNITION ACTIVE</div>
</div></div></div>

<div class="mt-6 grid grid-cols-12 gap-6">
<div class="col-span-12 lg:col-span-5 glass border border-white/10 rounded-3xl p-4">
<div class="flex items-center justify-between mb-3"><div><span class="section-header">DATA AGGREGATION ENGINE</span></div><div class="text-[10px] px-3 py-1 bg-white/5 rounded-2xl border border-white/10 text-white/60">LIVE</div></div>
<div class="bg-[#020617] border border-white/10 rounded-2xl p-3">
<canvas id="chart-wave" style="height:80px;width:100%"></canvas>
</div>
<div class="mt-2 text-[10px] text-white/40 px-1 flex items-center justify-between font-mono"><span id="agg-footer">20 STATIONS</span><span id="agg-count">748,696 RECORDS</span></div>
</div>
<div class="col-span-12 lg:col-span-7 glass border border-white/10 rounded-3xl p-4">
<div class="flex items-center justify-between mb-3 px-1">
<div class="section-header">OBSERVATIONS</div>
<div class="flex items-center gap-2"><select id="stn" class="bg-white/5 border border-white/10 rounded-2xl px-3 py-1.5 text-xs text-white cursor-pointer"></select><button id="load-btn" class="px-3 py-1.5 rounded-2xl text-xs font-medium bg-gradient-to-r from-cyan-500 to-teal-500 text-white cursor-pointer">Load</button></div>
<div class="font-mono text-xs bg-white/5 border border-white/10 px-3 py-1 rounded-2xl text-cyan-400" id="year-display">2024</div>
</div>
<div id="view-container" style="min-height:250px"><div id="tbl" class="overflow-x-auto"><div class="text-center py-16 text-white/30 text-sm">Select station and click Load</div></div></div>
</div></div></div>

<script>
const PAGE=50;let raw=[],pg=0,stns=[],CH={},currentView='table';const $=id=>document.getElementById(id);
const DATA_STNS=["066214","086338","040842","009021","031011","014015","023000","094029","070351"];
const PIN_POS={"066214":{x:578,y:226},"086338":{x:505,y:244},"040842":{x:590,y:178},"009021":{x:345,y:217},"031011":{x:555,y:120},"014015":{x:420,y:60},"023000":{x:470,y:230},"094029":{x:525,y:273},"070351":{x:545,y:235},"004032":{x:365,y:130},"032040":{x:565,y:145},"076031":{x:510,y:225},"037010":{x:485,y:140},"072150":{x:545,y:238},"015590":{x:440,y:160},"091311":{x:530,y:265},"039083":{x:570,y:175},"003003":{x:385,y:115},"012038":{x:395,y:200},"068072":{x:570,y:230}};

function drawMap(){
  const svg=$('map-svg');const ns='http://www.w3.org/2000/svg';
  const g=svg.querySelector('#pins-group');if(!g)return;
  g.innerHTML='';
  stns.forEach(s=>{
    const pin=PIN_POS[s.id];if(!pin||!DATA_STNS.includes(s.id))return;
    const c=document.createElementNS(ns,'circle');
    c.setAttribute('cx',pin.x);c.setAttribute('cy',pin.y);
    c.setAttribute('r','4.5');c.setAttribute('fill','#67e8f9');
    c.setAttribute('stroke','rgba(255,255,255,0.3)');c.setAttribute('stroke-width','1.5');
    c.setAttribute('class','pin');c.dataset.id=s.id;
    c.addEventListener('click',()=>selectStation(s.id));
    g.appendChild(c);
    const t=document.createElementNS(ns,'text');
    t.setAttribute('x',pin.x);t.setAttribute('y',pin.y-10);
    t.setAttribute('fill','#94a3b8');t.setAttribute('font-size','8');
    t.setAttribute('text-anchor','middle');
    t.textContent=s.name.split('(')[0].trim();
    g.appendChild(t);
  });
  $('map-loading').classList.add('hidden');
}

async function selectStation(id){
  $('stn').value=id;
  const f=$('tl-s').value+'-01-01',t=$('tl-e').value+'-12-31';
  try{
    const r=await fetch(`/api/data/${id}?from=${f}&to=${t}&limit=100000`);
    if(!r.ok)throw new Error();
    raw=await r.json();if(raw.error)throw new Error();pg=0;
    const n=$('stn').selectedOptions[0]?.text||id;
    $('insight-records').textContent=raw.length.toLocaleString();
    $('insight-station').textContent=n.split('(')[0].trim();
    if(raw.length){const mx=raw.reduce((a,b)=>Math.max(a,b.tmax||0),0);$('insight-temp').textContent='+'+mx.toFixed(1)+'\u00b0C max'}
    if(raw[0])$('insight-range').textContent=raw[0].d.slice(0,4)+' - '+raw[raw.length-1].d.slice(0,4);
    renderTable();renderWave();
  }catch(e){$('insight-records').textContent='Error'}
}

function refreshInsights(){
  const metrics=document.querySelectorAll('.metric-row .stat-value');
  metrics.forEach((m,i)=>{setTimeout(()=>{m.style.transform='scale(1.1)';setTimeout(()=>{m.style.transform='scale(1)'},180)},i*80)});
}

function showView(view){
  document.querySelectorAll('.nav-item').forEach(x=>x.classList.remove('active'));
  event.currentTarget.classList.add('active');
  if(view==='dashboard')renderTable();
}

function renderTable(){
  if(!raw.length){$('tbl').innerHTML='<div class="text-center py-16 text-white/30 text-sm">No data</div>';return}
  const tp=Math.ceil(raw.length/PAGE),s=pg*PAGE,e=Math.min(s+PAGE,raw.length),p=raw.slice(s,e);
  $('tbl').innerHTML=`<table class="w-full text-xs"><thead><tr class="text-white/40 border-b border-white/5"><th class="text-left py-2 px-3 font-medium">Date</th><th class="text-right py-2 px-3 font-medium">Max</th><th class="text-right py-2 px-3 font-medium">Min</th></tr></thead><tbody>${p.map(d=>`<tr class="border-b border-white/5 hover:bg-white/5"><td class="py-1.5 px-3 text-white/70 font-mono">${d.d}</td><td class="py-1.5 px-3 text-right font-mono ${d.tmax!=null?'text-orange-400':'text-white/20'}">${d.tmax!=null?d.tmax.toFixed(1)+'\u00b0':'-'}</td><td class="py-1.5 px-3 text-right font-mono ${d.tmin!=null?'text-cyan-400':'text-white/20'}">${d.tmin!=null?d.tmin.toFixed(1)+'\u00b0':'-'}</td></tr>`).join('')}</tbody></table><div class="text-center text-white/40 py-2 font-mono text-[10px]">${s+1}\u2013${e} of ${raw.length.toLocaleString()}</div><div class="flex justify-center gap-2 pb-2"><button id="pp" class="px-3 py-1 rounded-xl bg-white/5 text-white/50 disabled:opacity-30 text-xs border border-white/10">&larr;</button><span class="text-xs text-white/50 font-mono px-2 py-1">${pg+1}/${tp}</span><button id="np" class="px-3 py-1 rounded-xl bg-white/5 text-white/50 disabled:opacity-30 text-xs border border-white/10">&rarr;</button></div>`;
  $('pp').addEventListener('click',()=>{if(pg>0){pg--;renderTable()}});
  $('np').addEventListener('click',()=>{if((pg+1)*PAGE<raw.length){pg++;renderTable()}});
}

function renderWave(){
  if(CH.wave)CH.wave.destroy();
  if(!raw.length)return;
  const data=raw.slice(-200).map(d=>d.tmax||0);
  const labels=raw.slice(-200).map(d=>d.d.slice(5,10));
  CH.wave=new Chart($('chart-wave'),{type:'line',data:{labels,datasets:[{data,borderColor:'#c026ff',backgroundColor:'rgba(192,38,255,0.05)',fill:true,pointRadius:0,tension:0.4,borderWidth:2.5}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{enabled:false}},scales:{x:{display:false},y:{display:false,grid:{display:false}}}}});
  CH.wave2=new Chart($('chart-wave2'),{type:'line',data:{labels,datasets:[{data,borderColor:'#67e8f9',backgroundColor:'rgba(103,232,249,0.05)',fill:true,pointRadius:0,tension:0.4,borderWidth:2.5}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{display:false},y:{display:false}}}});
}

function updateTimeline(){
  const s=parseInt($('tl-s').value),e=parseInt($('tl-e').value);
  if(s>e){$('tl-s').value=e;$('tl-e').value=s;}
  $('tl-range').textContent=$('tl-s').value+'-'+$('tl-e').value;
}
function adjustTimeline(d){const s=$('tl-s'),e=$('tl-e');let v=parseInt(e.value)+d;v=Math.max(1910,Math.min(2024,v));e.value=v;if(parseInt(s.value)>v)s.value=v;updateTimeline()}

$('load-btn').addEventListener('click',()=>{const sid=$('stn').value;if(sid)selectStation(sid)});
['tl-s','tl-e'].forEach(id=>{$(id).addEventListener('input',updateTimeline)});

async function init(){
  $('tl-s').value=2014;$('tl-e').value=2024;updateTimeline();
  try{
    stns=await(await fetch('/api/stations')).json();
    if(stns.error)throw new Error(stns.error);
    const sel=$('stn');sel.innerHTML=stns.map(s=>`<option value="${s.id}">${s.name}</option>`).join('');
    const gs=stns.find(s=>DATA_STNS.includes(s.id));if(gs)sel.value=gs.id;
    drawMap();
  }catch(e){}
}
init();
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def homepage(): return HOME

@app.get("/data", response_class=HTMLResponse)
def data_page(): return HOME
