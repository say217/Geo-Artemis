"""
main.py  —  Geo Artemis Application Entry Point
"""
import os
import time
import datetime as dt
from pathlib import Path

import requests
import pandas as pd

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


# ─────────────────────────────────────────────
#  Resolved paths
#  Layout on disk:
#    <project_root>/                   ← Geo Artemis/
#      Data_Source/
#        Nasa_Event_data.csv           ← NASA fetch target
#        USGS_DATA/
#          earthquakes.csv             ← USGS fetch target
#      Main/
#        app4/
#          Data/                       ← processed datasets live here
# ─────────────────────────────────────────────
_HERE         = Path(__file__).resolve().parent          # …/Main
PROJECT_ROOT  = _HERE.parent                             # …/Geo Artemis
DATA_SOURCE   = PROJECT_ROOT / "Data_Source"             # …/Geo Artemis/Data_Source
USGS_OUT_DIR  = DATA_SOURCE / "USGS_DATA"                # …/Geo Artemis/Data_Source/USGS_DATA
NASA_OUT_FILE = DATA_SOURCE / "Nasa_Event_data.csv"
USGS_OUT_FILE = USGS_OUT_DIR / "earthquakes.csv"


# ─────────────────────────────────────────────
#  Feature flags  (set True to enable fetching)
# ─────────────────────────────────────────────
NASA_EVENT_FETCH_ENABLED      = False   # Set to True to fetch NASA EONET events
USGS_EARTHQUAKE_FETCH_ENABLED = False  # Set to True to fetch USGS earthquake data


# ─────────────────────────────────────────────
#  USGS config
# ─────────────────────────────────────────────
USGS_URL        = "https://earthquake.usgs.gov/fdsnws/event/1/query"
USGS_MAX_LIMIT  = 2000    # max records to fetch and store
USGS_CHUNK_DAYS = 60      # days per API chunk to avoid timeouts
USGS_DAYS_BACK  = 20      # how far back to look


# ─────────────────────────────────────────────
#  USGS helpers
# ─────────────────────────────────────────────
def _usgs_fetch_raw(days_back: int = USGS_DAYS_BACK, data_limit: int = USGS_MAX_LIMIT) -> list:
    end_dt   = dt.date.today()
    start_dt = end_dt - dt.timedelta(days=days_back)

    records     = []
    chunk_start = start_dt

    while chunk_start <= end_dt and len(records) < data_limit:
        chunk_end = min(chunk_start + dt.timedelta(days=USGS_CHUNK_DAYS - 1), end_dt)
        offset    = 1

        while len(records) < data_limit:
            remaining = data_limit - len(records)
            params = {
                "format":    "geojson",
                "starttime": chunk_start.isoformat(),
                "endtime":   chunk_end.isoformat(),
                "limit":     min(remaining, 20_000),
                "offset":    offset,
            }

            response = requests.get(USGS_URL, params=params, timeout=(10, 60))
            response.raise_for_status()

            features = response.json().get("features", [])
            if not features:
                break

            records.extend(features)

            if len(features) < params["limit"]:
                break

            offset += params["limit"]

        chunk_start = chunk_end + dt.timedelta(days=1)

    return records[:data_limit]


