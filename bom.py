import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "http://www.bom.gov.au/"
}

def fetch_station_data(wmo_id: int):
    url = f"http://www.bom.gov.au/fwo/IDV60901/IDV60901.{wmo_id}.json"
    response = requests.get(url, headers=HEADERS, timeout=15)
    return response
