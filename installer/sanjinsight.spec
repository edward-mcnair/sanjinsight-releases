# sanjinsight.spec
# PyInstaller specification file for SanjINSIGHT
#
# Run from the project root on Windows:
#   pyinstaller installer/sanjinsight.spec
#
# Output: dist/SanjINSIGHT/  (one-folder bundle)
# Then Inno Setup wraps that folder into a single .exe installer.

import sys
import os
import importlib.util
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs

# ── Paths ─────────────────────────────────────────────────────────────────────
# This spec file lives in installer/ — project root is one level up
SPEC_DIR    = os.path.dirname(os.path.abspath(SPEC))
PROJECT_DIR = os.path.dirname(SPEC_DIR)

# ── Sanity-check: abort immediately if the scientific stack is missing ─────────
# A 13 MB output instead of ~130 MB means PyInstaller is running from the WRONG
# Python interpreter (one that doesn't have numpy/cv2/Qt5 installed).
# This check fails loudly here rather than silently producing a broken bundle.
_CRITICAL_PACKAGES = {
    'numpy':      'pip install numpy',
    'cv2':        'pip install opencv-python',
    'PyQt5':      'pip install PyQt5',
    'matplotlib': 'pip install matplotlib',
    'scipy':      'pip install scipy',
    'h5py':       'pip install h5py',
    'yaml':       'pip install PyYAML',
    'cryptography': 'pip install cryptography',
}
_missing_critical = {pkg: hint for pkg, hint in _CRITICAL_PACKAGES.items()
                     if importlib.util.find_spec(pkg) is None}
if _missing_critical:
    print("\n" + "=" * 70)
    print("ERROR: Critical packages are missing from this Python interpreter.")
    print(f"       Python: {sys.executable}")
    print()
    print("  This is usually caused by running PyInstaller from a different")
    print("  Python than the one where you ran 'pip install -r requirements.txt'.")
    print()
    print("  Missing packages:")
    for pkg, hint in _missing_critical.items():
        print(f"    {pkg:20s}  →  {hint}")
    print()
    print("  Fix: use build_installer.bat which calls 'python -m PyInstaller'")
    print("  so the same interpreter is used for pip and PyInstaller.")
    print("=" * 70 + "\n")
    sys.exit(1)

# ── Hidden imports ────────────────────────────────────────────────────────────
# PyInstaller cannot see modules loaded via importlib (our factory pattern)
# and some PyQt5 internals. List them all explicitly.
hidden_imports = [
    # ── Our factory-loaded drivers ──────────────────────────────────
    'hardware.cameras.ni_imaqdx',
    'hardware.cameras.pypylon_driver',
    'hardware.cameras.directshow',
    'hardware.cameras.simulated',
    'hardware.tec.meerstetter',
    'hardware.tec.atec',
    'hardware.tec.simulated',
    'hardware.fpga.ni9637',
    'hardware.fpga.simulated',
    'hardware.bias.keithley',
    'hardware.bias.visa_generic',
    'hardware.bias.rigol_dp832',
    'hardware.bias.simulated',
    'hardware.stage.thorlabs',
    'hardware.stage.serial_stage',
    'hardware.stage.simulated',
    'hardware.autofocus.sweep',
    'hardware.autofocus.hill_climb',
    'hardware.autofocus.simulated',

    # ── PyQt5 ───────────────────────────────────────────────────────
    'PyQt5',
    'PyQt5.QtCore',
    'PyQt5.QtGui',
    'PyQt5.QtWidgets',
    'PyQt5.QtSvg',
    'PyQt5.QtPrintSupport',
    'PyQt5.sip',

    # ── Scientific stack ─────────────────────────────────────────────
    'numpy',
    'numpy.core._multiarray_umath',
    'cv2',
    'matplotlib',
    'matplotlib.backends.backend_qt5agg',
    'matplotlib.backends.backend_agg',
    'mpl_toolkits.mplot3d',
    'scipy',
    'scipy.special._ufuncs_cxx',
    'h5py',
    'h5py.defs',
    'h5py.utils',
    'h5py._proxy',

    # ── Config / serial ──────────────────────────────────────────────
    'yaml',
    'serial',
    'serial.tools.list_ports',
    'serial.tools.list_ports_windows',

    # ── AI assistant — llama-cpp-python (optional, graceful if missing) ──
    # These are imported conditionally in ai/model_runner.py.
    # PyInstaller needs them listed here so they are bundled when present.
    'llama_cpp',
    'llama_cpp.llama',
    'llama_cpp.llama_cpp',
]

