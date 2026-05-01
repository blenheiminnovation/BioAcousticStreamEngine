"""API routes — detection history from CSV."""

import csv
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, Query

router = APIRouter()
_SETTINGS = Path("config/settings.yaml")


def _detections_path() -> Path:
    with open(_SETTINGS) as f:
        cfg = yaml.safe_load(f)
    return Path(cfg["output"].get("detections_csv", "output/detections.csv"))


@router.get("/detections")
def get_detections(
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    species: Optional[str] = Query(None),
    classifier: Optional[str] = Query(None),
    limit: int = Query(200, le=1000),
):
    path = _detections_path()
    if not path.exists():
        return {"detections": [], "total": 0}

    rows = []
    with open(path) as f:
        for row in csv.DictReader(f):
            if date_from and row.get("date", "") < date_from:
                continue
            if date_to and row.get("date", "") > date_to:
                continue
            if species and species.lower() not in row.get("species_common", "").lower():
                continue
            if classifier and row.get("classifier") != classifier:
                continue
            rows.append(row)

    rows.reverse()
    return {"detections": rows[:limit], "total": len(rows)}


@router.get("/detections/summary")
def get_summary(target_date: Optional[str] = Query(None, description="YYYY-MM-DD, default today")):
    path = _detections_path()
    today = target_date or date.today().strftime("%Y-%m-%d")

    if not path.exists():
        return {"date": today, "species": [], "total_calls": 0}

    counts: dict[str, dict] = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            if row.get("date") != today:
                continue
            name = row.get("species_common", "Unknown")
            if name not in counts:
                counts[name] = {
                    "species_common": name,
                    "species_scientific": row.get("species_scientific", ""),
                    "classifier": row.get("classifier", ""),
                    "calls": 0,
                    "max_confidence": 0.0,
                }
            counts[name]["calls"] += 1
            conf = float(row.get("confidence", 0))
            if conf > counts[name]["max_confidence"]:
                counts[name]["max_confidence"] = round(conf, 3)

    species_list = sorted(counts.values(), key=lambda x: -x["calls"])
    return {
        "date": today,
        "species": species_list,
        "total_calls": sum(s["calls"] for s in species_list),
        "species_count": len(species_list),
    }
