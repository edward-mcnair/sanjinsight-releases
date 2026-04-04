#!/usr/bin/env bash
# installer/build_installer_linux.sh
# One-command build for the SanjINSIGHT Linux AppImage.
#
# Usage (run from the project root OR from installer/):
#   bash installer/build_installer_linux.sh
#
# What this script does:
#   1. Resolves the active Python interpreter and prints it
#   2. pip install -r requirements.txt  (same Python as step 3)
#   3. python -m PyInstaller  (produces dist/SanjINSIGHT)
#   4. Creates a distributable AppImage  (requires appimagetool, optional)
#
# Requirements:
#   - Python 3.9+ (check: python3 --version)
#   - Linux with glibc 2.28+ (Ubuntu 18.04+, CentOS 8+, etc.)
#   - appimagetool (optional, for step 4)  https://github.com/AppImage/AppImageKit
#     Download from releases and place in PATH

set -euo pipefail

# ── Locate project root ────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

echo ""
echo "============================================================"
echo " SanjINSIGHT Linux AppImage Build"
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
    exit 1
fi

echo ""
echo "Using Python: $PYTHON"
$PYTHON --version

# ── Install dependencies ──────────────────────────────────────────────────────
echo ""
echo "Installing Python dependencies..."
$PYTHON -m pip install --upgrade pip
$PYTHON -m pip install -r requirements.txt

# ── Build with PyInstaller ───────────────────────────────────────────────────
echo ""
echo "Building with PyInstaller..."
$PYTHON -m PyInstaller --clean --noconfirm installer/sanjinsight_linux.spec

# ── Create AppImage (optional) ───────────────────────────────────────────────
if command -v appimagetool &>/dev/null; then
    echo ""
    echo "Creating AppImage..."
    # Note: This is a simplified example. You may need to adjust paths and setup.
    # For a proper AppImage, you need AppRun script, desktop file, etc.
    appimagetool dist/SanjINSIGHT.AppDir
    echo "AppImage created: SanjINSIGHT-x86_64.AppImage"
else
    echo ""
    echo "appimagetool not found. Skipping AppImage creation."
    echo "Install from: https://github.com/AppImage/AppImageKit/releases"
fi

echo ""
echo "============================================================"
echo " Build complete!"
echo "============================================================"
echo "Output: dist/SanjINSIGHT"
if [ -f "SanjINSIGHT-x86_64.AppImage" ]; then
    echo "AppImage: SanjINSIGHT-x86_64.AppImage"
fi