
from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import json, os
from .utils import nb_to_geojson, summarize

ROOT = os.path.dirname(os.path.dirname(__file__))
DATA_PATH = os.path.join(ROOT, "data", "nextbillion_response.json")
FRONTEND_PATH = os.path.join(os.path.dirname(ROOT), "frontend")

app = FastAPI(title="TomTom Route Viewer", version="1.0.0")

# Serve frontend
app.mount("/static", StaticFiles(directory=FRONTEND_PATH), name="static")

@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(FRONTEND_PATH, "index.html"), "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

# Avoid noisy 404 for browsers requesting a favicon
@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204, media_type="image/x-icon")

# Removed CDN proxy endpoints since SDK is self-hosted under /static/vendor/tomtom

@app.get("/api/summary")
def api_summary():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return JSONResponse(summarize(data))

@app.get("/api/routes")
def api_routes():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    geo = nb_to_geojson(data)
    return JSONResponse(geo)

@app.get("/api/raw")
def api_raw():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return JSONResponse(data)
