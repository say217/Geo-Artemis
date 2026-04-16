import json
import os
import time
from typing import Optional
from pathlib import Path

from fastapi import APIRouter, Request, status
from fastapi.responses import RedirectResponse, JSONResponse
import requests
from fastapi.templating import Jinja2Templates

from ..background_tasks import get_fetcher

router = APIRouter()

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
NEWS_DATA_DIR = Path(__file__).resolve().parent / "NEWS_DATA"
VIDEO_DATA_DIR = Path(__file__).resolve().parent / "vedio"
VIDEO_DATA_DIR.mkdir(exist_ok=True)
VIDEO_FILE_PATH = VIDEO_DATA_DIR / "videos.json"

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
VIDEO_REFRESH_INTERVAL = 6 * 60 * 60
MAX_VIDEOS = 8
NEWS_CHANNEL_IDS = [
    "UCupvZG-5ko_eiXAupbDfxWw",  # CNN
    "UCBx6eQ1x7ly_d8_4DtrS5DA",  # NDTV
    "UC16niRr50-MSBwiO3YDb3RA",  # BBC News
    "UCNye-wNBqNL5ZzHSJj3l8Bg",  # Al Jazeera English
    "UCN2Zl6Z9r0cXlC8_t8z0xvA",  # DW News
    "UCkQO3QsgTpNTsOw6ujimT5Q",  # Reuters
    "UC52X5wxOL_s5yw0dQk7NtgA",  # Associated Press
    "UCsytnH6PDjPz0pgfzbqpeDw",  # Sky News
    "UCt4t-jeY85JegMlZ-E5UWtA",  # India Today
    "UCIRYBXDze5krPDzAEOxFGVA",  # WION
]


def _fetch_video_items(query: str, channel_id: Optional[str] = None, region_code: Optional[str] = None):
    params = [
        "part=snippet",
        f"q={query}",
        "type=video",
        "videoDuration=long",
        "maxResults=6",
        "order=date",
        "relevanceLanguage=en",
        f"key={YOUTUBE_API_KEY}",
    ]
    if channel_id:
        params.append(f"channelId={channel_id}")
    if region_code:
        params.append(f"regionCode={region_code}")

    url = "https://www.googleapis.com/youtube/v3/search?" + "&".join(params)
    return requests.get(url, timeout=15).json().get("items", [])


def fetch_videos():
    """Fetch English news videos about climate/environment hazards (India + world)."""
    if not YOUTUBE_API_KEY:
        return {
            "last_updated": time.time(),
            "videos": [
                {"title": "Climate change news update", "thumbnail": "https://via.placeholder.com/320x180?text=Climate+News", "videoId": "dQw4w9WgXcQ", "channel": "Sample"},
                {"title": "Floods and storms worldwide", "thumbnail": "https://via.placeholder.com/320x180?text=Storm+News", "videoId": "dQw4w9WgXcQ", "channel": "Sample"},
                {"title": "Wildfire and heatwave alerts", "thumbnail": "https://via.placeholder.com/320x180?text=Wildfire+News", "videoId": "dQw4w9WgXcQ", "channel": "Sample"},
                {"title": "Weather warnings and storm updates", "thumbnail": "https://via.placeholder.com/320x180?text=Weather+News", "videoId": "dQw4w9WgXcQ", "channel": "Sample"},
                {"title": "Tsunami and coastal hazards", "thumbnail": "https://via.placeholder.com/320x180?text=Tsunami+News", "videoId": "dQw4w9WgXcQ", "channel": "Sample"},
                {"title": "India climate and disaster news", "thumbnail": "https://via.placeholder.com/320x180?text=India+Climate", "videoId": "dQw4w9WgXcQ", "channel": "Sample"},
            ]
        }

    query = (
        "climate change OR environment OR disaster OR hazards OR tsunami OR storm "
        "OR wildfire OR floods OR cyclone OR heatwave OR earthquake OR weather"
    )

    try:
        items = []
        if NEWS_CHANNEL_IDS:
            for channel_id in NEWS_CHANNEL_IDS:
                items.extend(_fetch_video_items(query, channel_id=channel_id))
        else:
            items.extend(_fetch_video_items(query, region_code="IN"))
            items.extend(_fetch_video_items(query, region_code="US"))

        videos_by_id = {}
        for item in items:
            video_id = item.get("id", {}).get("videoId")
            snippet = item.get("snippet", {})
            if not video_id or not snippet:
                continue
            videos_by_id[video_id] = {
                "title": snippet.get("title", ""),
                "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
                "videoId": video_id,
                "channel": snippet.get("channelTitle", "")
            }

        videos = list(videos_by_id.values())[:MAX_VIDEOS]
        return {"last_updated": time.time(), "videos": videos}
    except Exception:
        return {
            "last_updated": time.time(),
            "videos": [
                {"title": "Climate change news update", "thumbnail": "https://via.placeholder.com/320x180?text=Climate+News", "videoId": "dQw4w9WgXcQ", "channel": "Sample"},
                {"title": "Weather warnings and storm updates", "thumbnail": "https://via.placeholder.com/320x180?text=Weather+News", "videoId": "dQw4w9WgXcQ", "channel": "Sample"},
            ]
        }


def save_video_data(data):
    with open(VIDEO_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_video_data():
    if not VIDEO_FILE_PATH.exists():
        return None
    try:
        with open(VIDEO_FILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def get_or_refresh_videos():
    data = load_video_data()
    if not data:
        data = fetch_videos()
        save_video_data(data)
        return data

    last_updated = data.get("last_updated", 0)
    if time.time() - last_updated > VIDEO_REFRESH_INTERVAL:
        data = fetch_videos()
        save_video_data(data)
    return data


@router.get("/")
def home(request: Request):
    """Render the news dashboard"""
    if not request.session.get("is_verified"):
        return RedirectResponse(url="/app2/login", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse("home5.html", {"request": request})


@router.get("/get-news-data")
async def get_news_data(request: Request):
    """Retrieve all fetched news data from JSON files"""
    if not request.session.get("is_verified"):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    all_news = {}
    
    if NEWS_DATA_DIR.exists():
        for json_file in sorted(NEWS_DATA_DIR.glob("news_*.json")):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    key = json_file.stem
                    all_news[key] = data
            except Exception as e:
                pass
    
    return JSONResponse({
        "status": "success",
        "total_files": len(all_news),
        "data": all_news
    })


@router.get("/fetch-status")
async def fetch_status(request: Request):
    """Get the current status of background news fetching"""
    if not request.session.get("is_verified"):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    fetcher = get_fetcher()
    if not fetcher:
        return JSONResponse({"status": "Not initialized"}, status_code=500)
    
    status_info = fetcher.get_status()
    return JSONResponse({
        "status": "success",
        **status_info
    })


@router.get("/video/videos.json")
async def get_video_feed(request: Request):
    """Serve cached YouTube video data for the news dashboard"""
    if not request.session.get("is_verified"):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    data = get_or_refresh_videos()
    return JSONResponse(data)
