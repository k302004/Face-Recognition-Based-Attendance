#!/usr/bin/env bash
set -euo pipefail

sudo apt update
sudo apt install -y python3-venv python3-dev build-essential cmake libopenblas-dev liblapack-dev libjpeg-dev
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if [ ! -f config.json ]; then
	cp config.example.json config.json
fi
mkdir -p known_faces
sudo cp attendance-client.service /etc/systemd/system/attendance-client.service
sudo systemctl daemon-reload
sudo systemctl enable attendance-client
echo "Setup complete. Edit config.json and add one face image per student ID to known_faces/."
echo "After configuration, start scanning with: sudo systemctl start attendance-client"