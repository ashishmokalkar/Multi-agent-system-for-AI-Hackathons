#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ! -f "$project_root/frontend/dist/index.html" ]]; then
  echo "Frontend is not built. Run: cd frontend && npm install && npm run build" >&2
  exit 2
fi
export PYTHONPATH="$project_root/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m audio_competition_agents --mode mock serve --host 127.0.0.1 --port 8765
