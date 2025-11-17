# Flow Docs

Deep-dive notes on how the TomTom Route Viewer is wired end-to-end. Use this as a reference when onboarding new team members or debugging a specific stage of the flow.

---

## 1. Architecture Overview
- **Frontend** (`frontend/index.html`) is a static, vanilla JS page that hosts the TomTom Web Maps SDK, renders request + response data, and exposes workflow controls (Load, Optimize, Navigate, Driver push, Pause, Stop picker, Vehicle picker).
- **Backend** (`backend/app/main.py`) is a FastAPI service that serves the static frontend, exposes REST endpoints for NextBillion data (summary, GeoJSON, raw, request points), emits navigation pushes over WebSocket, and listens on specialized WebSocket channels for order/deviation updates. Helper conversions live in `backend/app/utils.py`.
- **Data layout** lives under `backend/data/`. Each assignment set gets its own folder (e.g., `backend/data/4/`) with request/response JSON and optional CSVs. When no `set=` query param is provided, the backend auto-picks the latest `nextbillion_response_*.json`.
- **Supporting scripts** include TLS bootstrapper (`scripts/setup_tls_and_run.sh`) and HTTPS/WSS smoke test (`scripts/verify_https_wss.py`).

---

## 2. TomTom Map Load Flow
1. **Local SDK bootstrapping** (`frontend/index.html`, lines 7-37):
   - `ensureTomTomSDK()` only loads `/static/vendor/tomtom/maps-web.min.js` and `/static/vendor/tomtom/maps.css` (self-hosted). If files are missing, the user gets an alert.
2. **API key reveal + persistence** (`index.html`, lines 55-124):
   - UI hides the key field until needed. Keys default from `window.__TOMTOM_API_KEY` or `localStorage`.
3. **`Load` button** (`index.html`, lines 205-234):
   - If the key did not change, it simply refreshes request points/vehicles.
   - Otherwise it tears down any existing map instance and calls `boot(apiKey)`.
4. **`boot()`** (`index.html`, lines 213-330):
   - Creates the `tt.map` instance with the provided key, defaulting to Johannesburg coordinates.
   - Registers `NavigationControl`, exposes `window._ttMap` for debugging, and wires a one-time `load` event to fetch request points + vehicle metadata as soon as the style finishes loading.
   - Prepares data sources/layers (`routes`, `route-lines*`, `fallback-lines*`, `route-points`, `focus-point`) and legend scaffolding.
   - Handles tile/auth errors, route point clicks (pan + reverse geocode), and ensures fallback layers are added once per style load to avoid race conditions.
5. **Request data rendering**:
   - `loadRequestPoints()` (`index.html`, lines 731-789) hits `/api/request-points?set=...`, injects the GeoJSON as `request` source, draws both simple circles and custom canvas-rendered “3D” pins, and fits bounds to all request points.
   - `loadRequestVehicles()` (`index.html`, lines 169-187) fills the vehicle dropdown from the request JSON before an optimization result exists.
6. **Optimized routes**:
   - `Optimize Route` button triggers `loadOptimizedRoutes()` (`index.html`, lines 338-414), which fetches `/api/summary` + `/api/routes`.
   - Once data arrives, the map source `routes` is updated, fallback LineStrings are generated (if the response lacks route geometries), bounds are refit, the legend is populated with vehicle colors, stops dropdown is rebuilt, and the navigation path cache is refreshed.
7. **Steps sidebar + click plumbing** (`index.html`, lines 415-520):
   - `renderRoute()` filters point features for the selected `route_index`, builds the left-hand step list, wires click handlers to center the map, highlights the matching line/points layer, and stores selection in `localStorage`.

---

## 3. NextBillion Data Pipeline
### 3.1 Backend data resolution
- `_list_data_files()` and `_resolve_data_path()` (`backend/app/main.py`, lines 62-138) locate response JSONs by version, filename, or assignment set. The resolver searches inside each `data/<set>` folder, then falls back to root-level files, and finally honors a `DATA_FILE` env override.
- `_load_json()` caches each file’s `mtime` and parsed data (`_DATA_CACHE`) to avoid repeated disk I/O when the same file is served to multiple viewers.

