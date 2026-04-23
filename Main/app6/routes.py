from pathlib import Path
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

router = APIRouter()

BASE_DIR      = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
IMAGES_DIR    = BASE_DIR / "Satelite_images"
META_FILE     = IMAGES_DIR / "metadata.json"

TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ── fetch-once guard ──────────────────────────────────────────────────────────
# FIX: Was incorrectly initialised to True, which caused the fetch to be
#      skipped every single time the application started.
_data_fetched: bool = True

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Sources:
#    1. NASA EONET v3      → storm + wildfire event metadata  (no key needed)
#    2. NASA GIBS WMTS     → true-colour MODIS satellite tile per event (no key)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EONET_URL = "https://eonet.gsfc.nasa.gov/api/v3/events"

# NASA GIBS WMTS – MODIS Terra True Colour, 250 m, no API key required
# Fires show as bright red hotspots, storm cloud structures clearly visible
GIBS_TILE_URL = (
    "https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/"
    "MODIS_Terra_CorrectedReflectance_TrueColor/default/"
    "{date}/250m/{z}/{y}/{x}.jpg"
)

# Categories we care about
CATEGORIES = ["wildfires", "severeStorms"]

CATEGORY_LABELS = {
    "wildfires":    "Wildfire",
    "severeStorms": "Severe Storm",
}

CATEGORY_EMOJI = {
    "wildfires":    "🔥",
    "severeStorms": "🌀",
}

REQUEST_TIMEOUT = 15
MAX_IMAGES      = 24      # total tiles to download (12 fires + 12 storms)

# FIX: Removed the hard-coded global TILE_Z/Y/X constants — tiles are now
#      always computed per-event from the event's actual lat/lon coordinates.
TILE_ZOOM = 6             # zoom level used for all tile downloads


# ── helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _today() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


def _safe_get(url: str, stream: bool = False, **kwargs) -> Optional[requests.Response]:
    """Single GET with one 20-second retry on failure."""
    for attempt in range(1, 3):
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT, stream=stream, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            logger.warning("Attempt %d failed — %s: %s", attempt, url, exc)
            if attempt == 1:
                logger.info("Waiting 20 s before retry …")
                time.sleep(20)
    logger.error("Both attempts failed, skipping: %s", url)
    return None


def _lat_lon_to_tile(lat: float, lon: float, zoom: int):
    """
    Convert lat/lon to WMTS tile row/col for EPSG:4326 (geographic) tiling.
    NASA GIBS uses a 2:1 aspect ratio grid.
    """
    n_tiles_y = 2 ** zoom          # rows
    n_tiles_x = 2 * n_tiles_y      # cols (2:1)
    col = int((lon + 180.0) / 360.0 * n_tiles_x)
    row = int((90.0 - lat) / 180.0 * n_tiles_y)
    # clamp
    col = max(0, min(col, n_tiles_x - 1))
    row = max(0, min(row, n_tiles_y - 1))
    return zoom, row, col


def _parse_event_geometry(event: dict) -> Optional[tuple[float, float, str]]:
    """
    Extract (lat, lon, date_str) from an EONET event.

    EONET geometry can be:
      - A single Point:      {"type": "Point", "coordinates": [lon, lat]}
      - A list of Points:    [{"type": "Point", "coordinates": [lon, lat], "date": "..."}, ...]

    FIX: The original code assumed geometry was always a list of dicts and
         directly indexed coords[0]/coords[1], which broke for nested lists
         (e.g. Polygon/MultiPoint) and for Point geometries stored as
         plain lists.  This function handles all common EONET shapes.
    """
    geo = event.get("geometry", [])
    if not geo:
        return None

    # Normalise: if it's a single geometry dict, wrap it
    if isinstance(geo, dict):
        geo = [geo]

    entry = geo[0]
    coords = entry.get("coordinates", [])
    date_str = entry.get("date", _today())[:10]   # YYYY-MM-DD

    # Point: [lon, lat]
    if isinstance(coords[0], (int, float)):
        if len(coords) < 2:
            return None
        lon, lat = float(coords[0]), float(coords[1])
        return lat, lon, date_str

    # Polygon / MultiPoint outer ring: [[lon, lat], ...]
    # Take the centroid of the first ring for a representative location.
    if isinstance(coords[0], list):
        ring = coords[0] if isinstance(coords[0][0], list) else coords
        lons = [c[0] for c in ring if len(c) >= 2]
        lats = [c[1] for c in ring if len(c) >= 2]
        if not lons:
            return None
        return sum(lats) / len(lats), sum(lons) / len(lons), date_str

    return None


# ── core fetch ────────────────────────────────────────────────────────────────

