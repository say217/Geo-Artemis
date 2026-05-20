import json
import os
import time
from typing import Optional
from pathlib import Path

from fastapi import APIRouter, Request, status
from fastapi.responses import RedirectResponse, JSONResponse
import requests
from fastapi.templating import Jinja2Templates


router = APIRouter()

templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent / "templates")
)

GLOB_DATA_DIR = Path(__file__).resolve().parent.parent / "app3" / "Glob_data"

# Category → filename mapping (mirrors app3/routes.py NEWS_FILES)
NEWS_CACHE_FILES = {
    "all":        GLOB_DATA_DIR / "all.json",
    "wildfire":   GLOB_DATA_DIR / "wildfire.json",
    "earthquake": GLOB_DATA_DIR / "earthquake.json",
    "war":        GLOB_DATA_DIR / "war.json",
    "protest":    GLOB_DATA_DIR / "protest.json",
    "pollution":  GLOB_DATA_DIR / "pollution.json",
    "noaa":       GLOB_DATA_DIR / "noaa.json",
}

# ── YouTube video cache (unchanged) ──────────────────────────────────────────
VIDEO_DATA_DIR = Path(__file__).resolve().parent / "vedio"
VIDEO_DATA_DIR.mkdir(exist_ok=True)
VIDEO_FILE_PATH = VIDEO_DATA_DIR / "videos.json"

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
# Enable/Disable real API fetching. Set to False to always use hardcoded Sample data.
YOUTUBE_FETCH_ENABLED = os.getenv("YOUTUBE_FETCH_ENABLED", "True").lower() == "true"

VIDEO_REFRESH_INTERVAL = 6 * 60 * 60   # 6 hours
MAX_VIDEOS = 20

NEWS_CHANNEL_IDS = [
    # ── General News Networks ────────────────────────────────────────────────
    "UCupvZG-5ko_eiXAupbDfxWw",  # CNN
    "UCBx6eQ1x7ly_d8_4DtrS5DA",  # NDTV
    "UC16niRr50-MSBwiO3YDb3RA",  # BBC News
  
 
    
    # ── Environmental & Wildlife News ────────────────────────────────────────
    "UCpDojzidHks6yNVEUodZ62w",  # National Geographic Official
    "UCxp2gLe8s_8fRxWr_qyqfKw",  # TED-Ed
    "UCkRfArvrzheW2E7b6SVVLLw",  # Kurzgesagt – In a Nutshell
    "UC3Ow7g0fmqy8A0BKOp4mxgQ",  # BBC Wildlife
    "UCtFayL7QUgH2qNzpIxlpFAg",  # Vox
    "UCt7IfZPvbCbmzU1L7bXqe2Q",  # Veritasium
    "UC_x5XG1OV2P6uZZ5FSM9Ttw",  # Crash Course
    "UCwWhs_6x42DyiJoQq0i5L0w",  # CGP Grey
    "UCi7GJPp5fJHqoWUFWkaSvzQ",  # World Wildlife Fund (WWF)
    "UC9-XoASoKe66sNKAE8RKnfg",  # Our Changing Climate
    "UCsKCJXY5QsztS88axjEUP4A",  # Climate Reality Project
    "UC4p4kgrJ-1_S6TFgUlbfO9A",  # Planet Patrol
    "UCMxsYvOJ4k7eXjVQN6X8Eow",  # Earth's Last Chance
    "UC5N9V4Aym8o9I9T2zPjoxyw",  # Planetary TV
    "UCEKBLj5PK9ydJ8WdlrO7DXg",  # NOVA PBS
    "UCsPLqYDcSwd9Z1Y0W2SEzAA",  # BBC Earth
    "UCJPWcaLS6-vKNMv0VYKpHFA",  # Nature League
    "UC73UOuoqvwL9G08pWx7YQLA",  # Survival of the Fittest
    "UCvDi7j8MYkL5RfOZaKFmZXA",  # Nature's Best Moments
    "UCRvmouFLgOSl0sNW9CwHfqA",  # Environmental News
    "UCELxZJ7gGrTscq5cJa1ZSlA",  # Green Living
    "UC_FIEbL__Lk2iJrCpn8c-tg",  # Earth Matters
    "UCWvWZE3aZk4eDfZL7EF1Vaw",  # Climate Matters
]