### 3.2 REST surface
- `/api/summary` (`main.py`, lines 270-275) returns a trimmed summary from `summarize()` (routes count, vehicle IDs, top-level summary) which the UI uses to display metrics and legend rows.
- `/api/routes` (`main.py`, lines 276-281) returns the GeoJSON created by `nb_to_geojson()` for the selected response file.
- `/api/raw` (`main.py`, lines 283-287) exposes the untouched NextBillion response for diagnostics.
- `/api/request-raw` + `/api/request-points` (`main.py`, lines 430-467) let the UI inspect the request payload. The raw form populates the vehicle list before optimization; the `request-points` variant extracts depots, vehicle start/end points, and job points as GeoJSON so the map can show ground-truth inputs.
- `/api/data-files` + `/api/mock-sets` (`main.py`, lines 480-347) list available response files and assignment folders. `/api/mock-sets/{id}/upload` accepts Jobs/Vehicles CSVs and stores them under the numbered folder, returning quick previews for the upload UI (`frontend/upload.html`).

### 3.3 NextBillion → GeoJSON conversion
- Implemented in `backend/app/utils.py` (`nb_to_geojson` and helpers):
  - Tries to decode `route.geometry` polylines at precision 1e-5 (fallback 1e-6). If the decoded sequence fails validation, it reconstructs a straight-line track from the ordered steps.
  - Every step becomes a GeoJSON Point with properties like `step_type`, `arrival`, `service`, `load`, and `location_index`.
  - Conversion normalizes coordinate order: NextBillion returns `[lat, lon]`, but GeoJSON/TomTom expect `[lon, lat]`.
  - `summarize()` (lines 69-74) plucks `result.summary` aggregates and vehicle IDs for quick consumption.

### 3.4 Frontend consumption
- `loadResponseSummary()` (`index.html`, lines 141-168) fetches `/api/summary`, updates the header badge (`routes: N | deliveries: …`), builds the vehicle dropdown, sets up the legend, and restores the user’s last-selected vehicle.
- `loadOptimizedRoutes()` uses `/api/routes` to hydrate the `routes` source, ensures fallback lines exist when the backend returns points only, and triggers `renderRoute()` + `renderStopsList()` to sync the UI.

---

## 4. GeoJSON & Coordinate Handling
- **Request-side**: `_resolve_request_path()` + `api_request_points()` (`main.py`, lines 408-467) parse either explicit `[lat, lon]` arrays or `"lat,lon"` strings. Depot IDs can resolve to shared coordinates through `location_index` indirection. Each vehicle contributes start/end Point features; each job contributes a Point tagged with `point_type=job`.
- **Response-side**: `nb_to_geojson()` enforces `[lon, lat]` ordering, validates bounding boxes, builds fallback lines when route geometry is missing, and tags each feature with `route_index` so the frontend can filter/highlight by vehicle.
- **Frontend bounding**: Helper `getBBox()` / `getBBoxForRoute()` functions compute map fit bounds for request points, entire GeoJSON, or a single route. `buildFallbackLines()` (lines 210-236) re-creates per-route LineStrings directly from point sequences whenever the server lacks line features.
- **Reverse geocoding**: When clicking a step or when navigation nears a stop, the UI hits TomTom’s reverse-geocode endpoint using the viewer’s API key, enriching step labels with human-readable addresses (`index.html`, lines 356-372 and 623-670).

---

## 5. Frontend Controls & Flow
- **Load** (`#loadBtn`):
  - Initializes the map with the provided TomTom key (or refreshes request data when the key is unchanged). Stores the key in `localStorage`.
- **Optimize Route** (`#optBtn`):
  - Fetches the latest summary/routes for the active assignment set. Populates the legend, steps list, stop dropdown, and navigation path, then fits the map to the selected route.
- **Vehicle Picker** (`#routeSelect`):
  - Drives which route is highlighted, which steps are listed, which stop set populates the dropdown, and which path is used when animating navigation. Selections persist in `localStorage`.
- **Stop Picker** (`#stopSelect`):
  - Jump-to-stop control; selecting an entry centers/focuses that point. Re-selecting the same entry recenters it.