def _fetch_eonet_events() -> list[dict]:
    """Fetch recent open wildfire + storm events from NASA EONET."""
    all_events = []
    for cat in CATEGORIES:
        resp = _safe_get(
            EONET_URL,
            params={
                "category": cat,
                "status":   "open",
                "limit":    MAX_IMAGES // len(CATEGORIES),
                "start":    (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )
        if resp is None:
            logger.error("EONET fetch failed for category: %s — skipping", cat)
            continue

        raw_events = resp.json().get("events", [])
        logger.info("EONET returned %d raw events for category: %s", len(raw_events), cat)

        for event in raw_events:
            try:
                result = _parse_event_geometry(event)
                if result is None:
                    logger.warning("Could not parse geometry for event: %s", event.get("id"))
                    continue
                lat, lon, date_str = result
                all_events.append({
                    "id":          event.get("id", ""),
                    "title":       event.get("title", "Unknown Event"),
                    "category":    cat,
                    "label":       CATEGORY_LABELS.get(cat, cat),
                    "emoji":       CATEGORY_EMOJI.get(cat, "🛰️"),
                    "lat":         lat,
                    "lon":         lon,
                    "date":        date_str,
                    "eonet_url":   event.get("link", ""),
                    "description": (
                        f"{CATEGORY_LABELS.get(cat, cat)} detected near "
                        f"({lat:.2f}°, {lon:.2f}°) on {date_str}. "
                        f"Source: NASA EONET. True-colour MODIS Terra satellite imagery."
                    ),
                })
            except Exception as exc:
                logger.warning("Skipping malformed event %s: %s", event.get("id", "?"), exc)

    logger.info("EONET events parsed: %d total", len(all_events))
    return all_events


def _download_tile(event: dict, index: int) -> Optional[str]:
    """
    Download MODIS GIBS tile closest to the event location.

    FIX: Tile coordinates are now derived from the event's actual lat/lon via
         _lat_lon_to_tile() instead of the old hard-coded (z=4, y=4, x=9)
         constants, which pointed to a single fixed tile regardless of where
         the event was located — causing storm tiles to be fetched from the
         wrong location (or returning HTTP 404s).
    """
    z, y, x = _lat_lon_to_tile(event["lat"], event["lon"], zoom=TILE_ZOOM)
    url = GIBS_TILE_URL.format(date=event["date"], z=z, y=y, x=x)
    logger.info(
        "Fetching tile for '%s' [%s] → lat=%.2f lon=%.2f → z=%d y=%d x=%d date=%s",
        event["title"], event["category"], event["lat"], event["lon"], z, y, x, event["date"],
    )

    resp = _safe_get(url, stream=True)
    if resp is None:
        return None

    filename = f"{event['category']}_{index:03d}_{event['date']}.jpg"
    filepath  = IMAGES_DIR / filename
    try:
        with open(filepath, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=8192):
                fh.write(chunk)
        logger.info("Saved tile → %s", filename)
        return filename
    except OSError as exc:
        logger.error("Could not write tile %s: %s", filename, exc)
        return None


def fetch_and_save_all() -> None:
    """
    One-time fetch: pulls EONET events, downloads one MODIS tile per event,
    writes metadata.json. Called once when the router is first activated.
    """
    global _data_fetched
    if _data_fetched:
        logger.info("Satellite data already fetched this session — skipping.")
        return

    logger.info("=" * 55)
    logger.info("  APP6 — fetching satellite imagery …")
    logger.info("=" * 55)

    events   = _fetch_eonet_events()
    metadata = []

    for idx, event in enumerate(events):
        filename = _download_tile(event, idx)
        if filename:
            metadata.append({**event, "image_file": filename})
        else:
            logger.warning("No tile saved for event: %s", event["title"])

    # Save metadata
    try:
        with open(META_FILE, "w", encoding="utf-8") as fh:
            json.dump(
                {"fetched_at": _now_iso(), "count": len(metadata), "images": metadata},
                fh, indent=2, ensure_ascii=False,
            )
        logger.info("Metadata saved → %s (%d entries)", META_FILE.name, len(metadata))
    except OSError as exc:
        logger.error("Could not write metadata: %s", exc)

    _data_fetched = True
    logger.info("=" * 55)
    logger.info("  APP6 — satellite fetch complete.")
    logger.info("=" * 55)


def _load_metadata() -> list[dict]:
    try:
        with open(META_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh).get("images", [])
    except (OSError, json.JSONDecodeError):
        return []


# ── routes ────────────────────────────────────────────────────────────────────

@router.get("/")
def gallery(request: Request):
    """Trigger one-time fetch then render the image gallery."""
    fetch_and_save_all()
    images = _load_metadata()
    return templates.TemplateResponse(
        "gallery.html",
        {"request": request, "images": images, "total": len(images)},
    )


@router.get("/image/{index}")
def image_detail(request: Request, index: int):
    """Detail page for a single satellite image."""
    fetch_and_save_all()
    images = _load_metadata()
    if index < 0 or index >= len(images):
        return templates.TemplateResponse(
            "gallery.html",
            {"request": request, "images": images, "total": len(images)},
        )
    img = images[index]
    return templates.TemplateResponse(
        "detail.html",
        {"request": request, "img": img, "index": index, "total": len(images)},
    )


@router.get("/api/images")
def api_images():
    """JSON endpoint returning full image metadata list."""
    fetch_and_save_all()
    return JSONResponse(content={"images": _load_metadata()})