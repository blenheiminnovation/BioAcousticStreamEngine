# Bioacoustic Stream Engine

A real-time bioacoustic monitoring platform for Blenheim Palace estate. Continuously streams live audio from field microphones, identifies species using AI classifiers, and logs every detection with confidence scores, timestamps, and call counts. Built to scale across birds, bats, insects, and soil acoustics.

---

## Features

- **Live microphone streaming** — continuous audio capture with configurable chunk size
- **BirdNET identification** — powered by [BirdNET-Analyzer](https://github.com/kahst/BirdNET-Analyzer) via [birdnetlib](https://github.com/joeweiss/birdnetlib); identifies 6,000+ species
- **Scheduled listening** — automatically wakes and sleeps around dawn chorus, morning song, and dusk windows calculated from local sunrise/sunset
- **Adaptive scheduling** — if nocturnal species (owls, nightjars) are detected, a night window is automatically added
- **Detailed logging** — every detection logged with date, time, species, scientific name, confidence, and call number within the session
- **Session summaries** — per-window species totals with max and average confidence
- **Extensible architecture** — bat, insect, and soil classifiers are structured and ready for model plug-ins

---

## Quick Start

### 1. System dependency

```bash
sudo apt-get install -y libportaudio2
```

### 2. Python environment

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

### 3. Run

```bash
# Listen now until Ctrl+C
.venv/bin/python -m ecoacoustics.main wake

# Listen for a set duration
.venv/bin/python -m ecoacoustics.main wake --duration 30

# Run the automated dawn/dusk schedule
.venv/bin/python -m ecoacoustics.main schedule

# Show today's schedule and detection summary
.venv/bin/python -m ecoacoustics.main status

# List available microphone devices
.venv/bin/python -m ecoacoustics.main list-devices
```

---

## Commands

| Command | Description |
|---|---|
| `wake` | Start listening immediately. Optional `--duration MINUTES`. |
| `schedule` | Auto wake/sleep based on configured listening windows. |
| `status` | Display today's schedule and species detected so far. |
| `list-devices` | Print available audio input devices and their indices. |

---

## Output

Results are written to the `output/` directory (created automatically).

### `output/detections.csv` — one row per detection

| Column | Description |
|---|---|
| `session_id` | Unique 8-character ID for the listening session |
| `window_name` | Which schedule window (dawn_chorus, dusk, manual, …) |
| `date` | YYYY-MM-DD |
| `time` | HH:MM:SS |
| `classifier` | Model used (bird, bat, insect, soil) |
| `species_common` | Common name, e.g. *Robin* |
| `species_scientific` | Scientific name, e.g. *Erithacus rubecula* |
| `confidence` | BirdNET confidence score (0–1) |
| `call_number_in_session` | Running count of calls for this species this session |
| `latitude` / `longitude` | Recording location |

### `output/sessions.csv` — one row per species per session

| Column | Description |
|---|---|
| `session_id` | Links to detections.csv |
| `window_name` | Schedule window name |
| `date` / `session_start` / `session_end` | Timing |
| `duration_mins` | Length of the listening session |
| `species` | Common name |
| `total_calls` | Total detections of this species in the session |
| `max_confidence` | Highest confidence score seen |
| `avg_confidence` | Mean confidence across all calls |

---

## Configuration

Edit `config/settings.yaml` to adjust behaviour without touching code.

```yaml
bird:
  min_confidence: 0.35      # detections below this are ignored
  latitude: 51.8403         # used by BirdNET for species filtering
  longitude: -1.3625

schedule:
  timezone: "Europe/London"
  windows:
    - name: dawn_chorus
      anchor: sunrise       # sunrise | sunset | noon | fixed
      offset_mins: -30      # start 30 min before sunrise
      duration_mins: 150

  adaptive:
    nocturnal:              # triggers a 23:00 night window if detected
      - "Tawny Owl"
      - "Barn Owl"
```

To listen on a specific microphone, run `list-devices` and set `audio.device` to the device index.

---

## Listening Schedule (Blenheim Palace, example summer day)

| Window | Approx. start | Duration |
|---|---|---|
| Dawn chorus | 30 min before sunrise (~04:40) | 2.5 hours |
| Morning song | 90 min after sunrise (~07:10) | 1 hour |
| Dusk | 60 min before sunset (~20:00) | 1.5 hours |
| Night *(adaptive)* | 23:00 | 1 hour |

Times shift daily with sunrise/sunset. Run `status` to see exact times for today.

---

## Project Structure

```
├── config/
│   └── settings.yaml               # All configuration
├── src/ecoacoustics/
│   ├── audio/
│   │   ├── capture.py              # Microphone stream → audio chunks
│   │   └── processor.py           # Resample + bandpass filter per classifier
│   ├── classifiers/
│   │   ├── base.py                 # BaseClassifier ABC and Detection dataclass
│   │   ├── bird.py                 # BirdNET via birdnetlib (active)
│   │   ├── bat.py                  # Stub — plug in BatDetective2 or similar
│   │   ├── insect.py               # Stub — plug in AVES fine-tune or sklearn model
│   │   └── soil.py                 # Energy + spectral centroid baseline
│   ├── output/
│   │   └── logger.py               # Console display + CSV writing
│   ├── pipeline.py                 # Orchestrates capture → classify → log
│   ├── scheduler.py                # Dawn/dusk window calculation and adaptation
│   ├── session.py                  # Per-session species call counting
│   └── main.py                     # CLI entry point
├── tests/
│   └── test_pipeline.py
└── output/                         # Created on first run
    ├── detections.csv
    └── sessions.csv
```

---

## Adding a New Classifier

1. Add a section to `config/settings.yaml` with `sample_rate`, `min_confidence`, and optional `freq_min_hz` / `freq_max_hz`
2. Implement `load()` and `classify()` in `src/ecoacoustics/classifiers/<name>.py` inheriting from `BaseClassifier`
3. Register it in `src/ecoacoustics/classifiers/__init__.py`
4. Add the name to `classifiers.active` in `settings.yaml`

The pipeline will automatically set up the correct audio stream and frequency filter.

---

## Roadmap

- [ ] Bat classifier (requires ultrasonic microphone, ≥192 kHz)
- [ ] Insect classifier — grasshoppers and crickets (2–20 kHz)
- [ ] Soil acoustics classifier — earthworm and root activity (50–2000 Hz)
- [ ] Web dashboard for live detection display
- [ ] Species activity heatmaps by time of day and season
- [ ] Automated weekly detection reports

---

## Dependencies

| Package | Purpose |
|---|---|
| `sounddevice` | Microphone capture |
| `birdnetlib` | BirdNET-Analyzer Python wrapper |
| `tensorflow-cpu` | TFLite runtime for BirdNET model |
| `batdetect2` | BatDetect2 PyTorch model |
| `librosa` | Audio resampling |
| `scipy` | Bandpass filtering |
| `astral` | Sunrise/sunset calculation |
| `rich` | Terminal display |
| `PyYAML` | Configuration loading |

---

## Credits

### BirdNET-Analyzer

Bird species identification is powered by **BirdNET-Analyzer**, developed by the [K. Lisa Yang Center for Conservation Bioacoustics](https://www.birds.cornell.edu/ccb/) at the Cornell Lab of Ornithology and the [Chair of Media Informatics](https://www.tu-chemnitz.de/informatik/MedienInformatik/index.php) at Chemnitz University of Technology.

> Kahl, S., Wood, C. M., Eibl, M., & Klinck, H. (2021).  
> **BirdNET: A deep learning solution for avian diversity monitoring.**  
> *Ecological Informatics*, 61, 101236.  
> https://doi.org/10.1016/j.ecoinf.2021.101236

- GitHub: [github.com/kahst/BirdNET-Analyzer](https://github.com/kahst/BirdNET-Analyzer)
- Python wrapper: [github.com/joeweiss/birdnetlib](https://github.com/joeweiss/birdnetlib)
- Covers 6,000+ bird species worldwide; location and date filtering applied for Blenheim Palace (51.84°N, 1.36°W)

### BatDetect2

Bat species identification is powered by **BatDetect2**, developed by [Oisin Mac Aodha](https://homepages.inf.ed.ac.uk/omacaodha/) at the University of Edinburgh and collaborators at Caltech and University College London.

> Mac Aodha, O., Martinez Balvanera, S., Damstra, E., Cooke, C., Eichinski, P., Browning, E., Barataudm M., Boughey, K., Coles, R., Giacomini, G., & Jones, K. E. (2022).  
> **Towards a General Approach for Bat Echolocation Detection and Classification.**  
> *bioRxiv* 2022.12.14.520490.  
> https://doi.org/10.1101/2022.12.14.520490

- GitHub: [github.com/macaodha/batdetect2](https://github.com/macaodha/batdetect2)
- Covers 17 UK and European bat species; trained on British bat call datasets
- Requires an ultrasonic microphone (≥192 kHz) — see bat classifier documentation

---

### Inspiration

This project was inspired by the work and vision of **Dr. Curt Lamberth**, whose research into acoustic biodiversity monitoring provided the founding ideas behind this system.

---

*Blenheim Palace Innovation — Bioacoustic Stream Engine*
