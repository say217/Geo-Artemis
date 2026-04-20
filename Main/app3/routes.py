from pathlib import Path
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests
from dotenv import load_dotenv
from fastapi import APIRouter, Request, Query, status
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

DATA_FOLDER = Path(__file__).resolve().parent / "Glob_data"
DATA_FOLDER.mkdir(parents=True, exist_ok=True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  🔧 DEVELOPMENT FLAG
#  Set FETCH_ENABLED = True  → app fetches live data from all APIs on startup
#  Set FETCH_ENABLED = False → app skips all external API calls and serves only
#                              from whatever JSON files already exist on disk.
#                              No crashes, no quota usage, safe for dev/testing.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FETCH_ENABLED: bool = False  # ← flip to True when you want to test live fetching

# ── File paths ────────────────────────────────────────────────────────────────
EVENTS_FILE = DATA_FOLDER / "events_data.json"          # capped globe payload

EVENTS_FILES = {
    "wildfire":   DATA_FOLDER / "events_wildfire.json",
    "earthquake": DATA_FOLDER / "events_earthquake.json",
    "pollution":  DATA_FOLDER / "events_pollution.json",
    "war":        DATA_FOLDER / "events_war.json",
    "protest":    DATA_FOLDER / "events_protest.json",
}

NEWS_FILES = {
    "all":        DATA_FOLDER / "all.json",
    "wildfire":   DATA_FOLDER / "wildfire.json",
    "earthquake": DATA_FOLDER / "earthquake.json",
    "war":        DATA_FOLDER / "war.json",
    "protest":    DATA_FOLDER / "protest.json",
    "pollution":  DATA_FOLDER / "pollution.json",
}

NEWS_API_KEY    = os.getenv("NEWS_API_KEY_GLOB")
OPENWEATHER_KEY = os.getenv("OPENWEATHER_KEY")

# ── Request config ────────────────────────────────────────────────────────────
REQUEST_TIMEOUT   = 10
MAX_RETRIES       = 2
RETRY_BACKOFF     = 1.5
NEWS_FETCH_DELAY  = 12    # seconds between NewsAPI calls (free tier rate limit)
NEWS_PAGE_SIZE    = 15    # articles saved per category (10–15 is plenty)

# ── Globe display cap per category ────────────────────────────────────────────
GLOBE_CAP = {
    "wildfire":   25,
    "earthquake": 25,
    "pollution":  20,
    "war":        10,
    "protest":    10,
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _one_month_ago_iso() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _one_month_ago_date() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")


def _get(url: str, **kwargs) -> Optional[requests.Response]:
    """GET with retry/backoff. 429 responses wait on Retry-After before retrying."""
    import time
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else 0
            if code == 429:
                wait = max(int(exc.response.headers.get("Retry-After", 15)), 15)
                logger.warning("429 for %s — waiting %ds (attempt %d/%d)", url, wait, attempt, MAX_RETRIES)
                time.sleep(wait)
            else:
                logger.warning("Attempt %d/%d failed for %s: %s", attempt, MAX_RETRIES, url, exc)
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BACKOFF * attempt)
        except requests.RequestException as exc:
            logger.warning("Attempt %d/%d failed for %s: %s", attempt, MAX_RETRIES, url, exc)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF * attempt)
    return None


def save_json(file_path: Path, payload: dict) -> None:
    wrapped = {"saved_at": _now_iso(), "data": payload}
    try:
        with open(file_path, "w", encoding="utf-8") as fh:
            json.dump(wrapped, fh, indent=2, ensure_ascii=False)
        logger.info("Saved %s (%d bytes)", file_path.name, file_path.stat().st_size)
    except OSError as exc:
        logger.error("Could not write %s: %s", file_path, exc)


def load_json(file_path: Path) -> Optional[dict]:
    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            wrapped = json.load(fh)
        return wrapped.get("data")
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read %s: %s", file_path, exc)
        return None


def _extract_coords(event: dict):
    try:
        if event.get("geometry") and event["geometry"][0]["type"] == "Point":
            coords = event["geometry"][0]["coordinates"]
            return coords[1], coords[0]
    except Exception:
        pass
    return None, None


