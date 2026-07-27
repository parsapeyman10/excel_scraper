"""Input sources: one combined workbook, or three separate files.

Two shop-floor realities are supported:

``single``
    One workbook that already contains the BOM sheet plus the ``top`` / ``bot``
    placement sheets — the classic layout this tool was born with.

``multi``
    Three independent files, exactly how the machine room usually exports
    them: the *مونتاژ ماشینی* (BOM) workbook, the **top** pick-and-place file
    and the **bot** pick-and-place file. Any of the two placement files may be
    omitted for a single-sided board.

Everything downstream (engine, CLI, GUI, reports) speaks :class:`SourceSet`,
so a plain path keeps working everywhere thanks to :meth:`SourceSet.coerce`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import sha256_file

SINGLE = "single"
MULTI = "multi"


class SourceError(ValueError):
    """Raised when a source set is incomplete or points at missing files."""


@dataclass(frozen=True, slots=True)
class SourceSet:
    """The file(s) one validation run reads from."""

    bom: Path
    top: Path | None = None
    bot: Path | None = None
    mode: str = SINGLE

    # -- constructors --------------------------------------------------
    @classmethod
    def single(cls, path: str | Path) -> SourceSet:
        return cls(bom=Path(path), mode=SINGLE)

    @classmethod
    def multi(
        cls,
        bom: str | Path,
        top: str | Path | None = None,
        bot: str | Path | None = None,
    ) -> SourceSet:
        return cls(
            bom=Path(bom),
            top=Path(top) if top else None,
            bot=Path(bot) if bot else None,
            mode=MULTI,
        )

    @classmethod
    def coerce(cls, value: Any) -> SourceSet:
        """Accept a :class:`SourceSet`, a path, or a mapping/sequence of paths."""
        if isinstance(value, SourceSet):
            return value
        if isinstance(value, (str, Path)):
            return cls.single(value)
        if isinstance(value, dict):
            return cls.multi(value["bom"], value.get("top"), value.get("bot"))
        if isinstance(value, (list, tuple)):
            parts = list(value) + [None, None]
            return cls.multi(parts[0], parts[1], parts[2])
        raise SourceError(f"Cannot interpret {value!r} as an input source")

    # -- queries -------------------------------------------------------
    @property
    def is_multi(self) -> bool:
        return self.mode == MULTI

    @property
    def primary(self) -> Path:
        """The path reports are named and keyed after."""
        return self.bom

    @property
    def paths(self) -> list[Path]:
        """Every distinct file that will be read, BOM first."""
        out: list[Path] = []
        for p in (self.bom, self.top, self.bot):
            if p is not None and not any(p == q for q in out):
                out.append(p)
        return out

    @property
    def label(self) -> str:
        if not self.is_multi:
            return self.bom.name
        parts = [f"BOM:{self.bom.name}"]
        if self.top:
            parts.append(f"TOP:{self.top.name}")
        if self.bot:
            parts.append(f"BOT:{self.bot.name}")
        return "  +  ".join(parts)

    def role_of(self, path: str | Path) -> str:
        p = Path(path)
        if not self.is_multi:
            return "workbook"
        if self.top and p == self.top:
            return "top"
        if self.bot and p == self.bot:
            return "bot"
        return "bom"

    # -- validation ----------------------------------------------------
    def validate(self) -> SourceSet:
        if self.mode not in (SINGLE, MULTI):
            raise SourceError(f"Unknown source mode {self.mode!r}")
        if self.is_multi and not self.top and not self.bot:
            raise SourceError(
                "Select at least one placement file (top or bot) in three-file mode."
            )
        missing = [str(p) for p in self.paths if not p.exists()]
        if missing:
            raise SourceError("File not found: " + ", ".join(missing))
        return self

    # -- fingerprint ---------------------------------------------------
    def sha256(self) -> str:
        """Content hash of the whole set (single file → that file's hash)."""
        digests = [sha256_file(str(p)) for p in self.paths]
        if len(digests) == 1:
            return digests[0]
        h = hashlib.sha256()
        for p, d in zip(self.paths, digests, strict=True):
            h.update(f"{p.name}:{d};".encode())
        return h.hexdigest()

    def total_size(self) -> int:
        return sum(p.stat().st_size for p in self.paths if p.exists())

    # -- serialisation -------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "bom": str(self.bom),
            "top": str(self.top) if self.top else "",
            "bot": str(self.bot) if self.bot else "",
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceSet:
        mode = data.get("mode", SINGLE)
        if mode == MULTI:
            return cls.multi(data["bom"], data.get("top") or None, data.get("bot") or None)
        return cls.single(data["bom"])
