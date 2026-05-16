#!/usr/bin/env python3
"""
Download open-licensed stock images for UK species from Wikipedia/Wikimedia Commons,
and save attribution metadata to species_images/_credits.json.

Usage:
    python scripts/download_species_images.py

All images originate from Wikipedia articles and are sourced from Wikimedia Commons
under Creative Commons licences.  You can replace any image with your own photo:
just save it with the same filename in species_images/ and update _credits.json
(or use the Gallery → Manage page in the BASE web UI).

_credits.json format:
    {
      "european_robin.jpg": {
        "author":      "Francis C. Franklin",
        "license":     "CC BY-SA 3.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/3.0/",
        "source_url":  "https://commons.wikimedia.org/wiki/File:Erithacus..."
      }
    }
"""

import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

import requests

OUTPUT_DIR = Path(__file__).parent.parent / "src/ecoacoustics/web/species_images"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CREDITS_FILE = OUTPUT_DIR / "_credits.json"

WIKI_SUMMARY   = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
COMMONS_API    = "https://commons.wikimedia.org/w/api.php"
HEADERS        = {"User-Agent": "BASE/1.0 bioacoustics@blenheimpalace.com"}

# fmt: off
# Keys are BirdNET / classifier common names; values are Wikipedia article titles.
SPECIES: dict[str, str] = {
    # ── Birds ─────────────────────────────────────────────────────────────────
    "European Robin":              "European robin",
    "Eurasian Blue Tit":           "Blue tit",
    "Great Tit":                   "Great tit",
    "Coal Tit":                    "Coal tit",
    "Long-tailed Tit":             "Long-tailed tit",
    "Marsh Tit":                   "Marsh tit",
    "Eurasian Blackbird":          "Common blackbird",
    "Song Thrush":                 "Song thrush",
    "Mistle Thrush":               "Mistle thrush",
    "Fieldfare":                   "Fieldfare",
    "Redwing":                     "Redwing",
    "Common Nightingale":          "Common nightingale",
    "Eurasian Blackcap":           "Eurasian blackcap",
    "Garden Warbler":              "Garden warbler",
    "Common Chiffchaff":           "Common chiffchaff",
    "Willow Warbler":              "Willow warbler",
    "Goldcrest":                   "Goldcrest",
    "Eurasian Wren":               "Eurasian wren",
    "Dunnock":                     "Dunnock",
    "Common Chaffinch":            "Common chaffinch",
    "European Goldfinch":          "European goldfinch",
    "Eurasian Bullfinch":          "Eurasian bullfinch",
    "European Starling":           "Common starling",
    "House Sparrow":               "House sparrow",
    "Eurasian Nuthatch":           "Eurasian nuthatch",
    "Eurasian Treecreeper":        "Eurasian treecreeper",
    "Great Spotted Woodpecker":    "Great spotted woodpecker",
    "Green Woodpecker":            "European green woodpecker",
    "Tawny Owl":                   "Tawny owl",
    "Barn Owl":                    "Barn owl",
    "Little Owl":                  "Little owl",
    "European Nightjar":           "European nightjar",
    "Eurasian Sparrowhawk":        "Eurasian sparrowhawk",
    "Common Buzzard":              "Common buzzard",
    "Red Kite":                    "Red kite",
    "Eurasian Kestrel":            "Common kestrel",
    "Peregrine Falcon":            "Peregrine falcon",
    "Eurasian Hobby":              "Eurasian hobby",
    "Common Swift":                "Common swift",
    "Barn Swallow":                "Barn swallow",
    "Common House-Martin":         "Common house martin",
    "Common Cuckoo":               "Common cuckoo",
    "Eurasian Jackdaw":            "Western jackdaw",
    "Eurasian Jay":                "Eurasian jay",
    "Eurasian Magpie":             "Eurasian magpie",
    "Carrion Crow":                "Carrion crow",
    "Rook":                        "Rook (bird)",
    "Common Raven":                "Common raven",
    "Common Wood-Pigeon":          "Common wood pigeon",
    "Stock Dove":                  "Stock dove",
    "Eurasian Collared-Dove":      "Eurasian collared dove",
    "European Turtle-Dove":        "European turtle dove",
    "Ring-necked Pheasant":        "Common pheasant",
    "Red-legged Partridge":        "Red-legged partridge",
    "Spotted Flycatcher":          "Spotted flycatcher",
    "European Pied Flycatcher":    "European pied flycatcher",
    "Common Redstart":             "Common redstart",
    "Mandarin Duck":               "Mandarin duck",
    "Mallard":                     "Mallard",
    "Gray Heron":                  "Grey heron",
    "Mute Swan":                   "Mute swan",
    "Canada Goose":                "Canada goose",
    "Common Kingfisher":           "Common kingfisher",
    "Eurasian Skylark":            "Eurasian skylark",
    "Common Firecrest":            "Common firecrest",
    "Yellowhammer":                "Yellowhammer",
    "Reed Bunting":                "Reed bunting",
    "Eurasian Curlew":             "Eurasian curlew",
    "Common Ringed Plover":        "Common ringed plover",
    "Common Shelduck":             "Common shelduck",
    "Rock Pigeon":                 "Rock dove",
    # ── Grasshoppers & crickets ───────────────────────────────────────────────
    "Field Grasshopper":           "Common field grasshopper",
    "Meadow Grasshopper":          "Meadow grasshopper",
    "Common Green Grasshopper":    "Omocestus viridulus",
    "Great Green Bush-cricket":    "Great green bush-cricket",
    "Roesel's Bush-cricket":       "Roesel's bush cricket",
    "Dark Bush-cricket":           "Dark bush-cricket",
    "Speckled Bush-cricket":       "Speckled bush-cricket",
    "Field Cricket":               "Field cricket",
    "Oak Bush-cricket":            "Oak bush-cricket",
    # ── Bats ──────────────────────────────────────────────────────────────────
    "Common Pipistrelle":          "Common pipistrelle",
    "Soprano Pipistrelle":         "Soprano pipistrelle",
    "Nathusius' Pipistrelle":      "Nathusius's pipistrelle",
    "Brown Long-eared Bat":        "Brown long-eared bat",
    "Daubenton's Bat":             "Daubenton's bat",
    "Noctule":                     "Common noctule",
    "Serotine":                    "Serotine bat",
    "Barbastelle":                 "Western barbastelle",
    "Greater Horseshoe Bat":       "Greater horseshoe bat",
    "Lesser Horseshoe Bat":        "Lesser horseshoe bat",
    # ── Bees ──────────────────────────────────────────────────────────────────
    "Honey Bee":                   "Western honey bee",
    "Buff-tailed Bumblebee":       "Buff-tailed bumblebee",
    "Tree Bumblebee":              "Tree bumblebee",
    "Red-tailed Bumblebee":        "Red-tailed bumblebee",
    "White-tailed Bumblebee":      "Bombus lucorum",
    "Common Carder Bee":           "Common carder bee",
}
# fmt: on


