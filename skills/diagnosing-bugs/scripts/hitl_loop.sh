#!/usr/bin/env bash
# Walk a person through a manual repro, one step at a time, then ask whether the symptom showed.
#
# Usage: hitl_loop.sh STEPS_FILE
#
# STEPS_FILE holds one step per line. Blank lines and lines starting with # are skipped.
# Each step is printed, and the script waits for the person to do it and press Enter.
# After the last step it asks whether the symptom showed.
#
# Exit codes: 0 green (symptom absent), 1 red (symptom reproduced), 2 usage error, quit or no verdict.
#
# Secrets stay off the screen: every environment variable named in HITL_REDACT (space-separated)
# has its value replaced with <REDACTED> wherever a step is shown.
set -u

if [[ $# -ne 1 || ! -r "$1" ]]; then
  echo "Usage: hitl_loop.sh STEPS_FILE" >&2
  exit 2
fi

steps=()
while IFS= read -r line || [[ -n "$line" ]]; do
  [[ -z "$line" || "$line" == \#* ]] && continue
  steps+=("$line")
done < "$1"

if [[ ${#steps[@]} -eq 0 ]]; then
  echo "hitl_loop: $1 has no steps" >&2
  exit 2
fi

redact() {
  local text="$1" name value
  for name in ${HITL_REDACT:-}; do
    value="${!name:-}"
    [[ -n "$value" ]] && text="${text//"$value"/<REDACTED>}"
  done
  printf '%s' "$text"
}

n=0
for step in "${steps[@]}"; do
  n=$((n + 1))
  printf 'Step %d: %s\n' "$n" "$(redact "$step")"
  printf 'Do it, then press Enter (q to quit): '
  read -r answer || answer=q
  if [[ "$answer" == q* ]]; then
    echo "Stopped at step $n."
    exit 2
  fi
done

printf 'Did the symptom show? [y/n]: '
read -r verdict || verdict=""
case "$verdict" in
  y*|Y*) echo "red: symptom reproduced"; exit 1 ;;
  n*|N*) echo "green: symptom absent"; exit 0 ;;
  *) echo "hitl_loop: no verdict; answer y or n" >&2; exit 2 ;;
esac
