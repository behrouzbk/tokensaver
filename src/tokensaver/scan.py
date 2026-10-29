"""Find the prompt files in a folder and measure what each one could save."""

from __future__ import annotations

import os
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from tokensaver.inputs import read_file
from tokensaver.optimizer import optimize, resolve_selection
from tokensaver.pricing import ModelInfo, input_cost

DEFAULT_PATTERNS = ("*.txt", "*.md", "*.prompt", "*.jinja", "*.jinja2", "*.j2")
SKIP_DIRS = frozenset({"node_modules", "__pycache__"})


@dataclass(frozen=True)
class FileScan:
    path: str  # relative to the scanned folder, with forward slashes
    tokens: int
    safe_saved: int  # tokens saved by the safe rules alone (optimize's default)
    all_saved: int  # tokens saved by every rule, review suggestions included


@dataclass(frozen=True)
class ScanResult:
    model: ModelInfo
    files: list[FileScan]  # biggest possible saving first
    skipped: list[str]  # files that are not UTF-8 text

    @property
    def tokens(self) -> int:
        return sum(f.tokens for f in self.files)

    @property
    def safe_saved(self) -> int:
        return sum(f.safe_saved for f in self.files)

    @property
    def all_saved(self) -> int:
        return sum(f.all_saved for f in self.files)

    @property
    def dollars_saved_all(self) -> float:
        return input_cost(self.all_saved, self.model)


def _skip_dir(path: Path) -> bool:
    """Hidden folders, dependency folders and Python virtual environments."""
    return path.name.startswith(".") or path.name in SKIP_DIRS or (path / "pyvenv.cfg").is_file()


def find_prompt_files(root: Path, patterns: tuple[str, ...] = DEFAULT_PATTERNS) -> list[Path]:
    """Files under `root` whose name matches a pattern (case-insensitive), sorted by path."""
    lowered = [p.lower() for p in patterns]
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        dirnames[:] = [d for d in dirnames if not _skip_dir(here / d)]
        found.extend(
            here / name for name in filenames if any(fnmatch(name.lower(), p) for p in lowered)
        )
    return sorted(found)


def scan(root: Path, model: ModelInfo, patterns: tuple[str, ...] = DEFAULT_PATTERNS) -> ScanResult:
    files, skipped = [], []
    everything = resolve_selection("all")
    for path in find_prompt_files(root, patterns):
        relative = path.relative_to(root).as_posix()
        try:
            text = read_file(path)
        except UnicodeDecodeError:
            skipped.append(relative)
            continue
        safe = optimize(text, model)
        full = optimize(text, model, everything)
        files.append(FileScan(relative, safe.tokens_before, safe.tokens_saved, full.tokens_saved))
    files.sort(key=lambda f: (-f.all_saved, f.path))
    return ScanResult(model=model, files=files, skipped=skipped)
