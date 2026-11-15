"""Protocol lint for the lecture-notes wiki.

Implements protocol §Linting (O1 — "both — a prose checklist and an
executable script that implements it", O2 — the five check categories).

Usage:
    python3 -m scripts.lint [<path>] [--only CHECK...] [--quiet] [--warn-strict]

With no path given, lints the project root (every `<domain>/<course>/`
directory under the current working directory). A specific course dir
narrows the scan. Exits non-zero if any error-severity problem is found.
"""
from __future__ import annotations

import argparse
import re
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional


# ------- model -------

@dataclass
class Problem:
    file: Path
    message: str
    check: str                 # one of CHECK_NAMES
    severity: str = "error"    # "error" | "warning"

    def format_line(self, root: Path) -> str:
        try:
            rel = self.file.relative_to(root)
        except ValueError:
            rel = self.file
        return f"{rel}: {self.severity}: [{self.check}] {self.message}"


@dataclass
class Report:
    problems: list[Problem] = field(default_factory=list)

    def add(self, file: Path, message: str, check: str, severity: str = "error") -> None:
        self.problems.append(Problem(file, message, check, severity))

    def errors(self) -> int:
        return sum(1 for p in self.problems if p.severity == "error")

    def warnings(self) -> int:
        return sum(1 for p in self.problems if p.severity == "warning")


# ------- parsing -------

_PROP_RE = re.compile(r"^:([A-Z_][A-Z0-9_]*):[ \t]*(.*?)[ \t]*$", re.MULTILINE)
_END_RE = re.compile(r"^:END:\s*$", re.MULTILINE)
_HEADING_RE = re.compile(r"^\*+\s+(.+?)(?:\s+:[A-Za-z0-9_@:-]+:)?\s*$", re.MULTILINE)
_ID_LINK = re.compile(r"\[\[id:([0-9a-fA-F-]+)")
_FILE_LINK = re.compile(r"\[\[file:([^\]]+?)\](?:\[[^\]]*\])?\]")
_FILENAME_RE = re.compile(
    r"^(?P<short>[a-z][a-z0-9-]*?)-(?P<num>\d+[a-z]?)(?:-(?P<slug>[a-z0-9-]+?))?\.org$"
)
_SUPP_FILENAME_RE = re.compile(r"^supp-(?P<slug>[a-z0-9][a-z0-9-]*)\.org$")
_TAG_RE = re.compile(r"^[a-z]+(-[a-z]+)*$")


def parse_properties(content: str) -> dict[str, str]:
    """Return {key: value} from the file-level :PROPERTIES: drawer."""
    end = _END_RE.search(content)
    if not end:
        return {}
    head = content[: end.start()]
    out: dict[str, str] = {}
    for m in _PROP_RE.finditer(head):
        out[m.group(1)] = m.group(2)
    return out


def extract_headings(content: str) -> list[str]:
    """Return top-level heading texts (`* Heading`) in document order."""
    headings = []
    for m in _HEADING_RE.finditer(content):
        line_start = content.rfind("\n", 0, m.start()) + 1
        prefix = content[line_start:m.start()]
        # Only accept if the heading is at the start of a line and is level-1.
        if prefix == "" and content[m.start():m.start() + 2] == "* ":
            headings.append(m.group(1).strip())
    return headings


def body_text(content: str) -> str:
    """Content after the :PROPERTIES:/:END: drawer and #+title: line."""
    end = _END_RE.search(content)
    tail = content[end.end():] if end else content
    tail = re.sub(r"^#\+title:.*\n?", "", tail, count=1, flags=re.MULTILINE | re.IGNORECASE)
    return tail


# ------- checks -------

REQUIRED_FIELDS = ["ID", "COURSE", "COURSE_SHORT", "TYPE", "PREV", "NEXT", "STATUS", "TAGS"]
VALID_TYPES = {"lecture", "assignment", "own-notes", "supplementary"}
VALID_STATUSES = {"stub", "draft", "clean"}

