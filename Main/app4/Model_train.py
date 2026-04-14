from pathlib import Path

import numpy as np
import pandas as pd
from joblib import dump
from sklearn.cluster import DBSCAN


def train_and_save_model(data_path: Path, model_path: Path, clustered_path: Path) -> None:
	df = pd.read_csv(data_path)
	
	# Remove any unnamed index columns that may exist
	df = df.loc[:, ~df.columns.str.contains('^Unnamed')]

	coords = np.radians(df[["lat", "lon"]].values)
	kms_per_radian = 6371.0088

	eps_km = 200
	eps = eps_km / kms_per_radian
	min_samples = 5

	print(f"Running DBSCAN with eps = {eps_km} km and min_samples = {min_samples}")

	dbscan = DBSCAN(
		eps=eps,
		min_samples=min_samples,
		metric="haversine",
		algorithm="ball_tree",
	)

	df["cluster"] = dbscan.fit_predict(coords)

	cluster_summary = (
		df.groupby("cluster")
		.agg(
			num_events=("Event_type", "count"),
			most_common_event=("Event_type", lambda x: x.mode()[0] if not x.empty else "None"),
			avg_magnitude=("magnitude", "mean"),
			avg_lat=("lat", "mean"),
			avg_lon=("lon", "mean"),
		)
		.round(2)
		.reset_index()
	)

	model_payload = {
		"eps_km": eps_km,
		"min_samples": min_samples,
		"core_coords": coords[dbscan.core_sample_indices_],
		"core_labels": df.iloc[dbscan.core_sample_indices_]["cluster"].values,
		"cluster_summary": cluster_summary,
	}

	model_path.parent.mkdir(parents=True, exist_ok=True)
	clustered_path.parent.mkdir(parents=True, exist_ok=True)

	dump(model_payload, model_path)
	df.to_csv(clustered_path, index=False)

	n_clusters = len(set(df["cluster"])) - (1 if -1 in df["cluster"].values else 0)
	noise_count = (df["cluster"] == -1).sum()
	print("Clustering complete!")
	print(f"   -> Number of hazard regions (clusters): {n_clusters}")
	print(f"   -> Noise/outlier events: {noise_count} ({noise_count/len(df)*100:.1f}%)")
	print(f"Clustered dataset saved to: {clustered_path}")
	print(f"Model saved to: {model_path}")


if __name__ == "__main__":
	base_dir = Path(__file__).resolve().parent
	data_file = base_dir / "Data" / "final_hazard_dataset.csv"
	model_file = base_dir / "model" / "dbscan_model.joblib"
	clustered_file = base_dir / "Data" / "final_hazard_dataset_with_clusters.csv"

	train_and_save_model(data_file, model_file, clustered_file)
