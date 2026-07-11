import os
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
    return psycopg2.connect(DATABASE_URL, connect_timeout=10)
