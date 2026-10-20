#!/usr/bin/env python3
"""Read-only discovery of Allan Clark's public listing cards.
Does not update the live website. Run in GitHub Actions or locally.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup

SOURCE = "https://independentagent.co.nz/team-member/allan-clark-297/"
OUT = Path("listing-sync-preview.json")
HEADERS = {"User-Agent": "AllanClarkListingPreview/0.1 (website integration feasibility check)"}


def main():
    response = requests.get(SOURCE, headers=HEADERS, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    # Collect likely property links for inspection. Do not infer a listing's
    # active/sold status until the source DOM or API can be verified.
    candidates = []
    seen = set()
    for a in soup.select("a[href]"):
        href = urljoin(SOURCE, a.get("href", ""))
        url = urlparse(href)
        if url.netloc not in {"independentagent.co.nz", "www.independentagent.co.nz"}:
            continue
        if not re.search(r"/(property|listing|residential|buy|sold)[/-]", url.path, re.I):
            continue
        href = href.split("#")[0]
        if href in seen:
            continue
        seen.add(href)
        img = a.find("img")
        parent = a.find_parent(["article", "li", "div"])
        surrounding = parent.get_text(" ", strip=True)[:500] if parent else ""
        candidates.append({
            "url": href,
            "link_text": a.get_text(" ", strip=True)[:180],
            "surrounding_text": surrounding,
            "image": urljoin(SOURCE, img.get("src", "")) if img and img.get("src") else None,
        })
    result = {
        "source": SOURCE,
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "http_status": response.status_code,
        "page_title": soup.title.get_text(" ", strip=True) if soup.title else "",
        "candidate_property_links": candidates,
        "candidate_count": len(candidates),
        "note": "Discovery only: property status and accuracy require manual verification before publishing.",
    }
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Found {len(candidates)} candidate links; wrote {OUT}")
    if not candidates:
        print("No matching links: source may use dynamic rendering or different URL patterns.")


if __name__ == "__main__":
    main()
