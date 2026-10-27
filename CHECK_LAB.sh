#!/usr/bin/env bash
# Makes synthetic live Bedrock calls; run only in your approved lab account.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
mode="${1:-role}"
compose=(docker compose -f compose.yaml)
case "$mode" in
  role) ;;
  env) compose+=(-f compose.aws-env.yaml) ;;
  profile) compose+=(-f compose.aws-profile.yaml) ;;
  *) echo "Usage: bash CHECK_LAB.sh role|env|profile"; exit 2 ;;
esac
"${compose[@]}" exec -T agent python -m agent.lab_doctor
"${compose[@]}" exec -T agent python -m agent.bedrock_check
"${compose[@]}" exec -T agent python -m agent.protocol_smoke
echo "Connectivity passed. Complete the invoice, QA and correction checklist in the UI."
