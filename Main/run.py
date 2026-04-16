import os
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .app1.routes import router as app1_router
from .app2.routes import router as app2_router
from .app3.routes import router as app3_router
from .app4.routes import router as app4_router
from .app5.routes import router as app5_router
from .app6.routes import router as app6_router
from .background_tasks import initialize_fetcher, get_fetcher

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


# Lifespan context manager for startup and shutdown events
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle app startup and shutdown"""
    # Startup
    print("=" * 50)
    print("🚀 Starting Geo Artemis Application...")
    print("=" * 50)
    
    # Initialize background news fetcher
    news_data_dir = Path(__file__).resolve().parent / "app5" / "NEWS_DATA"
    api_key = os.getenv("NEWS_API_KEY")
    serp_api_key = os.getenv("SERP_API")
    
    fetcher = initialize_fetcher(news_data_dir, api_key, serp_api_key)
    print(f"📰 News Data Directory: {news_data_dir}")
    
    # Start background news fetching
    fetcher.start_background_fetch()
    
    yield  # App runs here
    
    # Shutdown
    print("=" * 50)
    print("🛑 Shutting down Geo Artemis Application...")
    print("=" * 50)
    fetcher.stop_background_fetch()


app = FastAPI(lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY", "change-me"))

app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).resolve().parent / "app1" / "static")),
    name="static",
)

app.mount(
    "/app4/componets",
    StaticFiles(directory=str(Path(__file__).resolve().parent / "app4" / "componets")),
    name="app4_componets",
)

# Include routers
app.include_router(app1_router, prefix="/app1")
app.include_router(app2_router, prefix="/app2")
app.include_router(app3_router, prefix="/app3")
app.include_router(app4_router, prefix="/app4")
app.include_router(app5_router, prefix="/app5")
app.include_router(app6_router, prefix="/app6")

@app.get("/")
def root():
    return RedirectResponse(url="/app2/login")




