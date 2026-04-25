# Machine Learning Pipeline Updates - Summary

## Overview
Updated the ML pipeline in `Main/app4/` with enhanced data preprocessing, clustering, temporal analysis, and risk scoring.

---

## File Updates

### 1. **Prepaire.py** - Data Preprocessing Enhancement

#### New Features:
- **Robust Date Conversion**: Handles date parsing with UTC timezone awareness
- **Magnitude to Intensity Scaling**: Converts raw magnitude values to log-scaled intensity using `np.log1p()`
- **Improved Event Classification**: Case-insensitive classification function supporting:
  - Wildfire, Typhoon, Cyclone, Volcano
  - Iceberg variants (A, B, C, D)
  - Complex events, Other events
  
- **Temporal Feature Engineering**:
  - Year, Month, Day, Hour extraction
  - Day of week analysis
  - Weekend indicator (is_weekend)
  
- **Automatic Data Quality Checks**:
  - Missing value handling with median fill for magnitude
  - Validates required columns (lat, lon, date)
  - Provides warnings for missing columns

#### Output Files:
- `final_hazard_dataset.csv` - Cleaned data with engineered features
- `event_counts.csv` - Event type distribution statistics

---

### 2. **Model_train.py** - Advanced Clustering with Risk Analysis

#### New Features:

##### A. Event-Type Specific HDBSCAN:
- Different clustering parameters per event type:
  - **Cyclone/Typhoon**: eps_km = 300 km
  - **Wildfire**: eps_km = 100 km
  - **Iceberg**: eps_km = 200 km
  - **Volcano**: eps_km = 150 km
  - **Others**: eps_km = 150 km
- Dynamic `min_samples` based on subset size (1% of data)

##### B. Temporal Analysis:
- Year-over-year event count tracking
- Growth trend calculations per cluster
- Recent activity analysis (last 2 years)

##### C. Advanced Risk Scoring:
- **Risk Score** = num_events × avg_intensity
- **Risk Score Normalization** - scales between 0-1
- **Risk Levels** - Low, Medium, High classification
- **Time-Aware Risk Score** = risk_score × (1 + growth_factor)

##### D. High-Risk Region Detection:
- Identifies top 25% highest time-risk regions
- Tracks recent event activity vs. historical baseline
- Growth factor calculation for trend analysis

#### Output Files:
- `final_hazard_dataset_with_clusters.csv` - Data with cluster assignments
- `cluster_summary.csv` - Detailed cluster statistics with risk scores
- `High_risk_regions.csv` - High-risk regions with time-aware risk metrics
- `hdbscan_model.joblib` - Serialized model payload

#### Cluster Summary Fields:
```
- Event_type, cluster, num_events, avg_intensity
- avg_lat, avg_lon (cluster center)
- start_year, end_year, active_years
- events_per_year (stability metric)
- risk_score, risk_score_norm
- risk_level (Low/Medium/High)
```

#### High-Risk Fields:
```
- All cluster_summary fields +
- recent_events (last 2 years)
- growth_factor (recent vs. historical)
- time_risk_score (growth-adjusted risk)
```

---

### 3. **routes.py** - API Endpoints & Prediction

#### Updated Functions:

##### A. Enhanced `predict_region(lat, lon, df, eps_km=200)`:
- Returns structured prediction dict with:
  - `status`: "Assigned", "NewNoise", or "NoData"
  - `region`: cluster ID
  - `event_type`: predicted event type
  - `distance_km`: distance to nearest cluster center
  - `message`: human-readable result

##### B. New API Endpoints:

**GET `/app4/cluster-summary`**
- Returns all clusters with risk scores
- Fields: risk_score, risk_level, avg_intensity, events_per_year, etc.
- Useful for dashboards and monitoring

**GET `/app4/high-risk-regions`**
- Returns high-risk regions sorted by time_risk_score
- Fields: all cluster data + time_risk_score, growth_factor, recent_events
- Useful for alerts and decision support

#### Prediction Integration:
```python
result = predict_region(lat, lon, df)
# Returns: {
#   "status": "Assigned",
#   "region": 1234,
#   "event_type": "Cyclone",
#   "distance_km": 45.3,
#   "message": "→ Assigned to Region 1234 (Cyclone)\n Distance: 45.3 km"
# }
```

---

## Data Flow

```
NASA_Event_data.csv
    ↓
[Prepaire.py] - Data cleaning & feature engineering
    ↓
final_hazard_dataset.csv
    ↓
[Model_train.py] - Event-type clustering + risk scoring
    ↓
├─ final_hazard_dataset_with_clusters.csv
├─ cluster_summary.csv
├─ High_risk_regions.csv
└─ hdbscan_model.joblib
    ↓
[routes.py] - Prediction & API serving
    ↓
Web interface + JSON APIs
```

---

## Usage Examples

### Running Pipeline Manually:
```bash
python Main/app4/Prepaire.py
python Main/app4/Model_train.py
```

### Via Web Interface:
1. Click **"Train"** button - runs both preprocessing and clustering
2. Click **"Show Clusters"** - visualizes clusters on map
3. Use **"Predict"** form - predicts region for new coordinates

### Accessing Risk Data:
```bash
GET /app4/cluster-summary
GET /app4/high-risk-regions
```

---

## Key Improvements

✅ **Better Data Quality**: Robust date parsing, magnitude normalization  
✅ **Smarter Clustering**: Event-type-specific parameters for better regions  
✅ **Risk Awareness**: Multiple risk metrics (base, normalized, time-aware)  
✅ **Temporal Analysis**: Tracks event trends and growth patterns  
✅ **Prediction Ready**: New point classification with distance metrics  
✅ **API Ready**: New endpoints for risk data access  
✅ **Extensive Logging**: Detailed console output for monitoring  

---

## Data Stored in `Main/app4/Data/`

| File | Purpose |
|------|---------|
| `final_hazard_dataset.csv` | Preprocessed data (input to clustering) |
| `final_hazard_dataset_with_clusters.csv` | Data with cluster assignments |
| `cluster_summary.csv` | Cluster analysis + risk scores |
| `High_risk_regions.csv` | High-risk regions with time metrics |
| `event_counts.csv` | Event type distribution |

---

## Notes

- All paths are relative to the `app4` directory
- Supports historical data analysis and near real-time prediction
- Risk scores adjust based on recent trends
- Event types can be customized in `classify_event()` function
- HDBSCAN parameters can be tuned per event type in `train_and_save_model()`

---

**Last Updated**: April 19, 2026
