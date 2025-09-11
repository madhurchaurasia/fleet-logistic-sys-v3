
# TomTom Route Viewer (FastAPI + NextBillion)
This sample app renders an optimized route (jobs-only VRP) from a **NextBillion** response onto a **TomTom Maps SDK for Web** map.

## What this includes
- **FastAPI backend**
  - `GET /api/summary` — high-level stats (supports `?version=` or `?file=`)
  - `GET /api/routes` — GeoJSON (LineString per route + Point per step) (supports `?version=` or `?file=`)
  - `GET /api/raw` — raw NextBillion response (supports `?version=` or `?file=`)
  - `GET /api/data-files` — list available data files and the current default
  - Serves the static frontend at `/`
- **Frontend** (vanilla HTML/JS)
  - Paste your TomTom API key at the top bar and click **Load**
  - Draws all routes and step markers; left card lists steps for the first route with click-to-zoom

## Run locally
```bash
cd backend
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```
Then open http://127.0.0.1:8000/ and enter your **TomTom API key**.

> Data files
> - Place one or more files under `backend/data/` named `nextbillion_response.json`, `nextbillion_response_1.json`, `nextbillion_response_2.json`, ...
> - By default, the server auto-selects the latest numbered file (highest suffix). If none exist, it falls back to the base `nextbillion_response.json`.
> - Override selection via query params, e.g. `GET /api/summary?version=2` or `GET /api/routes?file=nextbillion_response_2.json`.
> - You can also set `DATA_FILE` env var to force a specific file.

## Notes
- NextBillion step locations are `[lat, lon]`. We convert to `[lon, lat]` for GeoJSON/TomTom.
- Styling is minimal on purpose; tweak line/circle paint in `index.html` layers.
- If you have multiple routes, all are drawn; the left panel lists steps for route `0`. Extend UI easily to pick routes.

## Self-hosted TomTom SDK (no external CDNs)
Some networks block TomTom/unpkg/jsDelivr CDNs. This app is configured to load the SDK only from your local filesystem.

1) Create the folder:
   - `frontend/vendor/tomtom/`
2) Download the two files from a network that allows it (any 6.x version):
   - `maps-web.min.js`
   - `maps.css`
   From, e.g.:
   - `https://cdn.jsdelivr.net/npm/@tomtom-international/web-sdk-maps@6/dist/`
   - or `https://unpkg.com/@tomtom-international/web-sdk-maps@6/dist/`
3) Place them into `frontend/vendor/tomtom/`.

They will be served at:
- `http://127.0.0.1:8000/static/vendor/tomtom/maps-web.min.js`
- `http://127.0.0.1:8000/static/vendor/tomtom/maps.css`

If these URLs return 200, the frontend will show `sdk: local` in the header badge.

> Note: earlier proxy endpoints (`/sdk/*`) have been removed; self-hosting is the supported method.

## Project layout
```
tomtom_fastapi_route_app/
├─ backend/
│  ├─ app/
│  │  ├─ main.py
│  │  └─ utils.py
│  ├─ data/
│  │  ├─ nextbillion_response.json (optional)
│  │  ├─ nextbillion_response_1.json
│  │  ├─ nextbillion_response_2.json
│  │  └─ ...
│  └─ requirements.txt
└─ frontend/
   └─ index.html
```
