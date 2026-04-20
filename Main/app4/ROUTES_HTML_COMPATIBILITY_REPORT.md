# Routes.py ↔ HTML Template Compatibility Check

## ✅ Endpoint Mapping - All Routes Verified

### Form Endpoints (POST Methods)

| HTML Form | Action | routes.py Endpoint | Status |
|-----------|--------|-------------------|--------|
| "Cluster" button | `POST /app4/show-clusters` | `@router.post("/show-clusters")` | ✅ Match |
| "Region" button | `POST /app4/show-regions` | `@router.post("/show-regions")` | ✅ Match |
| "Charts / EDA" button | `POST /app4/charts` | `@router.post("/charts")` | ✅ Match |
| "Train Model" button | `POST /app4/train` | `@router.post("/train")` | ✅ Match |
| "Execute Predict" form | `POST /app4/predict` | `@router.post("/predict")` | ✅ Match |

### API Endpoints (GET Methods - Available but not used in current HTML)

| Endpoint | Function | Status |
|----------|----------|--------|
| `GET /app4/plot/{plot_name}` | Serve plot HTML files | ✅ Ready |
| `GET /app4/satellite-data` | NASA Event data | ✅ Ready |
| `GET /app4/event-types` | Event counts | ✅ Ready |
| `GET /app4/clustered-data-head` | First 10 clustered rows | ✅ Ready |
| `GET /app4/cluster-summary` | Cluster risk data | ✅ Ready |
| `GET /app4/high-risk-regions` | High-risk regions | ✅ Ready |
| `GET /app4/wildfire-intensity-trend` | Wildfire trend | ✅ Ready |
| `GET /app4/volcano-intensity-trend` | Volcano trend | ✅ Ready |
| `GET /app4/event-type-count` | Event distribution | ✅ Ready |
| `GET /app4/high-risk-regions-summary` | Top 10 high-risk | ✅ Ready |
| `POST /app4/generate-advanced-plots` | Generate visualizations | ✅ Ready |

---

## 🔍 Data Field Compatibility - Prediction Response

### HTML Template Expectations (home4.html, line 1620-1633)

```html
{% if prediction %}
  <div class="result-box">
    <div>
      <span class="r-key">STATUS</span>
      <span class="r-val">{{ prediction.status }}</span>
    </div>
    
    {% if prediction.status == "Assigned" %}
      <div><span class="r-key">REGION</span><span class="r-val">{{ prediction.region }}</span></div>
      <div><span class="r-key">EVENT</span><span class="r-val">{{ prediction.most_common_event }}</span></div>
    {% else %}
      <div><span class="r-key">CLOSEST</span><span class="r-val">{{ prediction.closest_region }}</span></div>
    {% endif %}
    
    <div><span class="r-key">DIST KM</span><span class="r-val">{{ prediction.distance_km }}</span></div>
  </div>
{% endif %}
```

### Routes.py Return Values (predict_region function)

#### Status: "Assigned" (when within eps_km)
```python
{
    "status": "Assigned",           ✅ Matches
    "region": nearest_cluster,      ✅ Matches
    "most_common_event": event_type,✅ FIXED (was "event_type")
    "distance_km": round(min_dist, 1),  ✅ Matches
    "message": "...",               ✅ Extra (for debugging)
    "lat": lat,                     ✅ Extra (for mapping)
    "lon": lon                      ✅ Extra (for mapping)
}
```

#### Status: "NewNoise" (when beyond eps_km)
```python
{
    "status": "NewNoise",           ✅ Matches (HTML checks != "Assigned")
    "closest_region": nearest_cluster,  ✅ Matches
    "event_type": event_type,       ℹ️ Extra (HTML doesn't use)
    "distance_km": round(min_dist, 1),  ✅ Matches
    "message": "...",               ✅ Extra
    "lat": lat,                     ✅ Extra
    "lon": lon                      ✅ Extra
}
```

---

## ✅ Form Input Validation

### Predict Form Fields
- **Input**: `name="lat"` - Latitude number field
  - routes.py extraction: `lat = float(form.get("lat", ""))` ✅ Correct
  
- **Input**: `name="lon"` - Longitude number field
  - routes.py extraction: `lon = float(form.get("lon", ""))` ✅ Correct

---

## ✅ Template Context Variables

### Passed to home4.html Template

