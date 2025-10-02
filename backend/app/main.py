
from fastapi import FastAPI, Response, Query, HTTPException, UploadFile, File as FF, WebSocket, WebSocketDisconnect
import logging
import re
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import json, os, re, glob, time, asyncio
from pydantic import BaseModel
from .utils import nb_to_geojson, summarize
from fastapi import FastAPI, Response, Query, HTTPException, UploadFile, File as FF, WebSocket, WebSocketDisconnect
import json, os, glob, time, asyncio, subprocess

ROOT = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(ROOT, "data")
FRONTEND_PATH = os.path.join(os.path.dirname(ROOT), "frontend")

_FILENAME_BASE = "nextbillion_response"
_FILENAME_REGEX = re.compile(rf"^{re.escape(_FILENAME_BASE)}(?:_(\d+))?\.json$")

_DATA_CACHE: dict[str, tuple[float, dict]] = {}


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            if websocket not in self._connections:
                self._connections.append(websocket)
        logging.info("WS connected. active=%s", len(self._connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            if websocket in self._connections:
                self._connections.remove(websocket)
        logging.info("WS disconnected. active=%s", len(self._connections))

    async def broadcast(self, payload: dict) -> int:
        async with self._lock:
            targets = list(self._connections)
        if not targets:
            raise RuntimeError("No active connections")
        sent = 0
        for ws in targets:
            try:
                await ws.send_json(payload)
                sent += 1
            except Exception as exc:
                logging.warning("WS send failed, dropping connection: %s", exc)
                await self.disconnect(ws)
        if sent == 0:
            raise RuntimeError("No active connections")
        logging.info("WS broadcast to %s connection(s): %s", sent, payload)
        return sent


manager = ConnectionManager()

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

def _resolve_data_path(version: int | None = None, file: str | None = None, set_id: int | None = None) -> str:
    # If a set is specified, try to resolve a response JSON within that set folder
    if set_id is not None:
        set_dir = os.path.join(DATA_DIR, str(set_id))
        # Try common response filenames in priority order inside the set dir
        candidates = []
        candidates += [
            os.path.join(set_dir, f"Next_Billion_response_{set_id}.json"),
            os.path.join(set_dir, f"nextbillion_response_{set_id}.json"),
            os.path.join(set_dir, "Next_Billion_response.json"),
            os.path.join(set_dir, "nextbillion_response.json"),
        ]
        # If nothing in the set dir, also try at the DATA_DIR root (allows legacy placement)
        candidates += [
            os.path.join(DATA_DIR, f"Next_Billion_response_{set_id}.json"),
            os.path.join(DATA_DIR, f"nextbillion_response_{set_id}.json"),
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        raise HTTPException(status_code=404, detail=f"No response JSON found for set {set_id}")
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


class StartNavigationRequest(BaseModel):
    route_id: str

@app.get("/", response_class=HTMLResponse)
def upload_page():
    # Serve uploader UI
    upload = os.path.join(FRONTEND_PATH, "upload.html")
    index = os.path.join(FRONTEND_PATH, "index.html")
    target = upload if os.path.exists(upload) else index
    with open(target, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/viewer", response_class=HTMLResponse)
def viewer_page():
    with open(os.path.join(FRONTEND_PATH, "index.html"), "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

# Avoid noisy 404 for browsers requesting a favicon
@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204, media_type="image/x-icon")

# Removed CDN proxy endpoints since SDK is self-hosted under /static/vendor/tomtom


# ---- Merged from main1.py: missing routes added ----

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as exc:
        logging.exception("WS error: %s", exc)
        await manager.disconnect(websocket)


@app.post("/api/start-navigation")
async def api_start_navigation(req: StartNavigationRequest):
    payload = {
        "type": "start_navigation",
        "route_id": req.route_id,
        "ts": time.time(),
    }
    try:
        recipients = await manager.broadcast(payload)
    except RuntimeError:
        raise HTTPException(status_code=404, detail="No connected devices")
    return JSONResponse({"sent": True, "recipients": recipients})

@app.get("/api/summary")
def api_summary(version: int | None = Query(default=None), file: str | None = Query(default=None), set: int | None = Query(default=None)):
    path = _resolve_data_path(version=version, file=file, set_id=set)
    data = _load_json(path)
    return JSONResponse(summarize(data))

@app.get("/api/routes")
def api_routes(version: int | None = Query(default=None), file: str | None = Query(default=None), set: int | None = Query(default=None)):
    path = _resolve_data_path(version=version, file=file, set_id=set)
    data = _load_json(path)
    geo = nb_to_geojson(data)
    return JSONResponse(geo)

@app.get("/api/raw")
def api_raw(version: int | None = Query(default=None), file: str | None = Query(default=None), set: int | None = Query(default=None)):
    path = _resolve_data_path(version=version, file=file, set_id=set)
    data = _load_json(path)
    return JSONResponse(data)

_REQ_REGEX = re.compile(r"^(Next_Billion_request|nextbillion_request)(?:_(\d+))?\.json$")
_RESP_REGEX = re.compile(r"^(Next_Billion_response|nextbillion_response)(?:_(\d+))?\.json$")

def _list_mock_sets():
    sets = []
    if not os.path.isdir(DATA_DIR):
        return sets
    for name in os.listdir(DATA_DIR):
        if not name.isdigit():
            continue
        sid = int(name)
        set_dir = os.path.join(DATA_DIR, name)
        jobs = None
        vehicles = None
        request = None
        response = None
        # Expected names
        cand_jobs = [f"input_jobs_{sid}.csv", "input_jobs.csv"]
        cand_vehicles = [f"input_vehicles_{sid}.csv", "input_vehicles.csv"]
        for fn in cand_jobs:
            p = os.path.join(set_dir, fn)
            if os.path.exists(p):
                jobs = fn; break
        for fn in cand_vehicles:
            p = os.path.join(set_dir, fn)
            if os.path.exists(p):
                vehicles = fn; break
        # Detect request/response via regex, prefer suffix matching set id
        try:
            for fn in os.listdir(set_dir):
                if request is None and fn.endswith('.json'):
                    m = _REQ_REGEX.match(fn)
                    if m and (m.group(2) is None or int(m.group(2)) == sid):
                        request = fn
                if response is None and fn.endswith('.json'):
                    m = _RESP_REGEX.match(fn)
                    if m and (m.group(2) is None or int(m.group(2)) == sid):
                        response = fn
        except FileNotFoundError:
            pass
        # Fallback: look in DATA_DIR root if not found in set folder
        if request is None:
            for fn in os.listdir(DATA_DIR):
                m = _REQ_REGEX.match(fn)
                if m and (m.group(2) is not None and int(m.group(2)) == sid):
                    if os.path.exists(os.path.join(DATA_DIR, fn)):
                        request = fn; break
        if response is None:
            for fn in os.listdir(DATA_DIR):
                m = _RESP_REGEX.match(fn)
                if m and (m.group(2) is not None and int(m.group(2)) == sid):
                    if os.path.exists(os.path.join(DATA_DIR, fn)):
                        response = fn; break
        sets.append({
            "id": sid,
            "dir": name,
            "jobs": jobs,
            "vehicles": vehicles,
            "request": request,
            "response": response,
            "viewer_url": f"/viewer?set={sid}",
        })
    sets.sort(key=lambda x: x["id"])  # ascending ids
    return sets

def _ensure_set_dir(set_id: int) -> str:
    d = os.path.join(DATA_DIR, str(set_id))
    os.makedirs(d, exist_ok=True)
    return d

def _csv_preview(path: str, max_rows: int = 10) -> dict:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = [line.rstrip("\n\r") for _, line in zip(range(max_rows), f)]
        # naive CSV split by comma (no quotes handling for simplicity)
        rows = [ln.split(',') for ln in lines]
        return {"rows": rows}
    except FileNotFoundError:
        return {"rows": []}

@app.get("/api/mock-sets")
def api_mock_sets():
    return JSONResponse({"sets": _list_mock_sets()})

@app.post("/api/mock-sets/{set_id}/upload")
async def api_upload_set(set_id: int, jobs: UploadFile | None = FF(None), vehicles: UploadFile | None = FF(None)):
    sd = os.path.join(DATA_DIR, str(set_id))
    if not os.path.isdir(sd):
        logging.error(f"/api/mock-sets/{set_id}/upload: set folder not found: {sd}")
        raise HTTPException(status_code=404, detail=f"Set folder not found: {set_id}")
    saved = {}
    previews = {}
    logging.info(f"/api/mock-sets/{set_id}/upload: started")
    if jobs is not None:
        dest = os.path.join(sd, f"input_jobs_{set_id}.csv")
        content = await jobs.read()
        with open(dest, "wb") as out:
            out.write(content)
        saved["jobs"] = os.path.basename(dest)
        previews["jobs"] = _csv_preview(dest)
        logging.info(f"/api/mock-sets/{set_id}/upload: saved jobs -> {dest}")
    if vehicles is not None:
        dest = os.path.join(sd, f"input_vehicles_{set_id}.csv")
        content = await vehicles.read()
        with open(dest, "wb") as out:
            out.write(content)
        saved["vehicles"] = os.path.basename(dest)
        previews["vehicles"] = _csv_preview(dest)
        logging.info(f"/api/mock-sets/{set_id}/upload: saved vehicles -> {dest}")
    # Note: request and response files are hard-coded/mocked and not created here
    resp = {
        "set": set_id,
        "saved": saved,
        "preview": previews,
        "current": next((s for s in _list_mock_sets() if s["id"] == set_id), None),
    }
    logging.info(f"/api/mock-sets/{set_id}/upload: done -> {resp.get('current')}")
    return JSONResponse(resp)

# Resolve request JSON for a set
def _resolve_request_path(set_id: int) -> str:
    sd = os.path.join(DATA_DIR, str(set_id))
    candidates = [
        os.path.join(sd, f"Next_Billion_request_{set_id}.json"),
        os.path.join(sd, f"nextbillion_request_{set_id}.json"),
        os.path.join(sd, "Next_Billion_request.json"),
        os.path.join(sd, "nextbillion_request.json"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    # Legacy placement at root as fallback
    legacy = [
        os.path.join(DATA_DIR, f"Next_Billion_request_{set_id}.json"),
        os.path.join(DATA_DIR, f"nextbillion_request_{set_id}.json"),
    ]
    for c in legacy:
        if os.path.exists(c):
            return c
    raise HTTPException(status_code=404, detail=f"No request JSON found for set {set_id}")

@app.get("/api/request-raw")
def api_request_raw(set: int = Query(...)):
    path = _resolve_request_path(set)
    data = _load_json(path)
    return JSONResponse(data)

@app.get("/api/request-points")
def api_request_points(set: int = Query(...)):
    path = _resolve_request_path(set)
    req = _load_json(path)
    # Extract points for two common schemas:
    # A) Direct lat/lon arrays on vehicles.start/end and jobs.location
    # B) NextBillion-style location_index with a global locations.location list (strings "lat,lon") and depots mapping
    features = []

    def to_lonlat(v):
        # Accept list [lat,lon] or string "lat,lon"
        if isinstance(v, list) and len(v) == 2:
            lat, lon = float(v[0]), float(v[1])
            return [lon, lat]
        if isinstance(v, str) and "," in v:
            lat_s, lon_s = v.split(",", 1)
            lat, lon = float(lat_s.strip()), float(lon_s.strip())
            return [lon, lat]
        return None

    # Build coordinates array from request.locations.location
    coords_arr = []
    locs = (req.get("locations") or {}).get("location") or []
    for item in locs:
        pt = to_lonlat(item)
        if pt is not None:
            coords_arr.append(pt)
    def coord_by_index(idx):
        try:
            return coords_arr[idx]
        except Exception:
            return None

    # Build depot id -> coord via depots[*].location_index (or direct location)
    depot_coord = {}
    for d in req.get("depots") or []:
        did = d.get("id")
        c = None
        if isinstance(d.get("location_index"), int):
            c = coord_by_index(d["location_index"]) or None
        if c is None:
            c = to_lonlat(d.get("location"))
        if did and c:
            depot_coord[did] = c

    # Vehicles start/end
    vehicles = req.get("vehicles") or []
    for i, v in enumerate(vehicles):
        vid = v.get("id") or i
        # Direct location
        s = to_lonlat(v.get("start"))
        e = to_lonlat(v.get("end"))
        # Or via depot ids → depots → location_index → locations
        if s is None:
            s_ids = v.get("start_depot_ids") or []
            if s_ids:
                s = depot_coord.get(s_ids[0])
        if e is None:
            e_ids = v.get("end_depot_ids") or []
            if e_ids:
                e = depot_coord.get(e_ids[0])
        if s:
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": s},
                "properties": {"point_type": "start", "vehicle": vid}
            })
        if e:
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": e},
                "properties": {"point_type": "end", "vehicle": vid}
            })

    # Jobs
    for j in req.get("jobs") or []:
        jid = j.get("id")
        jc = to_lonlat(j.get("location") or j.get("loc"))
        if jc is None and isinstance(j.get("location_index"), int):
            jc = coord_by_index(j["location_index"]) or None
        if jc:
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": jc},
                "properties": {"point_type": "job", "id": jid}
            })

    return JSONResponse({"type": "FeatureCollection", "features": features})

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


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Consume incoming messages to keep the connection alive; payload ignored.
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception as exc:
        logging.exception("WS error: %s", exc)
        await manager.disconnect(websocket)


@app.post("/api/start-navigation")
async def api_start_navigation(req: StartNavigationRequest):
    payload = {
        "type": "start_navigation",
        "route_id": req.route_id,
        "ts": time.time(),
    }
    try:
        recipients = await manager.broadcast(payload)
    except RuntimeError:
        raise HTTPException(status_code=404, detail="No connected devices")
    return JSONResponse({"sent": True, "recipients": recipients})
