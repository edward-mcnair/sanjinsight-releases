"""
ai/manual_rag.py

Keyword-based retrieval-augmented generation (RAG) for the SanjINSIGHT
User Manual.

Design
------
* Parses UserManual.md by ## section headers at import time (cached via
  lru_cache so the file is only read once per process).
* Ranks sections by Jaccard similarity between query tokens and section
  body+heading tokens.
* Returns the top-N sections (each truncated to _MAX_WORDS_PER_SECTION) as
  a plain-text snippet ready to be appended to a query message.
* No external dependencies — pure stdlib + pathlib.

Token budget
------------
  Two sections × 250 words ≈ 650 tokens.  Combined with the system prompt
  (~2 600 tokens) and a typical question (~30 tokens) this stays well under
  the 4 096-token context window.

Usage
-----
    from ai.manual_rag import retrieve

    snippet = retrieve("what LED wavelength for GaAs?")
    # snippet is "" if no matching sections are found
    # or a plain-text block starting with "## Section Heading\\n..."
"""

from __future__ import annotations

import re
import pathlib
from functools import lru_cache

_MANUAL_PATH = pathlib.Path(__file__).parent.parent / "docs" / "UserManual.md"

# Maximum words per section returned in a snippet
_MAX_WORDS_PER_SECTION: int = 250

# Minimum Jaccard similarity (0–1) required to include a section.
# A low value intentionally casts a wide net; the top-N cap handles noise.
_MIN_SCORE: float = 0.01


# ── Synonym normalisation ─────────────────────────────────────────────────────
#
# Maps inflected / variant forms to their canonical token so that a query
# like "camera clipping" still matches manual sections that only say
# "saturation", and "calibrate temperature" matches "calibration".
#
# Applied symmetrically to *both* query tokens and section tokens, so
# Jaccard scores remain meaningful (the sets are normalised the same way).

_SYNONYMS: dict[str, str] = {
    # Camera / saturation
    "saturated":    "saturation",
    "saturating":   "saturation",
    "clipped":      "saturation",
    "clipping":     "saturation",
    "overexposed":  "saturation",
    # Temperature / thermal
    "overheating":  "thermal",
    "overheat":     "thermal",
    "overheated":   "thermal",
    # Calibration
    "calibrate":    "calibration",
    "calibrating":  "calibration",
    "calibrated":   "calibration",
    # Acquisition
    "acquire":      "acquisition",
    "acquiring":    "acquisition",
    "acquired":     "acquisition",
    # Troubleshooting
    "troubleshoot": "troubleshooting",
    "debug":        "troubleshooting",
    # Connection
    "disconnect":   "connection",
    "disconnected": "connection",
    "reconnect":    "connection",
    "reconnecting": "connection",
    # Export
    "exporting":    "export",
    "exported":     "export",
    # Analysis
    "analyze":      "analysis",
    "analyzed":     "analysis",
    "analyzing":    "analysis",
}


# ── Tokenisation ──────────────────────────────────────────────────────────────

def _tokenize(text: str) -> frozenset[str]:
    """Lowercase alphanumeric tokens of length ≥ 3, with synonym normalisation.

    Inflected or variant forms (e.g. "clipping", "calibrate") are mapped to
    their canonical form before being added to the token set, so Jaccard
    similarity is computed over normalised vocabulary on both sides.
    """
    tokens: set[str] = set()
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if len(w) >= 3:
            tokens.add(_SYNONYMS.get(w, w))
    return frozenset(tokens)


# ── Section parsing ───────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_sections() -> list[tuple[str, str, frozenset[str]]]:
    """
    Parse UserManual.md into a list of (heading, body, token_set) tuples.

    Returns an empty list if the file does not exist (packaged builds where
    the manual is not bundled, or unit tests running without the repo).

    The result is cached after the first call so repeated queries are O(1).
    """
    if not _MANUAL_PATH.exists():
        return []

    text = _MANUAL_PATH.read_text(encoding="utf-8")

    # Split on ## headings (but not ### or deeper)
    parts = re.split(r"(?m)^(## .+)$", text)

    sections: list[tuple[str, str, frozenset[str]]] = []
    # parts[0] is the document preamble before the first ## heading — skip it.
    # Remaining parts alternate: heading, body, heading, body, …
    i = 1
    while i + 1 < len(parts):
        heading = parts[i].strip()
        body    = parts[i + 1].strip()
        tokens  = _tokenize(heading + " " + body)
        if body:
            sections.append((heading, body, tokens))
        i += 2

    return sections


# ── Scoring & retrieval ───────────────────────────────────────────────────────

def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard similarity between two token sets."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _truncate(text: str, max_words: int) -> str:
    """Trim text to at most max_words words, appending ' …' when cut."""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + " \u2026"


def retrieve(
    query: str,
    n_sections: int = 2,
    min_score: float = _MIN_SCORE,
) -> str:
    """
    Retrieve the top-N most relevant User Manual sections for *query*.

    Parameters
    ----------
    query : str
        The user's question.  Used to score every manual section.
    n_sections : int
        Maximum number of sections to include in the returned snippet.
    min_score : float
        Minimum Jaccard score; sections below this threshold are discarded
        even if they are in the top-N.

    Returns
    -------
    str
        A plain-text snippet (one or more "## Heading\\nbody…" blocks
        separated by blank lines), or "" if no relevant sections found or
        the manual is not available.
    """
    sections = _load_sections()
    if not sections:
        return ""

    q_tokens = _tokenize(query)
    if not q_tokens:
        return ""

    scored = [
        (heading, body, _jaccard(q_tokens, tokens))
        for heading, body, tokens in sections
    ]
    scored.sort(key=lambda x: x[2], reverse=True)

    top = [(h, b) for h, b, s in scored[:n_sections] if s >= min_score]
    if not top:
        return ""

    return "\n\n".join(
        f"{heading}\n{_truncate(body, _MAX_WORDS_PER_SECTION)}"
        for heading, body in top
    )
