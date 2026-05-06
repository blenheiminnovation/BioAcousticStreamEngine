#!/usr/bin/env bash
# Ecoacoustics — one-shot install script for Linux (Ubuntu/Debian/Raspberry Pi OS)
# Run from the project root:  bash install.sh
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*"; exit 1; }
step() { echo -e "\n${GREEN}▶${NC} $*"; }

cd "$(dirname "$0")"

# ── 1. System dependencies ────────────────────────────────────────────────────
step "Checking system dependencies"

if ! dpkg -l libportaudio2 &>/dev/null; then
  warn "libportaudio2 not found — installing (requires sudo)"
  sudo apt-get install -y libportaudio2 portaudio19-dev
fi
ok "libportaudio2 present"

# pactl is used by the web UI for audio device enumeration
if ! command -v pactl &>/dev/null; then
  warn "pactl not found — installing pipewire-pulse (requires sudo)"
  sudo apt-get install -y pipewire-pulse
fi
ok "pactl present"

# ── 2. Python virtual environment ─────────────────────────────────────────────
step "Setting up Python environment"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  ok "Created .venv"
else
  ok ".venv already exists"
fi

.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -e "." --quiet
ok "Python packages installed"

# ── 3. BuzzDetect (bee classifier model) ─────────────────────────────────────
step "Setting up BuzzDetect bee model"

BUZZ_DIR="external/buzzdetect"
if [ ! -d "$BUZZ_DIR" ]; then
  if ! command -v git &>/dev/null; then
    err "git is required to download BuzzDetect. Install it with: sudo apt-get install git"
  fi
  mkdir -p external
  git clone --depth 1 --branch v1.0.1 \
    https://github.com/OSU-Bee-Lab/buzzdetect.git "$BUZZ_DIR"
  ok "BuzzDetect cloned to $BUZZ_DIR"
else
  ok "BuzzDetect already present at $BUZZ_DIR"
fi

# ── 4. Output directories ─────────────────────────────────────────────────────
step "Creating output directories"
mkdir -p output/clips
ok "output/ ready"

# ── 5. Configuration files ────────────────────────────────────────────────────
step "Checking configuration files"

if [ ! -f "config/settings.yaml" ]; then
  cp config/settings.yaml.example config/settings.yaml
  ok "Created config/settings.yaml from example — edit it to set your location and preferences"
else
  ok "config/settings.yaml already exists"
fi

if [ ! -f "config/secrets.yaml" ]; then
  cp config/secrets.yaml.example config/secrets.yaml
  ok "Created config/secrets.yaml from example — add MQTT credentials if needed"
else
  ok "config/secrets.yaml already exists"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  Installation complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  Next steps:"
echo "    1. Edit config/settings.yaml — set your location (lat/lon) and active classifiers"
echo "    2. Edit config/secrets.yaml  — add MQTT credentials if using the broker"
echo "    3. Run the web UI:"
echo "         bash start_web.sh"
echo "       or listen immediately:"
echo "         .venv/bin/python -m ecoacoustics.main wake"
echo ""
echo "  List available microphones:"
echo "    .venv/bin/python -m ecoacoustics.main list-devices"
echo ""
