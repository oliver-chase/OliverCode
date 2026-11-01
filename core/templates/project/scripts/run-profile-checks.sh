#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROFILE="local-runtime"

usage() {
  cat <<EOF
Usage: $0 [--profile repo-contract-only|local-runtime|private-overlay]
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    # `shift 2` on a value-taking flag dies bare under set -e if the flag is
    # the last argument (nothing left to shift); check first for a clean FAIL.
    --profile) [[ $# -ge 2 ]] || { echo "FAIL --profile requires a value" >&2; exit 1; }; PROFILE="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "FAIL unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

case "$PROFILE" in
  repo-contract-only|local-runtime|private-overlay) ;;
  *) echo "FAIL invalid profile: $PROFILE" >&2; exit 1 ;;
esac

require_file() {
  local path="$1"
  [[ -f "$path" ]] || { echo "FAIL missing file: $path" >&2; exit 1; }
}

echo "== Public/private profile checks =="
echo "repo=$REPO_ROOT"
echo "profile=$PROFILE"

require_file "$REPO_ROOT/README.md"
require_file "$REPO_ROOT/.env.example"
require_file "$REPO_ROOT/scripts/bootstrap-profile.sh"
require_file "$REPO_ROOT/scripts/run-profile-checks.sh"

if [[ "$PROFILE" == "local-runtime" || "$PROFILE" == "private-overlay" ]]; then
  require_file "$REPO_ROOT/.env.local"
fi

if [[ "$PROFILE" == "private-overlay" ]]; then
  require_file "$REPO_ROOT/.secrets/README.md"
fi

if [[ -f "$REPO_ROOT/package.json" ]]; then
  if ! command -v python3 >/dev/null 2>&1; then
    echo "info: python3 unavailable in this runtime; cannot check for qa:hygiene script, skipped repo-native hygiene"
  elif python3 - "$REPO_ROOT/package.json" <<'PY'
import json, sys
data=json.load(open(sys.argv[1]))
sys.exit(0 if 'qa:hygiene' in data.get('scripts', {}) else 1)
PY
  then
    if command -v npm >/dev/null 2>&1; then
      (cd "$REPO_ROOT" && npm run -s qa:hygiene)
    else
      echo "info: qa:hygiene present but npm is unavailable in this runtime; skipped repo-native hygiene"
    fi
  else
    echo "info: package.json has no qa:hygiene script; skipped repo-native hygiene"
  fi
elif [[ -f "$REPO_ROOT/scripts/check-structure-contract.mjs" ]]; then
  node "$REPO_ROOT/scripts/check-structure-contract.mjs"
else
  echo "info: no repo-native hygiene hook detected; structural checks only"
fi

echo "PASS public/private profile checks"