- **Navigation Controls**:
  - `Start Navigation` toggles simulated playback along the densified route path (`buildNavPath()` + `setNavTimer()`).
  - `Pause` switches to `Resume` while freezing the interval timer, and it only becomes enabled once navigation starts.
  - `Speed` dropdown controls the multiplier applied to interval progression (`nav.speed`, affecting timer cadence).
  - Navigation uses a custom DOM marker anchored by `tt.Marker`. As it advances it auto pans/eases the map and opens popups when near stops.
- **Driver Push** (`#driverNavBtn`):
  - Only visible for assignment `set=4`. Maps normalized vehicle IDs to canonical route IDs (`driverRouteMap`). Invokes `POST /api/start-navigation` to notify connected driver devices via WebSocket broadcast.
- **Assignment badge** shows the active `set` from URL params or `localStorage`. Upload view (`frontend/upload.html`) allows switching assignments and uploading CSVs before launching the viewer.

---

## 6. WebSocket Coverage
### 6.1 Broadcast channel (`/ws`)
- Managed by `ConnectionManager` (`main.py`, lines 23-57). Any client connecting to `/ws` is kept in `_connections`. Messages are currently one-way: the server expects a keep-alive text payload, but callbacks simply discard it.
- `POST /api/start-navigation` (`main.py`, lines 257-268) takes `{ "route_id": "route-#" }`, wraps it with `type=start_navigation` and a timestamp, and broadcasts the JSON payload to each connected device. If no devices are registered, it returns HTTP 404 so the UI can alert the dispatcher.

### 6.2 Order status channel (`/order/status`)
- Accepts JSON messages shaped like `{ "order-id": "...", "status": "..." }`. Upon receiving a message, the backend spawns `/home/devuser/netstar-logistics-hub/update_order_status.py` inside its sibling virtualenv, logs stdout/stderr, and replies with an acknowledgement or failure message to the same WebSocket client (`main.py`, lines 184-219). Invalid payloads receive a descriptive error string.

### 6.3 Driver deviation counter (`/driver/deviation_counter`)
- Mirrors the order channel but expects `{ "driver-id": "Driver-1", "counter": <int> }`. Valid updates trigger `/home/devuser/netstar-logistics-hub/update_driver-info.py`, and the client gets confirmation/error text (`main.py`, lines 221-255).

### 6.4 Deployment readiness
- `scripts/setup_tls_and_run.sh` provisions self-signed TLS certificates (unless `SSL_*` env variables point elsewhere), grants `python3` the `cap_net_bind_service` capability so it can bind to port 443 without root, and launches Uvicorn with TLS enabled.
- `scripts/verify_https_wss.py` runs three checks against the configured `PUBLIC_IP`: TCP handshake, HTTPS GET `/`, and a WSS connection to `/ws` using the `websockets` library. Handy sanity-check before letting mobile clients connect.

---

## 7. “Did I Miss Anything?” Extras
- **Fallback geometry logic** ensures maps remain usable even when the NextBillion response lacks `LineString` geometry: the frontend reconstructs polylines from ordered `Point` features; the backend `nb_to_geojson()` validates polylines before emitting them.
- **Legend + color system** uses a fixed palette (red/blue/green/purple/orange/brown). Both the legend and line layers share the same color mapping, so vehicle–color associations stay consistent.
- **Reverse-geocode throttling**: lookups only happen when the user clicks a step or when the simulated marker nears a new stop, reducing quota usage for the TomTom Search API.
- **Assignment uploader**: `frontend/upload.html` + `/api/mock-sets` lets ops teams inspect each assignment folder (Jobs CSV, Vehicles CSV, request, response) and quickly navigate to `/viewer?set=<id>` after uploading.
- **State persistence**: `localStorage` keys (`TT_API_KEY`, `TT_SET_ID`, `TT_SELECTED_ROUTE`) preserve operator preferences across sessions.
- **Error surfaces**: Map tile errors (401/403) prompt the user to re-enter the TomTom API key; failed fetches populate console warnings but keep the UI responsive.
- **Security knobs**: TLS script constrains cert/key locations via env vars, ensures strict file perms on `/etc/ssl/private/app.key`, and grants only the minimum capability needed to bind privileged ports.

Use these notes when tracing a behavior end-to-end: start with the UI control, follow the REST/WebSocket path through FastAPI, and look up the data source under `backend/data/`.
