# main.py
import os
import zipfile
import requests
import webbrowser
import hashlib
from datetime import datetime
from html.parser import HTMLParser
from typing import Dict

from generator import generate_site_code


# ===============================
# CONFIG
# ===============================

OUTPUT_DIR = "output"
IMAGES_DIR = "images"
ZIP_NAME = f"generated_site_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"


# ===============================
# HTML IMAGE PARSER
# ===============================

class ImageSrcParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.image_urls: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "img":
            return

        for attr, value in attrs:
            if attr.lower() == "src" and value.startswith(("http://", "https://")):
                self.image_urls.append(value)


# ===============================
# HELPERS
# ===============================

def safe_image_name(url: str) -> str:
    ext = os.path.splitext(url.split("?")[0])[1] or ".jpg"
    digest = hashlib.sha1(url.encode()).hexdigest()[:12]
    return f"img_{digest}{ext}"


def extract_image_urls(html: str) -> list[str]:
    parser = ImageSrcParser()
    parser.feed(html)
    return parser.image_urls


def download_images(files: Dict[str, str]) -> Dict[str, str]:
    """
    Downloads external images once and replaces URLs in HTML.
    """
    session = requests.Session()
    image_cache: dict[str, str] = {}

    for filename, content in files.items():
        if not filename.endswith(".html"):
            continue

        image_urls = extract_image_urls(content)

        for url in image_urls:
            if url not in image_cache:
                image_name = safe_image_name(url)
                local_path = os.path.join(IMAGES_DIR, image_name)
                full_path = os.path.join(OUTPUT_DIR, local_path)

                try:
                    response = session.get(url, timeout=10)
                    response.raise_for_status()

                    os.makedirs(os.path.dirname(full_path), exist_ok=True)
                    with open(full_path, "wb") as f:
                        f.write(response.content)

                    image_cache[url] = local_path
                    print(f"📥 Downloaded: {url}")

                except Exception as e:
                    print(f"⚠️ Failed to download {url}: {e}")
                    continue

            content = content.replace(url, image_cache[url])

        files[filename] = content

    return files


def save_files(files: Dict[str, str]):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for path, content in files.items():
        full_path = os.path.join(OUTPUT_DIR, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)


def zip_output():
    with zipfile.ZipFile(ZIP_NAME, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(OUTPUT_DIR):
            for file in files:
                filepath = os.path.join(root, file)
                arcname = os.path.relpath(filepath, OUTPUT_DIR)
                zipf.write(filepath, arcname)


# ===============================
# MAIN
# ===============================

def main():
    prompt = input("Enter your prompt (e.g., 'Create a coffee shop website'): ").strip()

    print("🧠 Generating site...")
    files = generate_site_code(prompt)

    print("🖼 Downloading images...")
    files = download_images(files)

    print("💾 Saving files...")
    save_files(files)

    print("📦 Creating zip...")
    zip_output()

    index_path = os.path.abspath(os.path.join(OUTPUT_DIR, "index.html"))
    if os.path.exists(index_path):
        webbrowser.open(f"file://{index_path}")
        print("🌐 Preview opened in browser.")

    print(f"✅ Done! {len(files)} files saved.")
    print(f"📦 Zip created: {ZIP_NAME}")


if __name__ == "__main__":
    main()
