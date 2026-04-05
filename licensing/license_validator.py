"""
licensing/license_validator.py — Ed25519 license key validation.

How it works
------------
Microsanj generates license keys offline using tools/gen_license.py with
a private Ed25519 key that never leaves their possession.

Each key is:   <base64url(json_payload)>.<base64url(ed25519_signature)>

The JSON payload contains customer info, tier, seat count, and expiry.
The app verifies the signature using the PUBLIC key baked in below —
so it can validate licenses completely offline without any server call.

Because Ed25519 is asymmetric, possessing the public key (which is in
every installed copy) does NOT allow generating new valid license keys.
Only the holder of the matching private key can do that.

Key generation
--------------
See tools/gen_license.py for the offline signing tool.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Optional

from licensing.license_model import LicenseInfo, LicenseTier, UNLICENSED

log = logging.getLogger(__name__)

# ── Baked-in public key ───────────────────────────────────────────────────────
# Ed25519 raw public key (32 bytes), base64-encoded.
# The matching PRIVATE KEY is held by Microsanj and never distributed.
# Regenerate the keypair with:  python tools/gen_license.py --generate-keys
_PUBLIC_KEY_B64 = "ge2cJaHYRA7ux6Um+W0J5yznK4Axsz6p8yzoY76S6is="


# ── Public API ────────────────────────────────────────────────────────────────

def validate_key(key_string: str) -> Optional[LicenseInfo]:
    """
    Validate a license key string.

    Returns a populated LicenseInfo on success, or None if:
      • the format is invalid
      • the signature does not verify
      • the license has expired

    This function is intentionally silent — all failures go to log.debug
    so users cannot use error messages to diagnose what is "wrong" with a
    forged key.
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
    except ImportError:
        log.warning("cryptography package not installed — license validation disabled")
        return None

    try:
        parts = key_string.strip().split(".")
        if len(parts) != 2:
            log.debug("License key: wrong number of segments (expected 2)")
            return None

        payload_b64, sig_b64 = parts

        # urlsafe_b64decode tolerates missing padding
        payload_bytes = base64.urlsafe_b64decode(payload_b64 + "==")
        sig_bytes     = base64.urlsafe_b64decode(sig_b64     + "==")

        # Load and verify
        pub_key_bytes = base64.b64decode(_PUBLIC_KEY_B64)
        pub_key = Ed25519PublicKey.from_public_bytes(pub_key_bytes)
        pub_key.verify(sig_bytes, payload_bytes)   # raises InvalidSignature if bad

        data = json.loads(payload_bytes.decode("utf-8"))

        tier_str = data.get("tier", "unlicensed")
        try:
            tier = LicenseTier(tier_str)
        except ValueError:
            log.debug(f"License key: unknown tier {tier_str!r}")
            return None

        info = LicenseInfo(
            tier     = tier,
            customer = data.get("customer", ""),
            email    = data.get("email", ""),
            seats    = int(data.get("seats", 1)),
            issued   = data.get("issued", ""),
            expires  = data.get("expires"),   # None if omitted = perpetual
            serial   = data.get("serial", ""),
            raw_key  = key_string.strip(),
        )

        if info.is_expired:
            log.info(f"License for {info.customer!r} expired on {info.expires}")
            return None

        log.info(
            f"License validated: {info.tier.value} / {info.customer!r} "
            f"(expires: {info.expires or 'never'})"
        )
        return info

    except InvalidSignature:
        log.debug("License key: signature invalid")
        return None
    except Exception as e:
        log.debug(f"License key validation error: {e}")
        return None


def load_license(prefs) -> LicenseInfo:
    """
    Load and validate the saved license key from user preferences.

    Returns the UNLICENSED sentinel if no key is stored or the key is
    invalid / expired.  Never raises.
    """
    key_string = prefs.get_pref("license.key", "")
    if not key_string:
        log.debug("No license key found in preferences")
        return UNLICENSED
    log.info("License key found in preferences (%d chars), validating…",
             len(key_string))
    info = validate_key(key_string)
    if info is None:
        log.warning("Stored license key failed validation — key is present "
                     "but could not be verified (cryptography issue?)")
    return info if info is not None else UNLICENSED


def save_license_key(prefs, key_string: str) -> Optional[LicenseInfo]:
    """
    Validate and persist a license key to user preferences.

    Returns the LicenseInfo on success, or None if the key is invalid.
    Does NOT save invalid keys.
    """
    info = validate_key(key_string)
    if info is not None:
        prefs.set_pref("license.key", key_string.strip())
        log.info(f"License key saved for {info.customer!r}")
    return info


def remove_license(prefs) -> None:
    """Remove the stored license key from user preferences."""
    prefs.set_pref("license.key", "")
    log.info("License key removed")
