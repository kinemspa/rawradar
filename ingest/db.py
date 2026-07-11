import os
import json
import hashlib
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS stations (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  source TEXT NOT NULL,
  latitude DOUBLE PRECISION,
  longitude DOUBLE PRECISION,
  elevation DOUBLE PRECISION,
  metadata JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS temperature_readings (
  id BIGSERIAL PRIMARY KEY,
  station_id TEXT NOT NULL REFERENCES stations(id),
  date DATE NOT NULL,
  tmax DOUBLE PRECISION,
  tmin DOUBLE PRECISION,
  source TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  source_url TEXT,
  raw_record JSONB,
  ingested_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(station_id, date, source)
);

CREATE INDEX IF NOT EXISTS idx_readings_station_date ON temperature_readings(station_id, date);
CREATE INDEX IF NOT EXISTS idx_readings_source ON temperature_readings(source);

CREATE TABLE IF NOT EXISTS ingestion_log (
  id BIGSERIAL PRIMARY KEY,
  source TEXT NOT NULL,
  station_id TEXT,
  files_downloaded INT DEFAULT 0,
  records_inserted INT DEFAULT 0,
  records_skipped INT DEFAULT 0,
  error TEXT,
  checksum TEXT,
  started_at TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ
);
"""


def get_connection():
    import psycopg2
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SCHEMA_SQL)
    conn.commit()
    cur.close()
    conn.close()
    print("Database schema initialised.")


def upsert_stations(stations):
    conn = get_connection()
    cur = conn.cursor()
    for s in stations:
        cur.execute("""
            INSERT INTO stations (id, name, source, latitude, longitude, elevation)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                latitude = EXCLUDED.latitude,
                longitude = EXCLUDED.longitude,
                elevation = EXCLUDED.elevation
        """, (s["id"], s["name"], s.get("source", "bom"), s["lat"], s["lon"], s.get("elev")))
    conn.commit()
    cur.close()
    conn.close()


def batch_upsert_readings(records, batch_size=5000):
    if not records:
        return 0, 0

    conn = get_connection()
    cur = conn.cursor()

    inserted = 0
    skipped = 0
    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        values = []
        for r in batch:
            raw_record = r.get("raw_record")
            raw_json_str = json.dumps(raw_record, sort_keys=True, default=str) if raw_record else "{}"
            content_hash = hashlib.sha256(raw_json_str.encode("utf-8")).hexdigest()
            raw_json = psycopg2.extras.Json(raw_record) if raw_record else None
            values.append((
                r["station_id"], r["date"],
                r.get("tmax"), r.get("tmin"),
                r["source"], content_hash,
                r.get("source_url"), raw_json,
            ))

        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO temperature_readings
                (station_id, date, tmax, tmin, source, content_hash, source_url, raw_record)
            VALUES %s
            ON CONFLICT (station_id, date, source) DO NOTHING
            """,
            values,
            template="(%s, %s::date, %s::double precision, %s::double precision, %s, %s, %s, %s::jsonb)",
        )
        inserted += cur.rowcount if cur.rowcount > 0 else 0

    conn.commit()
    cur.close()
    conn.close()

    total = len(records)
    skipped = total - inserted
    return inserted, skipped


def get_stations():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, source, latitude, longitude, elevation FROM stations ORDER BY name")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {"id": r[0], "name": r[1], "source": r[2], "lat": r[3], "lon": r[4], "elev": r[5]}
        for r in rows
    ]


def count_readings():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT source, COUNT(*) FROM temperature_readings GROUP BY source")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {r[0]: r[1] for r in rows}
