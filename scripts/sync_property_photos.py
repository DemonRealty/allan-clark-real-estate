#!/usr/bin/env python3
"""Refresh locally hosted lead photographs for already verified property listings.

Never changes listing statuses or adds/deletes properties. A failed fetch retains
the previous image and property data. Intended for scheduled GitHub Actions.
"""
import json
import mimetypes
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "properties.json"
IMAGES = ROOT / "assets" / "property-photos"
HEADERS = {"User-Agent": "AllanClarkRealEstate/1.0 (approved listing photograph synchronisation)"}
MAX_BYTES = 8 * 1024 * 1024


def get_image_url(html, listing_url):
    soup = BeautifulSoup(html, "html.parser")
    for selector in ('meta[property="og:image"]', 'meta[name="twitter:image"]'):
        tag = soup.select_one(selector)
        if tag and tag.get("content"):
            return urljoin(listing_url, tag["content"])
    # Prefer explicit property image only when metadata is missing.
    for selector in (".property-gallery img", ".listing-gallery img", ".property-images img", "article img"):
        tag = soup.select_one(selector)
        if tag:
            src = tag.get("data-src") or tag.get("src")
            if src:
                return urljoin(listing_url, src)
    return None


def valid_source(url):
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password


def download_image(session, url):
    if not valid_source(url):
        raise ValueError("Untrusted image URL")
    with session.get(url, timeout=30, stream=True, allow_redirects=True) as response:
        response.raise_for_status()
        if not valid_source(response.url):
            raise ValueError("Untrusted redirect")
        content_type = response.headers.get("content-type", "").split(";")[0].lower()
        extensions = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
        if content_type not in extensions:
            raise ValueError("Unsupported image content type: " + content_type)
        size = 0
        chunks = []
        for chunk in response.iter_content(chunk_size=65536):
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError("Image exceeds size limit")
            chunks.append(chunk)
        data = b"".join(chunks)
        if len(data) < 1024:
            raise ValueError("Image too small")
        return data, extensions[content_type]


def main():
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    IMAGES.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(HEADERS)
    changed = 0
    for item in payload.get("properties", []):
        if not item.get("verified") or not item.get("url"):
            continue
        url = item["url"]
        match = re.search(r"/listing/[^/]*-(\d+)/?$", urlparse(url).path)
        if not match or urlparse(url).hostname not in ("independentagent.co.nz", "www.independentagent.co.nz"):
            print("Skipping unrecognized property URL:", url)
            continue
        listing_id = match.group(1)
        try:
            page = session.get(url, timeout=30)
            page.raise_for_status()
            image_url = get_image_url(page.text, url)
            if not image_url:
                print("No photo found for", listing_id)
                continue
            data, extension = download_image(session, image_url)
            filename = f"{listing_id}{extension}"
            destination = IMAGES / filename
            if not destination.exists() or destination.read_bytes() != data:
                destination.write_bytes(data)
                changed += 1
            relative = "assets/property-photos/" + filename
            if item.get("image") != relative:
                item["image"] = relative
                changed += 1
            print("Photo ready for", listing_id, relative)
        except (requests.RequestException, ValueError, OSError) as exc:
            print("Keeping previous photo for", listing_id, str(exc))
    if changed:
        DATA.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Image sync changes:", changed)


if __name__ == "__main__":
    main()
