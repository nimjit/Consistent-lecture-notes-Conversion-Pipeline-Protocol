#!/usr/bin/env bash
# scripts/sync — idempotently convert, lint, and index all courses in the wiki
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

MATH_FMT="latex"
FORCE=0
DRY_RUN=""
WARN_STRICT=""
PULL=0
FILTER=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --math-format)
      MATH_FMT="$2"
      shift 2
      ;;
    --math-format=*)
      MATH_FMT="${1#--math-format=}"
      shift
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --dry-run)
      DRY_RUN="--dry-run"
      shift
      ;;
    --warn-strict)
      WARN_STRICT="--warn-strict"
      shift
      ;;
    --pull)
      PULL=1
      shift
      ;;
    -h|--help)
      cat <<'EOF'
Usage: ./scripts/sync [FILTER] [OPTIONS]

Walks all <domain>/<course>/ directories (or only those matching FILTER,
e.g. 'cs' or 'cs/my-course'):
  - Skips courses whose org-latex/ already exists and passes scripts.lint
  - Re-converts courses that are missing org-latex/ or fail scripts.lint
  - Continues past individual course errors and prints a summary at the end
  - Regenerates root index.org

Options:
  --pull                 git pull --ff-only in source/ or markdown/ before converting
  --force                Re-convert all courses even if already lint-clean
  --dry-run              Preview actions in staging without writing changes
  --warn-strict          Treat lint warnings as errors when checking existing builds
  --math-format FORMAT   'latex' (default) or 'typst'
EOF
      exit 0
      ;;
    -*)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
    *)
      FILTER="${1%/}"
      shift
      ;;
  esac
done

SKIPPED=()
CONVERTED=()
FAILED=()
NO_SOURCE=()

for domain_dir in "$ROOT"/*/; do
  [[ -d "$domain_dir" ]] || continue
  domain="$(basename "$domain_dir")"
  case "$domain" in
    protocol|scripts|_incoming|.*) continue ;;
  esac

  for course_dir in "$domain_dir"*/; do
    [[ -d "$course_dir" ]] || continue
    course="$(basename "$course_dir")"
    [[ "$course" == .* ]] && continue
    rel="$domain/$course"

    if [[ -n "$FILTER" && "$domain" != "$FILTER" && "$rel" != "$FILTER" ]]; then
      continue
    fi

    if [[ ! -d "$course_dir/source" && ! -d "$course_dir/markdown" ]]; then
      NO_SOURCE+=("$rel")
      continue
    fi

    if [[ $PULL -eq 1 ]]; then
      for sub in source markdown; do
        if [[ -d "$course_dir/$sub/.git" ]]; then
          echo "[PULL]    $rel/$sub"
          git -C "$course_dir/$sub" pull --ff-only 2>&1 | tail -1 || true
        fi
      done
    fi

    target_dir="$course_dir/org-$MATH_FMT"
    course_force=""
    [[ $FORCE -eq 1 ]] && course_force="--force"

    if [[ -d "$target_dir" && -n "$(ls -A "$target_dir" 2>/dev/null)" ]]; then
      if python3 -m scripts.lint "$course_dir" --math-format "$MATH_FMT" $WARN_STRICT --quiet >/dev/null 2>&1; then
        if [[ $FORCE -eq 0 ]]; then
          echo "[SKIP]    $rel (org-$MATH_FMT is lint-clean)"
          SKIPPED+=("$rel")
          continue
        fi
      else
        echo "[RETRY]   $rel (existing org-$MATH_FMT failed lint; rebuilding)"
        course_force="--force"
      fi
    fi

    echo "[CONVERT] $rel -> org-$MATH_FMT/"
    if PYTHONPATH="$ROOT/scripts" python3 -m convert "$course_dir" --math-format "$MATH_FMT" $course_force $DRY_RUN; then
      if [[ -n "$DRY_RUN" ]]; then
        CONVERTED+=("$rel (dry-run)")
      elif python3 -m scripts.lint "$course_dir" --math-format "$MATH_FMT" $WARN_STRICT --quiet; then
        CONVERTED+=("$rel")
      else
        echo "[FAIL]    $rel (converted, but lint reported errors)" >&2
        FAILED+=("$rel (lint failed)")
      fi
    else
      echo "[FAIL]    $rel (converter exited non-zero)" >&2
      FAILED+=("$rel (convert failed)")
    fi
  done
done

if [[ -z "$DRY_RUN" ]]; then
  echo ""
  echo "==> Refreshing root index.org..."
  python3 -m scripts.gen_project_index --root "$ROOT"

  echo "==> Auditing licenses & updating courses.org + .gitignore..."
  python3 -m scripts.gen_courses_org --root "$ROOT"
fi


echo ""
echo "================ Sync Summary ================"
echo "Skipped (already clean): ${#SKIPPED[@]}"
echo "Converted & verified:    ${#CONVERTED[@]}"
echo "Source-less (ignored):   ${#NO_SOURCE[@]}"
echo "Failed:                  ${#FAILED[@]}"

if [[ ${#FAILED[@]} -gt 0 ]]; then
  echo ""
  echo "Courses needing attention:"
  for item in "${FAILED[@]}"; do
    echo "  - $item"
  done
  exit 1
fi
