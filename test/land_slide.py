import requests
import json

LANDSLIDE_URL = "https://data.nasa.gov/resource/dd9e-wu2v.json"


def get_landslides(limit=500):
    landslides = []
    offset = 0
    batch_size = 100

    while len(landslides) < limit:
        params = {
            "$limit": batch_size,
            "$offset": offset
        }

        try:
            res = requests.get(LANDSLIDE_URL, params=params, timeout=10)
            res.raise_for_status()
            data = res.json()
        except requests.exceptions.RequestException as e:
            print(f"Request failed: {e}")
            break

        if not data:
            break

        for item in data:
            try:
                lat = float(item.get("latitude"))
                lon = float(item.get("longitude"))
            except (TypeError, ValueError):
                continue

            landslides.append({
                "id": len(landslides),
                "lat": lat,
                "lon": lon,
                "trigger": item.get("trigger", "unknown"),
                "date": item.get("date", "")
            })

            if len(landslides) >= limit:
                break

        offset += batch_size

    return landslides


if __name__ == "__main__":
    data = get_landslides(100)

    with open("landslides.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"Saved {len(data)} records")