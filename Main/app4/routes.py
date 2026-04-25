import json
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import APIRouter, Request, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from joblib import load
from sklearn.metrics.pairwise import haversine_distances

from .Model_train import train_and_save_model
from .Prepaire import load_prepare_data
from .plots import (
    get_event_distribution_data,
    get_wildfire_magnitude_data,
    get_volcano_events_data,
    get_cluster_summary_data,
    get_events_by_type_data,
    get_events_per_year_data,
    get_magnitude_distribution_data,
    get_geo_clusters_html,
    get_geo_clusters_clean_html,
    get_high_risk_regions_html,
    get_comprehensive_analysis_html,
    get_clustered_events_html,
    get_all_events_by_type_html,
    get_wildfire_intensity_trend_data,
    get_volcano_intensity_trend_data,
    get_event_type_count_data,
    get_high_risk_regions_data,
)

router = APIRouter()

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

# ─────────────────────────────────────────────
#  Resolved paths
#
#  Folder layout:
#    <project_root>/                        ← Geo Artemis/
#      Data_Source/
#        Nasa_Event_data.csv                ← raw NASA fetch output (written by main.py)
#        USGS_DATA/
#          earthquakes.csv                  ← raw USGS fetch output (written by main.py)
#      Main/
#        app4/                              ← this package
#          Data/
#            final_hazard_dataset.csv       ← prepared data (input = NASA file above)
#            final_hazard_dataset_with_clusters.csv
#            cluster_summary.csv
#            High_risk_regions.csv
#            event_counts.csv
#          model/
#            hdbscan_model.joblib
# ─────────────────────────────────────────────
_APP4_DIR    = Path(__file__).resolve().parent           # …/Main/app4
_MAIN_DIR    = _APP4_DIR.parent                          # …/Main
PROJECT_ROOT = _MAIN_DIR.parent                          # …/Geo Artemis

# Source: NASA raw data written by main.py lifespan
source_data_path = PROJECT_ROOT / "Data_Source" / "Nasa_Event_data.csv"

# Processed / trained artefacts — all live inside app4/Data/
_DATA_DIR        = _APP4_DIR / "Data"
prepared_data_path = _DATA_DIR / "final_hazard_dataset.csv"
data_path          = _DATA_DIR / "final_hazard_dataset_with_clusters.csv"

# Model
model_path = _APP4_DIR / "model" / "hdbscan_model.joblib"

# USGS earthquake CSV written by main.py lifespan
_usgs_data_path = PROJECT_ROOT / "Data_Source" / "USGS_DATA" / "earthquakes.csv"


# ─────────────────────────────────────────────
#  Haversine helper
# ─────────────────────────────────────────────
def _haversine_km(lat1: float, lon1: float, lat2: np.ndarray, lon2: np.ndarray) -> np.ndarray:
    lat1_rad = np.radians(lat1)
    lon1_rad = np.radians(lon1)
    lat2_rad = np.radians(lat2)
    lon2_rad = np.radians(lon2)

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(dlon / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(a))


def _load_cluster_points() -> list[dict]:
    if not data_path.exists():
        return []
    df = pd.read_csv(data_path)
    df = df.dropna(subset=["lat", "lon", "cluster"]).copy()
    return df[["lat", "lon", "cluster", "Event_type", "intensity"]].to_dict("records")


