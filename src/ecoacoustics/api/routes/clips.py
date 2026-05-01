"""API routes — audio clip library."""

import csv
import json
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()
_SETTINGS = Path("config/settings.yaml")


def _cfg() -> dict:
    with open(_SETTINGS) as f:
        return yaml.safe_load(f)


def _clips_dir() -> Path:
    return Path(_cfg().get("clips", {}).get("dir", "output/clips"))


def _species_classifier_map() -> dict[str, str]:
    """Build a species→classifier map from detections.csv, falling back to known_species.json."""
    cfg = _cfg()
    mapping: dict[str, str] = {}

    # Prefer detections.csv — always accurate and covers all historical data
    det_path = Path(cfg.get("output", {}).get("detections_csv", "output/detections.csv"))
    if det_path.exists():
        with open(det_path) as f:
            for row in csv.DictReader(f):
                name = row.get("species_common", "").strip()
                clf = row.get("classifier", "bird").strip()
                if name:
                    mapping[name] = clf
        return mapping

    # Fallback: known_species.json (only has classifier if set by new code)
    db_path = Path(cfg.get("clips", {}).get("species_db", "output/known_species.json"))
    if db_path.exists():
        with open(db_path) as f:
            db = json.load(f)
        for name, info in db.items():
            mapping[name] = info.get("classifier", "bird")

    return mapping


def _conf_from_path(path: Path) -> float:
    try:
        return int(path.stem.split("_conf")[-1]) / 100.0
    except (ValueError, IndexError):
        return 0.0


@router.get("/clips")
def list_species(classifier: str = None):
    clips_dir = _clips_dir()
    if not clips_dir.exists():
        return {"species": []}

    clf_map = _species_classifier_map()

    species_list = []
    for species_dir in sorted(clips_dir.iterdir()):
        if not species_dir.is_dir():
            continue
        clips = list(species_dir.glob("*.wav"))
        if not clips:
            continue
        name = species_dir.name.replace("_", " ")
        clf = clf_map.get(name, "bird")
        if classifier and classifier != clf:
            continue
        best = max(clips, key=_conf_from_path)
        species_list.append({
            "name": name,
            "dir": species_dir.name,
            "classifier": clf,
            "clip_count": len(clips),
            "best_confidence": round(_conf_from_path(best), 2),
        })

    return {"species": species_list}


@router.get("/clips/{species_dir}")
def list_clips(species_dir: str):
    clips_dir = _clips_dir() / species_dir
    if not clips_dir.exists():
        raise HTTPException(404, "Species not found")

    clips = []
    for wav in sorted(clips_dir.glob("*.wav"), reverse=True):
        parts = wav.stem.split("_")
        date_str = parts[0] if len(parts) > 0 else ""
        time_str = parts[1] if len(parts) > 1 else ""
        clips.append({
            "filename": wav.name,
            "date": f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}" if len(date_str) == 8 else "",
            "time": f"{time_str[:2]}:{time_str[2:4]}:{time_str[4:6]}" if len(time_str) == 6 else "",
            "confidence": round(_conf_from_path(wav), 2),
            "url": f"/api/clips/{species_dir}/{wav.name}/audio",
        })

    return {
        "species": species_dir.replace("_", " "),
        "clips": clips,
    }


@router.get("/clips/{species_dir}/{filename}/audio")
def stream_clip(species_dir: str, filename: str):
    path = _clips_dir() / species_dir / filename
    if not path.exists() or path.suffix != ".wav":
        raise HTTPException(404, "Clip not found")
    return FileResponse(str(path), media_type="audio/wav")


@router.delete("/clips/{species_dir}/{filename}")
def delete_clip(species_dir: str, filename: str):
    path = _clips_dir() / species_dir / filename
    if not path.exists():
        raise HTTPException(404, "Clip not found")
    path.unlink()
    return {"deleted": filename}
