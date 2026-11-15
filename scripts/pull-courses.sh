#!/usr/bin/env bash
# pull-courses.sh — git pull all course repos in this directory
BASE="$(cd "$(dirname "$0")" && pwd)"
found=0
for dir in "$BASE"/*/; do
  if [[ -d "$dir/.git" ]]; then
    name="$(basename "$dir")"
    echo "Pulling $name…"
    git -C "$dir" pull --ff-only 2>&1 | tail -1
    found=$((found + 1))
  fi
done
[[ $found -eq 0 ]] && echo "No git repos found in $BASE"
