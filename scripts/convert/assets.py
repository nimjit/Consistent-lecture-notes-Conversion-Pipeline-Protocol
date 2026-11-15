"""Collect, copy, and rewrite references to image attachments.

Protocol H1 (asset layout), H2 (name + org-id ref), H3 (caption).

Flow:
  1. For each page, collect_from_markdown() → list of (alt, raw_rel) refs.
  2. registry.allocate(raw_rel, page_source_dir, alt) resolves raw_rel against
     the containing file's directory to an absolute path, dedupes by that path,
     and returns an Asset with a descriptive slug and an org id. Call it per
     page, building a page-local {raw_rel → Asset} map for rewrite.
  3. After pandoc, rewrite_in_org() uses the page-local map to replace
     [[file:<raw>]] with [[attachment:<slug>.<ext>]] + #+NAME:.
  4. registry.copy_all(target_dir) copies the deduplicated source files
     to assets/attachments/.
"""
from __future__ import annotations

import re
import shutil
import urllib.parse
from pathlib import Path

from .ids import IdAllocator
from .model import Asset
from .slug import slugify

ATTACHMENTS_SUBDIR = "assets/attachments"

_IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".webp"}

# Markdown image: ![alt](path "title"?)
_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

# Org file link that could be an image, with optional description.
_ORG_FILE_IMG = re.compile(
    r"\[\[file:([^\]]+?\.(?:png|jpg|jpeg|gif|svg|pdf|webp))\](?:\[([^\]]*)\])?\]",
    re.IGNORECASE,
)


def _normalise_rel(path: str) -> str:
    path = urllib.parse.unquote(path)
    if path.startswith("./"):
        path = path[2:]
    return path.replace("\\", "/")


def _looks_like_image(path: str) -> bool:
    return any(path.lower().endswith(ext) for ext in _IMG_EXTS)


def collect_from_markdown(body: str) -> list[tuple[str, str]]:
    """[(alt, raw_rel_path)] of image refs in a markdown body.

    Skips URL references (http/https/data) which the asset registry can't
    resolve to a local file and which should pass through to pandoc as-is.
    """
    out: list[tuple[str, str]] = []
    for alt, path in _MD_IMAGE.findall(body):
        if path.startswith(("http://", "https://", "http:/", "https:/", "data:")):
            continue
        if not _looks_like_image(path):
            continue
        out.append((alt, path))
    return out


def collect_from_org(body: str) -> list[tuple[str, str]]:
    """[(desc, raw_rel_path)] of image refs in an org body."""
    out: list[tuple[str, str]] = []
    for m in _ORG_FILE_IMG.finditer(body):
        out.append(((m.group(2) or "").strip(), m.group(1)))
    return out


class AssetRegistry:
    """Deduplicates assets by resolved absolute path.

    Mints a descriptive slug per unique file; resolves slug collisions by
    appending `-2`, `-3`, ….
    """

    def __init__(self, allocator: IdAllocator):
        self.allocator = allocator
        self.by_abs: dict[Path, Asset] = {}
        self._slug_counts: dict[str, int] = {}

    def allocate(self, raw_rel: str, page_source_dir: Path, alt: str = "") -> Asset | None:
        """Resolve + mint if new; return existing if already registered.

        Returns None if the resolved path can't be computed. Note: existence
        is not checked here (copy_all logs missing files later).
        """
        rel = _normalise_rel(raw_rel)
        try:
            abs_path = (page_source_dir / rel).resolve()
        except Exception:
            return None
        if abs_path in self.by_abs:
            return self.by_abs[abs_path]

        stem = abs_path.stem
        slug = slugify(stem) or slugify(alt) or "attachment"
        if slug in self._slug_counts:
            self._slug_counts[slug] += 1
            slug = f"{slug}-{self._slug_counts[slug]}"
        else:
            self._slug_counts[slug] = 0

        asset = Asset(
            source_path=abs_path,
            target_slug=slug,
            extension=abs_path.suffix or ".bin",
            org_id=self.allocator.for_path(f"asset:{abs_path}"),
            caption=alt or None,
        )
        self.by_abs[abs_path] = asset
        return asset

    def copy_all(self, target_dir: Path) -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        for asset in self.by_abs.values():
            if not asset.source_path.exists():
                print(f"  warning: asset source missing: {asset.source_path}")
                continue
            shutil.copy2(asset.source_path, target_dir / asset.target_filename)


def rewrite_in_org(org_body: str, page_assets: dict[str, Asset]) -> str:
    """Rewrite org file-image links to point at `../assets/attachments/`.

    Links use the standard `[[file:...]]` form so Emacs renders them inline
    with `org-toggle-inline-images` without any `.dir-locals.el` setup. The
    descriptive slug remains the filename. A `#+CAPTION:` line precedes
    the link when the upstream alt-text was present.

    Keys are normalised raw paths (as they appear in the body); fall back
    to a basename match if the full path misses.
    """
    def _replace(m: re.Match) -> str:
        rel = _normalise_rel(m.group(1))
        asset = page_assets.get(rel)
        if asset is None:
            basename = Path(rel).name
            for k, v in page_assets.items():
                if Path(k).name == basename:
                    asset = v
                    break
        if asset is None:
            return m.group(0)
        link = f"[[file:../assets/attachments/{asset.target_filename}]]"
        if asset.caption:
            return f"#+CAPTION: {asset.caption}\n{link}"
        return link

    return _ORG_FILE_IMG.sub(_replace, org_body)
