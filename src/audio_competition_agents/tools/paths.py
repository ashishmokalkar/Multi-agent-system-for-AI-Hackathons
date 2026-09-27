from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .base import ToolPermissionError


@dataclass(frozen=True)
class PathPolicy:
    read_roots: tuple[Path, ...]
    write_root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "read_roots", tuple(root.resolve() for root in self.read_roots))
        object.__setattr__(self, "write_root", self.write_root.resolve())

    @staticmethod
    def _inside(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def readable(self, value: str | Path) -> Path:
        path = Path(value).expanduser().resolve()
        if not any(self._inside(path, root) for root in self.read_roots):
            raise ToolPermissionError(f"read path is outside configured roots: {path}")
        if not path.exists():
            raise FileNotFoundError(path)
        return path

    def writable(self, value: str | Path) -> Path:
        path = Path(value).expanduser().resolve()
        if not self._inside(path, self.write_root):
            raise ToolPermissionError(f"write path is outside run root: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
