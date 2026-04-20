"""
main.py  —  only the lifespan block needs to change.
Remove the serp_api_key argument from initialize_fetcher().
"""
import os
from pathlib import Path
NASA_EVENT_FETCH_ENABLED = True  # Set to False to skip NASA event fetch
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


try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle app startup and shutdown."""
    print("=" * 50)
    print(" Starting Geo Artemis Application...")
    print("=" * 50)

    # NASA event fetch logic
    if NASA_EVENT_FETCH_ENABLED:
        try:
            import requests
            import pandas as pd
            nasa_url = "https://eonet.gsfc.nasa.gov/api/v3/events"
            response = requests.get(nasa_url)
            data = response.json()
            events = data["events"]
            rows = []
            for event in events:
                for g in event["geometry"]:
                    rows.append({
                        "event": event["title"],
                        "date": g["date"],
                        "magnitude": g.get("magnitudeValue"),
                        "lat": g["coordinates"][1],
                        "lon": g["coordinates"][0]
                    })
            df = pd.DataFrame(rows)
            data_dir = Path(__file__).resolve().parent.parent / "Data_Source"
            data_dir.mkdir(parents=True, exist_ok=True)
            out_path = data_dir / "Nasa_Event_data.csv"
            df.to_csv(out_path, index=False)
            print(f"NASA event data saved to {out_path}")
            print(df.head(30))
        except Exception as e:
            print(f"NASA event fetch failed: {e}")
    else:
        print("NASA_EVENT_FETCH_ENABLED is False – skipping NASA event fetch.")

    yield  # app runs here

    print("=" * 50)
    print("🛑 Shutting down Geo Artemis Application...")
    print("=" * 50)


app = FastAPI(lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY", "change-me"))

app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).resolve().parent / "app1" / "static")),
    name="static",
)
app.mount(
    "/app4/componets",
    StaticFiles(
        directory=str(Path(__file__).resolve().parent / "app4" / "componets")
    ),
    name="app4_componets",
)

app.include_router(app1_router, prefix="/app1")
app.include_router(app2_router, prefix="/app2")
app.include_router(app3_router, prefix="/app3")
app.include_router(app4_router, prefix="/app4")
app.include_router(app5_router, prefix="/app5")
app.include_router(app6_router, prefix="/app6")


@app.get("/")
def root():
    return RedirectResponse(url="/app2/login")