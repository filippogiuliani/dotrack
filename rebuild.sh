#!/bin/sh
# Rebuild and restart doTrack. Data stays in ./doTrack_data (mounted on /app/data).
set -e
cd "$(dirname "$0")"
if [ ! -f .env ]; then
  echo "The .env file is missing: copy .env.example to .env and configure it." >&2
  exit 1
fi
sudo docker build -t dotrack .
sudo docker rm -f dotrack 2>/dev/null || true
sudo docker run -d --restart unless-stopped -p 3001:3001 --env-file .env \
  -v "$(pwd)/doTrack_data:/app/data" --name dotrack dotrack
echo "doTrack started on http://localhost:3001"
