# plots.py Enhancement Summary

## New Plotting Functions Added

### 1. **High-Risk Regions Visualization**
**Function**: `get_high_risk_regions_html()`
- **Type**: Interactive Plotly Scatter Geo
- **Output**: `high_risk_regions.html`
- **Features**:
  - Displays high-risk region centroids as dots
  - Color-coded by Event Type
  - Bubble size represents time-aware risk score
  - Hover shows cluster ID, risk score, event type
  - Dark theme with white outlined markers
- **Data Source**: High_risk_regions.csv

---

### 2. **Comprehensive Analysis Dashboard**
**Function**: `get_comprehensive_analysis_html()`
- **Type**: 4-Panel Matplotlib Figure (PNG)
- **Output**: `comprehensive_analysis.png`
- **Panels**:
  1. **Top Regions by Event Count** (Bar chart with hue by event type)
  2. **Intensity Distribution** (Box plot for top 10 regions)
  3. **Events by Hazard Type** (Bar chart with viridis palette)
  4. **Events per Year** (Line plot with markers)
- **Features**: High-resolution (100 dpi), tight layout, legend

---

### 3. **Clustered Events Map**
**Function**: `get_clustered_events_html()`
- **Type**: Interactive Plotly Scatter Geo
- **Output**: `clustered_events.html`
- **Features**:
  - Shows only clustered events (noise removed)
  - Color by cluster ID
  - Size by intensity
  - Hover data: intensity, year, month, day, cluster
  - Semi-transparent markers (opacity=0.7)
  - Title: "Hazard Regions Discovered by DBSCAN"

---

### 4. **All Events by Type Baseline**
**Function**: `get_all_events_by_type_html()`
- **Type**: Interactive Plotly Scatter Geo
- **Output**: `all_events_by_type.html`
- **Features**:
  - Shows ALL events (including noise/unclustered)
  - Color by Event Type
  - Size by intensity (smaller scale)
  - Hover shows intensity, year, cluster assignment
  - Light transparent markers (opacity=0.6)
  - Baseline view for comparison

---

### 5. **Wildfire Intensity Trend**
**Function**: `get_wildfire_intensity_trend_data()`
- **Returns**: Chart data (labels, data, title)
- **Features**:
  - Average wildfire intensity (log-scaled) per year
  - Sorted chronologically
  - Precision: 3 decimal places
  - Useful for temporal trend analysis

---

### 6. **Volcano Intensity Trend**
**Function**: `get_volcano_intensity_trend_data()`
- **Returns**: Chart data (labels, data, title)
- **Features**:
  - Average volcano intensity (log-scaled) per year
  - Sorted chronologically
  - Precision: 3 decimal places
  - Shows long-term patterns

---

### 7. **Event Type Distribution**
**Function**: `get_event_type_count_data()`
- **Returns**: Chart data with event type counts
- **Features**:
  - Simple count distribution
  - Used in dashboards and summaries
  - Returns labels, data, title

---

### 8. **High-Risk Regions Summary**
**Function**: `get_high_risk_regions_data()`
- **Returns**: Chart data with top 10 high-risk regions
- **Features**:
  - Cluster IDs, time-risk scores, event types
  - Sorted by risk score (descending)
  - Includes event type labels for each region

---

## New API Endpoints (in routes.py)

### GET Endpoints
- `GET /app4/wildfire-intensity-trend` → Wildfire trend data (JSON)
- `GET /app4/volcano-intensity-trend` → Volcano trend data (JSON)
- `GET /app4/event-type-count` → Event type distribution (JSON)
- `GET /app4/high-risk-regions-summary` → Top 10 high-risk regions (JSON)

### POST Endpoints
- `POST /app4/generate-advanced-plots` → Generate all advanced visualizations

---

## Output Files Generated

All plots are saved to `Main/app4/plots/` directory:

| File | Type | Description |
|------|------|-------------|
| `high_risk_regions.html` | HTML | Interactive high-risk region centroids map |
| `comprehensive_analysis.png` | PNG | 4-panel analysis dashboard |
| `clustered_events.html` | HTML | Interactive DBSCAN clustered events map |
| `all_events_by_type.html` | HTML | Interactive baseline view (all events) |

---

## Data Quality Features

✅ **Error Handling**: Try-catch blocks for all external data loading  
✅ **Namespace Cleaning**: Removes unnamed index columns from CSVs  
✅ **Validation**: Checks for empty datasets before plotting  
✅ **Logging**: Console output for debugging  
✅ **Graceful Fallback**: Returns None for missing data  

---

## Integration with Training Pipeline

1. **Data Flow**:
   - `Model_train.py` → Generates `High_risk_regions.csv`
   - `plots.py` → Reads CSV and generates visualizations
   - `routes.py` → Serves visualizations via API

2. **Automatic Generation**:
   - Plots are generated on-demand
   - Cache-friendly (generated once, served many times)
   - No database queries needed

---

## Usage Examples

### Generate Advanced Plots
```bash
POST /app4/generate-advanced-plots
# Generates all 4 visualization files
```

### View High-Risk Regions
```bash
GET /app4/plot/high_risk_regions
# Opens high_risk_regions.html in browser
```

### Get Wildfire Trend Data
```bash
GET /app4/wildfire-intensity-trend
# Returns: {"labels": [...], "data": [...], "title": "..."}
```

### Explore Clustered Events
```bash
GET /app4/plot/clustered_events
# Opens interactive map of DBSCAN clusters
```

---

## Color Schemes Used

- **High-Risk Regions**: Set1 (qualitative, 9 colors)
- **Clustered Events**: Light24 (24 distinct colors)
- **All Events**: Set1 (qualitative, 9 colors)
- **Comprehensive Dashboard**: 
  - husl (bars), Set2 (boxplot), viridis (countplot), custom red (#FF6B6B) for line

---

## Performance Considerations

- **PNG Generation**: Uses matplotlib (fast, lightweight)
- **HTML Files**: Plotly generates (~500KB each)
- **Data Loading**: Minimal overhead (reads CSV only)
- **Caching**: Files persist after generation

---

**Last Updated**: April 19, 2026
**Status**: ✅ All functions tested and error-free
