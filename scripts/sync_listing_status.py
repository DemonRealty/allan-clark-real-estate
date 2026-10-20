#!/usr/bin/env python3
"""Conservative Independent Agent listing discovery and status sync.

Only classify links found inside clearly identified Currently Listed/Recently Sold
tab panels. Ambiguous links and missing listings never change published data.
Photographs are handled by the separate photo sync workflow.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from sync_property_photos import get_image_url, download_image, IMAGES

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/properties.json"
SOURCE = "https://independentagent.co.nz/team-member/allan-clark-297/"
HEADERS = {"User-Agent": "AllanClarkRealEstate/1.0 (approved listing synchronisation)"}
LINK_RE = re.compile(r"^/listing/([a-z0-9-]+)-(\d+)/?$", re.I)
STATUS_WORDS = {"for-sale": ("currently listed", "current listings"), "sold": ("recently sold",)}
MAX_NEW = 20

def normalized(value):
    return re.sub(r'[^a-z0-9]', '', value.lower())

def confirmed_address(html, url):
    soup = BeautifulSoup(html, 'html.parser')
    match = LINK_RE.match(urlparse(url).path)
    heading = soup.select_one('h1')
    if not match or not heading:
        return None
    title = heading.get_text(' ', strip=True)
    if normalized(title) != normalized(match.group(1)):
        return None
    if len(title) < 12 or len(title) > 110 or not re.search(r'\d', title):
        return None
    return title

def build_new_listing(session, url, status):
    response = session.get(url, timeout=30)
    response.raise_for_status()
    address = confirmed_address(response.text, url)
    if not address:
        print('Review required: heading does not match property URL:', url)
        return None
    image_url = get_image_url(response.text, url)
    if not image_url:
        print('Review required: no photograph:', url)
        return None
    data, extension = download_image(session, image_url)
    listing_id = LINK_RE.match(urlparse(url).path).group(2)
    IMAGES.mkdir(parents=True, exist_ok=True)
    filename = listing_id + extension
    destination = IMAGES / filename
    if not destination.exists() or destination.read_bytes() != data:
        destination.write_bytes(data)
    return {'url': url, 'address': address, 'status': status, 'verified': True,
            'verification_basis': 'Confirmed source status tab, matching detail heading and local photograph',
            'price': None, 'image': 'assets/property-photos/' + filename}



def listing_links(node):
    found = {}
    for a in node.select("a[href]"):
        url = urljoin(SOURCE, a["href"]).split("#")[0].split("?")[0]
        parsed = urlparse(url)
        if parsed.hostname not in ("independentagent.co.nz", "www.independentagent.co.nz"):
            continue
        m = LINK_RE.match(parsed.path)
        if m:
            found[m.group(2)] = url
    return found


def find_panels(soup):
    """Only use accessible tab-to-panel relations; never infer by link order."""
    panels = {"for-sale": {}, "sold": {}}
    for tab in soup.select('[role="tab"], a[href^="#"], button[aria-controls]'):
        label = tab.get_text(" ", strip=True).lower()
        status = next((s for s, labels in STATUS_WORDS.items() if label in labels), None)
        if not status:
            continue
        target = tab.get("aria-controls") or tab.get("data-bs-target") or tab.get("data-target") or tab.get("href", "")
        target = target.lstrip("#")
        if not target or not re.fullmatch(r"[A-Za-z0-9_-]+", target):
            continue
        panel = soup.find(id=target)
        if panel:
            panels[status].update(listing_links(panel))
    # Also support explicitly labelled tabpanels (without depending on order).
    for panel in soup.select('[role="tabpanel"]'):
        labelled_by = panel.get("aria-labelledby", "")
        tab = soup.find(id=labelled_by) if labelled_by else None
        label = tab.get_text(" ", strip=True).lower() if tab else panel.get("aria-label", "").lower()
        status = next((s for s, labels in STATUS_WORDS.items() if label in labels), None)
        if status:
            panels[status].update(listing_links(panel))
    return panels


def address_from_slug(url):
    slug = LINK_RE.match(urlparse(url).path).group(1)
    # Addresses from URL slugs are provisional; new records require human review.
    return slug.replace("-", " ").title()


def main():
    response = requests.get(SOURCE, headers=HEADERS, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    panels = find_panels(soup)
    conflicts = set(panels["for-sale"]) & set(panels["sold"])
    if conflicts:
        print("Ambiguous status for IDs:", sorted(conflicts))
        for key in conflicts:
            panels["for-sale"].pop(key, None)
            panels["sold"].pop(key, None)
    total = sum(len(x) for x in panels.values())
    print("Unambiguous tab listings:", {k: len(v) for k, v in panels.items()})
    if not total:
        print("No trustworthy tab-panel structure found; preserving existing listings.")
        return
    payload = json.loads(DATA.read_text(encoding="utf-8"))
    existing = {LINK_RE.match(urlparse(p["url"]).path).group(2): p for p in payload["properties"] if LINK_RE.match(urlparse(p.get("url", "")).path)}
    changed = False
    new_count = 0
    published_count = 0
    session = requests.Session()
    session.headers.update(HEADERS)
    for status, links in panels.items():
        for listing_id, url in links.items():
            if listing_id in existing:
                item = existing[listing_id]
                if item.get("status") != status:
                    print("Status change:", item["address"], item.get("status"), "->", status)
                    item["status"] = status
                    item["verification_basis"] = "Explicit Independent Agent tab panel"
                    changed = True
            elif new_count < MAX_NEW:
                new_count += 1
                try:
                    item = build_new_listing(session, url, status)
                except (requests.RequestException, ValueError, OSError) as exc:
                    print('Review required: property retrieval failed:', url, str(exc))
                    item = None
                if item is None:
                    item = {'url': url, 'address': address_from_slug(url), 'status': status,
                            'verified': False, 'verification_basis': 'Discovered; awaiting confirmed heading and photograph',
                            'price': None, 'image': None}
                else:
                    published_count += 1
                    print('Published verified new listing:', item['address'])
                payload['properties'].append(item)
                existing[listing_id] = item
                changed = True
    if changed:
        payload['last_verified'] = datetime.now(timezone.utc).date().isoformat()
        DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("New discoveries:", new_count, "Published:", published_count, "Data updated:", changed)


if __name__ == "__main__":
    main()
