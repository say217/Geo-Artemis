import json
from pathlib import Path

from fastapi import APIRouter, Request, status
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from ..background_tasks import get_fetcher

router = APIRouter()

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
NEWS_DATA_DIR = Path(__file__).resolve().parent / "NEWS_DATA"


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
