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

    # ── Optional hardware packages (import gracefully if missing) ────
    # nifpga, pypylon, pyMeCom, pyvisa — these are installed separately
    # on the instrument PC. PyInstaller won't fail if they're absent.

    # ── AI assistant — llama-cpp-python (optional, graceful if missing) ──
    # These are imported conditionally in ai/model_runner.py.
    # PyInstaller needs them listed here so they are bundled when present.
    'llama_cpp',
    'llama_cpp.llama',
    'llama_cpp.llama_cpp',
]

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
    upx_exclude=[],
    name='SanjINSIGHT',          # output folder: dist/SanjINSIGHT/
)