SECTIONS_BY_TYPE = {
    "lecture":        ["Prev. lecture", "Content", "Summary", "Next lecture"],
    "own-notes":      ["Prev. lecture", "Content", "Summary", "Next lecture"],
    "assignment":     ["Problem statement", "Solution", "Reflection"],
    "supplementary": ["Content"],
}

CHECK_NAMES = {"frontmatter", "sections", "links", "filename", "tags"}


def check_frontmatter(f: Path, props: dict, report: Report) -> None:
    for key in REQUIRED_FIELDS:
        if key not in props:
            report.add(f, f"missing frontmatter field :{key}:", "frontmatter")

    ptype = props.get("TYPE", "")
    if ptype and ptype not in VALID_TYPES:
        report.add(f, f"TYPE={ptype!r} not in {sorted(VALID_TYPES)}", "frontmatter")

    # NUMBER required for everything except supplementary.
    if ptype != "supplementary" and not props.get("NUMBER"):
        report.add(f, "missing or empty :NUMBER:", "frontmatter")

    status = props.get("STATUS", "")
    if status and status not in VALID_STATUSES:
        report.add(f, f"STATUS={status!r} not in {sorted(VALID_STATUSES)}", "frontmatter")

    pid = props.get("ID", "")
    if pid:
        try:
            uuid.UUID(pid)
        except ValueError:
            report.add(f, f"ID={pid!r} is not a valid UUID", "frontmatter")


def check_sections(f: Path, props: dict, content: str, report: Report) -> None:
    ptype = props.get("TYPE")
    required = SECTIONS_BY_TYPE.get(ptype)
    if required is None:
        return  # frontmatter check will flag the bad TYPE
    headings = extract_headings(content)
    for required_name in required:
        if required_name not in headings:
            report.add(f, f"missing required section * {required_name}", "sections")


def check_links(
    f: Path,
    content: str,
    all_ids: set[str],
    report: Report,
) -> None:
    body = body_text(content)
    for m in _ID_LINK.finditer(body):
        target = m.group(1).lower()
        if target not in all_ids:
            report.add(f, f"id:{target[:8]}… points at nothing", "links")

    for m in _FILE_LINK.finditer(body):
        raw = m.group(1).split("::", 1)[0]  # drop ::*Heading fragment
        if raw.startswith(("http://", "https://", "data:")):
            continue
        resolved = (f.parent / raw).resolve()
        if not resolved.exists():
            report.add(f, f"file link does not resolve: {raw}", "links")


def check_filename(f: Path, props: dict, report: Report) -> None:
    """Filename pattern agrees with COURSE_SHORT, NUMBER, TYPE/subdir."""
    name = f.name
    parent = f.parent.name
    ptype = props.get("TYPE", "")

    # Supplementary filename uses the supp- prefix and has no number.
    if ptype == "supplementary":
        if parent != "supplementary":
            report.add(f, f"supplementary file not under supplementary/ (parent={parent!r})", "filename")
        if not _SUPP_FILENAME_RE.match(name):
            report.add(f, f"supplementary filename {name!r} doesn't match supp-<slug>.org", "filename")
        return

    m = _FILENAME_RE.match(name)
    if not m:
        report.add(f, f"filename {name!r} doesn't match <short>-NN-slug.org", "filename")
        return

    short = props.get("COURSE_SHORT", "")
    if short and m.group("short") != short:
        report.add(f, f"filename short {m.group('short')!r} ≠ COURSE_SHORT {short!r}", "filename")

    number = props.get("NUMBER", "")
    if number and m.group("num") != number:
        report.add(f, f"filename number {m.group('num')!r} ≠ NUMBER {number!r}", "filename")

    expected_parent = {
        "lecture": "lectures",
        "own-notes": "lectures",
        "assignment": "assignments",
    }.get(ptype)
    if expected_parent and parent != expected_parent:
        report.add(
            f, f"TYPE={ptype} should live under {expected_parent}/, got {parent}/",
            "filename",
        )