def _us_aqi(pm25: float) -> int:
    c = float(pm25)
    breakpoints = [
        (0.0,    12.0,   0,  50),
        (12.1,   35.4,  51, 100),
        (35.5,   55.4, 101, 150),
        (55.5,  150.4, 151, 200),
        (150.5, 250.4, 201, 300),
        (250.5, 350.4, 301, 400),
        (350.5, 500.4, 401, 500),
    ]
    for clo, chi, ilo, ihi in breakpoints:
        if c <= chi:
            return round((ihi - ilo) / (chi - clo) * (c - clo) + ilo)
    return 500


# ── Event fetchers (only called when FETCH_ENABLED = True) ───────────────────

def _fetch_wildfires() -> list[dict]:
    events = []
    resp = _get(
        "https://eonet.gsfc.nasa.gov/api/v3/events",
        params={
            "category": "wildfires",
            "status":   "open",
            "limit":    200,
            "start":    _one_month_ago_iso(),
        },
    )
    if resp is None:
        logger.error("Wildfire fetch failed after retries")
        return events
    for event in resp.json().get("events", []):
        lat, lng = _extract_coords(event)
        if lat is not None:
            events.append({
                "id":    event.get("id"),
                "type":  "wildfire",
                "lat":   lat,
                "lng":   lng,
                "title": event.get("title"),
                "date":  event.get("geometry", [{}])[0].get("date", ""),
            })
    logger.info("Wildfires (past 30 days): %d total", len(events))
    return events


def _fetch_earthquakes() -> list[dict]:
    events = []
    resp = _get(
        "https://earthquake.usgs.gov/fdsnws/event/1/query",
        params={
            "format":       "geojson",
            "minmagnitude": 4.5,
            "starttime":    _one_month_ago_date(),
            "endtime":      datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "orderby":      "magnitude",
            "limit":        500,
        },
    )
    if resp is None:
        logger.error("Earthquake fetch failed after retries")
        return events
    for feat in resp.json().get("features", []):
        coords = feat.get("geometry", {}).get("coordinates", [None, None])
        props  = feat.get("properties", {})
        events.append({
            "id":    feat.get("id"),
            "type":  "earthquake",
            "lat":   coords[1],
            "lng":   coords[0],
            "mag":   props.get("mag"),
            "title": props.get("title"),
            "date":  datetime.fromtimestamp(
                         props["time"] / 1000, tz=timezone.utc
                     ).isoformat() if props.get("time") else "",
        })
    logger.info("Earthquakes (past 30 days, M≥4.5): %d total", len(events))
    return events


def _fetch_pollution() -> list[dict]:
    events = []
    if not OPENWEATHER_KEY:
        logger.warning("OPENWEATHER_KEY not set – skipping pollution")
        return events

    cities = [
        {"name": "New Delhi",   "lat": 28.60,  "lon": 77.20},
        {"name": "Beijing",     "lat": 39.90,  "lon": 116.40},
        {"name": "Lahore",      "lat": 31.50,  "lon": 74.30},
        {"name": "Dhaka",       "lat": 23.80,  "lon": 90.40},
        {"name": "Jakarta",     "lat": -6.20,  "lon": 106.80},
        {"name": "Kolkata",     "lat": 22.57,  "lon": 88.36},
        {"name": "London",      "lat": 51.50,  "lon": -0.10},
        {"name": "Mexico City", "lat": 19.43,  "lon": -99.13},
        {"name": "Cairo",       "lat": 30.06,  "lon": 31.24},
        {"name": "Karachi",     "lat": 24.86,  "lon": 67.01},
        {"name": "Mumbai",      "lat": 19.08,  "lon": 72.88},
        {"name": "Shanghai",    "lat": 31.23,  "lon": 121.47},
        {"name": "Seoul",       "lat": 37.57,  "lon": 126.98},
        {"name": "Tehran",      "lat": 35.69,  "lon": 51.39},
        {"name": "Ulaanbaatar", "lat": 47.91,  "lon": 106.88},
        {"name": "Nairobi",     "lat": -1.29,  "lon": 36.82},
        {"name": "Lagos",       "lat": 6.52,   "lon": 3.38},
        {"name": "Chengdu",     "lat": 30.66,  "lon": 104.07},
        {"name": "Ho Chi Minh", "lat": 10.82,  "lon": 106.63},
        {"name": "Riyadh",      "lat": 24.69,  "lon": 46.72},
    ]
    for city in cities:
        resp = _get(
            "http://api.openweathermap.org/data/2.5/air_pollution",
            params={"lat": city["lat"], "lon": city["lon"], "appid": OPENWEATHER_KEY},
        )
        if resp is None:
            continue
        try:
            pm25 = resp.json()["list"][0]["components"]["pm2_5"]
            aqi  = _us_aqi(pm25)
            if aqi > 100:
                events.append({
                    "id":    f"pol-{city['name'].replace(' ', '-').lower()}",
                    "type":  "pollution",
                    "lat":   city["lat"],
                    "lng":   city["lon"],
                    "aqi":   aqi,
                    "pm25":  round(pm25, 2),
                    "title": f"AQI {aqi} — {city['name']}",
                    "date":  _now_iso(),
                })
        except (KeyError, IndexError, TypeError) as exc:
            logger.warning("Pollution parse error for %s: %s", city["name"], exc)
    events.sort(key=lambda e: e["aqi"], reverse=True)
    logger.info("Pollution hotspots (AQI>100): %d total", len(events))
    return events