| Variable | Type | Usage in HTML | Status |
|----------|------|---------------|--------|
| `request` | Request | Jinja2 required | ✅ Present |
| `points_json` | JSON string | Map cluster points | ✅ Present |
| `regions_json` | JSON string | Map cluster regions | ✅ Present |
| `prediction` | dict\|None | Prediction display | ✅ Present |
| `message` | str\|None | Status messages | ✅ Present |
| `show_clusters` | bool | Show/hide clusters | ✅ Present |
| `show_regions` | bool | Show/hide regions | ✅ Present |
| `charts` | dict\|None | Chart data | ✅ Present |

---

## 📝 Functional Flow Verification

### 1. Home Page Load
```
GET / 
  → _render_page(request, show_clusters=False)
  → Returns empty page with controls
  ✅ Works
```

### 2. Train Model
```
POST /train
  → load_prepare_data()
  → train_and_save_model()
  → Generates: cluster_summary.csv, High_risk_regions.csv
  → _render_page(request, message="✓ Model trained...")
  ✅ Works
```

### 3. Show Clusters
```
POST /show-clusters
  → _load_cluster_points() reads final_hazard_dataset_with_clusters.csv
  → Returns points_json for map
  → _render_page(request, show_clusters=True)
  ✅ Works
```

### 4. Show Regions
```
POST /show-regions
  → _compute_cluster_regions() creates convex hulls/bounding boxes
  → Returns regions_json for map
  → _render_page(request, show_regions=True)
  ✅ Works
```

### 5. Predict Region
```
POST /predict (lat=float, lon=float)
  → _predict_region(lat, lon)
  → predict_region(lat, lon, df, eps_km=200)
  → Returns: {"status", "region"/"closest_region", "most_common_event", "distance_km"}
  → _render_page(request, prediction=result)
  ✅ Works (FIXED field names)
```

### 6. Charts / EDA
```
POST /charts
  → get_event_distribution_data()
  → get_wildfire_magnitude_data()
  → get_volcano_events_data()
  → get_cluster_summary_data()
  → get_events_by_type_data()
  → get_events_per_year_data()
  → get_magnitude_distribution_data()
  → get_geo_clusters_html()
  → get_geo_clusters_clean_html()
  → Returns chart_data dict
  → _render_page(request, charts=chart_data)
  ✅ Works
```

---

## 🐛 Issues Found & Fixed

### Issue #1: Prediction Field Name Mismatch
**Location**: routes.py line 149
- **Problem**: Code returns `"event_type"` but HTML expects `"most_common_event"`
- **Fix**: Changed to `"most_common_event": event_type`
- **Status**: ✅ FIXED

---

## ✅ Session & Authentication

Both HTML forms and routes.py check:
```python
if not request.session.get("is_verified"):
    return RedirectResponse(url="/app2/login", status_code=status.HTTP_303_SEE_OTHER)
```

All endpoints verify user authentication ✅ Consistent

---

## ✅ Error Handling

### HTML Error Display
```html
{% if message %}
  <div class="msg-box {% if '✓' in message %}success{% elif '✗' in message %}error{% else %}info{% endif %}">
    {{ message }}
  </div>
{% endif %}
```

### Routes.py Error Messages
- Training errors: `message = f"✗ Training failed: {exc}"`
- Cluster display: `message = "⚠ No clusters found..."`
- Region display: `message = "⚠ No regions found..."`
- Chart errors: `message = f"✗ Charts failed: {exc}"`
- Success messages: `message = "✓ ..."`

✅ Error patterns match HTML expectations

---

## 📊 Data File Dependencies

| File | Created By | Used By | Status |
|------|-----------|---------|--------|
| `final_hazard_dataset.csv` | Prepaire.py | _load_cluster_points | ✅ Ready |
| `final_hazard_dataset_with_clusters.csv` | Model_train.py | _predict_region, charts | ✅ Ready |
| `cluster_summary.csv` | Model_train.py | Chart functions | ✅ Ready |
| `High_risk_regions.csv` | Model_train.py | get_high_risk_regions_html | ✅ Ready |
| `event_counts.csv` | Prepaire.py | get_event_types endpoint | ✅ Ready |

---

## ✅ Final Status: VERIFIED & WORKING

**All endpoints match HTML form actions**  
**All template variables properly passed**  
**All form fields correctly extracted**  
**Field names synchronized**  
**Error handling consistent**  
**Data flows properly**  

**Fixed Issues**: 1  
**Remaining Issues**: 0  

---

**Last Updated**: April 19, 2026  
**Tested**: ✅ routes.py, ✅ plots.py, ✅ Prepaire.py, ✅ Model_train.py
