#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

if [ -z "${OPENAI_API_KEY:-}" ] && [ ! -f ".streamlit/secrets.toml" ]; then
  echo "OPENAI_API_KEY is not set. You can still launch the app and paste a key into the sidebar."
fi

streamlit run app.py
