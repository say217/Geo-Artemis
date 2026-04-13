"""Visualization functions for hazard data analysis."""
from pathlib import Path

import pandas as pd


def _get_df():
    """Load clustered dataset."""
    base_dir = Path(__file__).resolve().parent
    data_path = base_dir / "Data" / "final_hazard_dataset_with_clusters.csv"
    if not data_path.exists():
        return None
    return pd.read_csv(data_path)


def read_plot_html(file_path: str) -> str:
    """Read plot HTML file and return content."""
    if not file_path or not Path(file_path).exists():
        return None
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"Error reading plot file: {e}")
        return None


def get_plot_file_path(filename: str) -> str:
    """Get the path to a plot file."""
    plot_dir = Path(__file__).resolve().parent / "plots"
    return str(plot_dir / filename)


def get_event_distribution_data():
    """Event type distribution - returns chart data."""
    df = _get_df()
    if df is None or len(df) == 0:
        return None
    
    counts = df['Event_type'].value_counts()
    return {
        "labels": counts.index.tolist(),
        "data": counts.values.tolist(),
        "title": "Distribution of Event Types"
    }


def get_wildfire_magnitude_data():
    """Wildfire magnitude trend."""
    df = _get_df()
    if df is None or len(df) == 0:
        return None
    
    wildfire_data = df[df['Event_type'] == 'Wildfire']
    if len(wildfire_data) == 0:
        return None
    
    wildfire_magnitude_by_year = wildfire_data.groupby('year')['magnitude'].mean().reset_index()
    return {
        "labels": wildfire_magnitude_by_year['year'].astype(str).tolist(),
        "data": wildfire_magnitude_by_year['magnitude'].round(2).tolist(),
        "title": "Average Wildfire Magnitude Over Years"
    }


def get_volcano_events_data():
    """Volcano events per year."""
    df = _get_df()
    if df is None or len(df) == 0:
        return None
    
    volcano_data = df[df['Event_type'] == 'Volcano']
    if len(volcano_data) == 0:
        return None
    
    volcano_count_by_year = volcano_data.groupby('year').size().reset_index(name='count')
    return {
        "labels": volcano_count_by_year['year'].astype(str).tolist(),
        "data": volcano_count_by_year['count'].tolist(),
        "title": "Number of Volcano Events Per Year"
    }


def get_cluster_summary_data():
    """Cluster summary statistics."""
    df = _get_df()
    if df is None or len(df) == 0:
        return None
    
    cluster_summary = (
        df.groupby('cluster')
        .agg(
            num_events=('Event_type', 'count'),
            most_common_event=('Event_type', lambda x: x.mode()[0] if not x.empty else 'None'),
            avg_magnitude=('magnitude', 'mean'),
        )
        .round(2)
        .reset_index()
    )
    
    # Exclude noise points and get top clusters
    cluster_summary_clean = cluster_summary[cluster_summary['cluster'] != -1].sort_values('num_events', ascending=False).head(15)
    
    return {
        "labels": cluster_summary_clean['cluster'].astype(str).tolist(),
        "data": cluster_summary_clean['num_events'].tolist(),
        "title": "Top 15 Events per Region"
    }


def get_events_by_type_data():
    """Events by hazard type."""
    df = _get_df()
    if df is None or len(df) == 0:
        return None
    
    event_counts = df['Event_type'].value_counts()
    return {
        "labels": event_counts.index.tolist(),
        "data": event_counts.values.tolist(),
        "title": "Events by Hazard Type"
    }


def get_events_per_year_data():
    """Events per year."""
    df = _get_df()
    if df is None or len(df) == 0:
        return None
    
    events_per_year = df.groupby('year').size()
    return {
        "labels": events_per_year.index.astype(str).tolist(),
        "data": events_per_year.values.tolist(),
        "title": "Total Hazard Events per Year"
    }


def get_magnitude_distribution_data():
    """Magnitude distribution by cluster."""
    df = _get_df()
    if df is None or len(df) == 0:
        return None
    
    df_clean = df[df['cluster'] != -1]
    if len(df_clean) == 0:
        return None
    
    # Get top clusters and their magnitude stats
    top_clusters = df_clean['cluster'].value_counts().head(10).index.tolist()
    magnitudes_by_cluster = {}
    
    for cluster in top_clusters:
        cluster_data = df_clean[df_clean['cluster'] == cluster]['magnitude'].dropna()
        magnitudes_by_cluster[str(cluster)] = {
            "mean": float(cluster_data.mean()),
            "min": float(cluster_data.min()),
            "max": float(cluster_data.max()),
            "count": int(len(cluster_data))
        }
    
    return {
        "clusters": top_clusters,
        "data": magnitudes_by_cluster,
        "title": "Magnitude Distribution by Region"
    }


def get_geo_clusters_html():
    """Map 1: All events colored by cluster - saves HTML file and returns path."""
    df = _get_df()
    if df is None or len(df) == 0:
        return None
    
    import plotly.express as px
    
    eps_km = 200  # Same as training parameter
    
    fig = px.scatter_geo(
        df,
        lat='lat',
        lon='lon',
        color='cluster',
        hover_name='Event_type',
        hover_data=['magnitude', 'year', 'month', 'day'],
        title=f'Hazard Regions Discovered by DBSCAN (eps={eps_km} km)',
        labels={'cluster': 'Region ID'},
        color_continuous_scale='Plasma',
        projection='natural earth',
        size='magnitude',
        size_max=15
    )
    fig.update_traces(marker=dict(line=dict(width=0.5, color='DarkSlateGrey')))
    fig.update_layout(height=600, template='plotly_dark')
    
    # Save to plots folder
    plot_dir = Path(__file__).resolve().parent / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = plot_dir / "geo_clusters_all.html"
    fig.write_html(file_path)
    
    return str(file_path)


def get_geo_clusters_clean_html():
    """Map 2: Clean view (no noise points) - saves HTML file and returns path."""
    df = _get_df()
    if df is None or len(df) == 0:
        return None
    
    import plotly.express as px
    
    df_clean = df[df['cluster'] != -1]
    if len(df_clean) == 0:
        return None
    
    fig = px.scatter_geo(
        df_clean,
        lat='lat',
        lon='lon',
        color='cluster',
        hover_name='Event_type',
        hover_data=['magnitude', 'year'],
        title='Clustered Hazard Regions (Noise Removed)',
        projection='natural earth',
        color_continuous_scale='Viridis',
        size='magnitude',
        size_max=12
    )
    fig.update_layout(height=600, template='plotly_dark')
    fig.update_traces(marker=dict(line=dict(width=0.5, color='#334155')))
    
    # Save to plots folder
    plot_dir = Path(__file__).resolve().parent / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    
    file_path = plot_dir / "geo_clusters_clean.html"
    fig.write_html(file_path)
    
    return str(file_path)