def check_tags(f: Path, props: dict, major_tags: set[str], report: Report) -> None:
    raw = props.get("TAGS", "")
    tags = [t for t in raw.split() if t]
    for t in tags:
        if not _TAG_RE.match(t):
            report.add(
                f, f"tag {t!r} not lowercase-hyphenated-full-words",
                "tags",
            )


# ------- driver -------

def iter_course_dirs(root: Path, target_subdir: str = "org-latex") -> Iterable[Path]:
    """Yield `<domain>/<course>/` dirs that contain a `<target_subdir>/` tree."""
    for domain in sorted(root.iterdir()):
        if not domain.is_dir() or domain.name.startswith("."):
            continue
        if domain.name in {"protocol", "scripts", ".staging", ".convert-cache"}:
            continue
        for course in sorted(domain.iterdir()):
            if not course.is_dir():
                continue
            if (course / target_subdir).is_dir():
                yield course


def iter_org_files(org_dir: Path) -> Iterable[Path]:
    for sub in ("lectures", "assignments", "supplementary"):
        d = org_dir / sub
        if d.is_dir():
            yield from sorted(d.glob("*.org"))


def _load_major_tags(root: Path) -> set[str]:
    tags_file = root / "tags.org"
    if not tags_file.exists():
        return set()
    text = tags_file.read_text(encoding="utf-8")
    tags = set()
    for m in re.finditer(r"^\s*[-+]\s*=([a-z][a-z0-9-]*)=", text, re.MULTILINE):
        tags.add(m.group(1))
    return tags


def lint(
    path: Path,
    only: Optional[set[str]] = None,
    target_subdir: str = "org-latex",
) -> Report:
    """Walk the tree under `path` and run selected checks."""
    report = Report()
    only = only or CHECK_NAMES

    if (path / target_subdir).is_dir():
        courses = [path]
        root = path.parent.parent
    else:
        courses = list(iter_course_dirs(path, target_subdir=target_subdir))
        root = path

    # First pass: collect all IDs across the scope.
    all_ids: set[str] = set()
    files: list[tuple[Path, dict, str]] = []  # (file, props, content)
    for course in courses:
        for org in iter_org_files(course / target_subdir):
            content = org.read_text(encoding="utf-8")
            props = parse_properties(content)
            files.append((org, props, content))
            pid = props.get("ID", "")
            if pid:
                all_ids.add(pid.lower())

    major_tags = _load_major_tags(root)

    for f, props, content in files:
        if "frontmatter" in only:
            check_frontmatter(f, props, report)
        if "sections" in only:
            check_sections(f, props, content, report)
        if "links" in only:
            check_links(f, content, all_ids, report)
        if "filename" in only:
            check_filename(f, props, report)
        if "tags" in only:
            check_tags(f, props, major_tags, report)

    return report


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="python3 -m scripts.lint",
        description="Lint the lecture-notes wiki against protocol §Linting.",
    )
    p.add_argument("path", type=Path, nargs="?", default=Path("."),
                   help="Project root or a specific course dir.")
    p.add_argument("--math-format", choices=["latex", "typst"], default="latex",
                   help="Target tree to lint: 'latex' -> org-latex/ (default) or 'typst' -> org-typst/.")
    p.add_argument("--only", choices=sorted(CHECK_NAMES), nargs="+", metavar="CHECK",
                   help="Run only the named check(s).")
    p.add_argument("--quiet", "-q", action="store_true",
                   help="Print only the final summary line.")
    p.add_argument("--warn-strict", action="store_true",
                   help="Treat warnings as errors (exit non-zero on any problem).")
    args = p.parse_args(argv)

    only = set(args.only) if args.only else None
    target_subdir = f"org-{args.math_format}"
    report = lint(args.path.resolve(), only=only, target_subdir=target_subdir)

    root = args.path.resolve()
    if not args.quiet:
        for pb in report.problems:
            print(pb.format_line(root), file=sys.stdout)

    errs, warns = report.errors(), report.warnings()
    files = len({pb.file for pb in report.problems})
    print(f"{errs} error(s), {warns} warning(s) across {files} file(s)")

    if errs:
        return 1
    if args.warn_strict and warns:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
