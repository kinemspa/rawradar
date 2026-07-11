import requests
import json
from datetime import datetime, timezone

HEADERS = {
    "User-Agent": "RawRadar/1.0 (weather data archive)",
    "Accept": "application/json",
    "Referer": "http://www.bom.gov.au/",
}

SOURCE_URL_TPL = "http://www.bom.gov.au/fwo/IDV60901/IDV60901.{wmo_id}.json"


def fetch_current(station_wmo):
    url = SOURCE_URL_TPL.format(wmo_id=station_wmo)
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


def parse_observations(raw_json, station_id):
    records = []
    try:
        data = raw_json["observations"]["data"]
    except (KeyError, TypeError):
        return records

    for obs in data:
        date_str = obs.get("local_date_time_full", "")
        if len(date_str) >= 8:
            date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
        else:
            continue

        tmax = obs.get("air_temp")
        tmin_temp = obs.get("apparent_t")

        if tmax is None and tmin_temp is None:
            continue

        records.append({
            "station_id": station_id,
            "date": date,
            "tmax": float(tmax) if tmax else None,
            "tmin": None,
            "source": "bom_api",
            "source_url": SOURCE_URL_TPL.format(wmo_id=station_id),
            "raw_record": obs,
        })

    return records
