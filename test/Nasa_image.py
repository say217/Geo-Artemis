import requests
import os
import random
from datetime import datetime

# =========================
# CONFIG
# =========================
SAVE_DIR = "images"
os.makedirs(SAVE_DIR, exist_ok=True)

DATE = datetime.utcnow().strftime("%Y-%m-%d")

LAYER = "MODIS_Terra_CorrectedReflectance_TrueColor"

BASE_URL = f"https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/{LAYER}/default/{DATE}/GoogleMapsCompatible_Level4"

MAX_IMAGES = 35


# =========================
# DOWNLOAD TILE
# =========================
def download_tile(z, x, y):
    url = f"{BASE_URL}/{z}/{y}/{x}.jpg"

    try:
        r = requests.get(url, timeout=10)

        if r.status_code == 200 and len(r.content) > 1000:
            filename = f"{SAVE_DIR}/tile_{z}_{x}_{y}.jpg"
            with open(filename, "wb") as f:
                f.write(r.content)

            print("Saved:", filename)
            return True
        else:
            print("Skip:", url, "Status:", r.status_code)

    except Exception as e:
        print("Error:", e)

    return False


# =========================
# FETCH WITH RANDOM TILES
# =========================
def fetch_images():
    z = 4
    max_tile = 2 ** z   # valid tile range

    count = 0
    tried = set()

    while count < MAX_IMAGES:
        x = random.randint(0, max_tile - 1)
        y = random.randint(0, max_tile - 1)

        if (x, y) in tried:
            continue

        tried.add((x, y))

        success = download_tile(z, x, y)

        if success:
            count += 1
            print(f"{count}/{MAX_IMAGES}")


# =========================
# RUN
# =========================
if __name__ == "__main__":
    fetch_images()