#!/usr/bin/env bash
# SRS Solar Daily Log - Linux Production Service Runner
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

export PORT="${PORT:-8000}"
export TIMEZONE="${TIMEZONE:-Asia/Kolkata}"
export APP_ENV="${APP_ENV:-production}"

echo "========================================================"
echo "SRS Solar Daily Log - M/s. SRS KUMARAN INDIA PVT LTD"
echo "Antichettipalayam 1 MW Solar Plant"
echo "========================================================"

# Activate virtual environment if present
if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
fi

# Initialize database schema and seeds
echo "Initializing database..."
python3 -m app.cli init-db

echo "Starting SRS Solar Web Server on http://127.0.0.1:${PORT}..."
exec python3 -m app.web.app