def _compute_cluster_regions() -> list[dict]:
    """Compute refined regions for each cluster, filtering out excessively large areas."""
    if not data_path.exists():
        return []

    df = pd.read_csv(data_path)
    df = df.dropna(subset=["lat", "lon", "cluster"]).copy()

    regions = []
    for cluster_id in df["cluster"].unique():
        if cluster_id == -1:  # Skip noise
            continue

        points = df[df["cluster"] == cluster_id][["lat", "lon"]].values
        
        # ── 1. Filter out "Too Big" or "Too Wide" regions ──────────────────────
        # Clusters spanning more than 40 degrees longitude or 30 degrees latitude
        # are often artifacts or global trends rather than localized hazards.
        lat_span = points[:, 0].max() - points[:, 0].min()
        lon_span = points[:, 1].max() - points[:, 1].min()
        
        if lon_span > 40 or lat_span > 30:
            continue

        center = points.mean(axis=0)

        # ── 2. Create Bounds ──────────────────────────────────────────────────
        if len(points) < 3:
            # For 1-2 points, create a very tight bounding box
            radius = 0.08  # Approx 9km
            bounds = [
                [center[0] - radius, center[1] - radius],
                [center[0] + radius, center[1] - radius],
                [center[0] + radius, center[1] + radius],
                [center[0] - radius, center[1] + radius],
            ]
        else:
            try:
                from scipy.spatial import ConvexHull
                hull = ConvexHull(points)
                raw_bounds = points[hull.vertices].tolist()
                
                # Tiny buffer expansion
                bounds = []
                for p in raw_bounds:
                    lat_buf = 0.02 if p[0] >= center[0] else -0.02
                    lon_buf = 0.02 if p[1] >= center[1] else -0.02
                    bounds.append([p[0] + lat_buf, p[1] + lon_buf])
            except Exception:
                bounds = [
                    [points[:, 0].min() - 0.05, points[:, 1].min() - 0.05],
                    [points[:, 0].max() + 0.05, points[:, 1].min() - 0.05],
                    [points[:, 0].max() + 0.05, points[:, 1].max() + 0.05],
                    [points[:, 0].min() - 0.05, points[:, 1].max() + 0.05],
                ]

        regions.append({
            "cluster": int(cluster_id),
            "bounds":  bounds,
            "center":  center.tolist(),
            "count":   len(points),
        })

    return regions


def predict_region(lat: float, lon: float, df, eps_km: float = 200):
    """Predict which region a new point belongs to."""
    clustered_df = df[df["cluster"] != -1].copy()

    if clustered_df.empty:
        return {"status": "NoData", "message": "No clusters available."}

    centroids = (
        clustered_df
        .groupby("cluster")[["lat", "lon"]]
        .mean()
        .reset_index()
    )

    new_point      = np.radians([[lat, lon]])
    centroid_coords = np.radians(centroids[["lat", "lon"]].values)

    distances    = haversine_distances(new_point, centroid_coords) * 6371.0088
    min_dist     = float(distances.min())
    nearest_idx  = int(distances.argmin())
    nearest_cluster = int(centroids.iloc[nearest_idx]["cluster"])

    subset     = clustered_df[clustered_df["cluster"] == nearest_cluster]
    event_type = subset["Event_type"].mode()[0] if not subset.empty else "Unknown"

    if min_dist <= eps_km:
        return {
            "status":           "Assigned",
            "region":           nearest_cluster,
            "most_common_event": event_type,
            "distance_km":      round(min_dist, 1),
            "message":          f"-> Assigned to Region {nearest_cluster} ({event_type})\n   Distance: {min_dist:.1f} km",
        }
    else:
        return {
            "status":         "NewNoise",
            "closest_region": nearest_cluster,
            "event_type":     event_type,
            "distance_km":    round(min_dist, 1),
            "message":        f"-> NEW / Noise Event\n   Closest region: {nearest_cluster} ({min_dist:.1f} km away)",
        }


def _predict_region(lat: float, lon: float) -> dict:
    if not data_path.exists():
        return {"status": "NoData"}

    try:
        df = pd.read_csv(data_path)
        df = df.loc[:, ~df.columns.str.contains("^Unnamed")]
        result = predict_region(lat, lon, df)
        result["lat"] = lat
        result["lon"] = lon
        return result
    except Exception as exc:
        return {"status": f"PredictionError: {str(exc)}"}


def _render_page(
    request: Request,
    prediction: dict | None = None,
    message: str | None = None,
    show_clusters: bool = True,
    show_regions: bool = False,
    charts: dict | None = None,
):
    points  = _load_cluster_points() if show_clusters else []
    regions = _compute_cluster_regions() if show_regions else []
    return templates.TemplateResponse(
        "home4.html",
        {
            "request":      request,
            "points_json":  json.dumps(points),
            "regions_json": json.dumps(regions),
            "prediction":   prediction,
            "message":      message,
            "show_clusters": show_clusters,
            "show_regions":  show_regions,
            "charts":       charts,
        },
    )


