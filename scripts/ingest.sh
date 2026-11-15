#!/usr/bin/env bash
# scripts/ingest — convert one course, lint it, and refresh index.org
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ $# -lt 1 ]]; then
  echo "Usage: ./scripts/ingest <domain>/<course> [--force] [--dry-run] [--math-format typst] [--exclude ...]" >&2
  exit 1
fi

COURSE="$1"
shift

# Extract --math-format if passed so lint checks the matching directory
MATH_FMT="latex"
ARGS=("$@")
for ((i=0; i<${#ARGS[@]}; i++)); do
  if [[ "${ARGS[$i]}" == "--math-format" && $((i+1)) -lt ${#ARGS[@]} ]]; then
    MATH_FMT="${ARGS[$((i+1))]}"
  elif [[ "${ARGS[$i]}" == --math-format=* ]]; then
    MATH_FMT="${ARGS[$i]#--math-format=}"
  fi
done

echo "==> Converting $COURSE (math: $MATH_FMT)..."
PYTHONPATH="$ROOT/scripts" python3 -m convert "$ROOT/$COURSE" "$@"

if [[ " $* " != *" --dry-run "* ]]; then
  echo "==> Linting $COURSE/org-$MATH_FMT..."
  python3 -m scripts.lint "$ROOT/$COURSE" --math-format "$MATH_FMT"

  echo "==> Updating project index.org..."
  python3 -m scripts.gen_project_index --root "$ROOT"
fi