# ── Hardware packages — collected safely so a missing package never kills the build
#
# Strategy: use find_spec() as a guard for ALL packages.
# Packages in requirements.txt will always be found after "pip install -r requirements.txt".
# The guard is a safety net for builds run before pip install, or on CI machines
# that only install a subset of deps.  A missing package logs a warning and is
# skipped; it never aborts collection of numpy / Qt5 / everything else.


def _safe_collect(pkg: str) -> list:
    """collect_submodules() with a two-layer guard:
    1. find_spec() — skip silently if the package is not installed at all.
    2. try/except  — catch any exception collect_submodules() might raise
       (e.g. a broken __init__.py or a missing C extension inside the package).
    Either way, returns an empty list so the rest of the spec continues.
    """
    if importlib.util.find_spec(pkg) is None:
        print(f"[spec] INFO : '{pkg}' not found — skipping. "
              f"Run  pip install -r requirements.txt  if you need it bundled.")
        return []
    try:
        mods = collect_submodules(pkg)
        print(f"[spec] INFO : '{pkg}' — collected {len(mods)} submodule(s).")
        return mods
    except Exception as exc:
        print(f"[spec] WARN : collect_submodules('{pkg}') failed: {exc} — skipping.")
        return []


# pyMeCom — Meerstetter MeCom serial protocol (TEC-1089, LDD-1121)
# Import name is 'mecom'; pip name is 'pyMeCom'
hidden_imports += _safe_collect('mecom')

# pyvisa + pyvisa-py — VISA instrument control (Keithley SMU, SCPI supplies …)
hidden_imports += _safe_collect('pyvisa')

# pydp832 — Rigol DP832 native LAN driver (no NI-VISA required)
# May be named 'pydp832' or 'dp832' depending on installed version.
for _pydp832_mod in ('pydp832', 'dp832'):
    _mods = _safe_collect(_pydp832_mod)
    if _mods:
        hidden_imports += _mods
        break

# dcps — DC Power Supply helpers (Keithley 2400, Rigol DP800 …)
hidden_imports += _safe_collect('dcps')

# thorlabs_apt_device — Thorlabs APT/Kinesis motorised stage controllers
hidden_imports += _safe_collect('thorlabs_apt_device')

# pypylon — Basler camera SDK Python bindings
# SDK-dependent: also requires Basler pylon 8 installed at the OS level.
hidden_imports += _safe_collect('pypylon')

# ── Data files (non-Python assets bundled alongside the exe) ─────────────────
datas = [
    # ── App assets ────────────────────────────────────────────────────────────
    # SVG logos (used by status_header, report generator, settings tab)
    (os.path.join(PROJECT_DIR, 'assets', 'microsanj-logo.svg'),        'assets'),
    (os.path.join(PROJECT_DIR, 'assets', 'microsanj-logo-print.svg'),  'assets'),
    (os.path.join(PROJECT_DIR, 'assets', 'microsanj-bug.svg'),         'assets'),
    # App icons — main_app.py picks the right one per platform at runtime
    (os.path.join(PROJECT_DIR, 'assets', 'app-icon.png'),              'assets'),
    (os.path.join(PROJECT_DIR, 'assets', 'app-icon.ico'),              'assets'),
    (os.path.join(PROJECT_DIR, 'assets', 'app-icon.icns'),             'assets'),

    # ── Documentation (read at module-import time by ai/prompt_templates.py) ─
    # ai/prompt_templates.py resolves: Path(__file__).parent.parent / "docs"
    # which points to  <bundle_root>/docs/  in a frozen onedir build.
    *( [(os.path.join(PROJECT_DIR, 'docs', 'QuickstartGuide.md'),
          'docs'),
        (os.path.join(PROJECT_DIR, 'docs', 'UserManual.md'),
          'docs')]
       if os.path.isdir(os.path.join(PROJECT_DIR, 'docs')) else [] ),

    # ── Default config — user can edit this after installation ────────────────
    (os.path.join(PROJECT_DIR, 'config.yaml'), '.'),

    # Bundled material profiles (only if folder exists and has content)
    *( [(os.path.join(PROJECT_DIR, 'profiles', 'downloaded'),
          os.path.join('profiles', 'downloaded'))]
       if os.path.isdir(os.path.join(PROJECT_DIR, 'profiles', 'downloaded'))
          and any(os.scandir(os.path.join(PROJECT_DIR, 'profiles', 'downloaded')))
       else [] ),

    # Matplotlib data files (colormaps, fonts etc.)
    *collect_data_files('matplotlib'),

    # PyQt5 platform plugins and translations
    *collect_data_files('PyQt5', include_py_files=False),

    # h5py data files
    *collect_data_files('h5py'),

    # llama_cpp data files (only when installed — gracefully skipped if absent)
    *( collect_data_files('llama_cpp')
       if importlib.util.find_spec('llama_cpp') else [] ),
]

# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    [os.path.join(PROJECT_DIR, 'main_app.py')],   # entry point
    pathex=[PROJECT_DIR],
    binaries=[
        # llama_cpp native shared library (.dll/.dylib/.so) — skipped if not installed
        *( collect_dynamic_libs('llama_cpp')
           if importlib.util.find_spec('llama_cpp') else [] ),
    ],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[os.path.join(SPEC_DIR, 'hooks')],  # custom hooks folder
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # !! KEEP THIS LIST SHORT !!
        # Only exclude a module if you are 100% certain that NOTHING in our
        # dependency tree (including third-party packages like matplotlib,
        # pyparsing, scipy …) imports it at module-load time — even indirectly.
        #
        # Lessons learned:
        #   fnmatch  → shutil → zipfile → pyi_rth_inspect (PyInstaller bootstrap)
        #   unittest → pyparsing.testing → pyparsing → matplotlib.__init__
        #   pydoc    → potentially pulled by inspect-heavy libraries
        #   doctest  → occasionally imported by third-party testing helpers
        #   ftplib   → urllib.request may import it in some code paths
        #
        # tkinter is the only module we are confident is never touched by our
        # deps (we use PyQt5 exclusively; matplotlib uses Qt5Agg, not TkAgg).
        'tkinter',
    ],
    noarchive=False,
)

# ── PYZ archive ───────────────────────────────────────────────────────────────
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

# ── EXE (the launcher inside the bundle) ─────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,        # one-folder mode (better for debugging + updates)
    name='SanjINSIGHT',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,                     # compress binaries (requires UPX installed)
    upx_exclude=[                 # NEVER let UPX touch Qt5 or VC++ runtime DLLs —
        'Qt5Core.dll',            # UPX can corrupt them, causing DLL load failures
        'Qt5Gui.dll',             # on machines without the full MSVC runtime.
        'Qt5Widgets.dll',
        'Qt5Network.dll',
        'Qt5PrintSupport.dll',
        'Qt5Svg.dll',
        'Qt5XcbQpa.dll',
        'vcruntime140.dll',
        'vcruntime140_1.dll',
        'msvcp140.dll',
        'msvcp140_1.dll',
        'concrt140.dll',
        'python3*.dll',           # Python runtime — never compress
    ],
    console=False,                # no black console window — GUI app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(PROJECT_DIR, 'assets', 'app-icon.ico'),  # app icon (single source of truth)
    version=os.path.join(SPEC_DIR, 'version_info.txt'),         # Windows version metadata
)

# ── COLLECT (assemble the one-folder bundle) ──────────────────────────────────
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[                 # keep in sync with EXE block above
        'Qt5Core.dll', 'Qt5Gui.dll', 'Qt5Widgets.dll',
        'Qt5Network.dll', 'Qt5PrintSupport.dll', 'Qt5Svg.dll',
        'vcruntime140.dll', 'vcruntime140_1.dll',
        'msvcp140.dll', 'msvcp140_1.dll', 'concrt140.dll',
        'python3*.dll',
    ],
    name='SanjINSIGHT',          # output folder: dist/SanjINSIGHT/
)