# ─────────────────────────────────────────────
#  API Endpoints for AJAX
# ─────────────────────────────────────────────

@router.get("/api/cluster-points")
def api_cluster_points():
    """Return all cluster points as JSON."""
    points = _load_cluster_points()
    return {"data": points, "count": len(points)}


@router.get("/api/cluster-regions")
def api_cluster_regions():
    """Return all cluster polygons as JSON."""
    regions = _compute_cluster_regions()
    return {"data": regions, "count": len(regions)}


# ─────────────────────────────────────────────
#  Routes
# ─────────────────────────────────────────────

@router.get("/")
def home(request: Request):
    if not request.session.get("is_verified"):
        return RedirectResponse(url="/app2/login", status_code=status.HTTP_303_SEE_OTHER)
    return _render_page(request, show_clusters=False)


@router.post("/predict")
async def predict(request: Request):
    if not request.session.get("is_verified"):
        return RedirectResponse(url="/app2/login", status_code=status.HTTP_303_SEE_OTHER)

    form = await request.form()
    try:
        lat = float(form.get("lat", ""))
        lon = float(form.get("lon", ""))
    except ValueError:
        lat = None
        lon = None

    prediction = None
    if lat is not None and lon is not None:
        prediction = _predict_region(lat, lon)
        prediction["lat"] = lat
        prediction["lon"] = lon

    return _render_page(request, prediction=prediction, show_clusters=False)


@router.post("/train")
def train(request: Request):
    if not request.session.get("is_verified"):
        return RedirectResponse(url="/app2/login", status_code=status.HTTP_303_SEE_OTHER)

    try:
        if not source_data_path.exists():
            raise FileNotFoundError(
                f"NASA source file not found: {source_data_path}\n"
                "Enable NASA_EVENT_FETCH_ENABLED in main.py and restart, "
                "or place Nasa_Event_data.csv in Data_Source/ manually."
            )

        print(f"[TRAIN] Loading data from: {source_data_path}")
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        load_prepare_data(source_data_path, prepared_data_path)
        print(f"[TRAIN] Data prepared at: {prepared_data_path}")

        print("[TRAIN] Training model...")
        train_and_save_model(prepared_data_path, model_path, data_path)
        print(f"[TRAIN] Model saved at:    {model_path}")
        print(f"[TRAIN] Clusters saved at: {data_path}")

        message = "[OK] Model trained & saved successfully. Click 'Show Clusters' to visualize."
    except Exception as exc:
        print(f"[TRAIN ERROR] {str(exc)}")
        message = f"[ERROR] Training failed: {str(exc)}"

    return _render_page(request, message=message, show_clusters=False)


@router.post("/show-clusters")
def show_clusters(request: Request):
    if not request.session.get("is_verified"):
        return RedirectResponse(url="/app2/login", status_code=status.HTTP_303_SEE_OTHER)

    points = _load_cluster_points()
    if not points:
        return _render_page(
            request,
            message="⚠ No clusters found. Please train the model first.",
            show_clusters=False,
        )

    message = f"[OK] Showing {len(set(p['cluster'] for p in points))} cluster regions on map."
    return _render_page(request, message=message, show_clusters=True)


@router.post("/show-regions")
def show_regions(request: Request):
    if not request.session.get("is_verified"):
        return RedirectResponse(url="/app2/login", status_code=status.HTTP_303_SEE_OTHER)

    regions = _compute_cluster_regions()
    if not regions:
        return _render_page(
            request,
            message="⚠ No regions found. Please train the model first.",
            show_regions=False,
        )

    message = f"[OK] Showing {len(regions)} colored cluster regions overlay."
    return _render_page(request, message=message, show_regions=True, show_clusters=False)


