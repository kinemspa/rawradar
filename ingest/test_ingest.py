import sys, os
sys.path.insert(0, r"F:\Work\SpeshLab\Projects\RawRadar")
from main import app
print("OK -", len([r for r in app.routes if hasattr(r, "path")]), "routes")
