import psycopg2
import psycopg2.extras
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def get_connection():
    return psycopg2.connect(DATABASE_URL)

def create_table():
    conn = get_connection()
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

def insert_observation(station_wmo: int, data: dict):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO raw_observations (station_wmo, raw_json)
        VALUES (%s, %s)
    """, (station_wmo, psycopg2.extras.Json(data)))
    conn.commit()
    cur.close()
    conn.close()

def get_latest_observations(limit: int = 30):
    conn = get_connection()
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
        LIMIT %s
    """, (limit,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows
