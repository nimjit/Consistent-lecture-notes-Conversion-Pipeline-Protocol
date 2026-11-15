"""Update the license-blocked section of .gitignore from course metadata.

Reads `*/*/README.org` (and `courses.org` as a fallback) for each course's
`* Licence:` / `* License:` field. Any course without an explicitly free/open
license (e.g., CC BY, CC BY-SA, CC0, Public Domain, MIT, BSD, Apache-2.0,
GPL, LGPL, AGPL, MPL-2.0, GFDL, FAL) is added to `.gitignore`.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_LICENCE_RE = re.compile(r"\*\s*(?:Wiki )?[Ll]icen[cs]e:\*\s*(.+)")
_NONFREE_MARKERS = re.compile(
    r"\b(?:nc|nd|non-?commercial|no-?derivatives|all rights reserved|proprietary|unknown|unclear|tbd|none)\b",
    re.IGNORECASE,
)
_FREE_LICENCE_RE = re.compile(
    r"\b(?:"
    r"cc[\s-]*by(?:[\s-]*sa)?(?:[\s-]*\d(?:\.\d)?)?"
    r"|cc0(?:[\s-]*1\.0)?"
    r"|public[\s-]*domain"
    r"|unlicense"
    r"|wtfpl"
    r"|mit"
    r"|isc"
    r"|bsd(?:[\s-]*[23][\s-]*clause)?"
    r"|apache(?:[\s-]*2\.0)?"
    r"|a?gpl(?:[\s-]*v?[23](?:\.0)?(?:-or-later|-only|\+)?)?"
    r"|lgpl(?:[\s-]*v?[23](?:\.\d)?(?:-or-later|-only|\+)?)?"
    r"|mpl[\s-]*2\.0"
    r"|gfdl"
    r"|free art licen[cs]e|fal"
    r"|artistic[\s-]*2\.0"
    r")\b",
    re.IGNORECASE,
)

BEGIN_MARKER = "# === BEGIN LICENSE-BLOCKED COURSES (managed by scripts/update_gitignore.py) ==="
END_MARKER = "# === END LICENSE-BLOCKED COURSES ==="


def is_free_licence(raw: str | None) -> bool:
    if not raw:
        return False
    cleaned = raw.strip().strip("=~/")
    if not cleaned or _NONFREE_MARKERS.search(cleaned):
        return False
    return bool(_FREE_LICENCE_RE.search(cleaned))


def _read_readme_licence(course_dir: Path) -> str | None:
    readme = course_dir / "README.org"
    if not readme.exists():
        return None
    text = readme.read_text(encoding="utf-8", errors="replace")
    m = _LICENCE_RE.search(text)
    return m.group(1).strip() if m else None


def _read_courses_org_licences(root: Path) -> dict[str, str]:
    """Fallback lookup of `domain/slug -> licence` from root courses.org if present."""
    courses_org = root / "courses.org"
    if not courses_org.exists():
        return {}
    text = courses_org.read_text(encoding="utf-8", errors="replace")
    found: dict[str, str] = {}
    current_course: str | None = None
    for line in text.splitlines():
        cm = re.search(r"\b([a-z-]+/[a-z0-9-]+)\b", line)
        if line.startswith("*") and cm:
            current_course = cm.group(1)
        lm = _LICENCE_RE.search(line)
        if current_course and lm:
            found[current_course] = lm.group(1).strip()
    return found


def scan_courses(root: Path) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Return (allowed, blocked) lists of `(domain/course, licence_str)`."""
    fallback = _read_courses_org_licences(root)
    allowed: list[tuple[str, str]] = []
    blocked: list[tuple[str, str]] = []

    for domain_dir in sorted(root.iterdir()):
        if not domain_dir.is_dir() or domain_dir.name.startswith("."):
            continue
        if domain_dir.name in {"protocol", "scripts", "_incoming"}:
            continue
        for course_dir in sorted(domain_dir.iterdir()):
            if not course_dir.is_dir() or course_dir.name.startswith("."):
                continue
            rel = f"{domain_dir.name}/{course_dir.name}"
            lic = _read_readme_licence(course_dir) or fallback.get(rel)
            if is_free_licence(lic):
                allowed.append((rel, lic or ""))
            else:
                blocked.append((rel, lic or "(missing)"))

    return allowed, blocked


def update_gitignore(root: Path, blocked: list[tuple[str, str]]) -> Path:
    gi_path = root / ".gitignore"
    existing = gi_path.read_text(encoding="utf-8") if gi_path.exists() else ""

    lines = [BEGIN_MARKER]
    for rel, lic in blocked:
        lines.append(f"# {rel} — {lic}")
        lines.append(f"{rel}/")
    lines.append(END_MARKER)
    block = "\n".join(lines)

    pattern = re.compile(
        re.escape(BEGIN_MARKER) + r".*?" + re.escape(END_MARKER),
        re.DOTALL,
    )
    if pattern.search(existing):
        updated = pattern.sub(block, existing)
    else:
        sep = "\n\n" if existing and not existing.endswith("\n\n") else ""
        updated = existing + sep + block + "\n"

    gi_path.write_text(updated, encoding="utf-8")
    return gi_path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python3 -m scripts.update_gitignore")
    p.add_argument("--root", type=Path, default=Path("."), help="Project root.")
    p.add_argument("--verbose", "-v", action="store_true", help="Print allowed and blocked courses.")
    args = p.parse_args(argv)

    root = args.root.resolve()
    allowed, blocked = scan_courses(root)
    gi_path = update_gitignore(root, blocked)

    print(f"updated {gi_path}: {len(allowed)} free/allowed, {len(blocked)} license-blocked")
    if args.verbose:
        print("\nAllowed:")
        for rel, lic in allowed:
            print(f"  + {rel} [{lic}]")
        print("\nBlocked:")
        for rel, lic in blocked:
            print(f"  - {rel} [{lic}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
