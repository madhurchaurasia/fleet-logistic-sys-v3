
from typing import Any, Dict, List

def _decode_polyline(s: str, precision: int = 5) -> List[List[float]]:
    """Decode an encoded polyline string into a list of [lon, lat].
    Supports standard Google/OSRM encoding. Precision defaults to 1e-5.
    """
    if not s:
        return []
    coords: List[List[float]] = []
    index = 0
    lat = 0
    lon = 0
    factor = 10 ** precision
    length = len(s)
    while index < length:
        # latitude
        result = 0
        shift = 0
        while True:
            if index >= length:
                break
            b = ord(s[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlat = ~(result >> 1) if (result & 1) else (result >> 1)
        lat += dlat

        # longitude
        result = 0
        shift = 0
        while True:
            if index >= length:
                break
            b = ord(s[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlon = ~(result >> 1) if (result & 1) else (result >> 1)
        lon += dlon

        coords.append([lon / factor, lat / factor])  # [lon, lat]
    return coords

def _is_valid_coords(coords: List[List[float]]) -> bool:
    if not coords or len(coords) < 2:
        return False
    # sample a few points
    sample = coords[:10]
    for x, y in sample:
        if x is None or y is None:
            return False
        if not (-180 <= x <= 180 and -90 <= y <= 90):
            return False
    return True

def nb_to_geojson(nb: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert NextBillion Optimization 'result' into a GeoJSON FeatureCollection:
    - One LineString per route (connecting step locations in order)
    - Point features for each step (start/job/end) with useful properties
    """
    result = nb.get("result", {})
    routes = result.get("routes", [])
    features: List[Dict[str, Any]] = []
    for ridx, route in enumerate(routes):
        steps = route.get("steps", [])
        coords: List[List[float]] = []
        # Prefer decoded road geometry when available; fallback to straight lines between steps
        geom = route.get("geometry")
        if isinstance(geom, str) and geom:
            try:
                coords = _decode_polyline(geom, precision=5)
                # If decoded values look invalid, retry with precision=6
                if not _is_valid_coords(coords):
                    coords = _decode_polyline(geom, precision=6)
            except Exception:
                coords = []
        if not _is_valid_coords(coords):
            for s in steps:
                loc = s.get("location")
                if isinstance(loc, list) and len(loc) == 2:
                    # NextBillion gives [lat, lon]; TomTom & GeoJSON expect [lon, lat]
                    lat, lon = loc[0], loc[1]
                    coords.append([lon, lat])
        # If still invalid, skip adding the line feature to avoid map errors
        if not _is_valid_coords(coords):
            coords = []
        if coords:
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "route_index": ridx,
                    "vehicle": route.get("vehicle"),
                    "cost": route.get("cost"),
                    "distance": route.get("distance"),
                    "duration": route.get("duration"),
                    "setup": route.get("setup"),
                }
            })
        # Add step points
        for s in steps:
            loc = s.get("location")
            if isinstance(loc, list) and len(loc) == 2:
                lat, lon = loc[0], loc[1]
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": {
                        "step_type": s.get("type"),
                        "id": s.get("id"),
                        "arrival": s.get("arrival"),
                        "duration": s.get("duration"),
                        "service": s.get("service"),
                        "waiting_time": s.get("waiting_time"),
                        "load": s.get("load"),
                        "location_index": s.get("location_index"),
                        "route_index": ridx,
                    }
                })
    return {"type": "FeatureCollection", "features": features}

def summarize(nb: Dict[str, Any]) -> Dict[str, Any]:
    res = nb.get("result", {})
    return {
        "code": res.get("code"),
        "summary": res.get("summary"),
        "routes_count": len(res.get("routes", [])),
        "vehicles": [r.get("vehicle") for r in res.get("routes", [])],
    }
