"""
ai/manual_rag.py

Keyword-based retrieval-augmented generation (RAG) for the SanjINSIGHT
User Manual.

Design
------
* Parses UserManual.md by ## section headers at import time (cached via
  lru_cache so the file is only read once per process).
* Ranks sections by BM25 relevance score — a well-established probabilistic
  retrieval model that weights rare matching terms more heavily than common
  ones and normalises for document length (Okapi BM25, k1=1.5, b=0.75).
* The BM25 index is built lazily alongside the section list and cached.
* For the public min_score threshold, Jaccard similarity (0–1) is used so
  the API contract remains stable and existing callers / tests are unaffected;
  BM25 only affects the *ordering* of results above the threshold.
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

import math
import re
import pathlib
from collections import Counter
from functools import lru_cache

_MANUAL_PATH = pathlib.Path(__file__).parent.parent / "docs" / "UserManual.md"

# Maximum words per section returned in a snippet
_MAX_WORDS_PER_SECTION: int = 250

# Minimum Jaccard similarity (0–1) required to include a section.
# A low value intentionally casts a wide net; the top-N cap handles noise.
# BM25 is used for *ordering* above this threshold, not for filtering.
_MIN_SCORE: float = 0.01

# BM25 tuning parameters (standard Okapi BM25 defaults)
_BM25_K1: float = 1.5   # term saturation: higher → more weight on TF
_BM25_B:  float = 0.75  # length normalisation: 1.0 = full, 0.0 = none


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


def _tokenize_list(text: str) -> list[str]:
    """Return a list of normalised tokens (with repetitions) for BM25 TF counts."""
    tokens: list[str] = []
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if len(w) >= 3:
            tokens.append(_SYNONYMS.get(w, w))
    return tokens


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


# ── BM25 index ────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_bm25_index() -> tuple[dict, list, list, float]:
    """
    Build a BM25 index over all manual sections.  Cached after first call.

    Returns
    -------
    idf : dict[str, float]
        Inverse document frequency per normalised term.
    term_freqs : list[Counter]
        Per-section term frequency counters (one Counter per section,
        same order as _load_sections()).
    doc_lengths : list[int]
        Total token count per section.
    avgdl : float
        Average document length across all sections.

    If the manual is not available, returns ({}, [], [], 1.0).
    """
    sections = _load_sections()
    if not sections:
        return {}, [], [], 1.0

    n          = len(sections)
    term_freqs: list[Counter] = []
    doc_lengths: list[int]   = []

    for heading, body, _ in sections:
        tokens = _tokenize_list(heading + " " + body)
        term_freqs.append(Counter(tokens))
        doc_lengths.append(len(tokens))

    avgdl = sum(doc_lengths) / n if n else 1.0

    # IDF: Okapi BM25 IDF formula (smooth, always positive)
    #   idf(t) = log( (N - df(t) + 0.5) / (df(t) + 0.5) + 1 )
    df: Counter = Counter()
    for tf in term_freqs:
        for term in tf:
            df[term] += 1

    idf: dict[str, float] = {
        term: math.log((n - freq + 0.5) / (freq + 0.5) + 1)
        for term, freq in df.items()
    }

    return idf, term_freqs, doc_lengths, avgdl


# ── Scoring & retrieval ───────────────────────────────────────────────────────

def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Jaccard similarity between two token sets."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _bm25(query_tokens: frozenset[str],
          idf: dict, tf_counter: Counter,
          doc_len: int, avgdl: float) -> float:
    """
    Okapi BM25 relevance score for one document given a query.

    Parameters
    ----------
    query_tokens : frozenset[str]
        Normalised, unique query terms (from _tokenize()).
    idf : dict
        IDF weights from _load_bm25_index().
    tf_counter : Counter
        Term frequencies for this document.
    doc_len : int
        Total token count in this document.
    avgdl : float
        Average document length across the corpus.
    """
    score    = 0.0
    k1, b    = _BM25_K1, _BM25_B
    dl_norm  = 1 - b + b * doc_len / avgdl   # length normalisation factor
    for term in query_tokens:
        term_idf = idf.get(term, 0.0)
        if term_idf == 0.0:
            continue
        tf = tf_counter.get(term, 0)
        score += term_idf * (tf * (k1 + 1)) / (tf + k1 * dl_norm)
    return score


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

    Sections are filtered by Jaccard similarity ≥ min_score (stable API
    contract), then re-ranked by BM25 score for better result ordering.

    Parameters
    ----------
    query : str
        The user's question.  Used to score every manual section.
    n_sections : int
        Maximum number of sections to include in the returned snippet.
    min_score : float
        Minimum Jaccard score (0–1); sections below this threshold are
        discarded even if they score well under BM25.

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

    # Build BM25 index (cached after first call)
    idf, term_freqs, doc_lengths, avgdl = _load_bm25_index()

    # Score each section: filter by Jaccard threshold, rank by BM25
    scored: list[tuple[str, str, float]] = []   # (heading, body, bm25_score)
    for i, (heading, body, tokens) in enumerate(sections):
        jac = _jaccard(q_tokens, tokens)
        if jac < min_score:
            continue
        bm = _bm25(q_tokens, idf, term_freqs[i], doc_lengths[i], avgdl)
        scored.append((heading, body, bm))

    if not scored:
        return ""

    scored.sort(key=lambda x: x[2], reverse=True)
    top = [(h, b) for h, b, _ in scored[:n_sections]]

    return "\n\n".join(
        f"{heading}\n{_truncate(body, _MAX_WORDS_PER_SECTION)}"
        for heading, body in top
    )
