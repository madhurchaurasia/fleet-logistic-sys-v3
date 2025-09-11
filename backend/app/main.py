
from fastapi import FastAPI, Response, Query
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import json, os, re, glob
from .utils import nb_to_geojson, summarize

ROOT = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(ROOT, "data")

_FILENAME_BASE = "nextbillion_response"
_FILENAME_REGEX = re.compile(rf"^{re.escape(_FILENAME_BASE)}(?:_(\d+))?\.json$")

def _list_data_files():
    files = []
    for path in glob.glob(os.path.join(DATA_DIR, f"{_FILENAME_BASE}*.json")):
        name = os.path.basename(path)
        m = _FILENAME_REGEX.match(name)
        if m:
            ver = int(m.group(1)) if m.group(1) else 0
            files.append({"name": name, "version": ver, "path": path})
    files.sort(key=lambda x: x["version"])  # ascending
    return files

def _resolve_data_path(version: int | None = None, file: str | None = None) -> str:
    # 1) explicit file query param
    if file:
        safe_name = os.path.basename(file)
        candidate = os.path.join(DATA_DIR, safe_name)
        if os.path.commonpath([DATA_DIR, os.path.realpath(candidate)]) != DATA_DIR:
            raise FileNotFoundError("Invalid file path")
        if os.path.exists(candidate):
            return candidate
        raise FileNotFoundError(f"Data file not found: {safe_name}")
    # 2) explicit version query param
    files = _list_data_files()
    if version is not None:
        for f in files:
            if f["version"] == version:
                return f["path"]
        raise FileNotFoundError(f"Version not found: {version}")
    # 3) env var
    env_data_file = os.getenv("DATA_FILE")
    if env_data_file:
        env_path = env_data_file if os.path.isabs(env_data_file) else os.path.join(DATA_DIR, env_data_file)
        if os.path.exists(env_path):
            return env_path
    # 4) latest numbered if available, else base
    if files:
        return files[-1]["path"]
    # fallback to base name
    fallback = os.path.join(DATA_DIR, f"{_FILENAME_BASE}.json")
    if os.path.exists(fallback):
        return fallback
    raise FileNotFoundError("No data files found")

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
def api_summary(version: int | None = Query(default=None), file: str | None = Query(default=None)):
    path = _resolve_data_path(version=version, file=file)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return JSONResponse(summarize(data))

@app.get("/api/routes")
def api_routes(version: int | None = Query(default=None), file: str | None = Query(default=None)):
    path = _resolve_data_path(version=version, file=file)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    geo = nb_to_geojson(data)
    return JSONResponse(geo)

@app.get("/api/raw")
def api_raw(version: int | None = Query(default=None), file: str | None = Query(default=None)):
    path = _resolve_data_path(version=version, file=file)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return JSONResponse(data)

@app.get("/api/data-files")
def api_data_files():
    files = _list_data_files()
    default_path = None
    try:
        default_path = _resolve_data_path()
    except FileNotFoundError:
        default_path = None
    return JSONResponse({
        "files": [{"name": f["name"], "version": f["version"]} for f in files],
        "default": os.path.basename(default_path) if default_path else None,
    })
