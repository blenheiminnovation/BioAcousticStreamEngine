# BioAcoustic Stream Engine (BASE)

*Created by **David Green** — Head of Innovation and AI, Blenheim Palace*

A real-time bioacoustic monitoring platform for Blenheim Palace estate. Continuously streams live audio from field microphones, identifies species using AI classifiers, and logs every detection with confidence scores, timestamps, and call counts. Built to scale across birds, bats, insects, and soil acoustics.

This project was born from a belief that technology can bring people closer to the natural world. By making acoustic biodiversity monitoring open, accessible, and shareable, the goal is to engage more people with nature — learning together, sharing what we hear, and building a deeper collective understanding of the living world around us.

---

## Features

- **Live microphone streaming** — continuous audio capture with configurable chunk size; multiple concurrent microphones supported, each assigned to a different classifier
- **BirdNET identification** — powered by [BirdNET-Analyzer](https://github.com/kahst/BirdNET-Analyzer) via [birdnetlib](https://github.com/joeweiss/birdnetlib); identifies 6,000+ species
- **Bat detection** — powered by [BatDetect2](https://github.com/macaodha/batdetect2); 17 UK/European species; requires an ultrasonic microphone (≥192 kHz)
- **Scheduled listening** — automatically wakes and sleeps around dawn chorus, morning song, and dusk windows calculated from local sunrise/sunset
- **Adaptive scheduling** — if nocturnal species (owls, nightjars) are detected, a night window is automatically added
- **Detailed logging** — every detection logged with date, time, species, scientific name, confidence, and call number within the session
- **Session summaries** — per-window species totals with max and average confidence
- **Live MQTT streaming** — every detection published as JSON in real time; direct or bridge connection; configurable via web UI
- **Browser dashboard** — full web UI for live monitoring, schedule management, audio clips, reports, and settings
- **Extensible architecture** — insect and soil classifiers are structured and ready for model plug-ins

---

## Quick Start

The easiest way to install is with the provided script — it handles all system libraries, Python packages, the BuzzDetect bee model, and config files in one step:

```bash
git clone https://github.com/blenheiminnovation/BioAcousticStreamEngine.git
cd BioAcousticStreamEngine
bash install.sh
```

Then launch the web UI:

```bash
bash start_web.sh
```

A browser tab opens automatically at `http://localhost:8000`. Edit `config/settings.yaml` to set your recording location and active classifiers.

---

### Manual install

If you prefer to install step by step:

#### 1. System libraries

```bash
sudo apt-get install -y \
  libportaudio2 \
  libsndfile1 \
  python3-venv \
  python3-dev \
  git
```

> **Audio device listing** (web UI): also requires `pactl`, which ships with PipeWire/PulseAudio. Install with `sudo apt-get install -y pipewire-pulse` if not already present.

#### 2. Python environment

```bash
python3 -m venv .venv
.venv/bin/pip install -e "."
```

#### 3. Bee classifier model (BuzzDetect)

No action needed — if `bee` is active in `config/settings.yaml`, BASE downloads the BuzzDetect model automatically on first run (~16 MB, one-time).

> **Requires `git`** — the auto-download uses `git clone`. If `git` is not installed the bee classifier will be silently disabled rather than crash, but you will get no bee detections. Install it with:
> ```bash
> sudo apt-get install -y git
> ```

#### 4. Output directories and config

```bash
mkdir -p output/clips
cp config/settings.yaml.example config/settings.yaml
cp config/secrets.yaml.example config/secrets.yaml
```

Edit `config/settings.yaml` to set your location (latitude/longitude) and which classifiers to run.

#### 5. Run

```bash
# Launch the web UI (recommended)
bash start_web.sh

# Or use the command line:
.venv/bin/python -m ecoacoustics.main wake            # listen until Ctrl+C
.venv/bin/python -m ecoacoustics.main wake --duration 30  # listen for 30 min
.venv/bin/python -m ecoacoustics.main schedule        # run dawn/dusk schedule
.venv/bin/python -m ecoacoustics.main status          # today's summary
.venv/bin/python -m ecoacoustics.main list-devices    # list microphones
```

---

## Web UI

BioAcoustic Stream Engine (BASE) includes a browser-based dashboard for managing and monitoring the system without touching the command line.

```bash
.venv/bin/python -m ecoacoustics.main web
```

A browser tab opens automatically at `http://localhost:8000`. A desktop launcher is also provided — double-click `bioacoustic-stream-engine.desktop` to start.

### Pages

| Page | Features |
|---|---|
| **Dashboard** | Live detection feed, real-time VU meter, per-device start/stop controls, today's species count and call totals |
| **Schedule** | Today's listening windows, add/remove custom windows, assign classifiers and microphones per organism group |
| **Clips** | Browse saved audio clips by species and classifier, play in browser, delete clips |
| **Reports** | Date and species filtering, daily summary table, download detections/sessions as CSV, clear all logs |
| **Settings** | Recording location (name, lat/lon), MQTT broker configuration with connection test, classifier device assignment |

### Web command options

```bash
.venv/bin/python -m ecoacoustics.main web --port 8080   # change port
.venv/bin/python -m ecoacoustics.main web --no-browser  # don't auto-open browser
```

---

## Running 24/7 (Continuous Monitoring)

BASE is designed to run unattended around the clock. Follow these steps to keep it running reliably.

### 1. Enable autostart (already configured)

The web UI and pipeline autostart on login via a systemd user service. Verify it is enabled:

```bash
systemctl --user status bioacoustic-stream-engine
```

### 2. Enable linger — keep the service alive when logged out

By default, user services stop when you log out of the desktop. Enable linger so BASE keeps running regardless:

```bash
loginctl enable-linger $USER
```

### 3. Prevent the system from sleeping

```bash
# Stop the OS from suspending automatically
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target

# Prevent screen blanking (useful if monitoring the spectrogram)
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-timeout 0
gsettings set org.gnome.desktop.session idle-delay 0
```

### 4. Prevent lid close from suspending (laptops)

```bash
sudo sed -i 's/#HandleLidSwitch=suspend/HandleLidSwitch=ignore/' /etc/systemd/logind.conf
sudo sed -i 's/#HandleLidSwitchExternalPower=suspend/HandleLidSwitchExternalPower=ignore/' /etc/systemd/logind.conf
sudo systemctl restart systemd-logind
```

### 5. Keep it plugged in

Battery depletion will stop recording. If running on a laptop, connect AC power and set the power button action to **Do Nothing** in system settings.

### Verify end-to-end

After applying the above, reboot and confirm BASE is running without logging in:

```bash
systemctl --user is-active bioacoustic-stream-engine   # should print: active
```

---

## Commands

| Command | Description |
|---|---|
| `wake` | Start listening immediately. Optional `--duration MINUTES`. |
| `schedule` | Auto wake/sleep based on configured listening windows. |
| `status` | Display today's schedule and species detected so far. |
| `list-devices` | Print available audio input devices and their indices. |
| `web` | Launch the browser UI. Optional `--port` and `--no-browser`. |

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

## MQTT

Every detection is published to a local [Mosquitto](https://mosquitto.org/) broker in real time, enabling live integration with dashboards, alerting pipelines, Node-RED, Home Assistant, or any MQTT-compatible consumer.

### Setup

```bash
sudo apt-get install -y mosquitto mosquitto-clients
sudo systemctl enable --now mosquitto
```

### Topics

| Topic | Content |
|---|---|
| `bioacoustics/detections` | Every detection, all classifiers |
| `bioacoustics/detections/bird` | Bird detections only |
| `bioacoustics/detections/bat` | Bat detections only |
| `bioacoustics/detections/insect` | Insect detections only |
| `bioacoustics/detections/soil` | Soil acoustics detections only |

The topic prefix (`bioacoustics`) is configurable in `config/settings.yaml`.

### Payload

Each message is a JSON object:

```json
{
  "session_id": "a3f1b2c4",
  "window_name": "dawn_chorus",
  "date": "2026-05-01",
  "time": "05:23:11",
  "classifier": "bird",
  "species_common": "Robin",
  "species_scientific": "Erithacus rubecula",
  "confidence": 0.8731,
  "call_number_in_session": 3,
  "latitude": 51.8403,
  "longitude": -1.3625,
  "location_name": "Blenheim Palace",
  "device_name": "Built-in Microphone"
}
```

### Monitor live detections

```bash
mosquitto_sub -t "bioacoustics/#" -v
```

### Connection modes

#### Mode A — Bridge (recommended for cloud or public WiFi)

Run a local Mosquitto broker and configure it to bridge to a cloud broker such as EMQX Cloud. The Python code connects to `localhost` with no credentials; Mosquitto handles authentication to the remote broker transparently.

```yaml
# config/settings.yaml
mqtt:
  enabled: true
  host: "localhost"
  port: 1883
  topic_prefix: "bioacoustics"
```

See [Mosquitto bridge setup](#mosquitto-bridge-to-emqx-cloud) below for the broker-side config.

#### Mode B — Direct (fixed IP or local network)

Connect the Python code straight to a remote or local broker. Set `tls: true` when connecting to a TLS-secured broker (port 8883). Add credentials to `config/secrets.yaml` (see [Credentials](#credentials)).

```yaml
# config/settings.yaml
mqtt:
  enabled: true
  host: "your-broker-ip-or-hostname"
  port: 8883
  tls: true
  topic_prefix: "bioacoustics"
```

Set `enabled: false` to disable MQTT without removing the configuration.

### Credentials

Broker credentials are kept out of `settings.yaml` (which is committed to git) and stored in a local-only file instead.

```bash
cp config/secrets.yaml.example config/secrets.yaml
```

Edit `config/secrets.yaml` and fill in your username and password:

```yaml
mqtt:
  username: "your-username"
  password: "your-password"
```

`config/secrets.yaml` is listed in `.gitignore` and will never be committed. `config/secrets.yaml.example` is committed as a safe template.

In bridge mode (Mode A) credentials are not needed here — they live in the Mosquitto bridge config on the host machine, outside the repository.

### Mosquitto bridge to EMQX Cloud

Create `/etc/mosquitto/conf.d/emqx_bridge.conf`:

```
connection emqx-cloud
address your-broker.emqxsl.com:8883

bridge_cafile /etc/ssl/certs/ca-certificates.crt
bridge_tls_version tlsv1.3

remote_username your-username
remote_password your-password

topic bioacoustics/# out 0

cleansession true
start_type automatic
```

```bash
sudo systemctl restart mosquitto
```

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

mqtt:
  enabled: true
  host: "localhost"
  port: 1883
  topic_prefix: "bioacoustics"
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
│   ├── settings.yaml               # All configuration (safe to commit)
│   ├── secrets.yaml                # Broker credentials — gitignored, never committed
│   └── secrets.yaml.example        # Template for secrets.yaml
├── src/ecoacoustics/
│   ├── api/
│   │   ├── app.py                  # FastAPI application and WebSocket broadcast
│   │   ├── pipeline_manager.py     # Pipeline lifecycle management for web UI
│   │   ├── state.py                # Shared state across API routes
│   │   └── routes/
│   │       ├── status.py           # Pipeline start/stop, system status
│   │       ├── schedule.py         # Listening window CRUD
│   │       ├── detections.py       # Detection history and summary
│   │       ├── clips.py            # Audio clip library
│   │       ├── reports.py          # CSV downloads and log management
│   │       ├── devices.py          # Audio input device listing
│   │       └── settings.py         # Location, MQTT, classifier settings
│   ├── audio/
│   │   ├── capture.py              # Microphone stream → audio chunks
│   │   └── processor.py            # Resample + bandpass filter per classifier
│   ├── classifiers/
│   │   ├── base.py                 # BaseClassifier ABC and Detection dataclass
│   │   ├── bird.py                 # BirdNET via birdnetlib (active)
│   │   ├── bat.py                  # BatDetect2 — 17 UK/European species
│   │   ├── insect.py               # Orthoptera — wired for OrthopterOSS / OpenSoundscape
│   │   └── soil.py                 # Energy + spectral centroid baseline
│   ├── output/
│   │   ├── logger.py               # Console display + CSV writing
│   │   └── mqtt_publisher.py       # Publishes detections to MQTT broker
│   ├── web/
│   │   ├── index.html              # Single-page app shell
│   │   ├── style.css               # Dark nature-themed design system
│   │   └── app.js                  # Dashboard, schedule, clips, reports, settings
│   ├── pipeline.py                 # Orchestrates capture → classify → log
│   ├── scheduler.py                # Dawn/dusk window calculation and adaptation
│   ├── session.py                  # Per-session species call counting
│   └── main.py                     # CLI entry point (wake, schedule, status, web)
├── tests/
│   └── test_pipeline.py
├── start_web.sh                    # One-click web UI launcher
├── bioacoustic-stream-engine.desktop  # Desktop launcher
└── output/                         # Created on first run
    ├── detections.csv
    ├── sessions.csv
    ├── clips/                      # Per-species audio clip library
    └── known_species.json          # All-time species registry
```

---

## Adding a New Classifier

1. Add a section to `config/settings.yaml` with `sample_rate`, `min_confidence`, and optional `freq_min_hz` / `freq_max_hz`
2. Implement `load()` and `classify()` in `src/ecoacoustics/classifiers/<name>.py` inheriting from `BaseClassifier`
3. Register it in `src/ecoacoustics/classifiers/__init__.py`
4. Add the name to `classifiers.active` in `settings.yaml`

The pipeline will automatically set up the correct audio stream and frequency filter.

---

## Training a Custom Insect Classifier

The insect classifier ([insect.py](src/ecoacoustics/classifiers/insect.py)) accepts any [OpenSoundscape](https://opensoundscape.org/) `.model` file. The notebooks in [training/notebooks/](training/notebooks/) walk through the full pipeline — ECOSoundSet audio → labelled clips → trained ResNet18 → deployed in BASE.

### Why a separate environment

The BASE runtime (`.venv`) bundles `tensorflow-cpu` and `batdetect2`, which conflict with the `opensoundscape` + PyTorch stack used for training. A dedicated `.venv-training` keeps both working side-by-side without version conflicts.

### 1. Create the training environment

```bash
python3 -m venv .venv-training
.venv-training/bin/pip install --upgrade pip
.venv-training/bin/pip install \
    opensoundscape==0.10.2 \
    librosa \
    soundfile \
    scikit-learn \
    matplotlib \
    pandas \
    numpy \
    ipykernel \
    jupyter
```

Register it as a Jupyter kernel (this is what the notebooks call "Python (orthoptera-training)"):

```bash
.venv-training/bin/python -m ipykernel install \
    --user \
    --name orthoptera-training \
    --display-name "Python (orthoptera-training)"
```

In VS Code, open any notebook, click the kernel picker in the top-right, and select **Python (orthoptera-training)**.

### 2. Download training datasets

Install `zenodo_get` if not already available:

```bash
.venv-training/bin/pip install zenodo_get
```

Then fetch the datasets. **ECOSoundSet** (~125 GB) is the primary source — 200 European Orthoptera species with strong labels. **InsectSet459** (~68 GB) can supplement sparse species.

```bash
mkdir -p datasets/ecosoundset datasets/insectset459

cd datasets/ecosoundset
zenodo_get 15043892        # ECOSoundSet — Funosas et al. 2025

cd ../insectset459
zenodo_get 14056458        # InsectSet459 — Faiss et al. 2025

cd ../..
```

Downloads can take several hours. Run them in `tmux` or `screen` so they survive a disconnected terminal:

```bash
tmux new -s datasets
# run the two zenodo_get commands above, then Ctrl+B D to detach
```

### 3. Run the notebooks

Open the notebooks in order — each one builds on the last:

| Notebook | What it does |
|---|---|
| [`00_verify_setup.ipynb`](training/notebooks/00_verify_setup.ipynb) | Confirm all packages installed; optional WAV file smoke-test |
| [`01_explore_data.ipynb`](training/notebooks/01_explore_data.ipynb) | Inspect ECOSoundSet, class balance, spectrogram preview |
| [`02_prepare_labels.ipynb`](training/notebooks/02_prepare_labels.ipynb) | Build OpenSoundscape one-hot train/val/test CSVs |
| [`03_train_model.ipynb`](training/notebooks/03_train_model.ipynb) | Train ResNet18, evaluate on held-out test set, save model |

The trained model is saved to `models/orthoptera_uk.model`.

### 4. Activate the model in BASE

Edit `config/settings.yaml`:

```yaml
insect:
  model_path: "models/orthoptera_uk.model"
  min_confidence: 0.5
  clip_duration: 3.0

classifiers:
  active:
    - bird
    - insect   # add this line
```

Restart BASE — insect detections will appear in the live feed immediately.

---

## Roadmap

- [x] Bat classifier — BatDetect2, 17 UK/European species (requires ultrasonic microphone ≥192 kHz)
- [x] Web dashboard — live detections, schedule management, audio clips, reports, settings
- [x] MQTT live feed — direct and bridge connection modes, configurable via UI
- [x] Multi-microphone support — per-classifier device assignment
- [x] Bee buzz classifier — BuzzDetect v1.0.1 (YAMNet, 16 kHz; detects insect flight buzz)
- [x] Insect classifier — grasshoppers and bush crickets; ResNet18 v1 trained by Blenheim Palace Innovation on InsectSet459 + ECOSoundSet, 8 UK species
- [x] Soil Acoustic Index (SAI) — beta implementation using ACI + spectral entropy
- [x] Species activity heatmaps by time of day and season

---

## Dependencies

### System libraries (Linux)

| Library | Purpose | Install |
|---|---|---|
| `libportaudio2` | Audio capture runtime (sounddevice) | `apt-get install libportaudio2` |
| `libsndfile1` | Audio file I/O runtime (soundfile/librosa) | `apt-get install libsndfile1` |
| `python3-venv` | Python virtual environment support | `apt-get install python3-venv` |
| `python3-dev` | Python headers for compiled pip packages | `apt-get install python3-dev` |
| `pipewire-pulse` / `pulseaudio` | `pactl` command for audio device listing in web UI | `apt-get install pipewire-pulse` |
| `git` | Required to clone BuzzDetect bee model | `apt-get install git` |

### Python packages

| Package | Purpose |
|---|---|
| `sounddevice` | Microphone capture |
| `soundfile` | Audio file reading/writing |
| `birdnetlib` | BirdNET-Analyzer Python wrapper |
| `tensorflow-cpu` | TFLite runtime for BirdNET model |
| `batdetect2` | BatDetect2 PyTorch model |
| `librosa` | Audio resampling |
| `scipy` | Bandpass filtering |
| `numpy` | Numerical audio processing |
| `astral` | Sunrise/sunset calculation |
| `rich` | Terminal display |
| `PyYAML` | Configuration loading |
| `paho-mqtt` | MQTT client for live detection publishing |
| `fastapi` | REST API and WebSocket server for web UI |
| `uvicorn` | ASGI server |
| `websockets` | WebSocket support |
| `python-multipart` | File upload handling in web UI |

### External models (not on PyPI)

| Model | Classifier | How to install |
|---|---|---|
| [BuzzDetect v1.0.1](https://github.com/OSU-Bee-Lab/buzzdetect) | Bee | Downloaded automatically on first run (requires `git`). `install.sh` also handles this proactively. |
| BirdNET weights | Bird | Downloaded automatically by `birdnetlib` on first run |
| BatDetect2 weights | Bat | Downloaded automatically by `batdetect2` on first run |

---

## Licence

This project is released under the [MIT Licence](LICENSE).

BioAcoustic Stream Engine (BASE) was built at Blenheim Palace to advance open research into acoustic biodiversity monitoring. We believe this kind of tooling should be freely available to conservation practitioners, researchers, and developers everywhere. You are welcome to use, adapt, and build on this work — and we actively encourage contributions that extend coverage to new species groups, habitats, or classifier models.

If you use this project in your own work, a credit or citation is appreciated but not required.

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

### Contributors

This project was conceived by the Blenheim Palace Innovation Team, combining our own work with contributions from pre-trained models and open research. We are excited to engage others and to learn together more about our natural world.

Harry Hanson · Tawhid Shahrior · Dr. Matthias Rolf · Max Caminow · Dr. Dave Gasca · Arnaud Fontannaz · Filipe Salbany

---

### BuzzDetect

Bee buzz detection is powered by **BuzzDetect** (v1.0.1), developed by the [OSU Bee Lab](https://github.com/OSU-Bee-Lab) at Ohio State University.

> Hearon, L. et al. (2025).  
> **buzzdetect: An open-source tool for passive acoustic monitoring of pollinator activity.**  
> *Journal of Insect Science*, 25(6), ieaf104.  
> https://doi.org/10.1093/jisesa/ieaf104

- GitHub: [github.com/OSU-Bee-Lab/buzzdetect](https://github.com/OSU-Bee-Lab/buzzdetect)
- Uses YAMNet transfer learning to detect insect flight buzz (class `ins_buzz`) at 16 kHz
- Detects insect buzz presence/absence; does not identify species
- Can run concurrently with the bird classifier on the same microphone

---

### Orthoptera Classifier — OrthopterOSS

The insect classifier (`insect.py`) is built around the **OpenSoundscape** CNN framework and is designed to accept **OrthopterOSS** — the Orthoptera acoustic classifier referenced in:

> *Recent technological developments allow for passive acoustic monitoring of Orthoptera*  
> Scientia Entomologica, 2025  
> https://doi.org/10.1016/j.ecoinf.2025.xxx (ScienceDirect)

OrthopterOSS achieves **86.4% true positive rate across 17 Orthoptera species** and is expected to be publicly released in 2025. Once available, activation requires two steps:

**1. Install the model**

```bash
# Once OrthopterOSS is released:
pip install orthopteross
# Or download the model file directly from the OrthopterOSS GitHub release
```

**2. Configure BASE**

Edit `config/settings.yaml`:

```yaml
insect:
  model_path: "models/orthoptera.model"   # path to downloaded model file
  min_confidence: 0.5
  clip_duration: 3.0

classifiers:
  active:
    - bird
    - insect   # add this line
```

Detections will appear immediately in the live feed under the 🦗 Insects tab, with each species labelled as Grasshopper, Bush Cricket, or Cricket automatically.

**Target UK species** (subject to OrthopterOSS species list):

| Species | Common Name | Group |
|---|---|---|
| *Chorthippus brunneus* | Field Grasshopper | Grasshopper |
| *Chorthippus parallelus* | Meadow Grasshopper | Grasshopper |
| *Omocestus viridulus* | Common Green Grasshopper | Grasshopper |
| *Tettigonia viridissima* | Great Green Bush-cricket | Bush Cricket |
| *Roeseliana roeselii* | Roesel's Bush-cricket | Bush Cricket |
| *Pholidoptera griseoaptera* | Dark Bush-cricket | Bush Cricket |
| *Leptophyes punctatissima* | Speckled Bush-cricket | Bush Cricket |
| *Meconema thalassinum* | Oak Bush-cricket | Bush Cricket |
| *Gryllus campestris* | Field Cricket | Cricket |

**Alternative model sources** for training your own:
- [InsectSet459](https://zenodo.org/records/14056458) — 459 species, 310 Orthoptera, strong EU coverage (Faiss et al. 2025)
- [ECOSoundSet](https://doi.org/10.5281/zenodo.15043892) — 200 EU Orthoptera species, finely annotated (Funosas et al. 2025)

Both datasets work with OpenSoundscape's CNN training pipeline. Any `.model` file trained with OpenSoundscape will load directly into BASE.

---

### OpenSoundscape

The insect classifier is built on **OpenSoundscape**, an open-source bioacoustics framework developed by the [Kitzes Lab](https://www.kitzeslab.org/) at the University of Pittsburgh.

> Lapp, S., Rhinehart, T., Freeland, M., Alvarez, J., Diaz, J., Lin, T-Y., Kitzes, J. (2023).  
> **OpenSoundscape: An open-source bioacoustics analysis package for Python.**  
> *Methods in Ecology and Evolution*, 14(11), 2686–2698.  
> https://doi.org/10.1111/2041-210X.14196

- Website: [opensoundscape.org](https://opensoundscape.org)
- GitHub: [github.com/kitzeslab/opensoundscape](https://github.com/kitzeslab/opensoundscape)
- Provides the CNN model format, training pipeline, and inference engine used to train and run the Orthoptera classifier
- The `orthoptera_uk.model` shipped with BASE was trained using OpenSoundscape on ECOSoundSet data

---

### Inspiration

This project was inspired by the work and vision of **Dr. Curt Lamberth**, whose research into acoustic biodiversity monitoring provided the founding ideas behind this system.

---

*Blenheim Palace Innovation — BioAcoustic Stream Engine (BASE)*
