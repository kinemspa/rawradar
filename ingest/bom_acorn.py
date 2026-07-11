import os
import tarfile
import gzip
from ftplib import FTP
from collections import defaultdict

FTP_HOST = "ftp.bom.gov.au"
ACORN_PATH = "/anon/home/ncc/www/change/ACORN_SAT_daily"
LATEST_VERSION = "v2.6.0"

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "acorn_sat")


def download_tar(metric):
    filename = f"acorn_sat_{LATEST_VERSION}_daily_{metric}.tar.gz"
    local_path = os.path.join(RAW_DIR, filename)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)

    if os.path.exists(local_path):
        print(f"  Already cached: {local_path}")
        return local_path

    print(f"  Downloading {filename}...")
    ftp = FTP(FTP_HOST)
    ftp.login()
    with open(local_path, "wb") as f:
        ftp.retrbinary(f"RETR {ACORN_PATH}/{filename}", f.write)
    ftp.quit()
    print(f"  Saved to {local_path}")
    return local_path


def parse_metric_file(content, metric):
    records = {}
    lines = content.strip().split("\n")
    for line in lines:
        line = line.strip()
        if not line or line.startswith("date"):
            continue
        parts = line.split(",")
        if len(parts) < 2:
            continue
        date_str = parts[0].strip()
        temp_str = parts[1].strip()
        if not date_str or not temp_str:
            continue
        try:
            temp = float(temp_str)
        except ValueError:
            continue
        records[date_str] = {"temp": temp, "raw_line": line}
    return records


def extract_all(target_stations):
    station_set = set(target_stations)
    source_url = (
        f"ftp://{FTP_HOST}{ACORN_PATH}/"
        f"acorn_sat_{LATEST_VERSION}_daily_{{metric}}.tar.gz"
    )

    station_data = defaultdict(dict)

    for metric in ("tmax", "tmin"):
        tar_path = download_tar(metric)
        files_processed = 0

        with gzip.GzipFile(tar_path) as gz:
            with tarfile.TarFile(fileobj=gz) as tar:
                for member in tar.getmembers():
                    if not member.name.endswith(".csv"):
                        continue
                    parts = member.name.split(".")
                    if len(parts) < 2:
                        continue
                    sid = parts[1]
                    if sid not in station_set:
                        continue
                    f = tar.extractfile(member)
                    content = f.read().decode("utf-8", errors="replace")
                    parsed = parse_metric_file(content, metric)
                    for date_str, data in parsed.items():
                        entry = station_data[(sid, date_str)]
                        entry[f"{metric}_temp"] = data["temp"]
                        entry[f"{metric}_raw"] = data["raw_line"]
                    files_processed += 1

        print(f"  {metric}: {files_processed} station files, "
              f"{len(parsed)} dates each")

    records = []
    for (sid, date_str), data in station_data.items():
        raw_record = {
            "tmax": data.get("tmax_raw", ""),
            "tmin": data.get("tmin_raw", ""),
        }
        records.append({
            "station_id": sid,
            "date": date_str,
            "tmax": data.get("tmax_temp"),
            "tmin": data.get("tmin_temp"),
            "source": "bom_acorn",
            "source_url": source_url,
            "raw_record": raw_record,
        })

    return records