def _static_conflicts() -> list[dict]:
    return [
        {"id": "war-ukraine",     "type": "war", "startLat": 48.3,  "startLng": 34.6,  "endLat": 55.7,  "endLng": 37.6,   "title": "Ukraine–Russia Front",     "date": "2022-02-24"},
        {"id": "war-middle-east", "type": "war", "startLat": 31.5,  "startLng": 34.4,  "endLat": 30.0,  "endLng": 31.2,   "title": "Gaza Crisis Zone",          "date": "2023-10-07"},
        {"id": "war-sudan",       "type": "war", "startLat": 12.8,  "startLng": 30.1,  "endLat": 15.5,  "endLng": 32.5,   "title": "Sudan Conflict",             "date": "2023-04-15"},
        {"id": "war-myanmar",     "type": "war", "startLat": 16.8,  "startLng": 96.1,  "endLat": 21.9,  "endLng": 96.1,   "title": "Myanmar Civil War",          "date": "2021-02-01"},
        {"id": "war-haiti",       "type": "war", "startLat": 18.97, "startLng": -72.29,"endLat": 19.10, "endLng": -72.10, "title": "Haiti Gang Conflict",         "date": "2023-03-01"},
        {"id": "war-sahel",       "type": "war", "startLat": 12.36, "startLng": -1.53, "endLat": 15.45, "endLng": 2.11,   "title": "Sahel Insurgency",            "date": "2020-01-01"},
        {"id": "pro-paris",       "type": "protest", "lat": 48.85,  "lng": 2.35,  "title": "Civil Unrest: Paris",          "date": _now_iso()},
        {"id": "pro-delhi",       "type": "protest", "lat": 28.61,  "lng": 77.20, "title": "Farmers Protest: New Delhi",   "date": _now_iso()},
        {"id": "pro-london",      "type": "protest", "lat": 51.50,  "lng": -0.12, "title": "Climate March: London",        "date": _now_iso()},
        {"id": "pro-dhaka",       "type": "protest", "lat": 23.81,  "lng": 90.41, "title": "Student Protests: Dhaka",      "date": _now_iso()},
        {"id": "pro-tbilisi",     "type": "protest", "lat": 41.69,  "lng": 44.83, "title": "Pro-EU March: Tbilisi",        "date": _now_iso()},
        {"id": "pro-belgrade",    "type": "protest", "lat": 44.80,  "lng": 20.47, "title": "Anti-Govt Protests: Belgrade", "date": _now_iso()},
    ]


# ── Event assembly ────────────────────────────────────────────────────────────

