BOM_STATIONS = [
    {"id": "066214", "name": "Sydney (Observatory Hill)", "lat": -33.86, "lon": 151.21, "elev": 39},
    {"id": "086338", "name": "Melbourne (Olympic Park)", "lat": -37.82, "lon": 144.98, "elev": 7},
    {"id": "040842", "name": "Brisbane Aero", "lat": -27.39, "lon": 153.13, "elev": 5},
    {"id": "009021", "name": "Perth Airport", "lat": -31.93, "lon": 115.98, "elev": 15},
    {"id": "023000", "name": "Adelaide (West Terrace)", "lat": -34.92, "lon": 138.62, "elev": 48},
    {"id": "094029", "name": "Hobart (Ellerslie Road)", "lat": -42.89, "lon": 147.33, "elev": 51},
    {"id": "014015", "name": "Darwin Airport", "lat": -12.42, "lon": 130.89, "elev": 30},
    {"id": "070351", "name": "Canberra Airport", "lat": -35.31, "lon": 149.20, "elev": 577},
    {"id": "031011", "name": "Cairns Aero", "lat": -16.87, "lon": 145.75, "elev": 3},
    {"id": "004032", "name": "Port Hedland", "lat": -20.38, "lon": 118.63, "elev": 6},
    {"id": "032040", "name": "Townsville Aero", "lat": -19.25, "lon": 146.77, "elev": 5},
    {"id": "076031", "name": "Mildura Airport", "lat": -34.24, "lon": 142.09, "elev": 50},
    {"id": "037010", "name": "Camooweal", "lat": -19.92, "lon": 138.12, "elev": 229},
    {"id": "072150", "name": "Wagga Wagga AMO", "lat": -35.16, "lon": 147.46, "elev": 147},
    {"id": "015590", "name": "Alice Springs Airport", "lat": -23.80, "lon": 133.89, "elev": 546},
    {"id": "091311", "name": "Launceston Airport", "lat": -41.42, "lon": 147.12, "elev": 168},
    {"id": "039083", "name": "Rockhampton Aero", "lat": -23.38, "lon": 150.48, "elev": 10},
    {"id": "003003", "name": "Broome Airport", "lat": -17.96, "lon": 122.24, "elev": 7},
    {"id": "012038", "name": "Kalgoorlie-Boulder", "lat": -30.78, "lon": 121.45, "elev": 365},
    {"id": "068072", "name": "Nowra", "lat": -34.95, "lon": 150.54, "elev": 109},
]

def get_bom_ids():
    return [s["id"] for s in BOM_STATIONS]

def get_all_stations():
    return BOM_STATIONS
