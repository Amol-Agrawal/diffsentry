"""File access for the agent: local checkout, GitHub API, or in-memory dict."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class RepoSource(Protocol):
    def read_file(self, path: str) -> str | None: ...

    def list_files(self) -> list[str]: ...


class LocalRepo:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def _safe(self, path: str) -> Path | None:
        p = (self.root / path).resolve()
        return p if p.is_relative_to(self.root) and p.is_file() else None

    def read_file(self, path: str) -> str | None:
        p = self._safe(path)
        if p is None:
            return None
        try:
            return p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def list_files(self) -> list[str]:
        skip = {".git", ".venv", "node_modules", "__pycache__"}
        out = []
        for p in self.root.rglob("*"):
            if p.is_file() and not any(part in skip for part in p.relative_to(self.root).parts):
                out.append(p.relative_to(self.root).as_posix())
        return sorted(out)


class InMemoryRepo:
    def __init__(self, files: dict[str, str]) -> None:
        self.files = dict(files)

    def read_file(self, path: str) -> str | None:
        return self.files.get(path)

    def list_files(self) -> list[str]:
        return sorted(self.files)