def fetch_events_payload() -> dict:
    """
    Fetches all event data, saves full per-category files, then returns
    a capped globe payload. Only called when FETCH_ENABLED = True.
    """
    conflicts = _static_conflicts()
    full: dict[str, list[dict]] = {
        "wildfire":   _fetch_wildfires(),
        "earthquake": _fetch_earthquakes(),
        "pollution":  _fetch_pollution(),
        "war":        [e for e in conflicts if e["type"] == "war"],
        "protest":    [e for e in conflicts if e["type"] == "protest"],
    }

    for cat, events in full.items():
        save_json(
            EVENTS_FILES[cat],
            {"type": cat, "events": events, "count": len(events), "fetched_at": _now_iso()},
        )

    globe_events: list[dict] = []
    for cat, events in full.items():
        cap    = GLOBE_CAP.get(cat, 25)
        sliced = events[:cap]
        globe_events.extend(sliced)
        logger.info("Globe display | %-12s %d / %d points shown", cat, len(sliced), len(events))

    logger.info("Total globe display points: %d", len(globe_events))
    return {"events": globe_events, "fetched_at": _now_iso()}


# ── News fetching (only called when FETCH_ENABLED = True) ────────────────────

_QUERY_MAP = {
    "all":        '("natural disaster" OR "military conflict" OR "civil unrest" OR "wildfire" OR "earthquake")',
    "wildfire":   '("wildfire" OR "forest fire" OR "bushfire")',
    "earthquake": '("earthquake" OR "seismic" OR "tsunami")',
    "war":        '("war" OR "military" OR "missiles" OR "conflict")',
    "protest":    '("protest" OR "riot" OR "civil unrest" OR "strike")',
    "pollution":  '("air quality" OR "smog" OR "AQI" OR "pollution")',
}


def fetch_news_for_category(category: str) -> dict:
    """Fetch up to NEWS_PAGE_SIZE articles for one category."""
    if not NEWS_API_KEY:
        logger.warning("NEWS_API_KEY not set – empty news for '%s'", category)
        return {"news": [], "filter": category, "fetched_at": _now_iso()}

    resp = _get(
        "https://newsapi.org/v2/everything",
        params={
            "q":        _QUERY_MAP[category],
            "sortBy":   "publishedAt",
            "language": "en",
            "pageSize": NEWS_PAGE_SIZE,   # 15 articles max per category
            "apiKey":   NEWS_API_KEY,
        },
    )

    if resp is None:
        logger.error("News fetch failed for '%s'", category)
        return {"news": [], "filter": category, "fetched_at": _now_iso()}

    articles = []
    for art in resp.json().get("articles", []):
        title = art.get("title", "").strip()
        if not title or title == "[Removed]":
            continue
        articles.append({
            "type":        category,
            "title":       title,
            "description": (art.get("description") or "")[:200],
            "source":      art.get("source", {}).get("name", ""),
            "url":         art.get("url", ""),
            "image":       art.get("urlToImage") or "",
            "date":        art.get("publishedAt", ""),
        })

    logger.info("News | %-12s %d articles", category, len(articles))
    return {"news": articles, "filter": category, "fetched_at": _now_iso()}


# ── Startup prefetch ──────────────────────────────────────────────────────────

