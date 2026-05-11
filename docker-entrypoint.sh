#!/usr/bin/env bash
# Bootstrap the container on first run: ensure config files exist by copying
# the .example templates if the user hasn't supplied their own.
set -euo pipefail

cd /app

if [ ! -f config/settings.yaml ]; then
    echo "[entrypoint] config/settings.yaml missing — seeding from settings.yaml.example"
    cp config/settings.yaml.example config/settings.yaml
fi

if [ ! -f config/secrets.yaml ]; then
    echo "[entrypoint] config/secrets.yaml missing — seeding from secrets.yaml.example"
    cp config/secrets.yaml.example config/secrets.yaml
fi

mkdir -p output/clips

exec "$@"