def _usgs_parse(features: list) -> pd.DataFrame:
    rows = []
    for eq in features:
        props  = eq["properties"]
        coords = eq["geometry"]["coordinates"]
        rows.append({
            "time":      props.get("time"),
            "magnitude": props.get("mag"),
            "place":     props.get("place"),
            "longitude": coords[0],
            "latitude":  coords[1],
            "depth_km":  coords[2],
            "url":       props.get("url"),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["time"] = pd.to_datetime(df["time"], unit="ms")
    return df


# ─────────────────────────────────────────────
#  Lifespan
# ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("=" * 50)
    print(" Starting Geo Artemis Application...")
    print("=" * 50)

    # Ensure output directories exist
    DATA_SOURCE.mkdir(parents=True, exist_ok=True)
    USGS_OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── NASA EONET fetch ──────────────────────
    if NASA_EVENT_FETCH_ENABLED:
        nasa_success = False
        for attempt in range(1, 3):
            try:
                print(f"NASA event fetch – attempt {attempt}...")
                response = requests.get("https://eonet.gsfc.nasa.gov/api/v3/events", timeout=30)
                response.raise_for_status()
                data   = response.json()
                events = data["events"]

                rows = []
                for event in events:
                    for g in event["geometry"]:
                        rows.append({
                            "event":     event["title"],
                            "date":      g["date"],
                            "magnitude": g.get("magnitudeValue"),
                            "lat":       g["coordinates"][1],
                            "lon":       g["coordinates"][0],
                        })

                df = pd.DataFrame(rows)
                df.to_csv(NASA_OUT_FILE, index=False)
                print(f"NASA event data saved → {NASA_OUT_FILE}  ({len(df)} rows)")
                print(df.head(30))
                nasa_success = True
                break

            except Exception as e:
                print(f"NASA event fetch attempt {attempt} failed: {e}")
                if attempt == 1:
                    print("Waiting 20 seconds before retrying...")
                    time.sleep(20)

        if not nasa_success:
            print("NASA event fetch failed after 2 attempts – skipping.")
    else:
        print("NASA_EVENT_FETCH_ENABLED is False – skipping NASA event fetch.")

    # ── USGS Earthquake fetch ─────────────────
    if USGS_EARTHQUAKE_FETCH_ENABLED:
        usgs_success = False
        for attempt in range(1, 3):
            try:
                print(f"USGS earthquake fetch – attempt {attempt}...")
                features = _usgs_fetch_raw(days_back=USGS_DAYS_BACK, data_limit=USGS_MAX_LIMIT)
                df       = _usgs_parse(features)

                df.to_csv(USGS_OUT_FILE, index=False)
                print(f"USGS earthquake data saved → {USGS_OUT_FILE}  ({len(df)} records)")
                print(df.head(10))
                usgs_success = True
                break

            except Exception as e:
                print(f"USGS earthquake fetch attempt {attempt} failed: {e}")
                if attempt == 1:
                    print("Waiting 20 seconds before retrying...")
                    time.sleep(20)

        if not usgs_success:
            print("USGS earthquake fetch failed after 2 attempts – skipping.")
    else:
        print("USGS_EARTHQUAKE_FETCH_ENABLED is False – skipping USGS earthquake fetch.")

    yield  # ← app runs here

    print("=" * 50)
    print("Shutting down Geo Artemis Application...")
    print("=" * 50)


# ─────────────────────────────────────────────
#  App setup
# ─────────────────────────────────────────────
app = FastAPI(lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY", "change-me"))

# ─────────────────────────────────────────────
#  Static mounts  ← ALL mounts before routers
# ─────────────────────────────────────────────
# app2 gets /static, app1 gets /app1/static
app.mount(
    "/static",
    StaticFiles(directory=str(_HERE / "app2" / "static")),
    name="app2_static",
)
app.mount(
    "/app1/static",
    StaticFiles(directory=str(_HERE / "app1" / "static")),
    name="app1_static",
)
app.mount(
    "/app4/componets",
    StaticFiles(directory=str(_HERE / "app4" / "componets")),
    name="app4_componets",
)

# app6 — ensure Satelite_images folder exists BEFORE StaticFiles initialises
_sat_dir = _HERE / "app6" / "Satelite_images"
_sat_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/app6/static",
    StaticFiles(directory=str(_sat_dir)),
    name="app6_static",
)

# ─────────────────────────────────────────────
#  Routers  ← always after static mounts
# ─────────────────────────────────────────────
app.include_router(app1_router, prefix="/app1")
app.include_router(app2_router, prefix="/app2")
app.include_router(app3_router, prefix="/app3")
app.include_router(app4_router, prefix="/app4")
app.include_router(app5_router, prefix="/app5")
app.include_router(app6_router, prefix="/app6")


@app.get("/")
def root():
    return RedirectResponse(url="/app2/login")