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
    return df[["lat", "lon", "cluster", "Event_type", "intensity"]].to_dict("records")


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


def predict_region(lat: float, lon: float, df, eps_km: float = 200):
	"""
	Predict which region a new point belongs to.
	Enhanced version with better handling of clustered data.
	"""
	clustered_df = df[df['cluster'] != -1].copy()

	if clustered_df.empty:
		return {
			"status": "NoData",
			"message": "No clusters available."
		}

	# Compute centroids
	centroids = (
		clustered_df
		.groupby('cluster')[['lat', 'lon']]
		.mean()
		.reset_index()
	)

	new_point = np.radians([[lat, lon]])
	centroid_coords = np.radians(centroids[['lat', 'lon']].values)

	distances = haversine_distances(new_point, centroid_coords) * 6371.0088

	min_dist = float(distances.min())
	nearest_idx = int(distances.argmin())
	nearest_cluster = int(centroids.iloc[nearest_idx]['cluster'])

	# Get event type for nearest cluster
	subset = clustered_df[clustered_df['cluster'] == nearest_cluster]
	event_type = subset['Event_type'].mode()[0] if not subset.empty else "Unknown"

	if min_dist <= eps_km:
		return {
			"status": "Assigned",
			"region": nearest_cluster,
			"most_common_event": event_type,
			"distance_km": round(min_dist, 1),
			"message": f"→ Assigned to Region {nearest_cluster} ({event_type})\n   Distance: {min_dist:.1f} km"
		}
	else:
		return {
			"status": "NewNoise",
			"closest_region": nearest_cluster,
			"event_type": event_type,
			"distance_km": round(min_dist, 1),
			"message": f"→ NEW / Noise Event\n   Closest region: {nearest_cluster} ({min_dist:.1f} km away)"
		}


def _predict_region(lat: float, lon: float) -> dict:
	if not data_path.exists():
		return {"status": "NoData"}

	try:
		df = pd.read_csv(data_path)
		df = df.loc[:, ~df.columns.str.contains('^Unnamed')]
		result = predict_region(lat, lon, df)
		result["lat"] = lat
		result["lon"] = lon
		return result
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

    return _render_page(request, prediction=prediction, show_clusters=False)


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
        return _render_page(request, message=message, charts=chart_data, show_clusters=False)
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

@router.get("/cluster-summary")
def get_cluster_summary():
	"""Serve cluster summary with risk scores as JSON."""
	base_dir = Path(__file__).resolve().parent
	cluster_summary_path = base_dir / "Data" / "cluster_summary.csv"
	
	if not cluster_summary_path.exists():
		return {"error": "Cluster summary file not found", "data": []}
	
	try:
		df = pd.read_csv(cluster_summary_path)
		df = df.loc[:, ~df.columns.str.contains('^Unnamed')]
		data = df.to_dict(orient="records")
		columns = df.columns.tolist()
		return {"columns": columns, "data": data, "count": len(df)}
	except Exception as e:
		return {"error": str(e), "data": []}


@router.get("/high-risk-regions")
def get_high_risk_regions():
	"""Serve high-risk regions with time-aware risk scores as JSON."""
	base_dir = Path(__file__).resolve().parent
	high_risk_path = base_dir / "Data" / "High_risk_regions.csv"
	
	if not high_risk_path.exists():
		return {"error": "High-risk regions file not found", "data": []}
	
	try:
		df = pd.read_csv(high_risk_path)
		df = df.loc[:, ~df.columns.str.contains('^Unnamed')]
		# Sort by time_risk_score descending
		df = df.sort_values(by='time_risk_score', ascending=False)
		data = df.to_dict(orient="records")
		columns = df.columns.tolist()
		return {"columns": columns, "data": data, "count": len(df)}
	except Exception as e:
		return {"error": str(e), "data": []}


@router.get("/wildfire-intensity-trend")
def wildfire_intensity_trend():
	"""Serve wildfire intensity trend data."""
	data = get_wildfire_intensity_trend_data()
	return data if data else {"error": "No wildfire data available"}


