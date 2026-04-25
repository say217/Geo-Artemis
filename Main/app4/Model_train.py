"""
Model_train.py — Improved HDBSCAN Hazard Clustering
===================================================
Key fixes vs. the original:
  • eps correctly converted km → radians (eps = km / 6371.0088)
  • Per-event-type HDBSCAN with carefully tuned eps / min_samples
  • Cluster-label offsetting uses a stable deterministic offset
  • Noise target: 20–40 %
  • Risk score fully normalised to [0, 100]
  • All output columns documented and consistently named
"""
from pathlib import Path

import numpy as np
import pandas as pd
from joblib import dump
from sklearn.cluster import HDBSCAN

# ──────────────────────────────────────────────────────────────────────────────
#  Constants
# ──────────────────────────────────────────────────────────────────────────────
EARTH_RADIUS_KM = 6371.0088          # WGS-84 mean radius

# Per-event-type eps (km).  Tune these to your data density.
# Larger eps  → fewer, bigger clusters, less noise
# Smaller eps → more, tighter clusters, more noise
EPS_KM_BY_EVENT: dict[str, float] = {
    'Cyclone':         500.0,
    'Typhoon':         500.0,
    'Wildfire':        120.0,
    'Prescribed_Fire': 120.0,
    'Fire':            120.0,
    'Iceberg_A':       300.0,
    'Iceberg_B':       300.0,
    'Iceberg_C':       300.0,
    'Iceberg_D':       300.0,
    'Volcano':         700.0, # Increased eps for Volcano
    'Complex':         200.0,
    'Other':           200.0,
}
DEFAULT_EPS_KM = 200.0

# min_samples: absolute floor and density fraction
MIN_SAMPLES_FLOOR  = 3
MIN_SAMPLES_FRAC   = 0.005   # 0.5 % of subset size (avoids huge values)
MIN_SAMPLES_CAP    = 20      # never require more than this


# ──────────────────────────────────────────────────────────────────────────────
#  Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _eps_radians(eps_km: float) -> float:
    """Convert kilometres to radians for sklearn Haversine HDBSCAN."""
    return eps_km / EARTH_RADIUS_KM


def _min_samples(n: int) -> int:
    """Dynamic min_samples bounded by floor and cap."""
    return int(np.clip(max(MIN_SAMPLES_FLOOR, n * MIN_SAMPLES_FRAC),
                       MIN_SAMPLES_FLOOR, MIN_SAMPLES_CAP))


def _run_hdbscan(coords_rad: np.ndarray, eps_km: float, n: int) -> np.ndarray:
    """Fit HDBSCAN with Haversine metric and return labels."""
    ms = _min_samples(n)
    db = HDBSCAN(
        min_cluster_size=ms,
        min_samples=ms,
        cluster_selection_epsilon=_eps_radians(eps_km),
        metric="haversine",
        algorithm="ball_tree",
        n_jobs=-1,
    )
    return db.fit_predict(coords_rad)


def _safe_normalise(series: pd.Series) -> pd.Series:
    """Min-max normalise; returns 0.0 series if all values are identical."""
    lo, hi = series.min(), series.max()
    if hi > lo:
        return (series - lo) / (hi - lo)
    return pd.Series(np.zeros(len(series), dtype=float), index=series.index)


# ──────────────────────────────────────────────────────────────────────────────
#  Step 1 — Per-event-type HDBSCAN
# ──────────────────────────────────────────────────────────────────────────────