def prefetch_all_data() -> None:
    """
    Runs once at startup.

    FETCH_ENABLED = False (default / dev mode):
        • Skips ALL external API calls (EONET, USGS, OpenWeather, NewsAPI).
        • Logs a clear notice and serves whatever JSON files exist on disk.
        • App starts instantly with zero API quota used.

    FETCH_ENABLED = True (test / production mode):
        • Fetches all event data (wildfire, earthquake, pollution + static conflicts).
        • Saves full per-category event JSON files.
        • Fetches 15 articles per news category with a 12 s delay between calls.
        • Skips any news category whose cache file already has articles (saves quota).
    """
    if not FETCH_ENABLED:
        logger.info("=" * 55)
        logger.info("  FETCH_ENABLED = False — skipping all API calls.")
        logger.info("  Serving from existing cache files (if any).")
        logger.info("  Set FETCH_ENABLED = True to fetch live data.")
        logger.info("=" * 55)
        return   # ← exit immediately, nothing fetched

    # ── Live fetch path ───────────────────────────────────────────────────────
    logger.info("=" * 55)
    logger.info("  FETCH_ENABLED = True — fetching all live data …")
    logger.info("=" * 55)

    # 1. Events (also writes per-category full files)
    events_payload = fetch_events_payload()
    save_json(EVENTS_FILE, events_payload)
    logger.info("Globe events cache: %d display points saved", len(events_payload["events"]))

    # 2. News — one file per category, throttled to avoid 429s
    import time
    for idx, (category, file_path) in enumerate(NEWS_FILES.items()):
        # Skip categories that already have a valid non-empty cache
        existing = load_json(file_path)
        if existing and existing.get("news"):
            logger.info("News cache hit — skipping '%s' (%d articles cached)", category, len(existing["news"]))
            continue

        if idx > 0:
            logger.info("Waiting %ds before next NewsAPI request …", NEWS_FETCH_DELAY)
            time.sleep(NEWS_FETCH_DELAY)

        payload = fetch_news_for_category(category)
        save_json(file_path, payload)

    logger.info("=" * 55)
    logger.info("  Prefetch complete → %s", DATA_FOLDER)
    logger.info("=" * 55)


# ── FastAPI startup hook ──────────────────────────────────────────────────────

@router.on_event("startup")
async def startup_prefetch():
    """Runs prefetch_all_data() in a thread pool so it doesn't block the event loop."""
    import asyncio
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, prefetch_all_data)


# ── HTTP routes ───────────────────────────────────────────────────────────────

@router.get("/")
def home(request: Request):
    if not request.session.get("is_verified"):
        return RedirectResponse(url="/app2/login", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse("home3.html", {"request": request})


@router.get("/api/events/all")
def get_all_events():
    """
    Returns the capped globe display payload from cache.
    If FETCH_ENABLED = False and no cache exists, returns an empty events list
    (no crash, no API call).
    """
    cached = load_json(EVENTS_FILE)
    if cached is not None:
        logger.info("Serving globe events from cache (%d points)", len(cached.get("events", [])))
        return JSONResponse(content=cached)

    if not FETCH_ENABLED:
        logger.warning("No events cache found and FETCH_ENABLED = False — returning empty payload")
        return JSONResponse(content={"events": [], "fetched_at": _now_iso()})

    # FETCH_ENABLED = True but cache is missing (cold-start race) — fetch live
    logger.warning("Globe events cache missing — fetching live")
    payload = fetch_events_payload()
    save_json(EVENTS_FILE, payload)
    return JSONResponse(content=payload)


@router.get("/api/events/{event_type}")
def get_events_by_type(event_type: str):
    """Returns the full (uncapped) saved dataset for a single event category."""
    if event_type not in EVENTS_FILES:
        return JSONResponse(
            status_code=404,
            content={"error": f"Unknown type '{event_type}'. Valid: {list(EVENTS_FILES.keys())}"},
        )
    cached = load_json(EVENTS_FILES[event_type])
    if cached is not None:
        return JSONResponse(content=cached)
    return JSONResponse(
        status_code=503,
        content={"error": "Cache not ready. Set FETCH_ENABLED = True and restart to populate."},
    )


@router.get("/api/news")
def get_news(filter_type: str = Query(default="all")):
    """
    Returns cached news articles for the requested category.
    If FETCH_ENABLED = False and no cache exists, returns an empty list (no crash).
    """
    category  = filter_type if filter_type in NEWS_FILES else "all"
    file_path = NEWS_FILES[category]

    cached = load_json(file_path)
    if cached is not None:
        logger.info("Serving news from cache (filter=%s, %d articles)", category, len(cached.get("news", [])))
        return JSONResponse(content=cached)

    if not FETCH_ENABLED:
        logger.warning("No news cache for '%s' and FETCH_ENABLED = False — returning empty", category)
        return JSONResponse(content={"news": [], "filter": category, "fetched_at": _now_iso()})

    # FETCH_ENABLED = True but cache is missing — fetch live
    logger.warning("News cache missing for '%s' — fetching live", category)
    payload = fetch_news_for_category(category)
    save_json(file_path, payload)
    return JSONResponse(content=payload)


