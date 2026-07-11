BOM_STATIONS = [
    {"id": "009021", "name": "Sydney (Observatory Hill)", "lat": -33.86, "lon": 151.21, "elev": 39},
    {"id": "086071", "name": "Melbourne (Olympic Park)", "lat": -37.82, "lon": 144.98, "elev": 7},
    {"id": "040913", "name": "Brisbane", "lat": -27.48, "lon": 153.04, "elev": 8},
    {"id": "009034", "name": "Perth", "lat": -31.93, "lon": 115.98, "elev": 15},
    {"id": "023090", "name": "Adelaide", "lat": -34.92, "lon": 138.62, "elev": 48},
    {"id": "094008", "name": "Hobart", "lat": -42.89, "lon": 147.33, "elev": 51},
    {"id": "014015", "name": "Darwin", "lat": -12.42, "lon": 130.89, "elev": 30},
    {"id": "070263", "name": "Canberra", "lat": -35.31, "lon": 149.20, "elev": 577},
    {"id": "004032", "name": "Cairns", "lat": -16.87, "lon": 145.75, "elev": 3},
    {"id": "031011", "name": "Geelong", "lat": -38.15, "lon": 144.35, "elev": 7},
    {"id": "040004", "name": "Amberley (Ipswich)", "lat": -27.63, "lon": 152.71, "elev": 27},
    {"id": "060139", "name": "Mildura", "lat": -34.24, "lon": 142.09, "elev": 50},
    {"id": "037010", "name": "Mount Isa", "lat": -20.73, "lon": 139.48, "elev": 343},
    {"id": "055054", "name": "Wagga Wagga", "lat": -35.16, "lon": 147.46, "elev": 147},
    {"id": "012042", "name": "Alice Springs", "lat": -23.80, "lon": 133.89, "elev": 546},
    {"id": "096003", "name": "Launceston", "lat": -41.42, "lon": 147.12, "elev": 168},
    {"id": "039083", "name": "Surfers Paradise", "lat": -28.00, "lon": 153.43, "elev": 3},
    {"id": "011052", "name": "Broome", "lat": -17.96, "lon": 122.24, "elev": 7},
    {"id": "015590", "name": "Kalgoorlie", "lat": -30.78, "lon": 121.45, "elev": 365},
    {"id": "072150", "name": "Wollongong", "lat": -34.43, "lon": 150.89, "elev": 10},
]

NOAA_GHCN_IDS = {
    "009021": "ASN00066037",
    "086071": "ASN00086071",
    "040913": "ASN00040223",
}

def get_bom_ids():
    return [s["id"] for s in BOM_STATIONS]


def get_all_stations():
    return BOM_STATIONS
