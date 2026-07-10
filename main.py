from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
import os
import asyncpg
import requests

load_dotenv()

app = FastAPI(title="RawRadar - Raw Weather Observations")

DATABASE_URL = os.getenv("DATABASE_URL")

@app.get("/", response_class=HTMLResponse)
def root():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>RawRadar</title>
        <style>
            body {
                background-color: #0f0f0f;
                color: #e0e0e0;
                font-family: Arial, sans-serif;
                text-align: center;
                padding: 50px;
            }
            h1 {
                color: #00d4ff;
            }
            button {
                background-color: #1f1f1f;
                color: #00d4ff;
                border: 1px solid #00d4ff;
                padding: 15px 30px;
                font-size: 18px;
                margin: 10px;
                cursor: pointer;
                border-radius: 8px;
            }
            button:hover {
                background-color: #00d4ff;
                color: #0f0f0f;
            }
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
async def health():
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.close()
        return {"status": "healthy", "db": "connected"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

@app.post("/setup")
async def setup_db():
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("""
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
        await conn.close()
        return {"status": "table created"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

@app.post("/ingest/station/{wmo_id}")
async def ingest_station(wmo_id: int):
    url = f"http://www.bom.gov.au/fwo/IDV60901/IDV60901.{wmo_id}.json"
    try:
        response = requests.get(url)
        data = response.json()
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("""
            INSERT INTO raw_observations (station_wmo, raw_json)
            VALUES ($1, $2)
        """, wmo_id, data)
        await conn.close()
        return {"status": "success", "station": wmo_id}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