def normalize(name: str) -> str:
    """Matches the JS _speciesImageUrl() normalization exactly.

    Apostrophes are stripped (not replaced) so "Roesel's" → "roesels"
    rather than "roesel_s".  All other non-alphanumeric runs become "_".
    """
    return re.sub(r"[^a-z0-9]+", "_", name.lower().replace("'", "")).strip("_")


def _filename_from_url(img_url: str) -> str:
    """Extract the Wikimedia Commons filename from a thumbnail URL."""
    parts = [p for p in urllib.parse.urlparse(img_url).path.split("/") if p]
    # Thumb URL: .../commons/thumb/h/hh/Filename.ext/NNpx-Filename.ext
    # Direct URL: .../commons/h/hh/Filename.ext
    return parts[-2] if "thumb" in parts else parts[-1]


def fetch_commons_credits(img_url: str) -> dict:
    """Query the Wikimedia Commons API for author and licence metadata."""
    wiki_filename = _filename_from_url(img_url)
    try:
        r = requests.get(
            COMMONS_API,
            params={
                "action": "query",
                "titles": f"File:{wiki_filename}",
                "prop": "imageinfo",
                "iiprop": "extmetadata",
                "format": "json",
            },
            headers=HEADERS,
            timeout=10,
        )
        data = r.json()
    except Exception:
        return {}

    pages = data.get("query", {}).get("pages", {})
    page = next(iter(pages.values()), {})
    meta = (page.get("imageinfo") or [{}])[0].get("extmetadata", {})

    raw_artist = meta.get("Artist", {}).get("value", "")
    author = re.sub(r"<[^>]+>", "", raw_artist).strip() or "Unknown"

    license_short = meta.get("LicenseShortName", {}).get("value", "")
    license_url   = meta.get("LicenseUrl",       {}).get("value", "")

    return {
        "author":      author,
        "license":     license_short,
        "license_url": license_url,
        "source_url":  f"https://commons.wikimedia.org/wiki/File:{wiki_filename}",
    }


