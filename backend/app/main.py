
from fastapi import FastAPI, Response, Query, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import json, os, re, glob
from .utils import nb_to_geojson, summarize

ROOT = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(ROOT, "data")
FRONTEND_PATH = os.path.join(os.path.dirname(ROOT), "frontend")

_FILENAME_BASE = "nextbillion_response"
_FILENAME_REGEX = re.compile(rf"^{re.escape(_FILENAME_BASE)}(?:_(\d+))?\.json$")

_DATA_CACHE: dict[str, tuple[float, dict]] = {}

def _list_data_files():
    files = []
    for path in glob.glob(os.path.join(DATA_DIR, f"{_FILENAME_BASE}*.json")):
        name = os.path.basename(path)
        m = _FILENAME_REGEX.match(name)
        if m:
            ver = int(m.group(1)) if m.group(1) else 0
            files.append({"name": name, "version": ver, "path": path})
    files.sort(key=lambda x: x["version"])  # ascending by version
    return files

def _resolve_data_path(version: int | None = None, file: str | None = None) -> str:
    # Explicit file name (must exist under DATA_DIR)
    if file:
        safe_name = os.path.basename(file)
        candidate = os.path.join(DATA_DIR, safe_name)
        if not candidate.startswith(DATA_DIR):
            raise FileNotFoundError("Invalid file path")
        if os.path.exists(candidate):
            return candidate
        raise FileNotFoundError(f"Data file not found: {safe_name}")
    files = _list_data_files()
    # Explicit version
    if version is not None:
        for f in files:
            if f["version"] == version:
                return f["path"]
        raise FileNotFoundError(f"Version not found: {version}")
    # Env var override
    env_data_file = os.getenv("DATA_FILE")
    if env_data_file:
        env_path = env_data_file if os.path.isabs(env_data_file) else os.path.join(DATA_DIR, env_data_file)
        if os.path.exists(env_path):
            return env_path
    # Latest numbered (or base file if present)
    if files:
        return files[-1]["path"]
    base = os.path.join(DATA_DIR, f"{_FILENAME_BASE}.json")
    if os.path.exists(base):
        return base
    raise FileNotFoundError("No data files found")

def _load_json(path: str) -> dict:
    try:
        mtime = os.path.getmtime(path)
        cached = _DATA_CACHE.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _DATA_CACHE[path] = (mtime, data)
        return data
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Data file not found: {os.path.basename(path)}")
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON in {os.path.basename(path)}: {str(e)}")

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
    data = _load_json(path)
    return JSONResponse(summarize(data))

@app.get("/api/routes")
def api_routes(version: int | None = Query(default=None), file: str | None = Query(default=None)):
    path = _resolve_data_path(version=version, file=file)
    data = _load_json(path)
    geo = nb_to_geojson(data)
    return JSONResponse(geo)

@app.get("/api/raw")
def api_raw(version: int | None = Query(default=None), file: str | None = Query(default=None)):
    path = _resolve_data_path(version=version, file=file)
    data = _load_json(path)
    return JSONResponse(data)

@app.get("/api/data-files")
def api_data_files():
    files = _list_data_files()
    try:
        default_path = _resolve_data_path()
        default_name = os.path.basename(default_path)
    except FileNotFoundError:
        default_name = None
    return JSONResponse({
        "files": [{"name": f["name"], "version": f["version"]} for f in files],
        "default": default_name,
    })
