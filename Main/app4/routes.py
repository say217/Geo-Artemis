import json
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import APIRouter, Request, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from joblib import load

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
)

router = APIRouter()

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


base_dir = Path(__file__).resolve().parent
project_root = base_dir.parents[1]  # Go up: app4 -> Main -> Geo Artemis
source_data_path = project_root / "Data_Source" / "final_hazard_dataset.csv"
prepared_data_path = base_dir / "Data" / "final_hazard_dataset.csv"
data_path = base_dir / "Data" / "final_hazard_dataset_with_clusters.csv"
model_path = base_dir / "model" / "dbscan_model.joblib"


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
    return df[["lat", "lon", "cluster", "Event_type", "magnitude"]].to_dict("records")


def _compute_cluster_regions() -> list[dict]:
    """Compute convex hull regions for each cluster."""
    if not data_path.exists():
        return []
    
    df = pd.read_csv(data_path)
    df = df.dropna(subset=["lat", "lon", "cluster"]).copy()
    
    regions = []
    for cluster_id in df["cluster"].unique():
        if cluster_id == -1:  # Skip noise
            continue
        
        cluster_points = df[df["cluster"] == cluster_id][["lat", "lon"]].values
        
        if len(cluster_points) < 3:
            # Too few points for hull, use buffer around centroid
            centroid = cluster_points.mean(axis=0)
            radius = 0.5  # degrees approximate buffer
            bounds = [
                [centroid[0] - radius, centroid[1] - radius],
                [centroid[0] + radius, centroid[1] - radius],
                [centroid[0] + radius, centroid[1] + radius],
                [centroid[0] - radius, centroid[1] + radius],
            ]
        else:
            # Compute convex hull
            try:
                from scipy.spatial import ConvexHull
                hull = ConvexHull(cluster_points)
                bounds = cluster_points[hull.vertices].tolist()
            except:
                # Fallback: use bounding box
                bounds = [
                    [cluster_points[:, 0].min(), cluster_points[:, 1].min()],
                    [cluster_points[:, 0].max(), cluster_points[:, 1].min()],
                    [cluster_points[:, 0].max(), cluster_points[:, 1].max()],
                    [cluster_points[:, 0].min(), cluster_points[:, 1].max()],
                ]
        
        regions.append({
            "cluster": int(cluster_id),
            "bounds": bounds,
            "center": cluster_points.mean(axis=0).tolist(),
            "count": len(cluster_points),
        })
    
    return regions


def _predict_region(lat: float, lon: float) -> dict:
    if not model_path.exists():
        return {"status": "ModelMissing"}

    try:
        model = load(model_path)
        core_coords = model["core_coords"]  # Already in radians
        core_labels = model["core_labels"]
        eps_km = float(model["eps_km"])
        summary_df = model["cluster_summary"]

        # Convert new point to radians for haversine
        new_lat_rad = np.radians(lat)
        new_lon_rad = np.radians(lon)
        
        # Extract lat/lon from core_coords (already in radians)
        core_lats = core_coords[:, 0]
        core_lons = core_coords[:, 1]
        
        # Calculate haversine distances
        dlat = core_lats - new_lat_rad
        dlon = core_lons - new_lon_rad
        a = np.sin(dlat / 2) ** 2 + np.cos(new_lat_rad) * np.cos(core_lats) * np.sin(dlon / 2) ** 2
        distances = 2 * 6371.0 * np.arcsin(np.sqrt(a))
        
        min_dist = float(distances.min())
        nearest_idx = int(distances.argmin())
        nearest_cluster = int(core_labels[nearest_idx])

        if min_dist <= eps_km:
            most_common = "Unknown"
            if isinstance(summary_df, pd.DataFrame):
                match = summary_df[summary_df["cluster"] == nearest_cluster]
                if not match.empty:
                    most_common = str(match.iloc[0]["most_common_event"])
            return {
                "status": "Assigned",
                "region": nearest_cluster,
                "distance_km": round(min_dist, 1),
                "most_common_event": most_common,
            }

        return {
            "status": "New/Noise",
            "closest_region": nearest_cluster,
            "distance_km": round(min_dist, 1),
        }
    except Exception as exc:
        return {"status": f"PredictionError: {str(exc)}"}


def _render_page(request: Request, prediction: dict | None = None, message: str | None = None, show_clusters: bool = True, show_regions: bool = False, charts: dict | None = None):
    points = _load_cluster_points() if show_clusters else []
    regions = _compute_cluster_regions() if show_regions else []
    return templates.TemplateResponse(
        "home4.html",
        {
            "request": request,
            "points_json": json.dumps(points),
            "regions_json": json.dumps(regions),
            "prediction": prediction,
            "message": message,
            "show_clusters": show_clusters,
            "show_regions": show_regions,
            "charts": charts,
        },
    )


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

    points = _load_cluster_points()
    prediction = None

    if lat is not None and lon is not None:
        prediction = _predict_region(lat, lon)
        prediction["lat"] = lat
        prediction["lon"] = lon

    return _render_page(request, prediction=prediction, show_clusters=len(points) > 0)


@router.post("/train")
def train(request: Request):
    if not request.session.get("is_verified"):
        return RedirectResponse(url="/app2/login", status_code=status.HTTP_303_SEE_OTHER)

    try:
        print(f"[TRAIN] Loading data from: {source_data_path}")
        load_prepare_data(source_data_path, prepared_data_path)
        print(f"[TRAIN] Data prepared at: {prepared_data_path}")
        
        print(f"[TRAIN] Training model...")
        train_and_save_model(prepared_data_path, model_path, data_path)
        print(f"[TRAIN] Model saved at: {model_path}")
        print(f"[TRAIN] Clusters saved at: {data_path}")
        
        message = "✓ Model trained & saved successfully. Click 'Show Clusters' to visualize."
    except Exception as exc:
        print(f"[TRAIN ERROR] {exc}")
        message = f"✗ Training failed: {exc}"

    return _render_page(request, message=message, show_clusters=False)