def fetch_image_url(wiki_title: str) -> str | None:
    url = WIKI_SUMMARY.format(title=requests.utils.quote(wiki_title))
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
    except requests.RequestException as exc:
        print(f"    network error: {exc}")
        return None
    if r.status_code != 200:
        print(f"    Wikipedia returned {r.status_code} for {wiki_title!r}")
        return None
    data = r.json()
    thumb = data.get("thumbnail") or data.get("originalimage")
    return thumb["source"] if thumb else None


def load_credits() -> dict:
    if CREDITS_FILE.exists():
        try:
            return json.loads(CREDITS_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_credits(credits: dict) -> None:
    CREDITS_FILE.write_text(json.dumps(credits, indent=2, ensure_ascii=False))


def download_one(common_name: str, wiki_title: str, credits: dict) -> bool:
    filename = normalize(common_name) + ".jpg"
    dest = OUTPUT_DIR / filename

    if dest.exists() and filename in credits:
        print(f"  — {filename:<44} already exists (with credits)")
        return True

    fetch_img = not dest.exists()
    if fetch_img:
        print(f"  ↓ {common_name:<42} ({wiki_title})")
    else:
        print(f"  ℹ {common_name:<42} fetching credits only")

    img_url = fetch_image_url(wiki_title)
    if not img_url:
        return False

    if fetch_img:
        try:
            r = requests.get(img_url, headers=HEADERS, timeout=15)
        except requests.RequestException as exc:
            print(f"    download error: {exc}")
            return False
        if r.status_code != 200:
            print(f"    image download failed ({r.status_code})")
            return False
        dest.write_bytes(r.content)
        print(f"    saved {filename}  ({len(r.content) // 1024} KB)")

    if filename not in credits:
        time.sleep(0.2)
        credit = fetch_commons_credits(img_url)
        if credit.get("author"):
            credits[filename] = credit
            print(f"    credited: {credit['author']} / {credit['license']}")
        else:
            print(f"    no credit metadata found")

    return True


def main() -> None:
    print(f"Saving images to: {OUTPUT_DIR}\n")
    credits = load_credits()
    ok = skip = fail = 0

    for common_name, wiki_title in SPECIES.items():
        filename = normalize(common_name) + ".jpg"
        dest = OUTPUT_DIR / filename
        if dest.exists() and filename in credits:
            skip += 1
            print(f"  — {filename:<44} already exists (with credits)")
            continue

        success = download_one(common_name, wiki_title, credits)
        if success:
            ok += 1
        else:
            fail += 1
        save_credits(credits)   # save after each so a crash doesn't lose progress
        time.sleep(0.35)

    save_credits(credits)
    print(f"\nDone.  {ok} processed · {skip} already complete · {fail} failed")
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