@router.post("/charts")
def charts(request: Request):
    if not request.session.get("is_verified"):
        return RedirectResponse(url="/app2/login", status_code=status.HTTP_303_SEE_OTHER)

    try:
        chart_data = {
            "event_dist":    get_event_distribution_data(),
            "wildfire":      get_wildfire_magnitude_data(),
            "volcano":       get_volcano_events_data(),
            "cluster_summary": get_cluster_summary_data(),
            "events_by_type":  get_events_by_type_data(),
            "events_per_year": get_events_per_year_data(),
            "magnitude_dist":  get_magnitude_distribution_data(),
        }

        geo_clusters_path       = get_geo_clusters_html()
        geo_clusters_clean_path = get_geo_clusters_clean_html()

        chart_data["geo_clusters_url"]       = "/app4/plot/geo_clusters_all" if geo_clusters_path else None
        chart_data["geo_clusters_clean_url"] = "/app4/plot/geo_clusters_clean" if geo_clusters_clean_path else None

        comprehensive_path = get_comprehensive_analysis_html()
        chart_data["comprehensive_url"] = "/app4/plot/comprehensive_analysis" if comprehensive_path else None

        return _render_page(
            request,
            message="✓ Exploratory Data Analysis - All Charts",
            charts=chart_data,
            show_clusters=False,
        )
    except Exception as exc:
        print(f"[CHARTS ERROR] {exc}")
        return _render_page(request, message=f"✗ Charts failed: {exc}")


@router.get("/plot/{plot_name}")
def get_plot(plot_name: str):
    """Serve plot HTML files."""
    if not all(c.isalnum() or c == "_" for c in plot_name):
        return {"error": "Invalid plot name"}

    file_path = _APP4_DIR / "plots" / f"{plot_name}.html"
    if not file_path.exists():
        return {"error": "Plot not found"}

    return FileResponse(file_path, media_type="text/html")


@router.get("/satellite-data")
def get_satellite_data():
    """Serve NASA Event data as JSON (reads from Data_Source/)."""
    nasa_data_path = PROJECT_ROOT / "Data_Source" / "Nasa_Event_data.csv"

    if not nasa_data_path.exists():
        return {"error": "NASA Event data not found — enable fetching or place file manually.", "data": []}

    try:
        df      = pd.read_csv(nasa_data_path)
        data    = df.head(100).to_dict(orient="records")
        columns = df.columns.tolist()
        return {"columns": columns, "data": data, "total_rows": len(df)}
    except Exception as e:
        return {"error": str(e), "data": []}


@router.get("/event-types")
def get_event_types():
    """Serve event count data from app4/Data/event_counts.csv."""
    event_counts_path = _DATA_DIR / "event_counts.csv"

    if not event_counts_path.exists():
        return {"error": "Event counts file not found — train the model first.", "data": []}

    try:
        df = pd.read_csv(event_counts_path)
        df = df.loc[:, ~df.columns.str.contains("^Unnamed")]
        return {"columns": df.columns.tolist(), "data": df.to_dict(orient="records")}
    except Exception as e:
        return {"error": str(e), "data": []}


@router.get("/clustered-data-head")
def get_clustered_data_head():
    """Serve first rows of clustered data as JSON."""
    if not data_path.exists():
        return {"error": "Clustered data file not found — train the model first.", "data": []}

    try:
        df = pd.read_csv(data_path)
        df = df.loc[:, ~df.columns.str.contains("^Unnamed")]
        return {"columns": df.columns.tolist(), "data": df.head(10).to_dict(orient="records")}
    except Exception as e:
        return {"error": str(e), "data": []}


@router.get("/cluster-summary")
def get_cluster_summary():
    """Serve cluster summary with risk scores as JSON."""
    cluster_summary_path = _DATA_DIR / "cluster_summary.csv"

    if not cluster_summary_path.exists():
        return {"error": "Cluster summary file not found — train the model first.", "data": []}

    try:
        df = pd.read_csv(cluster_summary_path)
        df = df.loc[:, ~df.columns.str.contains("^Unnamed")]
        return {"columns": df.columns.tolist(), "data": df.to_dict(orient="records"), "count": len(df)}
    except Exception as e:
        return {"error": str(e), "data": []}