VIDEO_SEARCH_QUERY = (
    "climate change OR natural disaster OR flood OR earthquake OR wildfire "
    "OR cyclone OR heatwave OR tsunami OR war OR conflict OR pollution "
    "OR environmental hazard OR international summit OR geopolitics OR weather forecast "
    "OR wildlife conservation OR endangered species OR biodiversity OR habitat destruction "
    "OR ocean acidification OR deforestation OR carbon emissions OR renewable energy "
    "OR environmental protection OR animal rescue OR nature documentary OR ecological crisis "
    "OR sustainable development OR climate summit OR extreme weather "
)



# ── YouTube helpers (unchanged) ───────────────────────────────────────────────

def _fetch_video_items(
    query: str,
    channel_id: Optional[str] = None,
    region_code: Optional[str] = None,
) -> list:
    params = [
        "part=snippet",
        f"q={requests.utils.quote(query)}",
        "type=video",
        "videoDuration=medium",
        "maxResults=10",
        "order=date",
        "relevanceLanguage=en",
        f"key={YOUTUBE_API_KEY}",
    ]
    if channel_id:
        params.append(f"channelId={channel_id}")
    if region_code:
        params.append(f"regionCode={region_code}")

    url = "https://www.googleapis.com/youtube/v3/search?" + "&".join(params)
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return resp.json().get("items", [])
    except Exception:
        return []


def fetch_videos() -> dict:
    """Fetch recent English news videos about hazards / world events."""
    if not YOUTUBE_FETCH_ENABLED or not YOUTUBE_API_KEY:
        return {
            "last_updated": time.time(),
            "videos": [
                {
                    "title": "Climate change & extreme weather news",
                    "thumbnail": "https://images.unsplash.com/photo-1564349683136-77e08dba1ef7?w=320&h=180&fit=crop",
                    "videoId": "dQw4w9WgXcQ",
                    "channel": "Global Intel",
                },
                {
                    "title": "Earthquake & Tsunami Risk Assessment 2026",
                    "thumbnail": "https://images.unsplash.com/photo-1511044491364-b0b2eff28ee1?w=320&h=180&fit=crop",
                    "videoId": "dQw4w9WgXcQ",
                    "channel": "Hazard Watch",
                },
                {
                    "title": "Wildfire Containment: Live Ops Update",
                    "thumbnail": "https://images.unsplash.com/photo-1542385151-efd9000785a0?w=320&h=180&fit=crop",
                    "videoId": "dQw4w9WgXcQ",
                    "channel": "Fire Control",
                },
            ],
        }

    try:
        raw_items: list = []
        for channel_id in NEWS_CHANNEL_IDS:
            raw_items.extend(
                _fetch_video_items(VIDEO_SEARCH_QUERY, channel_id=channel_id)
            )

        videos_by_id: dict = {}
        for item in raw_items:
            video_id = item.get("id", {}).get("videoId")
            snippet  = item.get("snippet", {})
            if not video_id or not snippet:
                continue
            if video_id in videos_by_id:
                continue
            videos_by_id[video_id] = {
                "title":     snippet.get("title", ""),
                "thumbnail": (
                    snippet.get("thumbnails", {})
                           .get("high", {})
                           .get("url", "")
                ),
                "videoId": video_id,
                "channel": snippet.get("channelTitle", ""),
            }

        videos = list(videos_by_id.values())[:MAX_VIDEOS]
        
        # If we fetched 0 videos (e.g. quota exceeded or empty results), 
        # try to return whatever we have in the local cache file instead of empty/sample.
        if not videos:
            cached = _load_video_data()
            if cached and cached.get("videos"):
                return cached

        return {"last_updated": time.time(), "videos": videos}

    except Exception:
        # On error, try to return cache first, then sample data as ultimate fallback
        cached = _load_video_data()
        if cached and cached.get("videos"):
            return cached
            
        return {
            "last_updated": time.time(),
            "videos": [
                {
                    "title": "Climate & environment news",
                    "thumbnail": "https://via.placeholder.com/320x180?text=Climate+News",
                    "videoId": "dQw4w9WgXcQ",
                    "channel": "Sample",
                },
            ],
        }


