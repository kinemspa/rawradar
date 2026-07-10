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

@app.post("/ingest/station/{wmo_id}")
async def ingest_station(wmo_id: int):
    url = f"http://www.bom.gov.au/fwo/IDV60901/IDV60901.{wmo_id}.json"
    try:
        response = requests.get(url)
        data = response.json()
        return {"status": "success", "station": wmo_id, "records": len(data.get('observations', {}).get('data', []))}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
