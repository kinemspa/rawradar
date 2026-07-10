from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from ftplib import FTP

app = FastAPI(title="RawRadar")

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

            <div class="flex gap-4">
                <a href="/data" class="bg-zinc-900 hover:bg-zinc-800 border border-white/10 px-8 py-4 rounded-3xl">View Data</a>
                <a href="/ftp" class="bg-zinc-900 hover:bg-zinc-800 border border-white/10 px-8 py-4 rounded-3xl">Historical FTP Browser</a>
            </div>
        </div>
    </body>
    </html>
    """

@app.get("/ftp", response_class=HTMLResponse)
def ftp_browser(path: str = ""):
    try:
        ftp = FTP('ftp.bom.gov.au')
        ftp.login()

        if not path:
            path = "/anon/home/ncc/www"

        # Build parent path
        parent = ""
        if path != "/anon/home/ncc/www":
            parts = path.rstrip("/").split("/")
            parent = "/".join(parts[:-1]) if len(parts) > 1 else "/anon/home/ncc/www"

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
                <div class="flex justify-between items-center mb-6">
                    <h1 class="text-3xl font-bold">BOM FTP Browser</h1>
                    <a href="/" class="text-sky-400 hover:underline">← Back to Home</a>
                </div>

                <div class="mb-4">
        """

        if parent:
            html += f'<a href="/ftp?path={parent}" class="inline-block mb-4 px-4 py-2 bg-zinc-800 hover:bg-zinc-700 rounded-xl text-sm">↑ Go Up</a>'

        html += f"""
                </div>

                <div class="bg-zinc-900 rounded-3xl p-6 border border-white/10">
                    <div class="text-sm text-zinc-400 mb-4 font-mono">Current path: {path}</div>
                    <div class="space-y-1">
        """

        for item in items:
            parts = item.split(maxsplit=8)
            if len(parts) >= 9:
                name = parts[8]
                is_dir = item.startswith('d')
                icon = "📁" if is_dir else "📄"
                if is_dir:
                    new_path = f"{path}/{name}".replace("//", "/")
                    html += f'<a href="/ftp?path={new_path}" class="block px-4 py-2 hover:bg-white/5 rounded-xl">{icon} {name}</a>'
                else:
                    html += f'<div class="px-4 py-2 text-zinc-400">{icon} {name}</div>'

        html += """
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
        return html

    except Exception as e:
        return {"status": "error", "detail": str(e)}
