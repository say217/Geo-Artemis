import datetime as dt
import os
import time
import requests
import pandas as pd

# USGS endpoint (query API)
URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"

# USGS API limit per request
MAX_LIMIT = 20000

# Chunk size to reduce request timeouts
CHUNK_DAYS = 60

def build_date_range_months(months_back=1):
    end_date = dt.date.today()
    start_date = end_date - dt.timedelta(days=months_back * 10)
    return start_date.isoformat(), end_date.isoformat()

def build_date_range_days(days_back=20):
    """Fetch data for the past N days"""
    end_date = dt.date.today()
    start_date = end_date - dt.timedelta(days=days_back)
    return start_date.isoformat(), end_date.isoformat()

def fetch_earthquake_data(url, start_date, end_date, retries=3):
    records = []
    start_dt = dt.date.fromisoformat(start_date)
    end_dt = dt.date.fromisoformat(end_date)

    chunk_start = start_dt
    while chunk_start <= end_dt:
        chunk_end = min(chunk_start + dt.timedelta(days=CHUNK_DAYS - 1), end_dt)
        offset = 1

        while True:
            params = {
                "format": "geojson",
                "starttime": chunk_start.isoformat(),
                "endtime": chunk_end.isoformat(),
                "limit": MAX_LIMIT,
                "offset": offset,
            }

            attempt = 0
            while True:
                try:
                    response = requests.get(url, params=params, timeout=(10, 60))
                    response.raise_for_status()
                    payload = response.json()
                    break
                except requests.exceptions.RequestException:
                    attempt += 1
                    if attempt >= retries:
                        raise
                    time.sleep(2 * attempt)

            features = payload.get("features", [])
            if not features:
                break

            records.extend(features)

            if len(features) < MAX_LIMIT:
                break

            offset += MAX_LIMIT

        chunk_start = chunk_end + dt.timedelta(days=1)

    return {"features": records}

def parse_data(data):
    records = []

    for eq in data["features"]:
        props = eq["properties"]
        coords = eq["geometry"]["coordinates"]

        record = {
            "time": props.get("time"),
            "magnitude": props.get("mag"),
            "place": props.get("place"),
            "longitude": coords[0],
            "latitude": coords[1],
            "depth_km": coords[2],
            "url": props.get("url")
        }

        records.append(record)

    return pd.DataFrame(records)

def save_to_csv(df, filename="earthquakes.csv"):
    # Convert timestamp (ms → readable datetime)
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    
    df.to_csv(filename, index=False)
    print(f"Saved {len(df)} records to {filename}")

if __name__ == "__main__":
    # Create output directory if it doesn't exist
    output_dir = "USGS_DATA"
    os.makedirs(output_dir, exist_ok=True)

    # Fetch and parse data (past 20 days)
    start_date, end_date = build_date_range_days(days_back=20)
    data = fetch_earthquake_data(URL, start_date, end_date)
    df = parse_data(data)

    # Save to USGS_DATA folder
    output_file = os.path.join(output_dir, "earthquakes.csv")
    save_to_csv(df, output_file)