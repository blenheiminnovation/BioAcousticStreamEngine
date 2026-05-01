#!/bin/bash
# Launch the Bioacoustic Stream Engine web UI.
# Run from the project root directory.

cd "$(dirname "$0")"
.venv/bin/python -m ecoacoustics.main web "$@"
