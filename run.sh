#!/usr/bin/env bash
set -e

echo "========================================================"
echo "  Vera - Research that knows you, and proves it."
echo "  Automated Test Build Launcher"
echo "========================================================"
echo ""

if [ ! -f .env ] && [ -f .env.example ]; then
    echo "[INFO] Creating .env from .env.example..."
    cp .env.example .env
    echo "[ACTION REQUIRED] Please edit .env and insert your TOKEN_FACTORY_API_KEY and TAVILY_API_KEY."
    echo ""
fi

if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3.10+ is required but not found in PATH."
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "[INFO] Provisioning virtual environment in .venv..."
    python3 -m venv .venv
    source .venv/bin/activate
    echo "[INFO] Installing backend dependencies..."
    pip install -r backend/requirements.txt
else
    source .venv/bin/activate
fi

echo "[INFO] Starting Vera unified server on http://127.0.0.1:8000 ..."
python3 -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
