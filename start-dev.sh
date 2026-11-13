#!/usr/bin/env bash
# Start the Laravel dev server (composer run dev) and the Pi SMS bridge
# (scripts/send_to_pi.py) together. Ctrl+C stops both.
set -euo pipefail

cd "$(dirname "$0")"

# Tunables (override via environment, e.g. HTTP_PORT=8093 ./start-dev.sh)
HTTP_PORT="${HTTP_PORT:-8092}"
SERIAL_PORT="${SERIAL_PORT:-/dev/cu.usbmodem101}"
BAUD="${BAUD:-115200}"

mkdir -p storage/logs

echo "Starting camera stream (scripts/camera_stream.py) on http://0.0.0.0:8090..."
python3 scripts/camera_stream.py > storage/logs/camera_stream.log 2>&1 &
CAM_PID=$!
echo "Camera stream PID: ${CAM_PID}  (log: storage/logs/camera_stream.log)"

echo "Starting Pi SMS bridge on http://0.0.0.0:${HTTP_PORT} (serial ${SERIAL_PORT} @ ${BAUD})..."
python3 scripts/send_to_pi.py --serve \
    --http-port "${HTTP_PORT}" \
    --serial-port "${SERIAL_PORT}" \
    --baud "${BAUD}" \
    > storage/logs/pi-sms-bridge.log 2>&1 &
PI_PID=$!

echo "Starting Laravel dev server (composer run dev)..."
composer run dev > storage/logs/laravel-dev.log 2>&1 &
DEV_PID=$!

cleanup() {
    echo "Stopping..."
    kill "${CAM_PID}" "${PI_PID}" "${DEV_PID}" 2>/dev/null || true
    wait "${CAM_PID}" "${PI_PID}" "${DEV_PID}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Pi SMS bridge PID: ${PI_PID}  (log: storage/logs/pi-sms-bridge.log)"
echo "Laravel dev PID:   ${DEV_PID}  (log: storage/logs/laravel-dev.log)"
echo "Press Ctrl+C to stop both."

wait
