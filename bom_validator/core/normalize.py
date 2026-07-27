"""Text normalisation utilities.

Real-world BOMs mix Persian/Arabic digits, non-breaking spaces, zero-width
joiners, Excel float artefacts ("1110101.0") and inconsistent casing. Every
comparison in the engine goes through here so matching is deterministic.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

# Persian & Arabic-Indic digits -> ASCII
_DIGIT_MAP = {
    **{ord("۰") + i: str(i) for i in range(10)},
    **{ord("٠") + i: str(i) for i in range(10)},
}

# Arabic letters that Persian users type interchangeably
_LETTER_MAP = {
    "ي": "ی",
    "ك": "ک",
    "ۀ": "ه",
    "ة": "ه",
    "أ": "ا",
    "إ": "ا",
    "آ": "ا",
    "ؤ": "و",
}

_ZERO_WIDTH = dict.fromkeys(
    map(ord, "\u200b\u200c\u200d\u200e\u200f\ufeff\u2060\u00ad"), None
)

_WS_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^0-9a-z\u0600-\u06ff]+")
_TRAILING_FLOAT_RE = re.compile(r"^(-?\d+)\.0+$")
_DESIGNATOR_SPLIT_RE = re.compile(r"[,;/\n\r\t|]+")
_DESIGNATOR_PART_RE = re.compile(r"^([A-Za-z_$#]+)\s*(\d+)$")
_RANGE_RE = re.compile(r"^([A-Za-z_$#]+)\s*(\d+)\s*[-–~]\s*(?:[A-Za-z_$#]*)(\d+)$")


def strip_zero_width(text: str) -> str:
    return text.translate(_ZERO_WIDTH)


def fold_digits(text: str) -> str:
    """Convert Persian/Arabic digits to ASCII digits."""
    return text.translate(_DIGIT_MAP)


def fold_letters(text: str) -> str:
    for src, dst in _LETTER_MAP.items():
        text = text.replace(src, dst)
    return text


_NULLISH = {"nan", "none", "nat", "<na>"}
_SIMPLE_RE = re.compile(r"^[!-~]+(?: [!-~]+)*$")  # printable ASCII, single spaces


def clean(value: object) -> str:
    """Light cleaning suitable for *display*: keeps case and inner spaces.

    A fast path short-circuits the common case (plain ASCII, already tidy),
    which is the majority of cells in a real workbook and avoids four full
    string rewrites per cell.
    """
    if value is None:
        return ""
    if type(value) is str:
        text = value
    elif isinstance(value, bool):
        text = str(value)
    elif isinstance(value, int):
        return str(value)
    else:
        text = str(value)

    if not text:
        return ""
    if _SIMPLE_RE.match(text):
        # already normalised: no unicode forms, no padding, no double spaces
        return "" if text.lower() in _NULLISH else text

    if text.strip().lower() in _NULLISH:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = strip_zero_width(text)
    text = fold_digits(text)
    text = text.replace("\u00a0", " ")
    return _WS_RE.sub(" ", text).strip()


@lru_cache(maxsize=100_000)
def canonical(
    value: str,
    *,
    case_insensitive: bool = True,
    strip_zeros: bool = False,
    trim_dot_zero: bool = True,
) -> str:
    """Aggressive normalisation used as a *matching key*."""
    text = clean(value)
    if not text:
        return ""
    text = fold_letters(text)
    if case_insensitive:
        text = text.lower()
    if trim_dot_zero:
        m = _TRAILING_FLOAT_RE.match(text)
        if m:
            text = m.group(1)
    if strip_zeros and text.isdigit():
        text = text.lstrip("0") or "0"
    return text


@lru_cache(maxsize=100_000)
def header_key(value: str) -> str:
    """Normalise a header cell for synonym lookup (no spaces/punctuation)."""
    text = canonical(value)
    text = fold_letters(text)
    return _NON_ALNUM_RE.sub("", text)


def to_int(value: object, default: int | None = None) -> int | None:
    """Robust integer coercion: handles '12', '12.0', '۱۲', ' 12 pcs'."""
    text = canonical(str(value)) if value is not None else ""
    if not text:
        return default
    try:
        return int(text)
    except ValueError:
        pass
    try:
        f = float(text)
        if f.is_integer():
            return int(f)
        return int(round(f))
    except ValueError:
        pass
    m = re.search(r"-?\d+(?:\.\d+)?", text)
    if m:
        try:
            return int(round(float(m.group())))
        except ValueError:
            return default
    return default


def to_float(value: object, default: float | None = None) -> float | None:
    text = canonical(str(value)) if value is not None else ""
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        m = re.search(r"-?\d+(?:\.\d+)?", text)
        return float(m.group()) if m else default


@lru_cache(maxsize=50_000)
def _expand_designators_text(text: str) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    tokens: list[str] = []
    for chunk in _DESIGNATOR_SPLIT_RE.split(text):
        chunk = chunk.strip()
        if not chunk:
            continue
        # "C1 C2 C3" (whitespace separated) is also a valid list, but
        # "C1 - C5" is a range and must survive intact.
        if _RANGE_RE.match(chunk):
            tokens.append(chunk)
        else:
            tokens.extend(t for t in chunk.split() if t)
    for token in tokens:
        rng = _RANGE_RE.match(token)
        if rng:
            prefix, start, end = rng.group(1), int(rng.group(2)), int(rng.group(3))
            if 0 <= end - start <= 4096:
                for n in range(start, end + 1):
                    d = f"{prefix}{n}"
                    if d.upper() not in seen:
                        seen.add(d.upper())
                        out.append(d)
                continue
        if token.upper() not in seen:
            seen.add(token.upper())
            out.append(token)
    return tuple(out)


def expand_designators(raw: object) -> tuple[str, ...]:
    """Split a designator cell into individual references.

    Understands comma/semicolon/newline separated lists and ranges such as
    ``C1-C5`` or ``R10~R14`` which are expanded to the full sequence.
    """
    text = clean(raw)
    if not text:
        return ()
    return _expand_designators_text(text)


def designator_sort_key(designator: str) -> tuple[str, int, str]:
    """Natural sort: C2 before C10."""
    m = _DESIGNATOR_PART_RE.match(designator.strip())
    if m:
        return (m.group(1).upper(), int(m.group(2)), "")
    return (designator.upper(), 0, designator)


_TOKEN_SPLIT_RE = re.compile(r"[\s,]+")


@lru_cache(maxsize=200_000)
def _similarity_cached(a: str, b: str) -> float:
    from difflib import SequenceMatcher

    # keep difflib's default heuristics so scores match previous releases
    base = SequenceMatcher(None, a, b).ratio()
    ta, tb = set(_TOKEN_SPLIT_RE.split(a)), set(_TOKEN_SPLIT_RE.split(b))
    if ta and tb:
        jac = len(ta & tb) / len(ta | tb)
        return max(base, (base + jac) / 2)
    return base


def similarity(a: str, b: str) -> float:
    """Cheap token-aware similarity in [0, 1] (no external deps).

    Memoised, so the repeated comparisons performed while fuzzy-matching a
    BOM against thousands of placements are served from cache.
    """
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # NB: SequenceMatcher is not symmetric, so the argument order is part of
    # the cache key — swapping it would change historical scores.
    return _similarity_cached(a, b)


def similarity_at_least(a: str, b: str, threshold: float) -> float:
    """``similarity(a, b)`` but returns 0.0 as soon as the pair cannot reach
    ``threshold``.

    ``real_quick_ratio``/``quick_ratio`` are upper bounds on the raw ratio and
    cost O(n) instead of O(n·m). Because the token blend can lift the raw
    ratio to at most ``(ratio + 1) / 2``, a pair whose upper bound is below
    ``2 * threshold - 1`` can never qualify and is discarded without running
    the expensive matcher. The score of every pair that *does* qualify is
    exactly what :func:`similarity` returns.
    """
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    from difflib import SequenceMatcher

    # small epsilon so a pair sitting exactly on the bound is never dropped
    need = 2.0 * threshold - 1.0 - 1e-9
    if need > 0.0:
        probe = SequenceMatcher(None, a, b)
        if probe.real_quick_ratio() < need or probe.quick_ratio() < need:
            return 0.0
    return _similarity_cached(a, b)


def clear_caches() -> None:
    """Reset the memoisation tables (used by tests and long-running GUIs)."""
    canonical.cache_clear()
    header_key.cache_clear()
    _similarity_cached.cache_clear()
    _expand_designators_text.cache_clear()


def cache_info() -> dict[str, tuple[int, int, int]]:
    """Hits/misses/size per cache — handy for profiling a slow workbook."""
    return {
        "canonical": (
            canonical.cache_info().hits,
            canonical.cache_info().misses,
            canonical.cache_info().currsize,
        ),
        "header_key": (
            header_key.cache_info().hits,
            header_key.cache_info().misses,
            header_key.cache_info().currsize,
        ),
        "similarity": (
            _similarity_cached.cache_info().hits,
            _similarity_cached.cache_info().misses,
            _similarity_cached.cache_info().currsize,
        ),
    }
