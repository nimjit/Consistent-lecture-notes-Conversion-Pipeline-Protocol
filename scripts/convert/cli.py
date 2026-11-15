"""CLI entry: python -m convert <course-path>."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .parsers import available_formats
from .pipeline import convert_course


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m convert",
        description="Convert a course source/ tree into protocol-compliant org-latex/ (or org-typst/).",
    )
    p.add_argument("course", type=Path, help="Course directory (contains source/ or markdown/).")
    p.add_argument("--format", choices=available_formats() + ["auto"], default="auto",
                   help="Parser to use (default: auto-detect).")
    p.add_argument("--math-format", choices=["latex", "typst"], default="latex",
                   help="Math output format and target dir: 'latex' -> org-latex/ (default) or 'typst' -> org-typst/.")
    p.add_argument("--short", default=None, help="Override the course short code.")
    p.add_argument("--name", default=None, help="Override the course display name.")
    p.add_argument("--force", action="store_true",
                   help="Overwrite an existing target directory (backing it up).")
    p.add_argument("--dry-run", action="store_true", help="Build in staging; do not commit.")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--exclude", action="append", default=[],
                   help="Exclude pages whose source path contains this fragment "
                        "(repeatable). Only honored by parsers that filter pages "
                        "(mdbook, jupyter-book).")
    args = p.parse_args(argv)

    fmt = None if args.format == "auto" else args.format
    try:
        convert_course(
            args.course,
            fmt=fmt,
            math_format=args.math_format,
            short_override=args.short,
            name_override=args.name,
            exclude=args.exclude or None,
            force=args.force,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
