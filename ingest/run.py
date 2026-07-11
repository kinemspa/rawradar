import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingest import stations, db
from ingest.bom_acorn import extract_all as extract_acorn
from ingest.bom_api import fetch_current, parse_observations
from ingest.noaa_ghcn import fetch_all as fetch_noaa


def seed_stations():
    print("== Seeding station metadata ==")
    all_stations = stations.get_all_stations()
    for s in all_stations:
        s["source"] = "bom"
    db.upsert_stations(all_stations)
    print(f"  {len(all_stations)} stations upserted")


def ingest_acorn():
    print("\n== ACORN-SAT (BOM adjusted) ==")
    target = stations.get_bom_ids()
    records = extract_acorn(target)
    print(f"  Total records parsed: {len(records)}")

    inserted, skipped = db.batch_upsert_readings(records)
    print(f"  Inserted: {inserted}, Skipped (duplicates): {skipped}")
    return inserted, skipped


def ingest_bom_api():
    print("\n== BOM API (current observations) ==")
    total_inserted = 0
    total_skipped = 0
    for s in stations.get_all_stations():
        try:
            raw = fetch_current(s["id"])
            records = parse_observations(raw, s["id"])
            if not records:
                continue
            inserted, skipped = db.batch_upsert_readings(records)
            total_inserted += inserted
            total_skipped += skipped
            print(f"  Station {s['id']} ({s['name']}): {len(records)} obs, "
                  f"{inserted} new, {skipped} dupes")
        except Exception as e:
            print(f"  Station {s['id']}: SKIPPED - {e}")
    print(f"  Total: {total_inserted} inserted, {total_skipped} skipped")
    return total_inserted, total_skipped


def ingest_noaa():
    print("\n== NOAA GHCN-Daily (independent) ==")
    mapping = stations.NOAA_GHCN_IDS
    records = fetch_noaa(mapping)
    print(f"  Total records parsed: {len(records)}")

    inserted, skipped = db.batch_upsert_readings(records)
    print(f"  Inserted: {inserted}, Skipped (duplicates): {skipped}")
    return inserted, skipped


def show_counts():
    print("\n== Record counts by source ==")
    counts = db.count_readings()
    for source, count in counts.items():
        print(f"  {source}: {count:,}")
    total = sum(counts.values())
    print(f"  TOTAL: {total:,}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="RawRadar data ingestion")
    parser.add_argument("--init-db", action="store_true", help="Initialise database schema")
    parser.add_argument("--seed-stations", action="store_true", help="Upsert station list")
    parser.add_argument("--acorn", action="store_true", help="Ingest ACORN-SAT data")
    parser.add_argument("--bom-api", action="store_true", help="Ingest BOM API current obs")
    parser.add_argument("--noaa", action="store_true", help="Ingest NOAA GHCN-Daily data")
    parser.add_argument("--all", action="store_true", help="Run all ingestions")
    parser.add_argument("--counts", action="store_true", help="Show record counts")

    args = parser.parse_args()

    if len(sys.argv) == 1:
        parser.print_help()
        return

    if args.init_db:
        db.init_db()
    if args.seed_stations or args.all:
        seed_stations()
    if args.acorn or args.all:
        ingest_acorn()
    if args.bom_api or args.all:
        ingest_bom_api()
    if args.noaa or args.all:
        ingest_noaa()
    if args.counts:
        show_counts()


if __name__ == "__main__":
    main()
