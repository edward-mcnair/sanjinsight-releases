#!/usr/bin/env bash
# installer/build_installer_mac.sh
# One-command build for the SanjINSIGHT macOS .app bundle.
#
# Usage (run from the project root OR from installer/):
#   bash installer/build_installer_mac.sh
#
# What this script does:
#   1. Resolves the active Python interpreter and prints it
#   2. pip install -r requirements.txt  (same Python as step 3)
#   3. Converts app-icon.png → app-icon.icns  (skipped if .icns exists)
#   4. python -m PyInstaller  (produces dist/SanjINSIGHT.app)
#   5. Creates a distributable .dmg  (requires create-dmg, optional)
#
# Key design choice: everything uses "python -m pip" and "python -m PyInstaller"
# rather than bare "pip" / "pyinstaller".  This guarantees that the same Python
# interpreter is used for both installing packages and building the bundle —
# mismatched interpreters are the #1 cause of broken or tiny output bundles.
#
# Requirements:
#   - Python 3.10+ (check: python3 --version)
#   - Xcode Command Line Tools  (check: xcode-select --print-path)
#   - create-dmg (optional, for step 5)  https://github.com/create-dmg/create-dmg
#     Install:  brew install create-dmg

set -euo pipefail

# ── Locate project root ────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

echo ""
echo "============================================================"
echo " SanjINSIGHT macOS App Bundle Build"
echo "============================================================"

# ── Resolve Python interpreter ─────────────────────────────────────────────────
# Prefer the project's .venv so the SAME environment that has PyQt5/numpy/etc
# is also the one running PyInstaller.  Fall back to python3 on PATH.
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
if [ -f "$VENV_PYTHON" ]; then
    PYTHON="$VENV_PYTHON"
elif command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    echo ""
    echo "ERROR: python3 not found on PATH and no .venv present."
    echo "       Create the venv:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi

PYTHON_EXE=$($PYTHON -c "import sys; print(sys.executable)")
PYTHON_VER=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo ""
echo "Python interpreter : $PYTHON_EXE"
echo "Python version     : $PYTHON_VER"
echo ""

# ── Step 1: Install / update Python dependencies ──────────────────────────────
echo "[1/4] Installing Python dependencies..."
$PYTHON -m pip install -r requirements.txt --quiet
echo "      Done."
echo ""

# ── Step 2: Generate .icns icon (if not already present) ──────────────────────
ICNS_PATH="$PROJECT_DIR/assets/app-icon.icns"
PNG_PATH="$PROJECT_DIR/assets/app-icon.png"

if [ -f "$ICNS_PATH" ]; then
    echo "[2/4] app-icon.icns already present — skipping icon generation."
elif [ -f "$PNG_PATH" ]; then
    echo "[2/4] Generating app-icon.icns from app-icon.png..."
    ICONSET_DIR="$SCRIPT_DIR/AppIcon.iconset"
    mkdir -p "$ICONSET_DIR"

    # Generate all required icon sizes from the source PNG
    for SIZE in 16 32 64 128 256 512; do
        sips -z $SIZE $SIZE "$PNG_PATH" --out "$ICONSET_DIR/icon_${SIZE}x${SIZE}.png"     >/dev/null 2>&1
        DOUBLE=$((SIZE * 2))
        sips -z $DOUBLE $DOUBLE "$PNG_PATH" --out "$ICONSET_DIR/icon_${SIZE}x${SIZE}@2x.png" >/dev/null 2>&1
    done

    iconutil -c icns "$ICONSET_DIR" -o "$ICNS_PATH"
    rm -rf "$ICONSET_DIR"
    echo "      Saved to: $ICNS_PATH"
else
    echo "[2/4] WARNING: No app-icon.png found — bundle will have no icon."
fi
echo ""

# ── Step 3: Build the PyInstaller .app bundle ─────────────────────────────────
echo "[3/4] Building .app bundle with PyInstaller..."
echo "      Spec: installer/sanjinsight_mac.spec"
echo ""

$PYTHON -m PyInstaller installer/sanjinsight_mac.spec --noconfirm --clean

APP_PATH="$PROJECT_DIR/dist/SanjINSIGHT.app"
if [ ! -d "$APP_PATH" ]; then
    echo ""
    echo "ERROR: dist/SanjINSIGHT.app not found after build."
    echo "       Check the PyInstaller output above."
    exit 1
fi

# Sanity-check: count files inside the bundle
FILE_COUNT=$(find "$APP_PATH" -type f | wc -l | tr -d ' ')
echo ""
if [ "$FILE_COUNT" -lt 100 ]; then
    echo "WARNING: SanjINSIGHT.app contains only $FILE_COUNT files."
    echo "         A full build typically has 300+ files."
    echo "         The bundle may be incomplete — check PyInstaller output above."
else
    echo "         Bundle OK: $FILE_COUNT files in dist/SanjINSIGHT.app"
fi
echo ""

# ── Step 4: Create distributable .dmg (optional) ─────────────────────────────
echo "[4/4] Packaging as .dmg..."

# Read version from version.py
VERSION=$($PYTHON -c "import sys; sys.path.insert(0,'$PROJECT_DIR'); from version import __version__; print(__version__)")
DMG_NAME="SanjINSIGHT-${VERSION}-mac.dmg"
DMG_PATH="$PROJECT_DIR/dist/$DMG_NAME"

if command -v create-dmg &>/dev/null; then
    rm -f "$DMG_PATH"
    create-dmg \
        --volname "SanjINSIGHT $VERSION" \
        --volicon "$ICNS_PATH" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon-size 100 \
        --icon "SanjINSIGHT.app" 175 190 \
        --hide-extension "SanjINSIGHT.app" \
        --app-drop-link 425 190 \
        "$DMG_PATH" \
        "$PROJECT_DIR/dist/SanjINSIGHT.app"
    echo ""
    echo "      DMG created: dist/$DMG_NAME"
else
    echo "      create-dmg not found — skipping DMG creation."
    echo "      Install with:  brew install create-dmg"
    echo "      Or distribute dist/SanjINSIGHT.app directly."
fi

echo ""
echo "============================================================"
echo " Build complete!"
echo " App bundle : dist/SanjINSIGHT.app"
if [ -f "$DMG_PATH" ]; then
    echo " DMG        : dist/$DMG_NAME"
fi
echo ""
echo " To run the app:"
echo "   open dist/SanjINSIGHT.app"
echo ""
echo " To code-sign (required for distribution outside Mac App Store):"
echo '   codesign --deep --force --sign "Developer ID Application: Microsanj, LLC" dist/SanjINSIGHT.app'
echo ""
echo " To notarize:"
echo '   xcrun notarytool submit dist/SanjINSIGHT.app --apple-id YOUR@EMAIL --team-id TEAMID --wait'
echo "============================================================"
echo ""