@router.get("/volcano-intensity-trend")
def volcano_intensity_trend():
	"""Serve volcano intensity trend data."""
	data = get_volcano_intensity_trend_data()
	return data if data else {"error": "No volcano data available"}


@router.get("/event-type-count")
def event_type_count():
	"""Serve event type distribution."""
	data = get_event_type_count_data()
	return data if data else {"error": "No event data available"}


@router.get("/high-risk-regions-summary")
def high_risk_regions_summary():
	"""Serve high-risk regions summary data."""
	data = get_high_risk_regions_data()
	return data if data else {"error": "No high-risk data available"}


@router.get("/all-events-2026")
def all_events_2026():
	"""Serve all events from 2026 for map display."""
	try:
		# Load the raw hazard dataset (not clustered)
		if not prepared_data_path.exists():
			return {"error": "Data file not found", "data": []}
		
		df = pd.read_csv(prepared_data_path)
		
		# Clean column names
		df.columns = df.columns.str.replace('^Unnamed: ', '', regex=True)
		
		# Filter for 2026 only
		if 'year' in df.columns:
			df_2026 = df[df['year'] == 2026].copy()
		else:
			# If year column doesn't exist, try to extract from date columns
			df_2026 = df.copy()
		
		if df_2026.empty:
			return {"error": "No events found for 2026", "data": [], "count": 0}
		
		# Prepare response data with required fields
		events_list = []
		for _, row in df_2026.iterrows():
			event_dict = {
				'lat': float(row.get('lat', row.get('latitude', row.get('Latitude', 0)))),
				'lon': float(row.get('lon', row.get('longitude', row.get('Longitude', 0)))),
				'Event_type': str(row.get('Event_type', row.get('most_common_event', 'Other'))),
				'intensity': float(row.get('intensity', row.get('magnitude', 1))),
				'year': int(row.get('year', 2026)),
				'month': int(row.get('month', 1)) if 'month' in row else 1
			}
			events_list.append(event_dict)
		
		return {
			"data": events_list,
			"count": len(events_list),
			"year": 2026
		}
	
	except Exception as e:
		return {
			"error": str(e),
			"data": [],
			"count": 0
		}


@router.get("/earthquake-points")
def get_earthquake_points():
	"""Serve earthquake data for map display from CSV file - Limited to top 1000 points."""
	try:
		earthquake_data_path = Path(__file__).resolve().parent.parent.parent / "USGS_DATA" / "earthquakes.csv"
		
		if not earthquake_data_path.exists():
			return {"error": "Earthquake data file not found", "data": [], "count": 0}
		
		# Load earthquake data from CSV with limit
		df = pd.read_csv(earthquake_data_path)
		
		if df.empty:
			return {"error": "No earthquake data available", "data": [], "count": 0}
		
		# Limit to top 1000 records (sorted by magnitude descending for most significant events)
		df_limited = df.nlargest(1000, 'magnitude') if 'magnitude' in df.columns else df.head(1000)
		
		# Extract earthquake points
		earthquakes_list = []
		for _, row in df_limited.iterrows():
			try:
				earthquake_dict = {
					'lon': float(row.get('longitude', row.get('lon', 0))),
					'lat': float(row.get('latitude', row.get('lat', 0))),
					'depth_km': float(row.get('depth_km', 0)),
					'magnitude': float(row.get('magnitude', 0)),
					'place': str(row.get('place', 'Unknown')),
					'time': str(row.get('time', 'N/A')),
					'url': str(row.get('url', ''))
				}
				earthquakes_list.append(earthquake_dict)
			except (ValueError, TypeError, KeyError):
				continue
		
		return {
			"data": earthquakes_list,
			"count": len(earthquakes_list),
			"total_in_file": len(df),
			"limited_to": 1000
		}
	
	except Exception as e:
		return {
			"error": str(e),
			"data": [],
			"count": 0
		}