def _save_video_data(data: dict):
    with open(VIDEO_FILE_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def _load_video_data() -> Optional[dict]:
    if not VIDEO_FILE_PATH.exists():
        return None
    try:
        with open(VIDEO_FILE_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def get_or_refresh_videos() -> dict:
    """Return cached video data, refreshing when the cache is stale."""
    data = _load_video_data()
    if not data:
        data = fetch_videos()
        _save_video_data(data)
        return data
    if time.time() - data.get("last_updated", 0) > VIDEO_REFRESH_INTERVAL:
        data = fetch_videos()
        _save_video_data(data)
    return data


# ── News cache helpers ────────────────────────────────────────────────────────

def _read_news_cache(category: str) -> list[dict]:
    """
    Read articles for one category from app3's Glob_data cache file.
    Returns a flat list of article dicts, or [] if the file is missing/empty.

    app3 file structure:
        {
          "saved_at": "2026-...",
          "data": {
            "news": [ { "type", "title", "description", "source",
                        "url", "image", "date" }, ... ],
            "filter": "wildfire",
            "fetched_at": "2026-..."
          }
        }
    """
    file_path = NEWS_CACHE_FILES.get(category)
    if file_path is None or not file_path.exists():
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            wrapped = json.load(fh)
        return wrapped.get("data", {}).get("news", [])
    except (OSError, json.JSONDecodeError):
        return []


def _build_news_payload() -> dict:
    """
    Read all 6 category cache files and merge into the payload structure
    expected by the frontend's loadNewsData() function.

    Frontend expects:
        {
          "status": "success",
          "total_files": N,
          "data": {
            "news_<category>": {
              "incident": "<Category>",
              "articles": [
                {
                  "headline": "...",
                  "description": "...",
                  "source": "...",
                  "url": "...",
                  "image": "...",
                  "published_at": "..."
                }, ...
              ]
            },
            ...
          }
        }
    """
    data: dict = {}
    total_articles = 0

    for category, file_path in NEWS_CACHE_FILES.items():
        articles_raw = _read_news_cache(category)
        if not articles_raw:
            continue   # skip empty / missing cache files silently

        # Normalise each article to the shape the frontend expects
        normalised = []
        for art in articles_raw:
            normalised.append({
                "headline":     art.get("title", ""),
                "description":  art.get("description", ""),
                "source":       art.get("source", ""),
                "url":          art.get("url", ""),
                "image":        art.get("image", ""),
                "published_at": art.get("date", ""),
            })

        data[f"news_{category}"] = {
            "incident": category.capitalize(),
            "articles": normalised,
        }
        total_articles += len(normalised)

    return {
        "status":      "success",
        "total_files": len(data),
        "total_articles": total_articles,
        "data":        data,
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/")
def home(request: Request):
    """Render the news dashboard."""
    if not request.session.get("is_verified"):
        return RedirectResponse(url="/app2/login", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse("home5.html", {"request": request})


@router.get("/get-news-data")
async def get_news_data(request: Request):
    """
    Return all saved news data as a single payload for the frontend.
    Reads directly from app3's Glob_data cache files — no live fetching.
    """
    if not request.session.get("is_verified"):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    payload = _build_news_payload()
    return JSONResponse(payload)


@router.get("/fetch-status")
async def fetch_status(request: Request):
    """
    Return a simple status object.
    Background fetcher has been removed — news is served from app3 cache.
    """
    if not request.session.get("is_verified"):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    # Check how many cache files exist and are non-empty
    cached_categories = []
    for category, file_path in NEWS_CACHE_FILES.items():
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as fh:
                    d = json.load(fh)
                count = len(d.get("data", {}).get("news", []))
                if count:
                    cached_categories.append({"category": category, "articles": count})
            except Exception:
                pass

    return JSONResponse({
        "status":            "success",
        "is_running":        False,          # no background fetcher
        "source":            "app3_cache",   # reading from Glob_data
        "cached_categories": cached_categories,
        "cache_dir":         str(GLOB_DATA_DIR),
    })


@router.get("/video/videos.json")
async def get_video_feed(request: Request):
    """Serve cached YouTube video data to the news dashboard."""
    if not request.session.get("is_verified"):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    data = get_or_refresh_videos()
    return JSONResponse(data)


@router.on_event("startup")
async def startup_video_prefetch():
    """Ensure video data is fresh on startup without overloading APIs."""
    import threading
    # Run in a thread to not block startup if fetching takes time
    thread = threading.Thread(target=get_or_refresh_videos)
    thread.start()
