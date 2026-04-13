from pathlib import Path

import pandas as pd


def load_prepare_data(source_path: Path, output_path: Path) -> pd.DataFrame:
	df = pd.read_csv(source_path)

	# Basic cleanup for consistent clustering inputs
	df = df.dropna(subset=["lat", "lon"]).copy()
	df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
	df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
	df = df.dropna(subset=["lat", "lon"]).copy()

	output_path.parent.mkdir(parents=True, exist_ok=True)
	df.to_csv(output_path, index=False)
	return df


if __name__ == "__main__":
	root_dir = Path(__file__).resolve().parents[1]  # Go up: app4 -> Main -> Geo Artemis
	source = root_dir / "Data_Source" / "final_hazard_dataset.csv"
	target = Path(__file__).resolve().parent / "Data" / "final_hazard_dataset.csv"

	prepared = load_prepare_data(source, target)
	print(f"Prepared rows: {len(prepared)}")
