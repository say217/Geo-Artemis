from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import json
import os
import time
import requests
from pathlib import Path

# Setup
app = FastAPI()
test_dir = Path(__file__).parent
video_folder = test_dir / "video"
templates_folder = test_dir / "templates"
FILE_PATH = video_folder / "videos.json"

# Create folders
video_folder.mkdir(exist_ok=True)

# Config
API_KEY = os.getenv("YOUTUBE_API_KEY")
REFRESH_INTERVAL = 6 * 60 * 60  # 6 hours
MAX_VIDEOS = 8
# Add YouTube channel IDs here to force news sources (leave empty to use region search)
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

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------- Helper Functions -------

def fetch_videos():
    """Fetch English news videos about climate/environment hazards (India + world)."""
    if not API_KEY:
        print("⚠️  YOUTUBE_API_KEY not set. Using sample data.")
        return {
            "last_updated": time.time(),
            "videos": [
                {"title": "Climate change news update", "thumbnail": "https://via.placeholder.com/320x180?text=Climate+News", "videoId": "dQw4w9WgXcQ", "channel": "Sample"},
                {"title": "Floods and storms worldwide", "thumbnail": "https://via.placeholder.com/320x180?text=Storm+News", "videoId": "dQw4w9WgXcQ", "channel": "Sample"},
                {"title": "Wildfire and heatwave alerts", "thumbnail": "https://via.placeholder.com/320x180?text=Wildfire+News", "videoId": "dQw4w9WgXcQ", "channel": "Sample"},
                {"title": "Weather warnings and storm updates", "thumbnail": "https://via.placeholder.com/320x180?text=Weather+News", "videoId": "dQw4w9WgXcQ", "channel": "Sample"},
                {"title": "Tsunami and coastal hazards", "thumbnail": "https://via.placeholder.com/320x180?text=Tsunami+News", "videoId": "dQw4w9WgXcQ", "channel": "Sample"},
                {"title": "Environment and climate policy", "thumbnail": "https://via.placeholder.com/320x180?text=Environment+News", "videoId": "dQw4w9WgXcQ", "channel": "Sample"},
                {"title": "India climate and disaster news", "thumbnail": "https://via.placeholder.com/320x180?text=India+Climate", "videoId": "dQw4w9WgXcQ", "channel": "Sample"},
            ]
        }

    query = (
        "climate change OR environment OR disaster OR hazards OR tsunami OR storm "
        "OR wildfire OR floods OR cyclone OR heatwave OR earthquake OR weather"
    )

    def fetch_region(region_code):
        url = (
            "https://www.googleapis.com/youtube/v3/search"
            f"?part=snippet&q={query}"
            "&type=video&videoDuration=long&maxResults=6"
            "&order=date"
            "&relevanceLanguage=en"
            f"&regionCode={region_code}"
            f"&key={API_KEY}"
        )
        res = requests.get(url).json()
        return res.get("items", [])

    def fetch_channel(channel_id):
        url = (
            "https://www.googleapis.com/youtube/v3/search"
            f"?part=snippet&q={query}"
            "&type=video&videoDuration=long&maxResults=6"
            "&order=date"
            "&relevanceLanguage=en"
            f"&channelId={channel_id}"
            f"&key={API_KEY}"
        )
        res = requests.get(url).json()
        return res.get("items", [])

    try:
        if NEWS_CHANNEL_IDS:
            items = []
            for channel_id in NEWS_CHANNEL_IDS:
                items.extend(fetch_channel(channel_id))
        else:
            items = fetch_region("IN") + fetch_region("US")
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
    except Exception as exc:
        print(f"❌ Failed to fetch from YouTube: {exc}")
        return {
            "last_updated": time.time(),
            "videos": [
                {"title": "Climate change news update", "thumbnail": "https://via.placeholder.com/320x180?text=Climate+News", "videoId": "dQw4w9WgXcQ", "channel": "Sample"},
                {"title": "Weather warnings and storm updates", "thumbnail": "https://via.placeholder.com/320x180?text=Weather+News", "videoId": "dQw4w9WgXcQ", "channel": "Sample"},
            ]
        }


def save_data(data):
    """Save video data to JSON file"""
    with open(FILE_PATH, "w") as f:
        json.dump(data, f, indent=2)
    print(f"✓ Saved videos to {FILE_PATH}")


def load_data():
    """Load video data from JSON file"""
    try:
        if FILE_PATH.exists():
            with open(FILE_PATH, "r") as f:
                return json.load(f)
    except:
        pass
    return None


def get_or_refresh_videos():
    """Load videos from cache or refresh if expired"""
    data = load_data()
    
    # No data, fetch new
    if not data:
        print("📥 No video data found, fetching...")
        data = fetch_videos()
        save_data(data)
        return data
    
    # Check if expired
    last_updated = data.get("last_updated", 0)
    if time.time() - last_updated > REFRESH_INTERVAL:
        print("🔄 Video data expired, refreshing...")
        data = fetch_videos()
        save_data(data)
        return data
    
    # Fresh data, use cache
    print("✓ Using cached video data")
    return data



# ------- FastAPI Routes -------

@app.get("/")
def serve_index():
    """Serve the main HTML dashboard"""
    html_path = templates_folder / "index.html"
    if html_path.exists():
        return FileResponse(html_path, media_type="text/html")
    return {"error": "index.html not found", "path": str(html_path)}


@app.get("/video/videos.json")
def get_videos():
    """Get video JSON data - checks timestamp and refreshes if needed"""
    data = get_or_refresh_videos()
    return data


@app.get("/health")
def health_check():
    """Check video data status"""
    if FILE_PATH.exists():
        data = load_data()
        if data:
            return {
                "status": "ok",
                "videos": len(data.get("videos", [])),
                "updated": data.get("last_updated", 0)
            }
    return {"status": "no_data"}


# ------- Startup Initialization -------

@app.on_event("startup")
def startup():
    """Check and load video data on server startup"""
    print("\n" + "="*60)
    print("🚀 Video Server Starting...")
    print("="*60)
    
    # Load or fetch video data
    data = get_or_refresh_videos()
    
    if data and data.get("videos"):
        print(f"✓ {len(data['videos'])} videos ready")
    
    print("📺 Dashboard: http://127.0.0.1:8000")
    print("🔗 API: http://127.0.0.1:8000/video/videos.json")
    print("🏥 Health: http://127.0.0.1:8000/health")
    print("="*60 + "\n")


# ------- Standalone Execution -------

if __name__ == "__main__":
    """Fetch and cache video data before starting server"""
    print("\n🎬 Pre-fetching video data...")
    data = fetch_videos()
    save_data(data)
    print(f"✓ {len(data.get('videos', []))} videos cached\n")
    
    print("📺 To start the server, run:")
    print("   uvicorn test.main:app --reload")
    print("\n   Then open: http://127.0.0.1:8000\n")
