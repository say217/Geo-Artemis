import os
import re
import requests
import json
from datetime import datetime, timedelta, time, timezone

API_KEY = os.getenv("GNEWS_API_KEY")  # now GNews API key
IMAGE_API_KEY = os.getenv("SERP_API")

# Hazard keywords
KEYWORDS = [
    "earthquake",
    "wildfire",
    "flood",
    "cyclone",
    "typhoon",
    "storm",
    "hurricane",
    "volcano eruption",
    "landslide",
    "tsunami"
]

# GNews endpoint
BASE_URL = "https://gnews.io/api/v4/search"

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "GNEWS_DATA")
DAY_COUNT = 2
IMAGES_PER_INCIDENT = 2
USER_AGENT = "GeoArtemisNewsFetcher/1.0 (+https://example.local)"


def fetch_news(keyword, start_dt, end_dt, session):
    if not API_KEY:
        raise ValueError("Missing GNEWS_API_KEY (GNews API key).")

    params = {
        "q": keyword,
        "lang": "en",
        "sortby": "publishedAt",
        "max": 5,  # equivalent to pageSize
        "from": start_dt.isoformat(),
        "to": end_dt.isoformat(),
        "apikey": API_KEY
    }

    response = session.get(
        BASE_URL,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=(5, 20),
    )
    response.raise_for_status()
    return response.json()


def search_images(query, session, num_images=2):
    if not IMAGE_API_KEY:
        raise ValueError("Missing SERP_API environment variable for image search.")

    url = "https://serpapi.com/search.json"
    params = {
        "q": query,
        "tbm": "isch",
        "ijn": "0",
        "api_key": IMAGE_API_KEY,
    }

    response = session.get(
        url,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=(5, 20),
    )
    response.raise_for_status()
    data = response.json()

    images = []
    if "images_results" in data:
        for img in data["images_results"]:
            if "original" in img:
                images.append(img["original"])
            if len(images) >= num_images:
                break

    return images


def sanitize_slug(text):
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_") or "incident"


def download_images(image_urls, file_prefix, session):
    saved_files = []
    for idx, url in enumerate(image_urls, start=1):
        try:
            if not url.startswith("http://") and not url.startswith("https://"):
                raise ValueError("Unsupported URL scheme")

            response = session.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=(5, 20),
                stream=True,
            )
            response.raise_for_status()

            file_path = f"{file_prefix}_{idx}.jpg"
            with open(file_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    f.write(chunk)

            saved_files.append(file_path)
        except Exception as exc:
            print(f"[!] Failed to download image {url} -> {exc}")

    return saved_files


def process_articles(raw_articles):
    processed = []

    for article in raw_articles:
        headline = (article.get("title") or "").strip()
        description = (article.get("description") or article.get("content") or "").strip()

        processed.append({
            "headline": headline,
            "source": article.get("source", {}).get("name"),
            "url": article.get("url"),
            "web_link": article.get("url"),
            "image": article.get("image"),  # GNews uses "image"
            "published_at": article.get("publishedAt"),
            "description": description
        })

    return processed


def main():
    print("[*] Fetching hazard news (GNews)...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    now_utc = datetime.now(timezone.utc)

    with requests.Session() as session:
        for day_index in range(1, DAY_COUNT + 1):
            day_offset = day_index - 1
            day_date = (now_utc - timedelta(days=day_offset)).date()
            start_dt = datetime.combine(day_date, time.min, tzinfo=timezone.utc)
            end_dt = datetime.combine(day_date, time.max, tzinfo=timezone.utc)

            for keyword in KEYWORDS:
                data = fetch_news(keyword, start_dt, end_dt, session)

                all_articles = []
                seen_urls = set()

                if "articles" in data:
                    for article in data["articles"]:
                        url = article.get("url")

                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            all_articles.append(article)

                structured = process_articles(all_articles)

                incident_slug = sanitize_slug(keyword)
                date_tag = day_date.isoformat()
                json_name = f"news_{day_index}_{incident_slug}_{date_tag}.json"
                json_path = os.path.join(OUTPUT_DIR, json_name)

                image_query = f"{keyword} {date_tag}"
                image_urls = search_images(image_query, session, IMAGES_PER_INCIDENT)
                image_prefix = os.path.join(
                    OUTPUT_DIR,
                    f"news_{day_index}_images_{incident_slug}_{date_tag}",
                )
                image_files = download_images(image_urls, image_prefix, session)

                output = {
                    "fetched_at": datetime.utcnow().isoformat(),
                    "day_index": day_index,
                    "day_date": day_date.isoformat(),
                    "incident": keyword,
                    "total_articles": len(structured),
                    "articles": structured,
                    "news_links": [item.get("url") for item in structured if item.get("url")],
                    "image_files": image_files,
                }

                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(output, f, indent=4)

                print(f"[✔] Saved {len(structured)} articles to {json_path}")


if __name__ == "__main__":
    main()