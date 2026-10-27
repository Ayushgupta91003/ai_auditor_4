#!/usr/bin/env bash
# Run from the Nuvepro terminal: bash START_LAB.sh role|env|profile
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
mode="${1:-role}"
compose=(docker compose -f compose.yaml)
case "$mode" in
  role) ;;
  env) compose+=(-f compose.aws-env.yaml) ;;
  profile) compose+=(-f compose.aws-profile.yaml) ;;
  *) echo "Usage: bash START_LAB.sh role|env|profile"; exit 2 ;;
esac
python3 scripts/setup_lab.py
"${compose[@]}" up --build -d --wait
"${compose[@]}" ps
"${compose[@]}" exec -T agent python -m agent.lab_doctor
echo "Open lab port 8501. Next: bash CHECK_LAB.sh $mode"
echo "See START_HERE_NUVEPRO.md for model IDs, private tracing setup and acceptance steps."
