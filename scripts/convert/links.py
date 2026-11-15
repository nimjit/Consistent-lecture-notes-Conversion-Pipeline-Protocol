"""Second-pass rewrite of inter-page links in a converted org body.

Pandoc renders markdown `[text](x.md)` as org `[[file:x.md][text]]`. This
module replaces those with `[[id:<uuid>][text]]` (protocol J1 / J3), and
rewrites intra-file section links `[[file:x.md#heading]]` to
`[[id:<uuid>]]` + `::*Heading` fragment (J2).

External URLs are left alone (J4).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from .model import Page

# [[file:xxx.md][desc]]  or  [[file:xxx.md]]
_ORG_FILE_LINK = re.compile(
    r"\[\[file:([^\]#]+?\.md)(?:#([^\]]+))?\](?:\[([^\]]*)\])?\]"
)


def build_lookup(pages: Iterable[Page]) -> dict[str, str]:
    """Build {source filename → org_id} for intra-course link resolution.

    Keyed on the markdown file's basename (lowercased).
    """
    out: dict[str, str] = {}
    for p in pages:
        out[p.source_path.name.lower()] = p.org_id
    return out


def rewrite(org_body: str, lookup: dict[str, str]) -> str:
    """Replace file: links that match known pages with id: links."""

    def _replace(m: re.Match) -> str:
        rel = Path(m.group(1)).name.lower()
        anchor = m.group(2)
        desc = m.group(3)
        uid = lookup.get(rel)
        if uid is None:
            return m.group(0)
        if anchor:
            # Convert anchor to a *Heading reference. Pandoc anchors tend to
            # be lowercased, hyphenated; strip hyphens for the heading match.
            heading = anchor.replace("-", " ")
            target = f"id:{uid}::*{heading}"
        else:
            target = f"id:{uid}"
        if desc:
            return f"[[{target}][{desc}]]"
        return f"[[{target}]]"

    return _ORG_FILE_LINK.sub(_replace, org_body)