@router.post("/show-clusters")
def show_clusters(request: Request):
    if not request.session.get("is_verified"):
        return RedirectResponse(url="/app2/login", status_code=status.HTTP_303_SEE_OTHER)

    points = _load_cluster_points()
    if len(points) == 0:
        message = "⚠ No clusters found. Please train the model first."
        return _render_page(request, message=message, show_clusters=False)
    
    message = f"✓ Showing {len(set(p['cluster'] for p in points))} cluster regions on map."
    return _render_page(request, message=message, show_clusters=True)


@router.post("/show-regions")
def show_regions(request: Request):
    if not request.session.get("is_verified"):
        return RedirectResponse(url="/app2/login", status_code=status.HTTP_303_SEE_OTHER)

    regions = _compute_cluster_regions()
    if len(regions) == 0:
        message = "⚠ No regions found. Please train the model first."
        return _render_page(request, message=message, show_regions=False)
    
    message = f"✓ Showing {len(regions)} colored cluster regions overlay."
    return _render_page(request, message=message, show_regions=True, show_clusters=False)


@router.post("/charts")
def charts(request: Request):
    if not request.session.get("is_verified"):
        return RedirectResponse(url="/app2/login", status_code=status.HTTP_303_SEE_OTHER)

    try:
        # Get chart data
        chart_data = {
            "event_dist": get_event_distribution_data(),
            "wildfire": get_wildfire_magnitude_data(),
            "volcano": get_volcano_events_data(),
            "cluster_summary": get_cluster_summary_data(),
            "events_by_type": get_events_by_type_data(),
            "events_per_year": get_events_per_year_data(),
            "magnitude_dist": get_magnitude_distribution_data(),
        }
        
        # Generate and serve geo plot URLs
        geo_clusters_path = get_geo_clusters_html()
        geo_clusters_clean_path = get_geo_clusters_clean_html()
        
        chart_data["geo_clusters_url"] = "/app4/plot/geo_clusters_all" if geo_clusters_path else None
        chart_data["geo_clusters_clean_url"] = "/app4/plot/geo_clusters_clean" if geo_clusters_clean_path else None
        
        message = "✓ Exploratory Data Analysis - All Charts"
        return _render_page(request, message=message, charts=chart_data)
    except Exception as exc:
        print(f"[CHARTS ERROR] {exc}")
        message = f"✗ Charts failed: {exc}"
        return _render_page(request, message=message)


@router.get("/plot/{plot_name}")
def get_plot(plot_name: str):
    """Serve plot HTML files."""
    base_dir = Path(__file__).resolve().parent
    plot_dir = base_dir / "plots"
    
    # Security: only allow alphanumeric and underscore
    if not all(c.isalnum() or c == '_' for c in plot_name):
        return {"error": "Invalid plot name"}
    
    file_path = plot_dir / f"{plot_name}.html"
    
    if not file_path.exists():
        return {"error": "Plot not found"}
    
    return FileResponse(file_path, media_type="text/html")


@router.get("/satellite-data")
def get_satellite_data():
    """Serve NASA Event data as JSON."""
    base_dir = Path(__file__).resolve().parent
    project_root = base_dir.parents[1]  # Go up: app4 -> Main -> Geo Artemis
    nasa_data_path = project_root / "Data_Source" / "Nasa_Event_data.csv"
    
    if not nasa_data_path.exists():
        return {"error": "NASA Event data not found", "data": []}
    
    try:
        df = pd.read_csv(nasa_data_path)
        # Convert to list of dicts and return only first 100 rows
        data = df.head(100).to_dict(orient="records")
        columns = df.columns.tolist()
        return {"columns": columns, "data": data, "total_rows": len(df)}
    except Exception as e:
        return {"error": str(e), "data": []}


@router.get("/event-types")
def get_event_types():
    """Serve event count data from event_counts.csv as JSON."""
    base_dir = Path(__file__).resolve().parent
    event_counts_path = base_dir / "Data" / "event_counts.csv"
    
    if not event_counts_path.exists():
        return {"error": "Event counts file not found", "data": []}
    
    try:
        df = pd.read_csv(event_counts_path)
        # Remove any unnamed columns
        df = df.loc[:, ~df.columns.str.contains('^Unnamed')]
        data = df.to_dict(orient="records")
        columns = df.columns.tolist()
        return {"columns": columns, "data": data}
    except Exception as e:
        return {"error": str(e), "data": []}


@router.get("/clustered-data-head")
def get_clustered_data_head():
    """Serve first rows of clustered data as JSON."""
    base_dir = Path(__file__).resolve().parent
    clustered_data_path = base_dir / "Data" / "final_hazard_dataset_with_clusters.csv"
    
    if not clustered_data_path.exists():
        return {"error": "Clustered data file not found", "data": []}
    
    try:
        df = pd.read_csv(clustered_data_path)
        # Remove any unnamed columns
        df = df.loc[:, ~df.columns.str.contains('^Unnamed')]
        # Return first 10 rows
        data = df.head(10).to_dict(orient="records")
        columns = df.columns.tolist()
        return {"columns": columns, "data": data}
    except Exception as e:
        return {"error": str(e), "data": []}