@router.get("/high-risk-regions")
def get_high_risk_regions():
    """Serve high-risk regions sorted by time_risk_score descending."""
    high_risk_path = _DATA_DIR / "High_risk_regions.csv"

    if not high_risk_path.exists():
        return {"error": "High-risk regions file not found — train the model first.", "data": []}

    try:
        df = pd.read_csv(high_risk_path)
        df = df.loc[:, ~df.columns.str.contains("^Unnamed")]
        # Use 'risk_score' as per the latest CSV structure
        sort_col = "risk_score" if "risk_score" in df.columns else (df.columns[0] if not df.empty else None)
        if sort_col:
            df = df.sort_values(by=sort_col, ascending=False)
        return {"columns": df.columns.tolist(), "data": df.to_dict(orient="records"), "count": len(df)}
    except Exception as e:
        return {"error": str(e), "data": []}


@router.get("/wildfire-intensity-trend")
def wildfire_intensity_trend():
    data = get_wildfire_intensity_trend_data()
    return data if data else {"error": "No wildfire data available"}


@router.get("/volcano-intensity-trend")
def volcano_intensity_trend():
    data = get_volcano_intensity_trend_data()
    return data if data else {"error": "No volcano data available"}


@router.get("/event-type-count")
def event_type_count():
    data = get_event_type_count_data()
    return data if data else {"error": "No event data available"}


@router.get("/high-risk-regions-summary")
def high_risk_regions_summary():
    data = get_high_risk_regions_data()
    return data if data else {"error": "No high-risk data available"}


@router.get("/all-events-2026")
def all_events_2026():
    """Serve all events from 2026 for map display (reads from app4/Data/)."""
    if not prepared_data_path.exists():
        return {"error": "Data file not found — train the model first.", "data": [], "count": 0}

    try:
        df = pd.read_csv(prepared_data_path)
        df.columns = df.columns.str.replace(r"^Unnamed: \d+", "", regex=True)

        df_2026 = df[df["year"] == 2026].copy() if "year" in df.columns else df.copy()

        if df_2026.empty:
            return {"error": "No events found for 2026", "data": [], "count": 0}

        events_list = []
        for _, row in df_2026.iterrows():
            try:
                events_list.append({
                    "lat":        float(row.get("lat", row.get("latitude", row.get("Latitude", 0)))),
                    "lon":        float(row.get("lon", row.get("longitude", row.get("Longitude", 0)))),
                    "Event_type": str(row.get("Event_type", row.get("most_common_event", "Other"))),
                    "intensity":  float(row.get("intensity", row.get("magnitude", 1))),
                    "year":       int(row.get("year", 2026)),
                    "month":      int(row.get("month", 1)) if "month" in row else 1,
                })
            except (ValueError, TypeError):
                continue

        return {"data": events_list, "count": len(events_list), "year": 2026}

    except Exception as e:
        return {"error": str(e), "data": [], "count": 0}


@router.get("/earthquake-points")
def get_earthquake_points():
    """Serve earthquake data from Data_Source/USGS_DATA/earthquakes.csv (top 1000 by magnitude)."""
    if not _usgs_data_path.exists():
        return {
            "error": (
                f"Earthquake data not found at {_usgs_data_path}. "
                "Enable USGS_EARTHQUAKE_FETCH_ENABLED in main.py and restart."
            ),
            "data":  [],
            "count": 0,
        }

    try:
        df = pd.read_csv(_usgs_data_path)
        if df.empty:
            return {"error": "No earthquake data available", "data": [], "count": 0}

        df_limited = (
            df.nlargest(1000, "magnitude") if "magnitude" in df.columns else df.head(1000)
        )

        earthquakes_list = []
        for _, row in df_limited.iterrows():
            try:
                earthquakes_list.append({
                    "lon":       float(row.get("longitude", row.get("lon", 0))),
                    "lat":       float(row.get("latitude",  row.get("lat", 0))),
                    "depth_km":  float(row.get("depth_km", 0)),
                    "magnitude": float(row.get("magnitude", 0)),
                    "place":     str(row.get("place", "Unknown")),
                    "time":      str(row.get("time", "N/A")),
                    "url":       str(row.get("url", "")),
                })
            except (ValueError, TypeError, KeyError):
                continue

        return {
            "data":          earthquakes_list,
            "count":         len(earthquakes_list),
            "total_in_file": len(df),
            "limited_to":    1000,
        }

    except Exception as e:
        return {"error": str(e), "data": [], "count": 0}