def _cluster_per_event_type(df: pd.DataFrame) -> pd.DataFrame:
    """
    Run HDBSCAN independently for each event type.

    Cluster labels are offset by a deterministic per-type integer so that IDs
    never collide across event types.  Noise remains -1.

    Returns the input dataframe with a new integer column 'cluster'.
    """
    df = df.copy()
    df["cluster"] = -1

    summary_rows = []
    type_offset = 0   # incremented after each event type

    for event in sorted(df['Event_type'].unique()):
        mask   = df['Event_type'] == event
        subset = df[mask]
        n      = len(subset)

        if n < MIN_SAMPLES_FLOOR:
            print(f'[{event}] SKIPPED — only {n} points')
            continue

        eps_km = EPS_KM_BY_EVENT.get(event, DEFAULT_EPS_KM)
        ms     = _min_samples(n)

        coords = np.radians(subset[['lat', 'lon']].values)

        labels = HDBSCAN(
            min_cluster_size=ms,
            min_samples=ms,
            cluster_selection_epsilon=_eps_radians(eps_km),
            metric='haversine',
            algorithm='ball_tree',
            n_jobs=-1,
        ).fit_predict(coords)

        # Offset positive labels; noise stays -1
        pos = labels != -1
        labels[pos] = labels[pos] + type_offset

        df.loc[mask, 'cluster'] = labels

        n_clusters = int(labels[pos].max() - labels[pos].min() + 1) if pos.any() else 0
        noise_pct  = round((labels == -1).sum() / n * 100, 1)
        type_offset += (n_clusters + 100)   # leave a gap between event types

        summary_rows.append({
            "Event_type":   event,
            "num_events":   n,
            "eps_km":       eps_km,
            "min_samples":  ms,
            "num_clusters": n_clusters,
            "noise_%":      noise_pct,
        })

        print(f'[{event}] eps={eps_km} km | min_s={ms} | n={n} | '
              f'clusters={n_clusters} | noise={noise_pct}%')

    event_summary = pd.DataFrame(summary_rows)
    return df, event_summary


# ──────────────────────────────────────────────────────────────────────────────
#  Step 2 — Temporal analysis per cluster
# ──────────────────────────────────────────────────────────────────────────────

def _temporal_analysis(df: pd.DataFrame) -> pd.DataFrame:
    """Compute year-over-year event counts and growth trend per cluster."""
    clustered = df[df["cluster"] != -1].copy()

    if clustered.empty:
        return pd.DataFrame()

    ct = (
        clustered
        .groupby(["cluster", "year"])
        .size()
        .reset_index(name="event_count")
    )
    ct["growth"] = (
        ct.groupby("cluster")["event_count"]
        .diff()
        .fillna(0)
    )

    trend = (
        ct.groupby("cluster")
        .agg(
            avg_events    = ("event_count", "mean"),
            max_events    = ("event_count", "max"),
            avg_growth    = ("growth",      "mean"),
            recent_growth = ("growth",      "last"),
        )
        .reset_index()
    )
    return trend


# ──────────────────────────────────────────────────────────────────────────────
#  Step 3 — Cluster summary with bounded risk score
# ──────────────────────────────────────────────────────────────────────────────

