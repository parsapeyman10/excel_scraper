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


def clean(value: object) -> str:
    """Light cleaning suitable for *display*: keeps case and inner spaces."""
    if value is None:
        return ""
    text = str(value)
    if text.strip().lower() in {"nan", "none", "nat", "<na>"}:
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


def expand_designators(raw: object) -> tuple[str, ...]:
    """Split a designator cell into individual references.

    Understands comma/semicolon/newline separated lists and ranges such as
    ``C1-C5`` or ``R10~R14`` which are expanded to the full sequence.
    """
    text = clean(raw)
    if not text:
        return ()
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


def designator_sort_key(designator: str) -> tuple[str, int, str]:
    """Natural sort: C2 before C10."""
    m = _DESIGNATOR_PART_RE.match(designator.strip())
    if m:
        return (m.group(1).upper(), int(m.group(2)), "")
    return (designator.upper(), 0, designator)


def similarity(a: str, b: str) -> float:
    """Cheap token-aware similarity in [0, 1] (no external deps)."""
    from difflib import SequenceMatcher

    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    base = SequenceMatcher(None, a, b).ratio()
    ta, tb = set(re.split(r"[\s,]+", a)), set(re.split(r"[\s,]+", b))
    if ta and tb:
        jac = len(ta & tb) / len(ta | tb)
        return max(base, (base + jac) / 2)
    return base
