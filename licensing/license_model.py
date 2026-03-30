"""
licensing/license_model.py — LicenseTier enum and LicenseInfo dataclass.

These are pure data classes with no external dependencies.  Safe to import
anywhere in the application without triggering the cryptography library.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class LicenseTier(str, Enum):
    """Commercial tier encoded inside the signed license payload."""
    UNLICENSED = "unlicensed"   # no key present / invalid key
    STANDARD   = "standard"    # single-seat, full hardware
    DEVELOPER  = "developer"   # standard + plugin SDK access
    SITE       = "site"        # multi-seat, full hardware + plugins


@dataclass
class LicenseInfo:
    """All information decoded from a validated license key."""

    tier:      LicenseTier
    customer:  str                    # customer / company name
    email:     str         = ""       # contact email
    seats:     int         = 1        # number of licensed seats
    issued:    str         = ""       # ISO date  YYYY-MM-DD
    expires:   Optional[str] = None   # ISO date, or None = perpetual
    serial:    str         = ""       # hardware serial lock (empty = any machine)
    raw_key:   str         = ""       # original key string (for re-saving)

    # ── Computed properties ──────────────────────────────────────────────

    @property
    def is_expired(self) -> bool:
        """True if the expiry date has passed."""
        if not self.expires:
            return False
        return self.expires < datetime.date.today().isoformat()

    @property
    def is_perpetual(self) -> bool:
        """True if the license has no expiry date."""
        return self.expires is None

    @property
    def days_until_expiry(self) -> Optional[int]:
        """Signed days remaining; negative means already expired."""
        if not self.expires:
            return None
        delta = datetime.date.fromisoformat(self.expires) - datetime.date.today()
        return delta.days

    @property
    def is_active(self) -> bool:
        """True when the license is present, not expired, and not UNLICENSED."""
        return self.tier != LicenseTier.UNLICENSED and not self.is_expired

    @property
    def tier_display(self) -> str:
        """Human-readable tier name for display in dialogs."""
        return {
            LicenseTier.UNLICENSED: "Unlicensed",
            LicenseTier.STANDARD:   "Standard",
            LicenseTier.DEVELOPER:  "Developer",
            LicenseTier.SITE:       "Site License",
        }.get(self.tier, self.tier.value.title())

    @property
    def expiry_display(self) -> str:
        """Human-readable expiry string."""
        if self.is_perpetual:
            return "Never (perpetual)"
        days = self.days_until_expiry
        if days is None:
            return "—"
        if days < 0:
            return f"Expired {abs(days)} days ago"
        if days == 0:
            return "Expires today"
        if days <= 30:
            return f"Expires in {days} days  ⚠"
        return self.expires   # plain date for anything > 30 days away


# ── Sentinel ─────────────────────────────────────────────────────────────────

#: Returned by load_license() when no valid key is found.
UNLICENSED = LicenseInfo(tier=LicenseTier.UNLICENSED, customer="")
