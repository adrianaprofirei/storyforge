"""Text helpers: tokenising lines into words, syllable estimates, speech duration."""

from __future__ import annotations

import re
import unicodedata

_WORD_RE = re.compile(r"[A-Za-z0-9À-ɏ']+(?:[-'][A-Za-z0-9À-ɏ]+)*|[^\sA-Za-z0-9]")


def slugify(text: str, max_len: int = 48) -> str:
    """ASCII snake_case id that starts with a letter, cut at a word boundary when possible."""
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"'", "", t)
    t = re.sub(r"[^a-zA-Z0-9]+", "_", t).strip("_").lower()
    if t and not t[0].isalpha():
        t = "x_" + t
    t = t or "item"
    if len(t) > max_len:
        cut = t[:max_len]
        t = cut.rsplit("_", 1)[0] if "_" in cut[max_len // 2:] else cut
    return t.strip("_") or "item"


def split_words(line: str) -> list[str]:
    """Words as displayed in captions (punctuation stays attached to the word)."""
    return [w for w in re.split(r"\s+", line.strip()) if w]


def bare_word(word: str) -> str:
    return re.sub(r"[^\w']", "", word).lower()


def syllables(word: str) -> int:
    w = bare_word(word)
    if not w:
        return 0
    if w.isdigit():
        return max(1, len(w))
    w = w.replace("'", "")
    groups = re.findall(r"[aeiouy]+", w)
    n = len(groups)
    if w.endswith("e") and not w.endswith(("le", "ee", "ye")) and n > 1:
        n -= 1
    return max(1, n)


PACE_FACTORS = {"slow": 0.8, "normal": 1.0, "fast": 1.18}


def estimate_speech_seconds(line: str, pace: str = "normal", emotion: str = "neutral") -> float:
    """Rough duration of a spoken line (used for silent mode and planning)."""
    words = split_words(line)
    if not words:
        return 0.0
    syl = sum(syllables(w) for w in words)
    rate = 4.6 * PACE_FACTORS.get(pace, 1.0)  # syllables per second, lively cartoon delivery
    if emotion in {"sad", "tired"}:
        rate *= 0.85
    elif emotion in {"shocked", "angry", "scared", "excited"}:
        rate *= 1.08
    pauses = sum(0.18 for w in words if w[-1:] in ",;:") + sum(0.25 for w in words if w[-1:] in ".!?…")
    return round(syl / rate + pauses + 0.15, 3)


def is_question(line: str) -> bool:
    return line.strip().endswith("?")


def ends_interrupted(line: str) -> bool:
    s = line.strip()
    return s.endswith(("—", "--", "-")) or s.endswith("...") and len(s) > 3 and s[-4] != "."
