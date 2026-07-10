from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from database import create_table, insert_observation, get_latest_observations
from bom import fetch_station_data

app = FastAPI(title="RawRadar - Raw Weather Observations")

@app.get("/", response_class=HTMLResponse)
def root():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>RawRadar</title>
        <style>
            body { background-color: #0f0f0f; color: #e0e0e0; font-family: Arial, sans-serif; text-align: center; padding: 50px; }
            h1 { color: #00d4ff; }
            button { background-color: #1f1f1f; color: #00d4ff; border: 1px solid #00d4ff; padding: 15px 30px; font-size: 18px; margin: 10px; cursor: pointer; border-radius: 8px; }
            button:hover { background-color: #00d4ff; color: #0f0f0f; }
        </style>
    </head>
    <body>
        <h1>RawRadar</h1>
        <p>Tracking original weather data.</p>
        <button onclick="window.location.href='/setup'">1. Setup Database Table</button><br>
        <button onclick="window.location.href='/ingest/station/95936'">2. Fetch Melbourne Raw Data</button><br><br>
        <button onclick="window.location.href='/data'">View Stored Raw Data</button>
    </body>
    </html>
    """

@app.get("/health")
def health():
    return {"status": "healthy", "db": "connected"}

@app.get("/setup")
def setup_db():
    return create_table()

@app.get("/ingest/station/{wmo_id}")
def ingest_station(wmo_id: int):
    try:
        response = fetch_station_data(wmo_id)
        if response.status_code != 200:
            return {"status": "error", "detail": f"BOM returned status {response.status_code}"}
        
        data = response.json()
        insert_observation(wmo_id, data)
        
        return {"status": "success", "station": wmo_id, "records": len(data.get('observations', {}).get('data', []))}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

@app.get("/data", response_class=HTMLResponse)
def view_data():
    try:
        rows = get_latest_observations(30)
        
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>RawRadar - Stored Data</title>
            <style>
                body { background-color: #0f0f0f; color: #e0e0e0; font-family: Arial, sans-serif; padding: 30px; }
                h1 { color: #00d4ff; }
                table { border-collapse: collapse; width: 100%; max-width: 1200px; margin: 20px auto; }
                th, td { border: 1px solid #444; padding: 10px; text-align: center; }
                th { background-color: #1f1f1f; color: #00d4ff; }
                tr:nth-child(even) { background-color: #1a1a1a; }
                .back-btn { background-color: #1f1f1f; color: #00d4ff; border: 1px solid #00d4ff; padding: 10px 20px; text-decoration: none; border-radius: 6px; }
            </style>
        </head>
        <body>
            <h1>RawRadar - Latest Stored Observations</h1>
            <a href="/" class="back-btn">← Back to Home</a>
            <table>
                <tr>
                    <th>ID</th>
                    <th>Station</th>
                    <th>Fetched At</th>
                    <th>Local Time</th>
                    <th>Air Temp (°C)</th>
                    <th>Apparent Temp (°C)</th>
                    <th>Gust (km/h)</th>
                    <th>Rain Trace (mm)</th>
                </tr>
        """

        for row in rows:
            html += f"""
                <tr>
                    <td>{row['id']}</td>
                    <td>{row['station_wmo']}</td>
                    <td>{row['fetched_at']}</td>
                    <td>{row.get('local_time', '-')}</td>
                    <td>{row.get('air_temp', '-')}</td>
                    <td>{row.get('apparent_t', '-')}</td>
                    <td>{row.get('gust_kmh', '-')}</td>
                    <td>{row.get('rain_trace', '-')}</td>
                </tr>
            """

        html += """
            </table>
        </body>
        </html>
        """
        return html
    except Exception as e:
        return {"status": "error", "detail": str(e)}
