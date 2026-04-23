from pathlib import Path

import pandas as pd
import numpy as np


# ─────────────────────────────────────────────
#  Event classification map (order matters — more specific first)
# ─────────────────────────────────────────────
_EVENT_RULES: list[tuple[str, str]] = [
    ("iceberg a",        "Iceberg_A"),
    ("iceberg b",        "Iceberg_B"),
    ("iceberg c",        "Iceberg_C"),
    ("iceberg d",        "Iceberg_D"),
    ("iceberg",          "Iceberg_A"),   # fallback for un-lettered icebergs
    ("typhoon",          "Typhoon"),
    ("cyclone",          "Cyclone"),
    ("wildfire",         "Wildfire"),
    ("prescribed fire",  "Prescribed_Fire"),
    ("volcano",          "Volcano"),
    ("complex",          "Complex"),
    ("fire",             "Fire"),
]


def classify_event(event: str) -> str:
    """
    Classify events based on event name (case-insensitive).
    Rules are checked in order — first match wins.
    """
    event_lower = str(event).lower()
    for keyword, label in _EVENT_RULES:
        if keyword in event_lower:
            return label
    return "Other"


# ─────────────────────────────────────────────
#  Intensity scaling helpers
# ─────────────────────────────────────────────

def _log_scale_intensity(series: pd.Series) -> pd.Series:
    """
    Apply log1p scaling then min-max normalise to [0, 1].
    Falls back to 0.5 if all values are identical.
    """
    logged = np.log1p(series)
    lo, hi = logged.min(), logged.max()
    if hi > lo:
        return (logged - lo) / (hi - lo)
    return pd.Series(np.full(len(series), 0.5), index=series.index)


