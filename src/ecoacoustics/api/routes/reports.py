"""API routes — reports and CSV downloads."""

import csv
import io
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

router = APIRouter()
_SETTINGS = Path("config/settings.yaml")


def _paths() -> tuple[Path, Path]:
    with open(_SETTINGS) as f:
        cfg = yaml.safe_load(f)
    out = cfg.get("output", {})
    return (
        Path(out.get("detections_csv", "output/detections.csv")),
        Path(out.get("sessions_csv", "output/sessions.csv")),
    )


@router.get("/reports/species")
def list_species(classifier: Optional[str] = Query(None)):
    """All unique species in detections.csv, optionally filtered by classifier."""
    det_path, _ = _paths()
    if not det_path.exists():
        return {"species": []}
    species: set[str] = set()
    with open(det_path) as f:
        for row in csv.DictReader(f):
            if classifier and row.get("classifier", "") != classifier:
                continue
            s = row.get("species_common", "").strip()
            if s:
                species.add(s)
    return {"species": sorted(species)}


@router.get("/reports/summary")
def summary_report(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    species: Optional[str] = Query(None),
    classifier: Optional[str] = Query(None),
):
    det_path, sess_path = _paths()
    date_from = date_from or (date.today() - timedelta(days=7)).strftime("%Y-%m-%d")
    date_to = date_to or date.today().strftime("%Y-%m-%d")

    # When filtering by species, read detections.csv (has species_common per row)
    # Otherwise read sessions.csv for aggregated daily totals
    if species or classifier:
        by_date: dict[str, dict] = {}
        if det_path.exists():
            with open(det_path) as f:
                for row in csv.DictReader(f):
                    if species and row.get("species_common", "") != species:
                        continue
                    if classifier and row.get("classifier", "") != classifier:
                        continue
                    d = row.get("date", "")
                    if not (date_from <= d <= date_to):
                        continue
                    if d not in by_date:
                        by_date[d] = {"date": d, "sessions": set(), "species": set(), "total_calls": 0}
                    by_date[d]["sessions"].add(row.get("session_id", ""))
                    by_date[d]["species"].add(row.get("species_common", ""))
                    by_date[d]["total_calls"] += 1
        rows = []
        for d, data in sorted(by_date.items()):
            rows.append({
                "date": d,
                "sessions": len(data["sessions"]),
                "species_count": len(data["species"]),
                "total_calls": data["total_calls"],
            })
    else:
        by_date = {}
        if sess_path.exists():
            with open(sess_path) as f:
                for row in csv.DictReader(f):
                    d = row.get("date", "")
                    if not (date_from <= d <= date_to):
                        continue
                    if d not in by_date:
                        by_date[d] = {"date": d, "sessions": 0, "species_set": set(), "total_calls": 0}
                    by_date[d]["sessions"] += 1
                    by_date[d]["species_set"].add(row.get("species", ""))
                    by_date[d]["total_calls"] += int(row.get("total_calls", 0))
        rows = []
        for d, data in sorted(by_date.items()):
            rows.append({
                "date": d,
                "sessions": data["sessions"],
                "species_count": len(data["species_set"]),
                "total_calls": data["total_calls"],
            })

    return {
        "date_from": date_from,
        "date_to": date_to,
        "species": species,
        "days": rows,
        "totals": {
            "sessions": sum(r["sessions"] for r in rows),
            "total_calls": sum(r["total_calls"] for r in rows),
        },
    }


@router.get("/reports/download/detections")
def download_detections(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    species: Optional[str] = Query(None),
    classifier: Optional[str] = Query(None),
):
    det_path, _ = _paths()
    date_from = date_from or ""
    date_to = date_to or "9999-99-99"

    output = io.StringIO()
    writer = None

    if det_path.exists():
        with open(det_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                d = row.get("date", "")
                if date_from and d < date_from:
                    continue
                if d > date_to:
                    continue
                if species and row.get("species_common", "") != species:
                    continue
                if classifier and row.get("classifier", "") != classifier:
                    continue
                if writer is None:
                    writer = csv.DictWriter(output, fieldnames=reader.fieldnames)
                    writer.writeheader()
                writer.writerow(row)

    output.seek(0)
    safe_species = f"_{species.replace(' ', '_')}" if species else ""
    filename = f"detections{safe_species}_{date_from or 'all'}_{date_to or 'all'}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/reports/download/sessions")
def download_sessions(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    species: Optional[str] = Query(None),
):
    _, sess_path = _paths()
    date_from = date_from or ""
    date_to = date_to or "9999-99-99"

    output = io.StringIO()
    writer = None

    if sess_path.exists():
        with open(sess_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                d = row.get("date", "")
                if date_from and d < date_from:
                    continue
                if d > date_to:
                    continue
                if species and row.get("species", "") != species:
                    continue
                if writer is None:
                    writer = csv.DictWriter(output, fieldnames=reader.fieldnames)
                    writer.writeheader()
                writer.writerow(row)

    output.seek(0)
    safe_species = f"_{species.replace(' ', '_')}" if species else ""
    filename = f"sessions{safe_species}_{date_from or 'all'}_{date_to or 'all'}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/reports/heatmap")
def heatmap(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    classifier: Optional[str] = Query(None),
):
    """Return detection counts bucketed by hour-of-day and month for heatmap rendering."""
    det_path, _ = _paths()
    date_from = date_from or ""
    date_to = date_to or "9999-99-99"

    # species -> hour (0-23) -> count
    by_hour: dict[str, list[int]] = defaultdict(lambda: [0] * 24)
    # species -> month (0-11) -> count
    by_month: dict[str, list[int]] = defaultdict(lambda: [0] * 12)
    classifiers_seen: set[str] = set()

    if det_path.exists():
        with open(det_path) as f:
            for row in csv.DictReader(f):
                d = row.get("date", "")
                if date_from and d < date_from:
                    continue
                if d > date_to:
                    continue
                clf = row.get("classifier", "")
                if classifier and clf != classifier:
                    continue
                species = row.get("species_common", "").strip()
                if not species:
                    continue
                classifiers_seen.add(clf)
                t = row.get("time", "00:00:00")
                hour = int(t.split(":")[0]) if t else 0
                month = int(d.split("-")[1]) - 1 if d and len(d) >= 7 else 0  # 0-indexed
                by_hour[species][hour] += 1
                by_month[species][month] += 1

    return {
        "by_hour": dict(by_hour),
        "by_month": dict(by_month),
        "classifiers": sorted(classifiers_seen),
        "date_from": date_from or None,
        "date_to": date_to if date_to != "9999-99-99" else None,
    }


@router.delete("/reports/logs")
def clear_logs():
    """Delete detections.csv and sessions.csv. Irreversible — UI must confirm first."""
    det_path, sess_path = _paths()
    cleared = []
    for p in [det_path, sess_path]:
        if p.exists():
            p.unlink()
            cleared.append(p.name)
    return {"cleared": cleared}
