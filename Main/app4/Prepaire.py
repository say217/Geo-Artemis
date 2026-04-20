from pathlib import Path

import pandas as pd
import numpy as np


def classify_event(event):
	"""
	Classify events based on event name (case-insensitive).
	"""
	event = str(event).lower()

	if 'wildfire' in event or 'fire' in event:
		return 'Wildfire'
	elif 'typhoon' in event:
		return 'Typhoon'
	elif 'cyclone' in event:
		return 'Cyclone'
	elif 'volcano' in event:
		return 'Volcano'
	elif 'iceberg a' in event:
		return 'Iceberg_A'
	elif 'iceberg b' in event:
		return 'Iceberg_B'
	elif 'iceberg c' in event:
		return 'Iceberg_C'
	elif 'iceberg d' in event:
		return 'Iceberg_D'
	elif 'complex' in event:
		return 'Complex'
	else:
		return 'Other'


def load_prepare_data(source_path: Path, output_path: Path) -> pd.DataFrame:
	"""
	Load and preprocess data with enhanced feature engineering.
	"""
	df = pd.read_csv(source_path)
	print(f"Original dataset shape: {df.shape}")
	print(f"Original columns: {df.columns.tolist()}")

	# ========================
	# 1. Clean lat/lon FIRST
	# ========================
	df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
	df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
	df = df.dropna(subset=['lat', 'lon']).copy()
	print(f"After lat/lon cleanup: {df.shape}")

	# ========================
	# 2. Convert date (robust)
	# ========================
	if 'date' in df.columns:
		df['date'] = pd.to_datetime(df['date'], errors='coerce', utc=True)
		# Remove rows with invalid dates
		df = df.dropna(subset=['date']).copy()
		print(f"After date conversion: {df.shape}")
	else:
		print("WARNING: 'date' column not found")
		# Create default date if missing
		df['date'] = pd.to_datetime('2026-01-01')

	# ========================
	# 3. Clean magnitude → convert to usable "intensity"
	# ========================
	if 'magnitude' in df.columns:
		df['magnitude'] = pd.to_numeric(df['magnitude'], errors='coerce')
		df['magnitude'] = df['magnitude'].fillna(df['magnitude'].median())
		# Log scaling (important for dataset normalization)
		df['intensity'] = np.log1p(df['magnitude'])
	else:
		print("WARNING: 'magnitude' column not found, creating default intensity")
		df['intensity'] = 1.0

	# ========================
	# 4. Improved classification
	# ========================
	if 'event' in df.columns:
		df['Event_type'] = df['event'].apply(classify_event)
	elif 'Event_type' not in df.columns:
		print("WARNING: Neither 'event' nor 'Event_type' column found")
		df['Event_type'] = 'Other'

	# ========================
	# 5. Remove timezone from date
	# ========================
	if pd.api.types.is_datetime64_any_dtype(df['date']):
		df['date'] = df['date'].dt.tz_localize(None)

		# ========================
		# 6. Extract time features
		# ========================
		df['year'] = df['date'].dt.year
		df['month'] = df['date'].dt.month
		df['day'] = df['date'].dt.day
		df['hour'] = df['date'].dt.hour
		df['dayofweek'] = df['date'].dt.dayofweek
		df['is_weekend'] = df['dayofweek'].isin([5, 6]).astype(int)

	# ========================
	# 7. Create final dataframe with selected columns
	# ========================
	final_df = df[['Event_type', 'lat', 'lon', 'intensity', 'year', 'month', 'day', 'hour', 'dayofweek', 'is_weekend']].copy()

	# ========================
	# 8. Final validation
	# ========================
	final_df = final_df.dropna().copy()
	print(f"Final dataset shape (after validation): {final_df.shape}")

	# ========================
	# 9. Reset index
	# ========================
	final_df = final_df.reset_index(drop=True)

	# ========================
	# 10. Final check
	# ========================
	print("\n=== PREPARED DATA INFO ===")
	print(final_df.info())
	print(f"\nPrepared rows: {len(final_df)}")

	# Count events by type
	event_counts = final_df["Event_type"].value_counts().reset_index()
	event_counts.columns = ["Event_type", "Count"]

	# Save outputs
	output_path.parent.mkdir(parents=True, exist_ok=True)
	final_df.to_csv(output_path, index=False)
	
	# Save event counts
	event_counts_path = output_path.parent / "event_counts.csv"
	event_counts.to_csv(event_counts_path, index=False)

	print("\nEvent Type Distribution:")
	print(event_counts)
	print(f"\nPrepared data saved to: {output_path}")
	print(f"Event counts saved to: {event_counts_path}")

	return final_df


if __name__ == "__main__":
	root_dir = Path(__file__).resolve().parents[1]  # Go up: app4 -> Main -> Geo Artemis
	source = root_dir / "Data_Source" / "Nasa_Event_data.csv"
	target = Path(__file__).resolve().parent / "Data" / "final_hazard_dataset.csv"

	prepared = load_prepare_data(source, target)
