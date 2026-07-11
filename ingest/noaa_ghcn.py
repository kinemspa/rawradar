import os
import requests
from collections import defaultdict

BASE_URL = "https://www1.ncdc.noaa.gov/pub/data/ghcn/daily"
STATION_LIST_URL = f"{BASE_URL}/ghcnd-stations.txt"

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "noaa_ghcn")


def download_station_file(station_id):
    filename = f"{station_id}.dly"
    local_path = os.path.join(RAW_DIR, filename)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)

    if os.path.exists(local_path):
        print(f"  Already cached: {local_path}")
        with open(local_path, "r") as f:
            return f.read()

    url = f"{BASE_URL}/all/{filename}"
    print(f"  Downloading {filename}...")
    resp = requests.get(url, timeout=30)
    if resp.status_code != 200:
        print(f"  [WARN] {filename} not found (HTTP {resp.status_code})")
        return None
    with open(local_path, "w", encoding="utf-8") as f:
        f.write(resp.text)
    return resp.text


def parse_ghcn_dly(content, station_id):
    records = defaultdict(dict)

    for line in content.strip().split("\n"):
        if len(line) < 40:
            continue
        sid = line[0:11].strip()
        year = int(line[11:15])
        month = int(line[15:17])
        element = line[17:21].strip()

        if element not in ("TMAX", "TMIN"):
            continue

        for day_offset in range(31):
            pos = 21 + day_offset * 8
            if pos + 8 > len(line):
                break
            try:
                day = int(line[pos:pos+3].strip())
            except ValueError:
                continue
            if day == 0:
                continue
            try:
                value = int(line[pos+3:pos+8].strip())
            except ValueError:
                continue
            if value == -9999:
                continue

            temp_c = value / 10.0
            date_str = f"{year:04d}-{month:02d}-{day:02d}"

            if element == "TMAX":
                records[(station_id, date_str)]["tmax"] = temp_c
            elif element == "TMIN":
                records[(station_id, date_str)]["tmin"] = temp_c

    result = []
    for (sid, date_str), data in records.items():
        result.append({
            "station_id": sid,
            "date": date_str,
            "tmax": data.get("tmax"),
            "tmin": data.get("tmin"),
            "source": "noaa_ghcn",
            "source_url": f"{BASE_URL}/all/{sid}.dly",
            "raw_record": data,
        })

    return result


def fetch_station(station_id):
    content = download_station_file(station_id)
    if content is None:
        return []
    records = parse_ghcn_dly(content, station_id)
    print(f"    {station_id}: {len(records)} daily records")
    return records


def fetch_all(station_mapping):
    all_records = []
    for bom_id, noaa_id in station_mapping.items():
        print(f"  Fetching NOAA station {noaa_id} (BOM {bom_id})...")
        records = fetch_station(noaa_id)
        for r in records:
            r["station_id"] = bom_id
        all_records.extend(records)
    return all_records