def load_prepare_data(source_path: Path, output_path: Path) -> pd.DataFrame:
    """
    Load and preprocess raw NASA event CSV with enhanced feature engineering.

    Parameters
    ----------
    source_path : Path
        Raw NASA event CSV — expected columns: event, date, magnitude, lat, lon
    output_path : Path
        Destination for the prepared dataset.

    Returns
    -------
    pd.DataFrame
        Cleaned and feature-engineered dataframe ready for DBSCAN.
    """
    source_path = Path(source_path)
    output_path = Path(output_path)

    if not source_path.exists():
        raise FileNotFoundError(
            f"Source data not found: {source_path}\n"
            "Enable NASA_EVENT_FETCH_ENABLED in main.py and restart the app, "
            "or manually place Nasa_Event_data.csv in Data_Source/."
        )

    df = pd.read_csv(source_path)

    # Strip unnamed index columns added by previous saves
    df = df.loc[:, ~df.columns.str.contains(r"^Unnamed", regex=True)]

    print(f"[PREPARE] Raw shape      : {df.shape}")
    print(f"[PREPARE] Columns found  : {df.columns.tolist()}")

    # ── 1. Normalise column names ─────────────────────────────────────────────
    col_map: dict[str, str] = {}
    for col in df.columns:
        lower = col.lower().strip()
        if lower in ("latitude", "lat"):
            col_map[col] = "lat"
        elif lower in ("longitude", "lon", "long"):
            col_map[col] = "lon"
        elif lower in ("event", "event_name", "title"):
            col_map[col] = "event"
        elif lower in ("date", "datetime", "timestamp", "time"):
            col_map[col] = "date"
        elif lower in ("magnitude", "mag", "size", "area"):
            col_map[col] = "magnitude"
    df = df.rename(columns=col_map)

    # ── 2. Clean lat / lon ────────────────────────────────────────────────────
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df = df.dropna(subset=["lat", "lon"]).copy()

    # Sanity-check bounds
    df = df[(df["lat"].between(-90, 90)) & (df["lon"].between(-180, 180))].copy()
    print(f"[PREPARE] After lat/lon clean : {df.shape}")

    # ── 3. Parse date ─────────────────────────────────────────────────────────
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=True)
        df = df.dropna(subset=["date"]).copy()
        print(f"[PREPARE] After date clean    : {df.shape}")
    else:
        print("[PREPARE] WARNING: 'date' column not found — defaulting to 2026-01-01")
        df["date"] = pd.to_datetime("2026-01-01", utc=True)

    # Strip timezone for downstream compatibility
    df["date"] = df["date"].dt.tz_convert(None)

    # ── 4. Magnitude → normalised intensity ──────────────────────────────────
    if "magnitude" in df.columns:
        df["magnitude"] = pd.to_numeric(df["magnitude"], errors="coerce")

        # Fill per-event-type median to avoid cross-type contamination
        if "event" in df.columns:
            df["Event_type_tmp"] = df["event"].apply(classify_event)
            df["magnitude"] = df.groupby("Event_type_tmp")["magnitude"].transform(
                lambda s: s.fillna(s.median() if s.notna().any() else 1.0)
            )
            df.drop(columns=["Event_type_tmp"], inplace=True)
        else:
            df["magnitude"] = df["magnitude"].fillna(df["magnitude"].median())

        df["intensity"] = _log_scale_intensity(df["magnitude"])
    else:
        print("[PREPARE] WARNING: 'magnitude' column not found — using default intensity 0.5")
        df["intensity"] = 0.5

    # ── 5. Event classification ───────────────────────────────────────────────
    if "event" in df.columns:
        df["Event_type"] = df["event"].apply(classify_event)
    elif "Event_type" not in df.columns:
        print("[PREPARE] WARNING: No event column found — defaulting to 'Other'")
        df["Event_type"] = "Other"

    # ── 6. Time features ──────────────────────────────────────────────────────
    df["year"]       = df["date"].dt.year
    df["month"]      = df["date"].dt.month
    df["day"]        = df["date"].dt.day
    df["hour"]       = df["date"].dt.hour
    df["dayofweek"]  = df["date"].dt.dayofweek
    df["is_weekend"] = df["dayofweek"].isin([5, 6]).astype(int)

    # Cyclical encoding for month (helps temporal distance)
    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)

    # ── 7. Build final dataframe ──────────────────────────────────────────────
    keep_cols = [
        "Event_type", "lat", "lon", "intensity",
        "year", "month", "day", "hour", "dayofweek", "is_weekend",
        "month_sin", "month_cos",
    ]
    if "magnitude" in df.columns:
        keep_cols.insert(3, "magnitude")

    final_df = df[[c for c in keep_cols if c in df.columns]].copy()
    final_df = final_df.dropna().reset_index(drop=True)

    print(f"[PREPARE] Final shape            : {final_df.shape}")
    print(f"\n[PREPARE] Event type distribution:")
    print(final_df["Event_type"].value_counts().to_string())

    # ── 8. Save outputs ───────────────────────────────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    final_df.to_csv(output_path, index=False)

    event_counts = (
        final_df["Event_type"]
        .value_counts()
        .reset_index()
        .rename(columns={"index": "Event_type", "Event_type": "Count",
                          "count": "Count"})     # pandas ≥2.0 renames automatically
    )
    # Ensure columns are named correctly regardless of pandas version
    event_counts.columns = ["Event_type", "Count"]
    event_counts.to_csv(output_path.parent / "event_counts.csv", index=False)

    print(f"\n[PREPARE] Saved prepared data → {output_path}")
    print(f"[PREPARE] Saved event counts  → {output_path.parent / 'event_counts.csv'}")

    return final_df


# ─────────────────────────────────────────────
#  Stand-alone execution helper
#  Usage: python -m Main.app4.Prepaire
# ─────────────────────────────────────────────
if __name__ == "__main__":
    _app4_dir     = Path(__file__).resolve().parent
    _project_root = _app4_dir.parent.parent

    source = _project_root / "Data_Source" / "Nasa_Event_data.csv"
    target = _app4_dir / "Data" / "final_hazard_dataset.csv"

    print(f"Source : {source}")
    print(f"Target : {target}")
    prepared = load_prepare_data(source, target)