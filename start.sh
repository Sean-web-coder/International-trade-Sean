#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
command -v codex >/dev/null || { echo 'Install Node.js LTS, then npm install -g @openai/codex'; exit 1; }
codex login status || codex login
exec .venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
