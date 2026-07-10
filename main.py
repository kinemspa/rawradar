from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv
import os
import psycopg2
import psycopg2.extras
import requests
from ftplib import FTP

load_dotenv()

app = FastAPI(title="RawRadar")

# ==================== HOMEPAGE ====================
@app.get("/", response_class=HTMLResponse)
def homepage():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>RawRadar</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-zinc-950 text-zinc-200">
        <div class="max-w-6xl mx-auto p-8">
            <h1 class="text-6xl font-bold tracking-tighter mb-2">RawRadar</h1>
            <p class="text-xl text-zinc-400 mb-10">Raw Weather Data Platform</p>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <a href="/data" class="block bg-zinc-900 hover:bg-zinc-800 border border-white/10 rounded-3xl p-8">
                    <div class="text-3xl mb-4">📊</div>
                    <div class="text-2xl font-semibold">View Data</div>
                    <div class="text-zinc-400 mt-1">Browse stored observations</div>
                </a>

                <a href="/ftp" class="block bg-zinc-900 hover:bg-zinc-800 border border-white/10 rounded-3xl p-8">
                    <div class="text-3xl mb-4">🗂️</div>
                    <div class="text-2xl font-semibold">Historical FTP Browser</div>
                    <div class="text-zinc-400 mt-1">Browse & download from BOM FTP</div>
                </a>
            </div>
        </div>
    </body>
    </html>
    """

# ==================== FTP BROWSER ====================
@app.get("/ftp", response_class=HTMLResponse)
def ftp_browser(path: str = ""):
    try:
        ftp = FTP('ftp.bom.gov.au')
        ftp.login()  # Anonymous login

        if not path:
            path = "/anon/home/ncc/www"

        ftp.cwd(path)
        items = []
        ftp.retrlines('LIST', items.append)
        ftp.quit()

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>RawRadar • FTP Browser</title>
            <script src="https://cdn.tailwindcss.com"></script>
        </head>
        <body class="bg-zinc-950 text-zinc-200">
            <div class="max-w-6xl mx-auto p-8">
                <div class="flex items-center justify-between mb-6">
                    <h1 class="text-3xl font-bold">BOM FTP Browser</h1>
                    <a href="/" class="text-sky-400 hover:underline">← Back to Home</a>
                </div>
                
                <div class="bg-zinc-900 rounded-3xl p-6 border border-white/10">
                    <div class="mb-4 text-sm text-zinc-400">Current path: <span class="font-mono">{path}</span></div>
                    
                    <div class="space-y-1">
        """

        for item in items:
            parts = item.split()
            if len(parts) >= 9:
                name = ' '.join(parts[8:])
                is_dir = item.startswith('d')
                icon = "📁" if is_dir else "📄"
                link = f"/ftp?path={path}/{name}" if is_dir else "#"
                html += f"""
                    <a href="{link}" class="flex items-center gap-x-3 px-4 py-2 hover:bg-white/5 rounded-xl">
                        <span>{icon}</span>
                        <span class="font-mono text-sm">{name}</span>
                    </a>
                """

        html += """
                    </div>
                </div>
                
                <div class="mt-6 text-xs text-zinc-500">
                    Browse the BOM FTP to find historical data. Click folders to navigate.
                </div>
            </div>
        </body>
        </html>
        """
        return html

    except Exception as e:
        return {"status": "error", "detail": str(e)}

# Keep other routes (setup, ingest, data, health) here if needed...
