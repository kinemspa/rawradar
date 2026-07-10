from fastapi import FastAPI
from dotenv import load_dotenv
import os
import asyncpg
import requests

load_dotenv()

app = FastAPI(title="RawRadar - Raw Weather Observations")

DATABASE_URL = os.getenv("DATABASE_URL")

@app.get("/")
def root():
    return {"message": "RawRadar is running. Tracking original weather data."}

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
