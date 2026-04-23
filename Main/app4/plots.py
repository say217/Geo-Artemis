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
    """Wildfire intensity trend."""
    df = _get_df()
    if df is None or len(df) == 0:
        return None
    
    wildfire_data = df[df['Event_type'] == 'Wildfire']
    if len(wildfire_data) == 0:
        return None
    
    wildfire_intensity_by_year = wildfire_data.groupby('year')['intensity'].mean().reset_index()
    return {
        "labels": wildfire_intensity_by_year['year'].astype(str).tolist(),
        "data": wildfire_intensity_by_year['intensity'].round(2).tolist(),
        "title": "Average Wildfire Intensity Over Years"
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
            avg_intensity=('intensity', 'mean'),
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
    """Intensity distribution by cluster."""
    df = _get_df()
    if df is None or len(df) == 0:
        return None
    
    df_clean = df[df['cluster'] != -1]
    if len(df_clean) == 0:
        return None
    
    # Get top clusters and their intensity stats
    top_clusters = df_clean['cluster'].value_counts().head(10).index.tolist()
    intensities_by_cluster = {}
    
    for cluster in top_clusters:
        cluster_data = df_clean[df_clean['cluster'] == cluster]['intensity'].dropna()
        intensities_by_cluster[str(cluster)] = {
            "mean": float(cluster_data.mean()),
            "min": float(cluster_data.min()),
            "max": float(cluster_data.max()),
            "count": int(len(cluster_data))
        }
    
    return {
        "clusters": top_clusters,
        "data": intensities_by_cluster,
        "title": "Intensity Distribution by Region"
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
        hover_data=['intensity', 'year', 'month', 'day'],
        title=f'Hazard Regions Discovered by DBSCAN (eps={eps_km} km)',
        labels={'cluster': 'Region ID'},
        color_continuous_scale='Plasma',
        projection='natural earth',
        size='intensity',
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
        hover_data=['intensity', 'year'],
        title='Clustered Hazard Regions (Noise Removed)',
        projection='natural earth',
        color_continuous_scale='Viridis',
        size='intensity',
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


def get_high_risk_regions_html():
    """Map 3: High-risk regions centroid view - saves HTML file and returns path."""
    df = _get_df()
    if df is None or len(df) == 0:
        return None
    
    import plotly.express as px
    
    # Load high-risk regions data
    base_dir = Path(__file__).resolve().parent
    high_risk_path = base_dir / "Data" / "High_risk_regions.csv"
    
    if not high_risk_path.exists():
        return None
    
    try:
        high_risk = pd.read_csv(high_risk_path)
        high_risk = high_risk.loc[:, ~high_risk.columns.str.contains('^Unnamed')]
        
        if len(high_risk) == 0:
            return None
        
        risk_col = 'risk_score' if 'risk_score' in high_risk.columns else ('time_risk_score' if 'time_risk_score' in high_risk.columns else None)
        
        if not risk_col:
            return None
            
        centroids = high_risk[['cluster', 'avg_lat', 'avg_lon', risk_col, 'Event_type']].copy()
        
        fig = px.scatter_geo(
            centroids,
            lat='avg_lat',
            lon='avg_lon',
            color='Event_type',
            size=risk_col,
            hover_data=['cluster', risk_col, 'Event_type'],
            title='🔥 High-Risk Regions Analysis',
            projection='natural earth',
            color_discrete_sequence=px.colors.qualitative.Set1
        )
        
        fig.update_layout(height=600, template='plotly_dark')
        fig.update_traces(marker=dict(line=dict(width=1, color='white'), opacity=0.8))
        
        # Save to plots folder
        plot_dir = Path(__file__).resolve().parent / "plots"
        plot_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = plot_dir / "high_risk_regions.html"
        fig.write_html(file_path)
        
        return str(file_path)
    except Exception as e:
        print(f"Error generating high-risk regions plot: {e}")
        return None


def get_comprehensive_analysis_html():
    """Comprehensive 4-panel matplotlib analysis - saves HTML file and returns path."""
    df = _get_df()
    if df is None or len(df) == 0:
        return None
    
    import matplotlib.pyplot as plt
    import seaborn as sns
    
    try:
        plt.figure(figsize=(16, 12))
        
        # ========================
        # Graph 1: Top regions by event count
        # ========================
        plt.subplot(2, 2, 1)
        
        cluster_summary = (
            df[df['cluster'] != -1]
            .groupby(['cluster', 'Event_type'])
            .size()
            .reset_index(name='num_events')
        )
        
        top_clusters = cluster_summary.groupby('cluster')['num_events'].sum().nlargest(10)
        
        top_data = cluster_summary[cluster_summary['cluster'].isin(top_clusters.index)]
        
        sns.barplot(
            data=top_data,
            x='cluster',
            y='num_events',
            hue='Event_type',
            palette='husl'
        )
        
        plt.title('Top 10 Hazard Regions by Event Count', fontsize=12, fontweight='bold')
        plt.xlabel('Cluster ID')
        plt.ylabel('Event Count')
        plt.xticks(rotation=45)
        plt.legend(title='Event Type', bbox_to_anchor=(1.05, 1), loc='upper left', fontsize=8)
        
        # ========================
        # Graph 2: Intensity distribution by region
        # ========================
        plt.subplot(2, 2, 2)
        
        subset = df[df['cluster'] != -1].copy()
        top_ids = top_clusters.index.tolist()
        subset = subset[subset['cluster'].isin(top_ids)]
        
        sns.boxplot(
            data=subset,
            x='cluster',
            y='intensity',
            palette='Set2'
        )
        
        plt.title('Intensity Distribution (Top Regions)', fontsize=12, fontweight='bold')
        plt.xlabel('Cluster ID')
        plt.ylabel('Intensity (log-scaled)')
        plt.xticks(rotation=45)
        
        # ========================
        # Graph 3: Events by type
        # ========================
        plt.subplot(2, 2, 3)
        
        event_counts = df['Event_type'].value_counts()
        
        sns.barplot(
            x=event_counts.index,
            y=event_counts.values,
            palette='viridis'
        )
        
        plt.title('Events by Hazard Type', fontsize=12, fontweight='bold')
        plt.ylabel('Count')
        plt.xlabel('Event Type')
        plt.xticks(rotation=45)
        
        # ========================
        # Graph 4: Events per year
        # ========================
        plt.subplot(2, 2, 4)
        
        yearly = df.groupby('year').size().reset_index(name='count')
        
        sns.lineplot(data=yearly, x='year', y='count', marker='o', linewidth=2, markersize=8, color='#FF6B6B')
        
        plt.title('Total Hazard Events per Year', fontsize=12, fontweight='bold')
        plt.xlabel('Year')
        plt.ylabel('Number of Events')
        plt.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        # Save to plots folder
        plot_dir = Path(__file__).resolve().parent / "plots"
        plot_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = plot_dir / "comprehensive_analysis.png"
        plt.savefig(file_path, dpi=100, bbox_inches='tight')
        plt.close()
        
        return str(file_path)
    except Exception as e:
        print(f"Error generating comprehensive analysis plot: {e}")
        return None


def get_clustered_events_html():
    """Map: Hazard regions discovered by DBSCAN - saves HTML file and returns path."""
    df = _get_df()
    if df is None or len(df) == 0:
        return None
    
    import plotly.express as px
    
    try:
        # Remove noise for clarity
        map_df = df[df['cluster'] != -1].copy()
        
        if len(map_df) == 0:
            return None
        
        fig = px.scatter_geo(
            map_df,
            lat='lat',
            lon='lon',
            color=map_df['cluster'].astype(str),
            hover_name='Event_type',
            hover_data={
                'intensity': True,
                'year': True,
                'month': True,
                'day': True,
                'cluster': True
            },
            title='Hazard Regions Discovered by DBSCAN',
            labels={'color': 'Region ID'},
            projection='natural earth',
            size='intensity',
            size_max=12,
            color_discrete_sequence=px.colors.qualitative.Light24
        )
        
        fig.update_traces(marker=dict(opacity=0.7, line=dict(width=0.5, color='white')))
        fig.update_layout(height=600, template='plotly_dark')
        
        # Save to plots folder
        plot_dir = Path(__file__).resolve().parent / "plots"
        plot_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = plot_dir / "clustered_events.html"
        fig.write_html(file_path)
        
        return str(file_path)
    except Exception as e:
        print(f"Error generating clustered events plot: {e}")
        return None


def get_all_events_by_type_html():
    """Map: All hazard events by type baseline view - saves HTML file and returns path."""
    df = _get_df()
    if df is None or len(df) == 0:
        return None
    
    import plotly.express as px
    
    try:
        fig = px.scatter_geo(
            df,
            lat='lat',
            lon='lon',
            color='Event_type',
            hover_name='Event_type',
            hover_data={
                'intensity': True,
                'year': True,
                'cluster': True
            },
            title='All Hazard Events by Type (Baseline View)',
            projection='natural earth',
            size='intensity',
            size_max=5,
            color_discrete_sequence=px.colors.qualitative.Set1
        )
        
        fig.update_traces(marker=dict(opacity=0.6, line=dict(width=0.5, color='rgba(0,0,0,0.2)')))
        fig.update_layout(height=600, template='plotly_dark')
        
        # Save to plots folder
        plot_dir = Path(__file__).resolve().parent / "plots"
        plot_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = plot_dir / "all_events_by_type.html"
        fig.write_html(file_path)
        
        return str(file_path)
    except Exception as e:
        print(f"Error generating all events plot: {e}")
        return None


def get_wildfire_intensity_trend_data():
    """Wildfire intensity trend using log-scaled intensity."""
    df = _get_df()
    if df is None or len(df) == 0:
        return None
    
    wildfire_data = df[df['Event_type'] == 'Wildfire']
    if len(wildfire_data) == 0:
        return None
    
    wildfire_intensity_by_year = (
        wildfire_data
        .groupby('year')['intensity']
        .mean()
        .reset_index()
        .sort_values('year')
    )
    return {
        "labels": wildfire_intensity_by_year['year'].astype(str).tolist(),
        "data": wildfire_intensity_by_year['intensity'].round(3).tolist(),
        "title": "Average Wildfire Intensity Over Years"
    }


def get_volcano_intensity_trend_data():
    """Volcano intensity trend using log-scaled intensity."""
    df = _get_df()
    if df is None or len(df) == 0:
        return None
    
    volcano_data = df[df['Event_type'] == 'Volcano']
    if len(volcano_data) == 0:
        return None
    
    volcano_intensity_by_year = (
        volcano_data
        .groupby('year')['intensity']
        .mean()
        .reset_index()
        .sort_values('year')
    )
    return {
        "labels": volcano_intensity_by_year['year'].astype(str).tolist(),
        "data": volcano_intensity_by_year['intensity'].round(3).tolist(),
        "title": "Average Volcano Intensity Over Years"
    }


def get_event_type_count_data():
    """Simple event type distribution."""
    df = _get_df()
    if df is None or len(df) == 0:
        return None
    
    event_counts = df['Event_type'].value_counts()
    return {
        "labels": event_counts.index.tolist(),
        "data": event_counts.values.tolist(),
        "title": "Distribution of Event Types"
    }


def get_high_risk_regions_data():
    """High-risk regions summary data."""
    base_dir = Path(__file__).resolve().parent
    high_risk_path = base_dir / "Data" / "High_risk_regions.csv"
    
    if not high_risk_path.exists():
        return None
    
    try:
        high_risk = pd.read_csv(high_risk_path)
        high_risk = high_risk.loc[:, ~high_risk.columns.str.contains('^Unnamed')]
        
        if len(high_risk) == 0:
            return None
        
        # Sort by risk score and get top 10
        risk_col = 'risk_score' if 'risk_score' in high_risk.columns else ('time_risk_score' if 'time_risk_score' in high_risk.columns else None)
        if not risk_col:
            return None
            
        top_regions = high_risk.nlargest(10, risk_col)
        
        return {
            "labels": top_regions['cluster'].astype(str).tolist(),
            "data": top_regions[risk_col].round(2).tolist(),
            "event_types": top_regions['Event_type'].tolist(),
            "title": f"Top 10 High-Risk Regions ({risk_col.replace('_', ' ').title()})"
        }
    except Exception as e:
        print(f"Error loading high-risk regions data: {e}")
        return None

