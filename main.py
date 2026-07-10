from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
import os
import psycopg2
import psycopg2.extras
import requests
import json

load_dotenv()

app = FastAPI(title="RawRadar - Raw Weather Observations")

DATABASE_URL = os.getenv("DATABASE_URL")

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "http://www.bom.gov.au/"
}

@app.get("/", response_class=HTMLResponse)
def root():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>RawRadar</title>
        <style>
            body { background-color: #0f0f0f; color: #e0e0e0; font-family: Arial, sans-serif; text-align: center; padding: 50px; }
            h1 { color: #00d4ff; }
            button { background-color: #1f1f1f; color: #00d4ff; border: 1px solid #00d4ff; padding: 15px 30px; font-size: 18px; margin: 10px; cursor: pointer; border-radius: 8px; }
            button:hover { background-color: #00d4ff; color: #0f0f0f; }
        </style>
    </head>
    <body>
        <h1>RawRadar</h1>
        <p>Tracking original weather data.</p>
        <button onclick="window.location.href='/setup'">1. Setup Database Table</button><br>
        <button onclick="window.location.href='/ingest/station/95936'">2. Fetch Melbourne Raw Data</button>
    </body>
    </html>
    """

@app.get("/health")
def health():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.close()
        return {"status": "healthy", "db": "connected"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

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

@app.get("/ingest/station/{wmo_id}")
def ingest_station(wmo_id: int):
    url = f"http://www.bom.gov.au/fwo/IDV60901/IDV60901.{wmo_id}.json"
    try:
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            return {"status": "error", "detail": f"BOM returned status {response.status_code}"}
        
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