def _build_cluster_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build per-cluster statistics and a normalised, interpretable risk score.

    Risk score components (all normalised to [0, 1] before combination):
      A. recency_ratio   = recent_events / total_events        (surge signal)
      B. growth_norm     = normalised growth_factor            (acceleration)
      C. log_freq_norm   = normalised log(events_per_year + 1) (persistence)
      D. intensity_norm  = normalised avg_intensity            (severity)

    Final score = mean(A, B, C, D) scaled to [0, 100].
    """
    clustered = df[df["cluster"] != -1].copy()
    if clustered.empty:
        return pd.DataFrame()

    # ── Base aggregation ──────────────────────────────────────────────────────
    base = (
        clustered
        .groupby(["Event_type", "cluster"])
        .agg(
            num_events    = ("Event_type",  "count"),
            avg_intensity = ("intensity",   "mean"),
            avg_lat       = ("lat",         "mean"),
            avg_lon       = ("lon",         "mean"),
            start_year    = ("year",        "min"),
            end_year      = ("year",        "max"),
        )
        .reset_index()
    )

    # Dominant event type per cluster (in case of mixed labels)
    dominant = (
        clustered
        .groupby("cluster")["Event_type"]
        .agg(lambda s: s.mode().iloc[0])
        .reset_index()
        .rename(columns={"Event_type": "dominant_event_type"})
    )
    base = base.merge(dominant, on="cluster", how="left")

    # ── Temporal features ─────────────────────────────────────────────────────
    base["active_years"]    = (base["end_year"] - base["start_year"] + 1).clip(lower=1)
    base["events_per_year"] = base["num_events"] / base["active_years"]

    # ── Recent activity (last 2 data years) ───────────────────────────────────
    recent_cutoff = int(df["year"].max()) - 1
    recent_counts = (
        clustered[clustered["year"] >= recent_cutoff]
        .groupby("cluster")
        .size()
        .reset_index(name="recent_events")
    )
    base = base.merge(recent_counts, on="cluster", how="left")
    base["recent_events"] = base["recent_events"].fillna(0)

    # ── Growth factor ─────────────────────────────────────────────────────────
    # Ratio of recent pace to historical average; cap at 5× to avoid inflation
    base["growth_factor"] = (
        base["recent_events"] / base["events_per_year"]
    ).replace([np.inf, -np.inf], 0).fillna(0).clip(upper=5.0)

    # ── Recency ratio ─────────────────────────────────────────────────────────
    base["recency_ratio"] = (
        base["recent_events"] / base["num_events"]
    ).clip(0, 1).fillna(0)

    # ── Bounded, interpretable risk score [0, 100] ────────────────────────────
    log_freq = np.log1p(base["events_per_year"])

    comp_A = base["recency_ratio"]                        # already [0, 1]
    comp_B = _safe_normalise(base["growth_factor"])       # [0, 1]
    comp_C = _safe_normalise(log_freq)                    # [0, 1]
    comp_D = _safe_normalise(base["avg_intensity"])       # [0, 1]

    base["risk_score"] = ((comp_A + comp_B + comp_C + comp_D) / 4 * 100).round(2)

    # ── Risk level classification ─────────────────────────────────────────────
    if len(base) >= 3:
        try:
            base["risk_level"] = pd.qcut(
                base["risk_score"],
                q=3,
                labels=["Low", "Medium", "High"],
                duplicates="drop",
            )
        except ValueError:
            base["risk_level"] = "Medium"
    else:
        base["risk_level"] = "Medium"

    base = base.sort_values("risk_score", ascending=False).reset_index(drop=True)

    return base


# ──────────────────────────────────────────────────────────────────────────────
#  Step 4 — High-risk region detection
# ──────────────────────────────────────────────────────────────────────────────

def _high_risk_regions(cluster_summary: pd.DataFrame) -> pd.DataFrame:
    """
    Select clusters in the top 25% by risk_score.
    Returns a clean dataframe with the columns needed by routes.py.
    """
    if cluster_summary.empty:
        return pd.DataFrame()

    threshold  = cluster_summary["risk_score"].quantile(0.75)
    high_risk  = cluster_summary[cluster_summary["risk_score"] >= threshold].copy()

    output_cols = [
        "cluster",
        "dominant_event_type",
        "Event_type",
        "avg_lat",
        "avg_lon",
        "num_events",
        "recent_events",
        "events_per_year",
        "growth_factor",
        "recency_ratio",
        "risk_score",
        "risk_level",
        "start_year",
        "end_year",
        "active_years",
    ]
    available = [c for c in output_cols if c in high_risk.columns]
    return high_risk[available].reset_index(drop=True)


# ──────────────────────────────────────────────────────────────────────────────
#  Public API
# ──────────────────────────────────────────────────────────────────────────────

def train_and_save_model(
    data_path:      Path,
    model_path:     Path,
    clustered_path: Path,
) -> dict:
    """
    Main entry point: load prepared data, run per-event-type HDBSCAN,
    compute risk scores, persist artefacts, and return a model payload dict.

    Parameters
    ----------
    data_path      : CSV produced by Prepaire.load_prepare_data
    model_path     : joblib output path for the model payload
    clustered_path : CSV output path with cluster column appended

    Returns
    -------
    dict with keys: cluster_summary, event_summary, high_risk, cluster_trend
    """
    # ── Ensure output directories exist ───────────────────────────────────────
    model_path.parent.mkdir(parents=True, exist_ok=True)
    clustered_path.parent.mkdir(parents=True, exist_ok=True)
    out_dir = clustered_path.parent

    # ── Load data ─────────────────────────────────────────────────────────────
    df = pd.read_csv(data_path)
    df = df.loc[:, ~df.columns.str.contains(r"^Unnamed", regex=True)]
    print(f"\n[TRAIN] Loaded {len(df):,} rows | {df['Event_type'].nunique()} event types")
    print(f"[TRAIN] Year range: {df['year'].min()} – {df['year'].max()}")

    # ── Step 1: Per-event-type HDBSCAN ─────────────────────────────────────────
    print("\n=== STEP 1 — PER-EVENT-TYPE HDBSCAN ===")
    df, event_summary = _cluster_per_event_type(df)

    overall_noise = (df["cluster"] == -1).mean() * 100
    n_clusters    = df[df["cluster"] != -1]["cluster"].nunique()
    print(f"\n[TRAIN] Overall noise : {overall_noise:.1f}%  (target 20–40%)")
    print(f"[TRAIN] Total clusters: {n_clusters}")
    print("\n=== EVENT SUMMARY ===")
    print(event_summary.to_string(index=False))

    # ── Step 2: Temporal analysis ─────────────────────────────────────────────
    print("\n=== STEP 2 — TEMPORAL ANALYSIS ===")
    cluster_trend = _temporal_analysis(df)
    if not cluster_trend.empty:
        print(cluster_trend.head(10).to_string(index=False))

    # ── Step 3 & 4: Cluster summary + risk score ──────────────────────────────
    print("\n=== STEP 3 — CLUSTER SUMMARY & RISK SCORING ===")
    cluster_summary = _build_cluster_summary(df)

    if not cluster_summary.empty:
        print(cluster_summary[[
            "cluster", "dominant_event_type", "num_events",
            "recent_events", "growth_factor", "risk_score", "risk_level",
        ]].head(15).to_string(index=False))
    else:
        print("[TRAIN] WARNING: cluster_summary is empty — all points may be noise.")

    # ── High-risk regions ─────────────────────────────────────────────────────
    print("\n=== STEP 4 — HIGH-RISK REGIONS ===")
    high_risk = _high_risk_regions(cluster_summary)

    if not high_risk.empty:
        print(high_risk[[
            "cluster", "dominant_event_type", "num_events",
            "recent_events", "risk_score", "risk_level",
        ]].to_string(index=False))
    else:
        print("[TRAIN] No high-risk clusters identified.")

    # ── Persist outputs ───────────────────────────────────────────────────────
    df.to_csv(clustered_path, index=False)
    print(f"\n[TRAIN] Clustered data   → {clustered_path}")

    cluster_summary_path = out_dir / "cluster_summary.csv"
    cluster_summary.to_csv(cluster_summary_path, index=False)
    print(f"[TRAIN] Cluster summary  → {cluster_summary_path}")

    high_risk_path = out_dir / "High_risk_regions.csv"
    high_risk.to_csv(high_risk_path, index=False)
    print(f"[TRAIN] High-risk file   → {high_risk_path}")

    event_summary_path = out_dir / "event_summary.csv"
    event_summary.to_csv(event_summary_path, index=False)

    # ── Model payload ─────────────────────────────────────────────────────────
    model_payload = {
        "eps_km_by_event":  EPS_KM_BY_EVENT,
        "default_eps_km":   DEFAULT_EPS_KM,
        "min_samples_frac": MIN_SAMPLES_FRAC,
        "cluster_summary":  cluster_summary,
        "event_summary":    event_summary,
        "high_risk":        high_risk,
        "cluster_trend":    cluster_trend,
    }
    dump(model_payload, model_path)
    print(f"[TRAIN] Model payload    → {model_path}")

    print(f"\n=== CLUSTERING COMPLETE ===")
    print(f"   Hazard regions (clusters) : {n_clusters}")
    print(f"   Noise / outlier events    : {(df['cluster'] == -1).sum():,} "
          f"({overall_noise:.1f}%)")

    return model_payload


# ──────────────────────────────────────────────────────────────────────────────
#  Stand-alone execution
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    base_dir       = Path(__file__).resolve().parent
    data_file      = base_dir / "Data"  / "final_hazard_dataset.csv"
    model_file     = base_dir / "model" / "hdbscan_model.joblib"
    clustered_file = base_dir / "Data"  / "final_hazard_dataset_with_clusters.csv"

    train_and_save_model(data_file, model_file, clustered_file)