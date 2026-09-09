"""Scrape the Bellhaven Senior Living website: community directory (paginated)
plus each community detail page. Output: data/website_locations.json."""
import json
import os
import re

import requests
from bs4 import BeautifulSoup

from .config import API_BASE, DATA_DIR

UA = {"User-Agent": "bellhaven-sync/1.0 (CRM reconciliation pipeline)"}


def _get(path: str) -> BeautifulSoup:
    r = requests.get(f"{API_BASE}{path}", headers=UA, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def scrape() -> list[dict]:
    # 1. Collect community links from the homepage AND the paginated
    # directory. They disagree: the homepage features Bellhaven Meadows of
    # Findlay ("new this year") which the directory does not list — that is
    # the homepage's "35 communities" vs the directory's 34.
    slugs = []
    home = _get("/")
    slugs += [a["href"] for a in home.select('a[href^="/communities/"]')]
    page = 1
    while True:
        soup = _get(f"/communities?page={page}")
        page_links = [a["href"] for a in soup.select('a[href^="/communities/"]')]
        new = [s for s in page_links if s not in slugs]
        if not new:
            break
        slugs.extend(new)
        page += 1
        if page > 10:  # safety
            break

    # 2. Parse each community detail page.
    locations = []
    for slug in slugs:
        soup = _get(slug)
        text = [t.strip() for t in soup.stripped_strings]
        try:
            i = text.index("Address")
            name = text[i - 1]
            street = text[i + 1]
            m = re.match(r"^(.*),\s+([A-Z]{2})\s+(\d{5})", text[i + 2])
            city, state, zip_ = m.group(1), m.group(2), m.group(3)
            j = text.index("Care Offerings")
            k = text.index("Administrator")
            care = text[j + 1:k]
            phone = text[text.index("Phone") + 1]
        except (ValueError, AttributeError) as e:
            raise ValueError(f"Unexpected page layout at {slug}: {e}") from e
        locations.append({
            "slug": slug.rsplit("/", 1)[-1],
            "name": name,
            "street": street,
            "city": city,
            "state": state,
            "zip": zip_,
            "care": care,
            "phone": phone,
        })

    os.makedirs(DATA_DIR, exist_ok=True)
    out = os.path.join(DATA_DIR, "website_locations.json")
    with open(out, "w") as f:
        json.dump(locations, f, indent=2)

    # 3. Count check: homepage marketing claim vs directory reality.
    home = _get("/")
    claim = re.search(r"serve (\d+) communities", home.get_text(" ", strip=True))
    claim_n = int(claim.group(1)) if claim else None
    print(f"[scraper] {len(locations)} communities scraped from directory "
          f"(homepage claims {claim_n}) -> {out}")
    if claim_n and claim_n != len(locations):
        print(f"[scraper] NOTE: homepage claims {claim_n} but directory lists "
              f"{len(locations)} — flagged in writeup")
    return locations


if __name__ == "__main__":
    scrape()
