#!/usr/bin/env python3
"""
scripts/fetch_inter.py  —  Download Inter font files into ui/fonts/

Run once from the project root before launching SanjINSIGHT:

    python scripts/fetch_inter.py

Downloads Inter v3.19 from the official GitHub release and extracts the
four static TTF weights (Regular, Medium, SemiBold, Bold) into ui/fonts/.
Requires internet access; no third-party dependencies beyond the stdlib.

After running, SanjINSIGHT automatically detects and loads the font files
on the next launch via ui/font_utils.py → load_inter().
"""

import io
import os
import sys
import urllib.request
import zipfile

VERSION    = "3.19"
RELEASE_URL = (
    f"https://github.com/rsms/inter/releases/download/"
    f"v{VERSION}/Inter-{VERSION}.zip"
)

WEIGHTS = ("Regular", "Medium", "SemiBold", "Bold")

# Path relative to this script: scripts/ → .. → ui/fonts/
_HERE     = os.path.dirname(os.path.abspath(__file__))
DEST_DIR  = os.path.normpath(os.path.join(_HERE, "..", "ui", "fonts"))


def _find_in_zip(zf: zipfile.ZipFile, filename: str) -> "str | None":
    """Return the full zip path of ``filename``, searching all entries."""
    for name in zf.namelist():
        if os.path.basename(name) == filename:
            return name
    return None


def main() -> None:
    os.makedirs(DEST_DIR, exist_ok=True)

    already = [
        f"Inter-{w}.ttf" for w in WEIGHTS
        if os.path.exists(os.path.join(DEST_DIR, f"Inter-{w}.ttf"))
    ]
    if len(already) == len(WEIGHTS):
        print("Inter fonts already present — nothing to do.")
        print(f"  Location: {DEST_DIR}/")
        return

    print(f"Downloading Inter {VERSION} from GitHub…  ", end="", flush=True)
    try:
        with urllib.request.urlopen(RELEASE_URL, timeout=60) as resp:
            data = resp.read()
    except Exception as exc:
        print(f"\nDownload failed: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"OK ({len(data) // 1024} KB)")

    print("Extracting font files…")
    ok = 0
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for weight in WEIGHTS:
            fname   = f"Inter-{weight}.ttf"
            zpath   = _find_in_zip(zf, fname)
            dest    = os.path.join(DEST_DIR, fname)
            if zpath is None:
                print(f"  ✗  {fname}  — not found in archive", file=sys.stderr)
                continue
            with zf.open(zpath) as src, open(dest, "wb") as dst:
                dst.write(src.read())
            print(f"  ✓  {fname}")
            ok += 1

    if ok == 0:
        print("\nNo fonts were extracted — check the archive structure.",
              file=sys.stderr)
        sys.exit(1)

    print(f"\nDone. {ok}/{len(WEIGHTS)} files installed in:")
    print(f"  {DEST_DIR}/")
    print("\nRestart SanjINSIGHT to load Inter automatically.")


if __name__ == "__main__":
    main()
