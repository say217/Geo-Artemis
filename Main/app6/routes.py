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

# ── cache window ──────────────────────────────────────────────────────────────
CACHE_HOURS = 12   # evry 12 hourse it refresh it self added a time stamp in the json

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Sources:
#    1. NASA EONET v3      → storm + wildfire event metadata  (no key needed)
#    2. NASA GIBS WMTS     → true-colour MODIS satellite tile per event (no key)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EONET_URL = "https://eonet.gsfc.nasa.gov/api/v3/events"

GIBS_TILE_URL = (
    "https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/"
    "MODIS_Terra_CorrectedReflectance_TrueColor/default/"
    "{date}/250m/{z}/{y}/{x}.jpg"
)

CATEGORIES = ["wildfires", "severeStorms"]

CATEGORY_LABELS = {
    "wildfires":    "Wildfire",
    "severeStorms": "Severe Storm",
}

CATEGORY_EMOJI = {
    "wildfires":    "",
    "severeStorms": "",
}

REQUEST_TIMEOUT = 15
MAX_IMAGES      = 24
TILE_ZOOM       = 6


# ── helpers ───────────────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_utc().isoformat().replace("+00:00", "Z")


def _today() -> str:
    return (_now_utc() - timedelta(days=1)).strftime("%Y-%m-%d")


def _metadata_is_fresh() -> bool:
    """
    Return True if metadata.json exists AND was fetched less than CACHE_HOURS ago.
    Reads the 'fetched_at' timestamp written by fetch_and_save_all().
    """
    if not META_FILE.exists():
        logger.info("metadata.json not found — fetch required.")
        return False

    try:
        with open(META_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        fetched_at_str = data.get("fetched_at")
        if not fetched_at_str:
            logger.warning("metadata.json has no 'fetched_at' field — treating as stale.")
            return False

        fetched_at = datetime.fromisoformat(fetched_at_str.replace("Z", "+00:00"))
        age = _now_utc() - fetched_at
        age_hours = age.total_seconds() / 3600

        if age_hours < CACHE_HOURS:
            logger.info(
                "Cache is fresh (%.1f h old, threshold %d h) — skipping fetch.",
                age_hours, CACHE_HOURS,
            )
            return True

        logger.info(
            "Cache is stale (%.1f h old, threshold %d h) — re-fetching.",
            age_hours, CACHE_HOURS,
        )
        return False

    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        logger.warning("Could not parse metadata.json: %s — treating as stale.", exc)
        return False


def _api_get(url: str, **kwargs) -> Optional[requests.Response]:
    """
    GET for critical API calls (EONET metadata).
    Retries once after a short 5-second pause so a transient hiccup doesn't
    abort the whole fetch session.  Does NOT stream.
    """
    for attempt in range(1, 3):
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            logger.warning("API attempt %d failed — %s: %s", attempt, url, exc)
            if attempt == 1:
                logger.info("Waiting 5 s before API retry …")
                time.sleep(5)
    logger.error("API: both attempts failed, skipping: %s", url)
    return None


def _tile_get(url: str) -> Optional[requests.Response]:
    """
    GET for a single GIBS tile — fails instantly with NO retry and NO sleep.
    Tiles are expendable: a bad tile is logged and skipped so the rest of the
    batch is not delayed.
    """
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, stream=True)
        resp.raise_for_status()
        return resp
    except requests.RequestException as exc:
        logger.warning("Tile fetch failed (skipping, no retry) — %s: %s", url, exc)
        return None


def _lat_lon_to_tile(lat: float, lon: float, zoom: int):
    """Convert lat/lon to WMTS tile row/col for EPSG:4326 geographic tiling."""
    n_tiles_y = 2 ** zoom
    n_tiles_x = 2 * n_tiles_y
    col = int((lon + 180.0) / 360.0 * n_tiles_x)
    row = int((90.0 - lat) / 180.0 * n_tiles_y)
    col = max(0, min(col, n_tiles_x - 1))
    row = max(0, min(row, n_tiles_y - 1))
    return zoom, row, col


