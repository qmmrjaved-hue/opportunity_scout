#!/usr/bin/env bash
cd "$(dirname "$0")"
if [ ! -x venv/bin/python ]; then
    echo "OpportunityScout is not installed yet. Run ./setup.sh first."
    exit 1
fi
URL="http://localhost:8501"
echo "Starting OpportunityScout at $URL (press Ctrl+C to stop)"
( sleep 5; (command -v open >/dev/null && open "$URL") || (command -v xdg-open >/dev/null && xdg-open "$URL") ) >/dev/null 2>&1 &
venv/bin/python -m streamlit run app.py
