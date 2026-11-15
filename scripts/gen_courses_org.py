"""Scan course repositories to detect licenses & metadata, then write courses.org and .gitignore.

Detection priority for each `<domain>/<course>/`:
  1. Explicit `* Licence:` / `* License:` override in `<course>/README.org`
  2. Dedicated license files (`LICENSE*`, `*LICENSE*`, `COPYING*`, `UNLICENSE*`)
     in `source/` or `markdown/`
  3. Structured project metadata (`CITATION.cff`, `package.json`, `pyproject.toml`,
     `Cargo.toml`, `_config.yml`, `book.toml`)
  4. License badges, Creative Commons URLs, or `## License` sections in upstream
     `README.md` / `README.rst` / `README.org`
  5. Fallback: `none stated`
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Policy switch:
#   "block-all" -> ignore all <domain>/<course>/ trees in .gitignore (publish tooling/protocol only)
#   "free-only" -> allow courses with verified free/open licences, block all others
GIT_EXPORT_POLICY = "block-all"

BEGIN_GITIGNORE = "# === BEGIN LICENSE-BLOCKED COURSES (managed by scripts/gen_courses_org.py) ==="
END_GITIGNORE = "# === END LICENSE-BLOCKED COURSES ==="

_README_LICENCE_RE = re.compile(r"\*\s*(?:Wiki )?[Ll]icen[cs]e:\*\s*(.+)")
_README_AUTHOR_RE = re.compile(r"\*\s*(?:Author|Origin|Upstream):\*\s*(.+)")

_NONFREE_MARKERS = re.compile(
    r"\b(?:nc|nd|non-?commercial|no-?derivatives|all rights reserved|proprietary|"
    r"personal|audit|unknown|unclear|tbd|none)\b",
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


@dataclass
class CourseRecord:
    domain: str
    slug: str
    fmt: str
    origin: str
    licence: str
    licence_source: str
    is_free: bool
    status: str


# ---------- license detection ----------

def is_free_licence(raw: str | None) -> bool:
    if not raw:
        return False
    cleaned = raw.strip().strip("=~/")
    if not cleaned or _NONFREE_MARKERS.search(cleaned):
        return False
    return bool(_FREE_LICENCE_RE.search(cleaned))


def _classify_cc_url_or_text(text: str) -> str | None:
    """Match Creative Commons licenses (checking NC/ND variants first)."""
    patterns: list[tuple[re.Pattern[str], str]] = [
        (re.compile(r"creativecommons\.org/licenses/by-nc-sa/(\d\.\d)", re.I), "CC BY-NC-SA {}"),
        (re.compile(r"creativecommons\.org/licenses/by-nc-nd/(\d\.\d)", re.I), "CC BY-NC-ND {}"),
        (re.compile(r"creativecommons\.org/licenses/by-nc/(\d\.\d)", re.I), "CC BY-NC {}"),
        (re.compile(r"creativecommons\.org/licenses/by-nd/(\d\.\d)", re.I), "CC BY-ND {}"),
        (re.compile(r"creativecommons\.org/licenses/by-sa/(\d\.\d)", re.I), "CC BY-SA {}"),
        (re.compile(r"creativecommons\.org/licenses/by/(\d\.\d)", re.I), "CC BY {}"),
        (re.compile(r"creativecommons\.org/publicdomain/zero/(\d\.\d)", re.I), "CC0 {}"),
        (re.compile(r"\bCC[\s-]+BY[\s-]+NC[\s-]+SA(?:[\s-]+(\d\.\d))?\b", re.I), "CC BY-NC-SA"),
        (re.compile(r"\bCC[\s-]+BY[\s-]+NC[\s-]+ND(?:[\s-]+(\d\.\d))?\b", re.I), "CC BY-NC-ND"),
        (re.compile(r"\bCC[\s-]+BY[\s-]+NC(?:[\s-]+(\d\.\d))?\b", re.I), "CC BY-NC"),
        (re.compile(r"\bCC[\s-]+BY[\s-]+ND(?:[\s-]+(\d\.\d))?\b", re.I), "CC BY-ND"),
        (re.compile(r"\bCC[\s-]+BY[\s-]+SA(?:[\s-]+(\d\.\d))?\b", re.I), "CC BY-SA"),
        (re.compile(r"\bCC[\s-]+BY(?:[\s-]+(\d\.\d))?\b", re.I), "CC BY"),
        (re.compile(r"\bCC0(?:[\s-]+1\.0)?\b", re.I), "CC0 1.0"),
        (re.compile(r"Attribution-NonCommercial-ShareAlike\s*(\d\.\d)?", re.I), "CC BY-NC-SA"),
        (re.compile(r"Attribution-NonCommercial\s*(\d\.\d)?", re.I), "CC BY-NC"),
        (re.compile(r"Attribution-ShareAlike\s*(\d\.\d)?", re.I), "CC BY-SA"),
        (re.compile(r"Creative Commons Attribution\s*(\d\.\d)?", re.I), "CC BY"),
    ]
    for rx, label in patterns:
        m = rx.search(text)
        if m:
            ver = m.group(1) if m.lastindex and m.group(1) else ""
            if "{}" in label:
                return label.format(ver).strip()
            return f"{label} {ver}".strip()
    return None


def _classify_license_file_text(text: str) -> str | None:
    cc = _classify_cc_url_or_text(text)
    if cc:
        return cc

    head = "\n".join(text.splitlines()[:40])
    if re.search(r"GNU AFFERO GENERAL PUBLIC LICENSE", head, re.I):
        ver = "v3" if re.search(r"Version\s+3", head, re.I) else ""
        return f"AGPL {ver}".strip()
    if re.search(r"GNU LESSER GENERAL PUBLIC LICENSE", head, re.I):
        m = re.search(r"Version\s+(\d+(?:\.\d+)?)", head, re.I)
        return f"LGPL v{m.group(1)}" if m else "LGPL"
    if re.search(r"GNU GENERAL PUBLIC LICENSE", head, re.I):
        m = re.search(r"Version\s+(\d+)", head, re.I)
        return f"GPL v{m.group(1)}" if m else "GPL"
    if re.search(r"GNU Free Documentation License", head, re.I):
        return "GFDL"
    if re.search(r"Apache License", head, re.I) and re.search(r"Version\s+2\.0", head, re.I):
        return "Apache 2.0"
    if re.search(r"Mozilla Public License.*2\.0", head, re.I | re.S):
        return "MPL 2.0"
    if re.search(r"Permission is hereby granted,\s*free of charge", text, re.I) and (
        re.search(r"\bMIT\b", head, re.I)
        or re.search(r"deal in the Software without restriction", text, re.I)
    ):
        return "MIT"
    if re.search(r"Redistribution and use in source and binary forms", text, re.I):
        if re.search(r"Neither the name of", text, re.I):
            return "BSD 3-Clause"
        return "BSD 2-Clause"
    if re.search(r"free and unencumbered software released into the public domain", text, re.I):
        return "Unlicense"
    return None


def _scan_license_files(upstream_dir: Path) -> tuple[str | None, str]:
    """Inspect LICENSE*, *LICENSE*, COPYING*, UNLICENSE* files in an upstream dir."""
    candidates: list[Path] = []
    for p in sorted(upstream_dir.iterdir()):
        if not p.is_file():
            continue
        upper = p.name.upper()
        if (
            upper.startswith(("LICENSE", "LICENCE", "COPYING", "UNLICENSE"))
            or upper.endswith(("_LICENSE", "-LICENSE", ".LICENSE"))
        ):
            candidates.append(p)

    for p in candidates:
        text = p.read_text(encoding="utf-8", errors="replace")
        detected = _classify_license_file_text(text)
        if detected:
            return detected, f"{upstream_dir.name}/{p.name}"
    return None, ""


def _scan_metadata_files(upstream_dir: Path) -> tuple[str | None, str]:
    """Check CITATION.cff, package.json, pyproject.toml, Cargo.toml, _config.yml."""
    cff = upstream_dir / "CITATION.cff"
    if cff.is_file():
        m = re.search(r"^license:\s*['\"]?([^'\"\n#]+)", cff.read_text(encoding="utf-8", errors="replace"), re.M)
        if m:
            return m.group(1).strip(), f"{upstream_dir.name}/CITATION.cff"

    pkg = upstream_dir / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8", errors="replace"))
            lic = data.get("license")
            if isinstance(lic, str) and lic.strip():
                return lic.strip(), f"{upstream_dir.name}/package.json"
        except Exception:
            pass

    for toml_name in ("pyproject.toml", "Cargo.toml"):
        tf = upstream_dir / toml_name
        if tf.is_file():
            m = re.search(r'^\s*license\s*=\s*"([^"]+)"', tf.read_text(encoding="utf-8", errors="replace"), re.M)
            if m:
                return m.group(1).strip(), f"{upstream_dir.name}/{toml_name}"

    cfg = upstream_dir / "_config.yml"
    if cfg.is_file():
        text = cfg.read_text(encoding="utf-8", errors="replace")
        cc = _classify_cc_url_or_text(text)
        if cc:
            return cc, f"{upstream_dir.name}/_config.yml"

    return None, ""


def _scan_upstream_readme(upstream_dir: Path) -> tuple[str | None, str]:
    """Extract license declarations from README.md / README.rst / README.org."""
    for name in ("README.md", "readme.md", "README.rst", "README.org", "README"):
        rp = upstream_dir / name
        if not rp.is_file():
            continue
        text = rp.read_text(encoding="utf-8", errors="replace")

        # 1. Explicit CC link or label anywhere in README
        cc = _classify_cc_url_or_text(text)
        if cc:
            return cc, f"{upstream_dir.name}/{name}"

        # 2. Shields.io / opensource.org license badge
        badge = re.search(r"img\.shields\.io/badge/[Ll]icen[cs]e-([A-Za-z0-9_.+-]+)-", text)
        if badge:
            return badge.group(1).replace("_", " ").replace("--", "-"), f"{upstream_dir.name}/{name}"

        # 3. Dedicated License heading section
        sec = re.search(r"(?:^|\n)#+\s*Licen[cs]e\b(.*?)(?:\n#+\s|\Z)", text, re.I | re.S)
        if sec:
            snippet = sec.group(1)
            for rx, label in [
                (re.compile(r"\bMIT\b"), "MIT"),
                (re.compile(r"\bApache[\s-]+2\.0\b", re.I), "Apache 2.0"),
                (re.compile(r"\bGPL[\s-]*v?3\b", re.I), "GPL v3"),
                (re.compile(r"\bGPL[\s-]*v?2\b", re.I), "GPL v2"),
                (re.compile(r"\bBSD[\s-]*3\b", re.I), "BSD 3-Clause"),
                (re.compile(r"\bBSD[\s-]*2\b", re.I), "BSD 2-Clause"),
            ]:
                if rx.search(snippet):
                    return label, f"{upstream_dir.name}/{name}"
    return None, ""


def detect_licence(course_dir: Path) -> tuple[str, str]:
    """Return `(licence_label, source_where_found)`."""
    # 1. Local course README.org override (highest priority)
    local_readme = course_dir / "README.org"
    if local_readme.is_file():
        text = local_readme.read_text(encoding="utf-8", errors="replace")
        m = _README_LICENCE_RE.search(text)
        if m:
            return m.group(1).strip(), "README.org"

    # 2. Inspect upstream source/ and markdown/ directories
    file_lic: str | None = None
    file_src = ""
    readme_lic: str | None = None
    readme_src = ""

    for sub in ("source", "markdown"):
        up = course_dir / sub
        if not up.is_dir():
            continue
        if not file_lic:
            file_lic, file_src = _scan_license_files(up)
        if not file_lic:
            file_lic, file_src = _scan_metadata_files(up)
        if not readme_lic:
            readme_lic, readme_src = _scan_upstream_readme(up)

    # Combine if both a code license file and a separate content CC license exist (e.g., MIT + CC BY)
    if file_lic and readme_lic and file_lic.lower() not in readme_lic.lower() and readme_lic.lower() not in file_lic.lower():
        return f"{file_lic} + {readme_lic}", f"{file_src}, {readme_src}"
    if file_lic:
        return file_lic, file_src
    if readme_lic:
        return readme_lic, readme_src

    return "none stated", "—"


# ---------- format & origin detection ----------

def detect_format(course_dir: Path) -> str:
    src = course_dir / "source"
    md = course_dir / "markdown"
    target = src if src.is_dir() else (md if md.is_dir() else None)
    if target is None:
        return "—"

    if (target / "_toc.yml").is_file() or (target / "_config.yml").is_file():
        return "Jupyter Book"
    if (target / "book.toml").is_file():
        return "mdBook"
    if (target / "_quarto.yml").is_file() or any(target.rglob("*.qmd")):
        return "Quarto"

    has_tex = any(target.rglob("*.tex"))
    has_ipynb = any(target.rglob("*.ipynb"))
    has_html = any(target.glob("*.html"))
    has_md = any(target.rglob("*.md"))

    if has_ipynb and has_tex:
        return "Jupyter+LaTeX"
    if has_ipynb:
        return "Jupyter"
    if has_tex:
        return "LaTeX"
    if has_html and not has_md:
        return "HTML"
    if md.is_dir() and not src.is_dir():
        return "nb-md"
    if has_md:
        return "Markdown"
    return "unknown"


def detect_origin(course_dir: Path) -> str:
    local_readme = course_dir / "README.org"
    if local_readme.is_file():
        text = local_readme.read_text(encoding="utf-8", errors="replace")
        m = _README_AUTHOR_RE.search(text)
        if m:
            return m.group(1).strip()

    for sub in ("source", "markdown"):
        git_dir = course_dir / sub / ".git"
        if git_dir.exists():
            res = subprocess.run(
                ["git", "-C", str(course_dir / sub), "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                check=False,
            )
            url = res.stdout.strip()
            if url:
                m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?$", url)
                return m.group(1) if m else url
    return "—"


def detect_status(course_dir: Path) -> str:
    parts = [
        sub for sub in ("source", "markdown", "org-latex", "org-typst")
        if (course_dir / sub).is_dir()
    ]
    return "+".join(parts) or "—"


# ---------- courses.org & .gitignore generation ----------

def scan_all_courses(root: Path) -> list[CourseRecord]:
    records: list[CourseRecord] = []
    for domain_dir in sorted(root.iterdir()):
        if not domain_dir.is_dir() or domain_dir.name.startswith("."):
            continue
        if domain_dir.name in {"protocol", "scripts", "_incoming"}:
            continue
        for course_dir in sorted(domain_dir.iterdir()):
            if not course_dir.is_dir() or course_dir.name.startswith("."):
                continue
            lic, lic_src = detect_licence(course_dir)
            records.append(
                CourseRecord(
                    domain=domain_dir.name,
                    slug=course_dir.name,
                    fmt=detect_format(course_dir),
                    origin=detect_origin(course_dir),
                    licence=lic,
                    licence_source=lic_src,
                    is_free=is_free_licence(lic),
                    status=detect_status(course_dir),
                )
            )
    return records


def _extract_preserved_notes(courses_org: Path, known_domains: set[str]) -> str:
    """Keep manual non-domain sections (e.g. '* Imported...' or '* Rejected') from existing courses.org."""
    if not courses_org.is_file():
        return ""
    text = courses_org.read_text(encoding="utf-8", errors="replace")
    kept: list[str] = []
    capturing = False
    for line in text.splitlines():
        if line.startswith("* ") and not line.startswith("** "):
            heading = line[2:].strip().lower()
            capturing = heading not in known_domains
        if capturing:
            kept.append(line)
    return "\n".join(kept).strip()


def render_courses_org(
    records: list[CourseRecord],
    preserved_notes: str,
    policy: str = GIT_EXPORT_POLICY,
) -> str:
    free_count = sum(1 for r in records if r.is_free)
    exported_count = sum(1 for r in records if (r.is_free and policy == "free-only"))
    blocked_count = len(records) - exported_count

    out: list[str] = [
        "#+title: Course registry",
        "#+startup: overview",
        "",
        "Auto-generated by =scripts/gen_courses_org.py= by inspecting upstream",
        "repository files (=LICENSE*=, =COPYING*=, =README*=, metadata) and local",
        "=README.org= overrides. Domain tables are regenerated on every run;",
        "any non-domain notes sections at the bottom are preserved.",
        "",
        f"- Export policy: ={policy}=",
        f"- Total courses: {len(records)}",
        f"- Free-licensed courses: {free_count}",
        f"- Git-tracked courses: {exported_count}",
        f"- Blocked in =.gitignore=: {blocked_count}",
        "",
    ]

    by_domain: dict[str, list[CourseRecord]] = {}
    for r in records:
        by_domain.setdefault(r.domain, []).append(r)

    for domain in sorted(by_domain):
        out.append(f"* {domain.capitalize()}")
        out.append("")
        out.append("| Folder | Format | Origin | Licence | Detected from | Git | Status |")
        out.append("|--------+--------+--------+---------+---------------+-----+--------|")
        for r in by_domain[domain]:
            if policy == "block-all":
                git_flag = "blocked (policy)"
            elif r.is_free:
                git_flag = "yes"
            else:
                git_flag = "blocked (licence)"
            out.append(
                f"| {r.slug} | {r.fmt} | {r.origin} | {r.licence} | {r.licence_source} | {git_flag} | {r.status} |"
            )
        out.append("")

    if preserved_notes:
        out.append(preserved_notes)
        out.append("")

    return "\n".join(out)


def write_gitignore(
    root: Path,
    records: list[CourseRecord],
    policy: str = GIT_EXPORT_POLICY,
) -> Path:
    gi_path = root / ".gitignore"
    existing = gi_path.read_text(encoding="utf-8") if gi_path.exists() else ""

    lines = [BEGIN_GITIGNORE]
    if policy == "block-all":
        lines.append("# Global policy: block all course trees and local course indexes")
        lines.append("courses.org")
        lines.append("index.org")
    for r in records:
        if policy == "block-all" or not r.is_free:
            reason = f"{r.licence}; policy={policy}" if policy == "block-all" else r.licence
            lines.append(f"# {r.domain}/{r.slug} — {reason}")
            lines.append(f"{r.domain}/{r.slug}/")
    lines.append(END_GITIGNORE)
    block = "\n".join(lines)

    pattern = re.compile(
        re.escape(BEGIN_GITIGNORE) + r".*?" + re.escape(END_GITIGNORE),
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
    p = argparse.ArgumentParser(prog="python3 -m scripts.gen_courses_org")
    p.add_argument("--root", type=Path, default=Path("."), help="Project root.")
    p.add_argument("--out", type=Path, default=None, help="Output Org file (default: <root>/courses.org).")
    p.add_argument(
        "--policy",
        choices=["block-all", "free-only"],
        default=GIT_EXPORT_POLICY,
        help="Git export policy (default: block-all).",
    )
    args = p.parse_args(argv)

    root = args.root.resolve()
    out_path = args.out or (root / "courses.org")

    records = scan_all_courses(root)
    known_domains = {r.domain.lower() for r in records}
    preserved = _extract_preserved_notes(out_path, known_domains)

    out_path.write_text(render_courses_org(records, preserved, policy=args.policy), encoding="utf-8")
    gi_path = write_gitignore(root, records, policy=args.policy)

    free_count = sum(1 for r in records if r.is_free)
    exported = free_count if args.policy == "free-only" else 0
    print(
        f"wrote {out_path} ({len(records)} courses: {free_count} free, "
        f"{exported} git-tracked, {len(records) - exported} blocked [policy={args.policy}])"
    )
    print(f"updated {gi_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
