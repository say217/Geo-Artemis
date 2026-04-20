from pathlib import Path

import numpy as np
import pandas as pd
from joblib import dump, load
from sklearn.cluster import DBSCAN


def train_and_save_model(data_path: Path, model_path: Path, clustered_path: Path) -> dict:
	"""
	Enhanced DBSCAN clustering with event-type specific parameters,
	temporal analysis, and advanced risk scoring.
	"""
	# Create directories EARLY to ensure they exist for all saves
	model_path.parent.mkdir(parents=True, exist_ok=True)
	clustered_path.parent.mkdir(parents=True, exist_ok=True)
	
	df = pd.read_csv(data_path)
	
	# Remove any unnamed index columns that may exist
	df = df.loc[:, ~df.columns.str.contains('^Unnamed')]

	kms_per_radian = 6371.0088
	print("\n=== RUNNING DBSCAN PER EVENT TYPE ===\n")

	# Initialize cluster column
	df['cluster'] = -1

	# Loop through each event type with tuned parameters
	for event in df['Event_type'].unique():
		subset = df[df['Event_type'] == event].copy()

		if len(subset) < 5:
			print(f"{event}: skipped (not enough data)")
			continue

		coords = np.radians(subset[['lat', 'lon']].values)

		# ================== TUNING PARAMETERS ==================
		if event in ['Cyclone', 'Typhoon']:
			eps_km = 300
		elif event == 'Wildfire':
			eps_km = 100
		elif 'Iceberg' in event:
			eps_km = 200
		elif event == 'Volcano':
			eps_km = 150
		else:
			eps_km = 150

		eps = eps_km / kms_per_radian

		# Dynamic min_samples (better than fixed 5)
		min_samples = max(5, int(len(subset) * 0.01))
		# ======================================================

		print(f"{event}: eps = {eps_km} km | min_samples = {min_samples} | samples = {len(subset)}")

		model = DBSCAN(
			eps=eps,
			min_samples=min_samples,
			metric='haversine',
			algorithm='ball_tree'
		)

		labels = model.fit_predict(coords)

		# Offset cluster labels to avoid overlap between event types
		unique_offset = hash(event) % 10000
		labels = np.where(labels != -1, labels + unique_offset, -1)

		df.loc[subset.index, 'cluster'] = labels

	# ========================
	# STEP: Temporal Analysis per Cluster
	# ========================

	# Remove noise for temporal analysis
	clustered_df = df[df['cluster'] != -1].copy()

	# Events per cluster per year
	cluster_time = (
		clustered_df
		.groupby(['cluster', 'year'])
		.size()
		.reset_index(name='event_count')
	)

	# Growth trend (year-over-year change)
	cluster_time['growth'] = (
		cluster_time
		.groupby('cluster')['event_count']
		.diff()
		.fillna(0)
	)

	cluster_trend_summary = (
		cluster_time
		.groupby('cluster')
		.agg(
			avg_events=('event_count', 'mean'),
			max_events=('event_count', 'max'),
			avg_growth=('growth', 'mean'),
			recent_growth=('growth', 'last')
		)
		.reset_index()
	)

	print("\n=== TEMPORAL CLUSTER ANALYSIS ===")
	print(cluster_trend_summary.head(10))

	# ========================
	# Clustering Summary by Event Type
	# ========================
	print("\nClustering Summary by Event Type:\n")

	summary_rows = []

	for event in df['Event_type'].unique():
		subset = df[df['Event_type'] == event]
		clusters = subset['cluster']

		n_clusters = len(set(clusters)) - (1 if -1 in clusters.values else 0)
		noise_count = (clusters == -1).sum()
		total = len(subset)
		noise_ratio = noise_count / total if total > 0 else 0

		# Quality interpretation
		if noise_ratio < 0.1:
			structure = "Highly Structured"
		elif noise_ratio < 0.3:
			structure = "Moderately Structured"
		else:
			structure = "Weak / Scattered"

		summary_rows.append({
			'Event_type': event,
			'num_events': total,
			'num_clusters': n_clusters,
			'noise_%': round(noise_ratio * 100, 2),
			'structure': structure
		})

		print(f"{event}:")
		print(f"   → Clusters: {n_clusters}")
		print(f"   → Noise: {noise_count} ({noise_ratio*100:.1f}%)")
		print(f"   → Pattern: {structure}\n")

	event_summary = pd.DataFrame(summary_rows)

	print("\n=== Structured Summary Table ===")
	print(event_summary)

	# ========================
	# STEP 4: ADVANCED CLUSTER ANALYSIS
	# ========================

	cluster_summary = (
		df[df['cluster'] != -1]
		.groupby(['Event_type', 'cluster'])
		.agg(
			num_events=('Event_type', 'count'),
			avg_intensity=('intensity', 'mean'),
			avg_lat=('lat', 'mean'),
			avg_lon=('lon', 'mean'),
			start_year=('year', 'min'),
			end_year=('year', 'max')
		)
		.reset_index()
	)

	# ========================
	# ADD TEMPORAL FEATURES
	# ========================
	cluster_summary['active_years'] = cluster_summary['end_year'] - cluster_summary['start_year'] + 1

	# events per year (stability)
	cluster_summary['events_per_year'] = (
		cluster_summary['num_events'] / cluster_summary['active_years']
	).fillna(0)

	# ========================
	# RISK SCORE (CORE UPGRADE)
	# ========================
	cluster_summary['risk_score'] = (
		cluster_summary['num_events'] *
		cluster_summary['avg_intensity']
	)

	# ========================
	# NORMALIZE RISK (optional but better)
	# ========================
	if cluster_summary['risk_score'].max() > cluster_summary['risk_score'].min():
		cluster_summary['risk_score_norm'] = (
			(cluster_summary['risk_score'] - cluster_summary['risk_score'].min()) /
			(cluster_summary['risk_score'].max() - cluster_summary['risk_score'].min())
		)
	else:
		cluster_summary['risk_score_norm'] = 0

	# ========================
	# RISK LEVEL CLASSIFICATION
	# ========================
	if len(cluster_summary) >= 3:
		cluster_summary['risk_level'] = pd.qcut(
			cluster_summary['risk_score'],
			q=3,
			labels=['Low', 'Medium', 'High'],
			duplicates='drop'
		)
	else:
		cluster_summary['risk_level'] = 'Medium'

	# ========================
	# SORT BY IMPORTANCE
	# ========================
	cluster_summary = cluster_summary.sort_values(
		by='risk_score',
		ascending=False
	)

	print("\n=== ADVANCED CLUSTER SUMMARY (Ranked Regions) ===")
	print(cluster_summary.head(15))

	# Save advanced cluster summary
	cluster_summary_path = Path(clustered_path).parent / "cluster_summary.csv"
	cluster_summary.to_csv(cluster_summary_path, index=False)
	print(f"\nCluster summary saved to: {cluster_summary_path}")

	# ========================
	# HIGH-RISK REGION DETECTION (TIME-AWARE)
	# ========================

	# STEP 1: Compute recent activity (last 2 years)
	recent_year = df['year'].max() if 'year' in df.columns else 0
	recent_df = df[df['year'] >= recent_year - 1] if 'year' in df.columns else df

	recent_activity = (
		recent_df[recent_df['cluster'] != -1]
		.groupby('cluster')
		.size()
		.reset_index(name='recent_events')
	)

	# STEP 2: Merge into cluster_summary
	cluster_summary = cluster_summary.merge(
		recent_activity,
		on='cluster',
		how='left'
	).fillna({'recent_events': 0})

	# STEP 3: Compute growth (recent vs historical average)
	cluster_summary['growth_factor'] = (
		cluster_summary['recent_events'] / cluster_summary['events_per_year']
	).replace([np.inf, -np.inf], 0).fillna(0)

	# STEP 4: New time-aware risk score
	cluster_summary['time_risk_score'] = (
		cluster_summary['risk_score'] *
		(1 + cluster_summary['growth_factor'])
	)

	# STEP 5: Select high-risk (top 25%)
	threshold = cluster_summary['time_risk_score'].quantile(0.75) if len(cluster_summary) > 0 else 0
	high_risk = cluster_summary[
		cluster_summary['time_risk_score'] > threshold
	]

	print("\nHIGH-RISK REGIONS (Time-Aware Risk):")
	print(
		high_risk[
			[
				'Event_type',
				'cluster',
				'num_events',
				'recent_events',
				'events_per_year',
				'growth_factor',
				'time_risk_score',
				'risk_level',
				'avg_lat',
				'avg_lon'
			]
		]
		.sort_values(by='time_risk_score', ascending=False)
	)

	high_risk_path = Path(clustered_path).parent / "High_risk_regions.csv"
	high_risk.to_csv(high_risk_path, index=False)
	print(f"\nHigh-risk regions saved to: {high_risk_path}")

	# ========================
	# Save model payload
	# ========================
	
	# Compute core points for model
	df_for_model = df[df['cluster'] != -1].copy()
	
	model_payload = {
		"eps_km": 150,  # default value
		"min_samples": 5,
		"cluster_summary": cluster_summary,
		"event_summary": event_summary,
		"high_risk": high_risk,
		"cluster_trend": cluster_trend_summary,
	}

	dump(model_payload, model_path)
	df.to_csv(clustered_path, index=False)

	n_clusters = len(set(df["cluster"])) - (1 if -1 in df["cluster"].values else 0)
	noise_count = (df["cluster"] == -1).sum()
	print("\n=== CLUSTERING COMPLETE ===")
	print(f"   → Number of hazard regions (clusters): {n_clusters}")
	print(f"   → Noise/outlier events: {noise_count} ({noise_count/len(df)*100:.1f}%)")
	print(f"\nClustered dataset saved to: {clustered_path}")
	print(f"Model saved to: {model_path}")

	return model_payload


if __name__ == "__main__":
	base_dir = Path(__file__).resolve().parent
	data_file = base_dir / "Data" / "final_hazard_dataset.csv"
	model_file = base_dir / "model" / "dbscan_model.joblib"
	clustered_file = base_dir / "Data" / "final_hazard_dataset_with_clusters.csv"

	train_and_save_model(data_file, model_file, clustered_file)
