#!/usr/bin/env bash
# OpportunityScout - one-time setup (macOS / Linux)
set -e
cd "$(dirname "$0")"

echo "=================================================="
echo "  OpportunityScout - one-time setup"
echo "=================================================="

PY=$(command -v python3 || command -v python || true)
if [ -z "$PY" ]; then
    echo "[ERROR] Python 3.10+ not found. Install it from https://www.python.org/downloads/ and rerun."
    exit 1
fi
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || {
    echo "[ERROR] Python 3.10 or newer is required (found $("$PY" --version))."; exit 1; }

if [ -x venv/bin/python ]; then
    echo "[1/4] Virtual environment already exists."
else
    echo "[1/4] Creating virtual environment..."
    "$PY" -m venv venv
fi

echo "[2/4] Installing Python packages - this can take a few minutes..."
venv/bin/python -m pip install --upgrade pip --quiet
venv/bin/python -m pip install -r requirements.txt

echo "[3/4] Installing the headless browser (Chromium)..."
venv/bin/python -m playwright install chromium

echo "[4/4] Gemini API key"
if [ -f .env ] && ! grep -q "your_gemini_api_key_here" .env; then
    echo "      Existing key found in .env - keeping it."
else
    echo "      Get a free key at https://aistudio.google.com/apikey"
    read -r -p "      Paste your key and press Enter (or just press Enter to add it later): " KEY || KEY=""
    if [ -z "$KEY" ]; then
        cp .env.example .env
        echo "      No key entered. Add it later by editing the .env file."
    else
        echo "GEMINI_API_KEY=$KEY" > .env
        echo "      Key saved to .env"
    fi
fi

chmod +x start.sh
echo
echo "Setup complete!  Run ./start.sh to launch the app."
