"""Staged write to .staging/<course>/<target_subdir>/, then atomic rename.

Refuses to overwrite a non-empty target directory unless --force.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path


class StagedWriter:
    def __init__(
        self,
        course_dir: Path,
        staging_root: Path | None = None,
        target_subdir: str = "org-latex",
    ):
        self.course_dir = course_dir
        self.target_subdir = target_subdir
        self.target = course_dir / target_subdir
        root = staging_root or (course_dir.parent.parent / ".staging")
        self.staging_dir = root / f"{course_dir.parent.name}--{course_dir.name}" / target_subdir

    def prepare(self) -> Path:
        """Clear and re-create the staging dir. Returns its path."""
        if self.staging_dir.exists():
            shutil.rmtree(self.staging_dir)
        self.staging_dir.mkdir(parents=True)
        return self.staging_dir

    def write(self, relpath: str, content: str) -> None:
        path = self.staging_dir / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def commit(self, force: bool = False, dry_run: bool = False) -> Path | None:
        """Move staging into place.

        If the target exists and is non-empty: abort unless force. If force,
        the existing tree is moved to <target_subdir>.bak-<timestamp>/.
        """
        if not any(self.staging_dir.iterdir()):
            raise RuntimeError("staging dir is empty; nothing to commit")

        if dry_run:
            print(f"  dry-run: would commit {self.staging_dir} -> {self.target}")
            return None

        if self.target.exists() and any(self.target.iterdir()):
            if not force:
                raise FileExistsError(
                    f"{self.target} is non-empty. Pass --force to replace it."
                )
            ts = time.strftime("%Y%m%d-%H%M%S")
            backup = self.target.with_name(f"{self.target_subdir}.bak-{ts}")
            self.target.rename(backup)
            print(f"  previous {self.target_subdir}/ backed up to {backup.name}")
        elif self.target.exists():
            self.target.rmdir()

        shutil.move(str(self.staging_dir), str(self.target))
        return self.target
