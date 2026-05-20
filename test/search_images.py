


import os
import requests

# ====== CONFIG ======
API_KEY = os.getenv("SERP_API")
QUERY = "Texas wildfire"                 # search query
NUM_IMAGES = 5               # number of images to download
SAVE_FOLDER = os.path.join(os.path.dirname(__file__), "images")  # test/images folder
USER_AGENT = "GeoArtemisImageFetcher/1.0 (+https://example.local)"
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB limit per image

# ====================

def search_images(query, api_key, num_images=10, session=None):
    if not api_key:
        raise ValueError("Missing SERP_API environment variable.")

    if session is None:
        session = requests.Session()

    url = "https://serpapi.com/search.json"

    params = {
        "q": query,
        "tbm": "isch",   # image search
        "ijn": "0",
        "api_key": api_key
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
        for img in data["images_results"][:num_images]:
            if "original" in img:
                images.append(img["original"])

    return images


def is_http_url(url):
    return url.startswith("http://") or url.startswith("https://")


def extension_from_content_type(content_type):
    if not content_type:
        return ".jpg"
    content_type = content_type.split(";")[0].strip().lower()
    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
        "image/tiff": ".tiff",
    }
    return mapping.get(content_type, ".jpg")


def download_images(image_urls, folder, session=None):
    if session is None:
        session = requests.Session()

    os.makedirs(folder, exist_ok=True)

    for i, url in enumerate(image_urls):
        try:
            if not is_http_url(url):
                raise ValueError("Unsupported URL scheme")

            response = session.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=(5, 20),
                stream=True,
            )
            response.raise_for_status()

            content_type = response.headers.get("Content-Type", "")
            if not content_type.startswith("image/"):
                raise ValueError(f"Unexpected Content-Type: {content_type}")

            ext = extension_from_content_type(content_type)
            file_path = os.path.join(folder, f"image_{i+1}{ext}")

            total = 0
            with open(file_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_IMAGE_BYTES:
                        raise ValueError("Image exceeds size limit")
                    f.write(chunk)

            print(f"[+] Downloaded: {file_path}")

        except Exception as e:
            print(f"[!] Failed to download {url} -> {e}")


def main():
    print("[*] Searching images...")
    with requests.Session() as session:
        image_urls = search_images(QUERY, API_KEY, NUM_IMAGES, session=session)

        print(f"[*] Found {len(image_urls)} images. Downloading...")
        download_images(image_urls, SAVE_FOLDER, session=session)

    print("[✔] Done!")


if __name__ == "__main__":
    main()