def _parse_event_geometry(event: dict) -> Optional[tuple[float, float, str]]:
    """Extract (lat, lon, date_str) from an EONET event."""
    geo = event.get("geometry", [])
    if not geo:
        return None

    if isinstance(geo, dict):
        geo = [geo]

    entry = geo[0]
    coords = entry.get("coordinates", [])
    date_str = entry.get("date", _today())[:10]

    if isinstance(coords[0], (int, float)):
        if len(coords) < 2:
            return None
        lon, lat = float(coords[0]), float(coords[1])
        return lat, lon, date_str

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
        resp = _api_get(
            EONET_URL,
            params={
                "category": cat,
                "status":   "open",
                "limit":    MAX_IMAGES // len(CATEGORIES),
                "start":    (_now_utc() - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"),
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


def _fetch_raw_tile(date: str, z: int, y: int, x: int) -> Optional["Image.Image"]:
    """
    Download a single GIBS tile and return it as a Pillow Image.
    Returns None instantly if the tile errors — no retry, no sleep.
    Tiles outside the valid grid are skipped silently.
    """
    from PIL import Image
    import io

    n_tiles_y = 2 ** z
    n_tiles_x = 2 * n_tiles_y
    if not (0 <= y < n_tiles_y and 0 <= x < n_tiles_x):
        return None   # outside grid boundary — fill with blank later

    url  = GIBS_TILE_URL.format(date=date, z=z, y=y, x=x)
    resp = _tile_get(url)
    if resp is None:
        return None

    try:
        raw = b"".join(resp.iter_content(chunk_size=8192))
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        return img
    except Exception as exc:
        logger.warning("Could not decode tile z=%d y=%d x=%d: %s", z, y, x, exc)
        return None


def _download_tile(event: dict, index: int) -> Optional[str]:
    """
    Fetch a 3×3 grid of GIBS tiles centred on the event's location and stitch
    them into one composite image so the event is never cut off at a tile edge.

    - Any individual tile that fails is replaced with a dark-grey blank —
      no retry, no sleep, no delay to the rest of the batch.
    - If the centre tile itself fails the whole event is skipped (nothing
      useful to show).
    - The stitched JPEG is saved with a UTC fetch timestamp in the filename.
    """
    from PIL import Image

    z, cy, cx = _lat_lon_to_tile(event["lat"], event["lon"], zoom=TILE_ZOOM)
    date       = event["date"]

    logger.info(
        "Stitching 3×3 tiles for '%s' [%s] → lat=%.2f lon=%.2f → centre z=%d y=%d x=%d date=%s",
        event["title"], event["category"], event["lat"], event["lon"], z, cy, cx, date,
    )

    # ── fetch 3×3 neighbourhood ───────────────────────────────────────────────
    grid: list[list[Optional[Image.Image]]] = []
    tile_w = tile_h = None   # determined from the first successfully decoded tile

    for dy in (-1, 0, 1):
        row_imgs: list[Optional[Image.Image]] = []
        for dx in (-1, 0, 1):
            img = _fetch_raw_tile(date, z, cy + dy, cx + dx)
            if img is not None and tile_w is None:
                tile_w, tile_h = img.size
            row_imgs.append(img)
        grid.append(row_imgs)

    # Centre tile is mandatory — if it failed, skip the event entirely
    centre = grid[1][1]
    if centre is None:
        logger.warning(
            "Centre tile missing for '%s' — skipping event.", event["title"]
        )
        return None

    if tile_w is None or tile_h is None:
        tile_w, tile_h = centre.size   # fallback

    # ── stitch ───────────────────────────────────────────────────────────────
    blank = Image.new("RGB", (tile_w, tile_h), color=(30, 30, 30))
    canvas_w = tile_w * 3
    canvas_h = tile_h * 3
    canvas   = Image.new("RGB", (canvas_w, canvas_h), color=(30, 30, 30))

    for row_idx, row_imgs in enumerate(grid):
        for col_idx, img in enumerate(row_imgs):
            paste_x = col_idx * tile_w
            paste_y = row_idx * tile_h
            canvas.paste(img if img is not None else blank, (paste_x, paste_y))
            if img is None:
                logger.debug(
                    "Blank fill for missing tile at grid[%d][%d] (dy=%d dx=%d)",
                    row_idx, col_idx, row_idx - 1, col_idx - 1,
                )

    # ── save ─────────────────────────────────────────────────────────────────
    fetched_ts = _now_utc().strftime("%Y%m%dT%H%M%SZ")
    filename   = f"{event['category']}_{index:03d}_{date}_{fetched_ts}.jpg"
    filepath   = IMAGES_DIR / filename

    try:
        canvas.save(str(filepath), format="JPEG", quality=85, optimize=True)
        logger.info("Saved stitched 3×3 tile → %s (%dx%d px)", filename, canvas_w, canvas_h)
        return filename
    except OSError as exc:
        logger.error("Could not write stitched tile %s: %s", filename, exc)
        return None


def _purge_old_images(keep: set) -> None:
    """
    Delete every .jpg in IMAGES_DIR whose filename is NOT in *keep*.

    Called only AFTER new images have been saved and metadata.json has been
    written successfully, so a failed fetch never leaves the directory empty.

    Only .jpg files are touched — metadata.json and any other files are
    left untouched regardless.
    """
    deleted = skipped = 0
    for path in IMAGES_DIR.glob("*.jpg"):
        if path.name in keep:
            skipped += 1
            continue
        try:
            path.unlink()
            logger.info("Deleted old image → %s", path.name)
            deleted += 1
        except OSError as exc:
            logger.warning("Could not delete %s: %s", path.name, exc)

    logger.info(
        "Purge complete — deleted %d old image(s), kept %d current image(s).",
        deleted, skipped,
    )


def fetch_and_save_all() -> None:
    """
    Fetch EONET events and download one MODIS tile per event, then write
    metadata.json.  Skips everything if metadata is less than CACHE_HOURS old.
    Called on every route activation; the freshness check is cheap (one file read).

    Cleanup order (safe):
      1. Fetch new images and save to disk
      2. Write metadata.json with the new filenames
      3. Only then delete images NOT in the new set
    This guarantees a failed fetch never wipes the previous cache.
    """
    if _metadata_is_fresh():
        return   # cache still valid — nothing to do

    logger.info("=" * 55)
    logger.info("  Fetching new satellite imagery …")
    logger.info("=" * 55)

    events   = _fetch_eonet_events()
    metadata = []

    for idx, event in enumerate(events):
        filename = _download_tile(event, idx)
        if filename:
            metadata.append({**event, "image_file": filename})
        else:
            logger.warning("No tile saved for event: %s", event["title"])

    # ── write metadata first ──────────────────────────────────────────────────
    metadata_written = False
    try:
        with open(META_FILE, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "fetched_at": _now_iso(),   # ISO-8601 UTC — used by _metadata_is_fresh()
                    "count":      len(metadata),
                    "images":     metadata,
                },
                fh, indent=2, ensure_ascii=False,
            )
        logger.info("Metadata saved → %s (%d entries)", META_FILE.name, len(metadata))
        metadata_written = True
    except OSError as exc:
        logger.error("Could not write metadata: %s — skipping purge to preserve old images.", exc)

    # ── purge old images only after metadata is safely on disk ────────────────
    if metadata_written and metadata:
        current_files = {entry["image_file"] for entry in metadata}
        _purge_old_images(keep=current_files)
    elif metadata_written and not metadata:
        logger.warning("No images were fetched — skipping purge to avoid empty gallery.")

    logger.info("=" * 55)
    logger.info("  Satellite fetch complete.")
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
    """Check cache freshness, fetch if stale, then render the image gallery."""
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