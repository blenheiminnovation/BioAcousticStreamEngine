#!/bin/bash
# Launch BASE in kiosk mode.
# Starts the web server if it is not already running, waits for it to be
# ready, then opens Chrome full-screen with no browser chrome.

cd "$(dirname "$0")"

# Start the server only if nothing is already on port 8000
if ! lsof -ti:8000 > /dev/null 2>&1; then
    .venv/bin/python -m ecoacoustics.main web &
    # Wait up to 15 s for the server to respond
    for i in $(seq 1 15); do
        sleep 1
        if curl -sf http://localhost:8000 > /dev/null 2>&1; then
            break
        fi
    done
fi

exec google-chrome \
    --kiosk \
    --no-first-run \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-restore-session-state \
    --disable-translate \
    --noerrdialogs \
    http://localhost:8000
