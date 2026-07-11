import hashlib
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ingest import db


def verify_hashes(limit=1000):
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, station_id, date, source, content_hash, raw_record
        FROM temperature_readings
        ORDER BY ingested_at DESC
        LIMIT %s
    """, (limit,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    verified = 0
    failed = 0
    for row in rows:
        record_id, station_id, date, source, stored_hash, raw_jsonb = row
        raw_str = json.dumps(raw_jsonb, sort_keys=True) if raw_jsonb else ""
        computed_hash = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()
        if computed_hash == stored_hash:
            verified += 1
        else:
            failed += 1
            print(f"  HASH MISMATCH: id={record_id} "
                  f"stn={station_id} date={date} src={source}")
            print(f"    Stored:    {stored_hash}")
            print(f"    Computed:  {computed_hash}")

    print(f"\nVerified {verified} records, {failed} mismatches (out of {len(rows)} checked)")


def check_source_integrity():
    """
    Compare each source's data for the same station+date.
    Look for significant differences between BOM ACORN-SAT and NOAA GHCN.
    """
    conn = db.get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            a.station_id,
            a.date,
            a.tmax AS acorn_tmax,
            a.tmin AS acorn_tmin,
            n.tmax AS noaa_tmax,
            n.tmin AS noaa_tmin
        FROM temperature_readings a
        JOIN temperature_readings n
            ON a.station_id = n.station_id
            AND a.date = n.date
        WHERE a.source = 'bom_acorn'
            AND n.source = 'noaa_ghcn'
            AND (a.tmax IS NOT NULL AND n.tmax IS NOT NULL)
        ORDER BY a.station_id, a.date
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        print("No overlapping BOM ACORN + NOAA data found.")
        return

    diffs = []
    for row in rows:
        station_id, date, acorn_tmax, acorn_tmin, noaa_tmax, noaa_tmin = row
        tmax_diff = abs(acorn_tmax - noaa_tmax)
        if tmax_diff > 1.0:
            diffs.append({
                "station_id": station_id,
                "date": str(date),
                "acorn_tmax": acorn_tmax,
                "noaa_tmax": noaa_tmax,
                "difference": round(tmax_diff, 2),
            })

    print(f"\nCross-source comparison (BOM ACORN vs NOAA GHCN):")
    print(f"  Overlapping records: {len(rows)}")
    print(f"  Records with >1.0°C TMAX difference: {len(diffs)}")
    for d in diffs[:20]:
        print(f"    Station {d['station_id']} on {d['date']}: "
              f"ACORN={d['acorn_tmax']}°C NOAA={d['noaa_tmax']}°C "
              f"(diff={d['difference']}°C)")
    if len(diffs) > 20:
        print(f"    ... and {len(diffs)-20} more")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--hashes", action="store_true", help="Verify stored SHA-256 hashes")
    parser.add_argument("--compare", action="store_true", help="Cross-source comparison")

    args = parser.parse_args()
    if args.hashes:
        verify_hashes()
    if args.compare:
        check_source_integrity()
    if not args.hashes and not args.compare:
        parser.print_help()
