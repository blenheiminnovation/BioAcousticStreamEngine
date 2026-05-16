"""
Gallery management API — image listing, credit editing, and image upload.

Images live in src/ecoacoustics/web/species_images/ and are served statically.
Credits are stored alongside them in _credits.json which is easy to hand-edit
or update via the Gallery → Manage page in the web UI.
"""

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

router = APIRouter()

_IMAGES_DIR   = Path(__file__).parent.parent.parent / "web/species_images"
_CREDITS_FILE = _IMAGES_DIR / "_credits.json"
_ALLOWED_MIME  = {"image/jpeg", "image/png", "image/webp"}
_ALLOWED_EXT   = {".jpg", ".jpeg", ".png", ".webp"}


def _load_credits() -> dict[str, Any]:
    if _CREDITS_FILE.exists():
        try:
            return json.loads(_CREDITS_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_credits(credits: dict) -> None:
    _CREDITS_FILE.write_text(json.dumps(credits, indent=2, ensure_ascii=False))


def _normalize_key(name: str) -> str:
    """'Eurasian Blue Tit' → 'eurasian_blue_tit'  (matches JS _speciesImageUrl)."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower().replace("'", "")).strip("_")


class CreditPayload(BaseModel):
    author:      str = ""
    license:     str = ""
    license_url: str = ""
    source_url:  str = ""


@router.get("/gallery")
def list_gallery_images():
    """Return all installed species images with their credit metadata."""
    credits = _load_credits()
    images = []
    for path in sorted(_IMAGES_DIR.glob("*.jpg")) + sorted(_IMAGES_DIR.glob("*.png")):
        if path.stem.startswith("_"):
            continue
        filename = path.name
        images.append({
            "key":      path.stem,
            "filename": filename,
            "url":      f"/species_images/{filename}",
            **credits.get(filename, {}),
        })
    return {"images": images}


@router.put("/gallery/{key}/credits")
def update_credits(key: str, payload: CreditPayload):
    """Update attribution metadata for one image."""
    credits = _load_credits()
    # Find the actual filename on disk for this key (could be .jpg or .png)
    matches = list(_IMAGES_DIR.glob(f"{key}.*"))
    matches = [m for m in matches if m.suffix.lower() in _ALLOWED_EXT]
    if not matches:
        raise HTTPException(status_code=404, detail=f"No image found for key '{key}'")
    filename = matches[0].name
    credits[filename] = payload.model_dump()
    _save_credits(credits)
    return {"ok": True, "filename": filename}


@router.post("/gallery/{key}/image")
async def upload_image(key: str, file: UploadFile = File(...)):
    """Replace the image for a species with an uploaded file.

    The key should be the normalised species name (e.g. 'european_robin').
    Accepts JPEG, PNG, or WebP.  The existing file is replaced in-place so
    any credits already stored are preserved — update them separately if needed.
    """
    if file.content_type not in _ALLOWED_MIME:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported image type '{file.content_type}'. Use JPEG, PNG, or WebP.",
        )

    # Validate key is safe (no path traversal)
    if not re.fullmatch(r"[a-z0-9_]+", key):
        raise HTTPException(status_code=400, detail="Invalid species key")

    ext = {
        "image/jpeg": ".jpg",
        "image/png":  ".png",
        "image/webp": ".webp",
    }[file.content_type]

    # Remove any old file for this key regardless of extension
    for old in _IMAGES_DIR.glob(f"{key}.*"):
        if old.suffix.lower() in _ALLOWED_EXT:
            old.unlink(missing_ok=True)

    dest = _IMAGES_DIR / f"{key}{ext}"
    dest.write_bytes(await file.read())

    return {"ok": True, "url": f"/species_images/{dest.name}"}
