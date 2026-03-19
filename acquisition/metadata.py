"""
acquisition/metadata.py

Per-result annotation: imaging modality, camera identity, tags, and
timestamped notes.

This module is intentionally decoupled from the acquisition pipeline so
it can be extended — new fields, new modalities, richer provenance — without
touching any computation code.

Key types
---------
NoteEntry       — one timestamped observation with author + free text.
ResultMetadata  — full annotation bag attached to one result or session.
TagRegistry     — global persistent store of all tags ever used; drives
                  autocomplete in the UI.  Singleton via get_registry().

Tag normalisation
-----------------
Tags are stored as plain lowercase strings with spaces replaced by hyphens.
The ``#`` prefix is accepted in input (familiar from social media / Slack)
but stripped before storage so ``#thermal-soak`` and ``thermal-soak`` are
the same tag.

Extending this module
---------------------
To add a new annotation field:
    1. Add it to ResultMetadata with a sensible default.
    2. Add to_dict() / from_dict() serialisation.
    3. Add corresponding field to SessionMeta in acquisition/session.py
       and bump CURRENT_SCHEMA in schema_migrations.py.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from typing import List, Optional

log = logging.getLogger(__name__)

# Registry file location — user-scoped so it accumulates across projects.
_DEFAULT_REGISTRY_PATH = os.path.expanduser("~/.microsanj/tag_registry.json")


# ── Note entry ─────────────────────────────────────────────────────────────

@dataclass
class NoteEntry:
    """One timestamped observation attached to a result.

    Notes are append-only: a note that has been saved is never edited,
    preserving the scientific record.  New observations are new entries.

    Fields
    ------
    timestamp       Unix epoch float (for sorting / duration maths).
    timestamp_str   Human-readable copy; generated in __post_init__ if empty.
    author          Operator name or login; may be empty.
    text            The observation text.  No length limit enforced here.
    """
    timestamp:     float = field(default_factory=time.time)
    timestamp_str: str   = ""
    author:        str   = ""
    text:          str   = ""

    def __post_init__(self) -> None:
        if not self.timestamp_str:
            self.timestamp_str = time.strftime(
                "%Y-%m-%d  %H:%M", time.localtime(self.timestamp))

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "NoteEntry":
        known = NoteEntry.__dataclass_fields__
        return NoteEntry(**{k: v for k, v in d.items() if k in known})


# ── Result metadata ────────────────────────────────────────────────────────

@dataclass
class ResultMetadata:
    """Annotation bag for one acquisition or scan result.

    Designed to be lightweight so it can be created at result-display time,
    filled in by the operator, and then passed to Session.from_result().

    Fields
    ------
    modality    Imaging modality string.  Canonical values:
                  "thermoreflectance"  TR lock-in signal (ΔR/R)
                  "ir_lockin"          IR lock-in signal
                  "ir_passive"         Passive IR (no lock-in)
                  "hybrid"             Simultaneous TR + IR
                  "optical"            Optical pump-probe
                Set automatically from the camera/hardware selection;
                operators should not need to type this.

    camera_id   Hardware identifier stamped at acquisition time.
                Examples: "TR-Andor-iStar-SN12345", "IR-FLIR-A35-SN67890".
                On single-camera systems this is the only camera.
                On dual-camera systems the operator selects a camera before
                scanning; this field records which one was used.
                Locked after acquisition — cannot be edited post-hoc.

    tags        User-defined label strings.  Stored without ``#`` prefix,
                lowercase, spaces replaced by hyphens.
                Examples: ["thermal-soak", "pre-etch", "lot-42"].

    notes       Append-only list of NoteEntry objects.  Use add_note() to
                append; do not modify the list directly.
    """

    modality:  str             = "thermoreflectance"
    camera_id: str             = ""
    tags:      List[str]       = field(default_factory=list)
    notes:     List[NoteEntry] = field(default_factory=list)

    # ── Mutation helpers ───────────────────────────────────────────────

    def add_note(self, text: str, author: str = "") -> NoteEntry:
        """Append a new timestamped note.  Returns the created entry."""
        entry = NoteEntry(text=text.strip(), author=author.strip())
        self.notes.append(entry)
        return entry

    def add_tag(self, tag: str) -> None:
        """Normalise and add *tag*; no-op if already present."""
        tag = normalise_tag(tag)
        if tag and tag not in self.tags:
            self.tags.append(tag)

    def remove_tag(self, tag: str) -> None:
        """Remove *tag* if present; no-op otherwise."""
        self.tags = [t for t in self.tags if t != normalise_tag(tag)]

    def set_tags(self, tags: List[str]) -> None:
        """Replace the entire tag list (normalises each entry)."""
        self.tags = [normalise_tag(t) for t in tags if normalise_tag(t)]

    # ── Serialisation ─────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "modality":  self.modality,
            "camera_id": self.camera_id,
            "tags":      list(self.tags),
            "notes":     [n.to_dict() for n in self.notes],
        }

    @staticmethod
    def from_dict(d: dict) -> "ResultMetadata":
        notes = [NoteEntry.from_dict(n) for n in d.get("notes", [])]
        return ResultMetadata(
            modality  = d.get("modality",  "thermoreflectance"),
            camera_id = d.get("camera_id", ""),
            tags      = [normalise_tag(t) for t in d.get("tags", []) if t],
            notes     = notes,
        )

    @staticmethod
    def empty() -> "ResultMetadata":
        """Return a blank metadata instance."""
        return ResultMetadata()


# ── Tag normalisation ──────────────────────────────────────────────────────

def normalise_tag(tag: str) -> str:
    """Canonical form: strip whitespace and ``#``, lowercase, spaces→hyphens.

    >>> normalise_tag("  #Thermal Soak  ")
    'thermal-soak'
    """
    return tag.strip().lstrip("#").lower().replace(" ", "-")


# ── Tag registry ───────────────────────────────────────────────────────────

class TagRegistry:
    """Persistent store of all tags used in the application.

    Each tag is stored with a usage count so suggestions can be ranked
    by frequency.  The backing file is a simple JSON dict::

        { "thermal-soak": 12, "pre-etch": 5, "lot-42": 1 }

    Usage
    -----
    All UI components should call ``get_registry()`` to access the
    module-level singleton rather than constructing a new instance.

        registry = get_registry()
        registry.suggest("the")        # → ["thermal-soak", "thermal-stress"]
        registry.record(["lot-42"])    # after saving a session

    Extending
    ---------
    To add tag categories (e.g. "Process step", "Lot/Wafer"), store
    category metadata in a separate dict inside the JSON file.  The
    ``_counts`` key can remain as-is for backward compatibility.
    """

    def __init__(self, path: str = _DEFAULT_REGISTRY_PATH) -> None:
        self._path   = path
        self._counts: dict[str, int] = {}
        self._load()

    # ── Persistence ───────────────────────────────────────────────────

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                # Support both flat {"tag": N} and wrapped {"counts": {...}}
                counts = data.get("counts", data)
                self._counts = {str(k): int(v) for k, v in counts.items()
                                if not k.startswith("_")}
        except json.JSONDecodeError as exc:
            # Corrupt / truncated file — rename it so the user keeps their data
            # and we start fresh rather than crashing or silently losing tags.
            bak = self._path + ".bak"
            try:
                os.replace(self._path, bak)
                log.warning(
                    "TagRegistry: '%s' is corrupt (%s) — moved to '%s'; "
                    "starting with an empty registry.",
                    self._path, exc, bak,
                )
            except OSError:
                log.warning(
                    "TagRegistry: '%s' is corrupt (%s) — could not rename; "
                    "starting with an empty registry.",
                    self._path, exc,
                )
        except Exception:
            log.debug("TagRegistry: could not load %s", self._path, exc_info=True)

    def save(self) -> None:
        """Persist registry to disk.  Called automatically by record()."""
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump({"counts": self._counts}, f, indent=2, sort_keys=True)
        except Exception:
            log.debug("TagRegistry: could not save %s", self._path, exc_info=True)

    # ── Core operations ───────────────────────────────────────────────

    def record(self, tags: List[str]) -> None:
        """Increment usage count for each tag and save.

        Call this once per session-save so counts reflect real usage.
        """
        for raw in tags:
            tag = normalise_tag(raw)
            if tag:
                self._counts[tag] = self._counts.get(tag, 0) + 1
        self.save()

    def suggest(self, prefix: str = "", limit: int = 8) -> List[str]:
        """Return up to *limit* tags matching *prefix*, ranked by usage.

        If *prefix* is empty, returns the most frequently used tags.
        """
        prefix = normalise_tag(prefix)
        if prefix:
            matches = [t for t in self._counts if t.startswith(prefix)]
        else:
            matches = list(self._counts)
        matches.sort(key=lambda t: -self._counts.get(t, 0))
        return matches[:limit]

    def all_tags(self) -> List[str]:
        """All known tags sorted by usage count descending."""
        return sorted(self._counts, key=lambda t: -self._counts[t])

    def usage(self, tag: str) -> int:
        """Return usage count for *tag* (0 if unknown)."""
        return self._counts.get(normalise_tag(tag), 0)

    def __len__(self) -> int:
        return len(self._counts)

    def __contains__(self, tag: str) -> bool:
        return normalise_tag(tag) in self._counts


# ── Module-level singleton ─────────────────────────────────────────────────

_registry: Optional[TagRegistry] = None


def get_registry() -> TagRegistry:
    """Return the module-level TagRegistry singleton.

    Initialised lazily on first call so import is always safe even if
    the registry file does not yet exist.
    """
    global _registry
    if _registry is None:
        _registry = TagRegistry()
    return _registry
