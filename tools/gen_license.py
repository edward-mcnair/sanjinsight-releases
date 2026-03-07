#!/usr/bin/env python3
"""
tools/gen_license.py — Microsanj SanjINSIGHT license key generator.

╔══════════════════════════════════════════════════════════════════╗
║  PRIVATE TOOL — do not include in the installer or distribute.   ║
║  Keep the private key file in a secure location (password        ║
║  manager, encrypted drive).  NEVER commit it to the repository.  ║
╚══════════════════════════════════════════════════════════════════╝

Setup (first time only)
-----------------------
  python tools/gen_license.py --generate-keys
  → Writes: microsanj_license_private.key  (keep secret)
  → Prints: the matching PUBLIC key to paste into license_validator.py

Generate a standard 1-year license
------------------------------------
  python tools/gen_license.py \\
      --key-file microsanj_license_private.key \\
      --customer "Stanford University" \\
      --email    lab@stanford.edu \\
      --tier     standard \\
      --seats    1 \\
      --days     365

Generate a perpetual site license (10 seats)
---------------------------------------------
  python tools/gen_license.py \\
      --key-file microsanj_license_private.key \\
      --customer "TSMC Research" \\
      --email    research@tsmc.com \\
      --tier     site \\
      --seats    10 \\
      --perpetual

Verify a key (without the private key)
---------------------------------------
  python tools/gen_license.py --verify "eyJ....<sig>"
"""

from __future__ import annotations

import argparse
import base64
import datetime
import json
import os
import sys


# ── Key generation ────────────────────────────────────────────────────────────

def generate_keys(output_file: str) -> None:
    """Generate a new Ed25519 keypair and save the private key to a file."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PublicFormat, PrivateFormat, NoEncryption,
    )

    private_key = Ed25519PrivateKey.generate()
    public_key  = private_key.public_key()

    priv_bytes = private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    pub_bytes  = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)

    priv_b64 = base64.b64encode(priv_bytes).decode()
    pub_b64  = base64.b64encode(pub_bytes).decode()

    with open(output_file, "w") as f:
        f.write(priv_b64 + "\n")

    print(f"[OK] Private key saved to: {output_file}")
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║  Paste this PUBLIC KEY into licensing/license_validator.py ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()
    print(f'_PUBLIC_KEY_B64 = "{pub_b64}"')
    print()
    print("[!] Store the private key file securely — never commit it to git.")


def load_private_key(key_file: str):
    """Load an Ed25519 private key from a base64 file."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PrivateFormat, NoEncryption,
    )
    with open(key_file) as f:
        priv_b64 = f.read().strip()
    priv_bytes = base64.b64decode(priv_b64)
    return Ed25519PrivateKey.from_private_bytes(priv_bytes)


# ── License generation ────────────────────────────────────────────────────────

def generate_license(
    private_key,
    customer:  str,
    email:     str,
    tier:      str,
    seats:     int,
    days:      int | None,
    perpetual: bool,
    serial:    str = "",
) -> str:
    """Sign a license payload and return the key string."""
    today = datetime.date.today()

    payload: dict = {
        "customer": customer,
        "email":    email,
        "tier":     tier,
        "seats":    seats,
        "issued":   today.isoformat(),
        "serial":   serial,
    }

    if not perpetual and days is not None:
        expiry = today + datetime.timedelta(days=days)
        payload["expires"] = expiry.isoformat()
    # omit "expires" for perpetual licenses

    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig_bytes     = private_key.sign(payload_bytes)

    payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode().rstrip("=")
    sig_b64     = base64.urlsafe_b64encode(sig_bytes).decode().rstrip("=")

    return f"{payload_b64}.{sig_b64}"


# ── Verification ──────────────────────────────────────────────────────────────

def verify_key(key_string: str) -> None:
    """Verify a key using the public key embedded in license_validator.py."""
    # Add the project root to path so we can import the licensing module
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, project_root)
    from licensing.license_validator import validate_key

    info = validate_key(key_string)
    if info is None:
        print("[FAIL] Key is INVALID or EXPIRED")
    else:
        print("[OK] Key is VALID")
        print(f"  Customer : {info.customer}")
        print(f"  Email    : {info.email}")
        print(f"  Tier     : {info.tier_display}")
        print(f"  Seats    : {info.seats}")
        print(f"  Issued   : {info.issued}")
        print(f"  Expires  : {info.expiry_display}")
        print(f"  Serial   : {info.serial or '(any machine)'}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="SanjINSIGHT license key generator (Microsanj internal tool)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--generate-keys",
        action="store_true",
        help="Generate a new Ed25519 keypair (first-time setup)",
    )
    mode.add_argument(
        "--key-file", metavar="FILE",
        help="Path to the private key file (base64, one line)",
    )
    mode.add_argument(
        "--verify", metavar="KEY_STRING",
        help="Verify an existing license key string",
    )

    # Key generation options
    parser.add_argument(
        "--output", default="microsanj_license_private.key",
        help="Output file for new private key (default: microsanj_license_private.key)",
    )

    # License fields
    parser.add_argument("--customer", default="",   help="Customer / company name")
    parser.add_argument("--email",    default="",   help="Contact email address")
    parser.add_argument("--tier",     default="standard",
                        choices=["standard", "site"],
                        help="License tier (default: standard)")
    parser.add_argument("--seats",    type=int, default=1,
                        help="Number of seats (default: 1)")
    parser.add_argument("--days",     type=int, default=365,
                        help="Validity period in days (default: 365)")
    parser.add_argument("--perpetual", action="store_true",
                        help="Issue a perpetual license (no expiry date)")
    parser.add_argument("--serial",   default="",
                        help="Optional hardware serial number to lock the license to")

    args = parser.parse_args()

    if args.generate_keys:
        generate_keys(args.output)

    elif args.verify:
        verify_key(args.verify)

    else:
        # Generate a license key
        if not args.customer:
            parser.error("--customer is required when generating a license")

        private_key = load_private_key(args.key_file)
        key_string  = generate_license(
            private_key = private_key,
            customer    = args.customer,
            email       = args.email,
            tier        = args.tier,
            seats       = args.seats,
            days        = args.days if not args.perpetual else None,
            perpetual   = args.perpetual,
            serial      = args.serial,
        )

        expiry_info = "perpetual" if args.perpetual else f"expires in {args.days} days"

        print()
        print(f"[OK] License generated for: {args.customer}")
        print(f"     Tier: {args.tier}  |  Seats: {args.seats}  |  {expiry_info}")
        print()
        print("─" * 72)
        print(key_string)
        print("─" * 72)
        print()
        print("Send the key string above to the customer.")
        print("They paste it into Help → License… in SanjINSIGHT.")


if __name__ == "__main__":
    main()
