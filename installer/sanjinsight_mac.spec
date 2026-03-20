# installer/sanjinsight_mac.spec
# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for the macOS app bundle.
# Run from the project root:
#   pyinstaller installer/sanjinsight_mac.spec --noconfirm --clean
#
# Output: dist/SanjINSIGHT.app

import importlib.util
import os
import sys

from PyInstaller.utils.hooks import (
    collect_data_files, collect_dynamic_libs, collect_submodules,
)

# ── pypylon — collect entire package: Python modules + bundled pylon.framework ─
# The pypylon wheel is self-contained: it ships pylon.framework inside the
# site-packages/pypylon/ directory (~30 MB), so no separate Basler SDK install
# is needed.  We collect each piece explicitly to keep datas/binaries/imports
# typed correctly regardless of PyInstaller version.
_pypylon_modules = collect_submodules('pypylon')          # list[str] — module names
_pypylon_datas   = collect_data_files('pypylon',
                       include_py_files=False)            # list[tuple] — (src, dest)
_pypylon_bins    = collect_dynamic_libs('pypylon')        # list[tuple] — (src, dest)

# SPECPATH is the absolute path of the installer/ directory.
# Inserting the project root lets us import version.py below.
_root = os.path.dirname(SPECPATH)
sys.path.insert(0, _root)

from version import __version__

block_cipher = None

# ── Icon ──────────────────────────────────────────────────────────────────────
# Use the .icns file for macOS; fall back gracefully if not yet generated.
_icns = os.path.join(_root, 'assets', 'app-icon.icns')
_icon = _icns if os.path.exists(_icns) else None

# ── Hidden imports ────────────────────────────────────────────────────────────
# Mirrors sanjinsight.spec — modules loaded via importlib (factory pattern)
# and PyQt5 internals that auto-discovery misses.
hidden_imports = [
    # ── Our factory-loaded hardware drivers ─────────────────────────
    'hardware.cameras.ni_imaqdx',
    'hardware.cameras.pypylon_driver',
    'hardware.cameras.simulated',
    'hardware.tec.meerstetter',
    'hardware.tec.atec',
    'hardware.tec.simulated',
    'hardware.fpga.ni9637',
    'hardware.fpga.bnc745',
    'hardware.fpga.simulated',
    'hardware.bias.keithley',
    'hardware.bias.visa_generic',
    'hardware.bias.amcad_bilt',
    'hardware.bias.simulated',
    'hardware.stage.thorlabs',
    'hardware.stage.serial_stage',
    'hardware.stage.simulated',
    'hardware.autofocus.sweep',
    'hardware.autofocus.hill_climb',
    'hardware.autofocus.simulated',

    # ── PyQt5 ────────────────────────────────────────────────────────
    'PyQt5',
    'PyQt5.QtCore',
    'PyQt5.QtGui',
    'PyQt5.QtWidgets',
    'PyQt5.QtSvg',
    'PyQt5.QtPrintSupport',
    'PyQt5.sip',

    # ── qtawesome (icon font) ────────────────────────────────────────
    'qtawesome',

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

    # ── pypylon (Basler camera SDK — self-contained wheel) ────────────
    # collect_submodules discovers the full module tree; explicit entries
    # below are a safety net in case the camera driver imports them lazily.
    'pypylon',
    'pypylon.pylon',
    'pypylon.genicam',
    *_pypylon_modules,

    # ── FLIR Boson SDK (bundled Python SDK) ──────────────────────────
    # All modules are pure-Python and shipped in hardware/cameras/boson/.
    # Listed explicitly because the factory loads them via importlib.
    'hardware.cameras.boson_driver',
    'hardware.cameras.boson',
    'hardware.cameras.boson.ClientFiles_Python',
    'hardware.cameras.boson.ClientFiles_Python.Client_API',
    'hardware.cameras.boson.ClientFiles_Python.Client_Dispatcher',
    'hardware.cameras.boson.ClientFiles_Python.Client_Packager',
    'hardware.cameras.boson.ClientFiles_Python.EnumTypes',
    'hardware.cameras.boson.ClientFiles_Python.ReturnCodes',
    'hardware.cameras.boson.ClientFiles_Python.Serializer_BuiltIn',
    'hardware.cameras.boson.ClientFiles_Python.Serializer_Struct',
    'hardware.cameras.boson.CommunicationFiles',
    'hardware.cameras.boson.CommunicationFiles.CommonFslp',
    'hardware.cameras.boson.CommunicationFiles.PySerialFslp',
    'hardware.cameras.boson.CommunicationFiles.PySerialPort',
    'hardware.cameras.boson.CommunicationFiles.FslpBase',
    'hardware.cameras.boson.CommunicationFiles.PortBase',
    'hardware.cameras.boson.CommunicationFiles.CSerialFslp',
    'hardware.cameras.boson.CommunicationFiles.CSerialPort',

    # ── pyqtgraph (real-time charts) ─────────────────────────────────
    # ui/charts.py imports via try/except so PyInstaller static analysis
    # misses it; list every subpackage used at runtime.
    'pyqtgraph',
    'pyqtgraph.Qt',
    'pyqtgraph.graphicsItems',
    'pyqtgraph.widgets',
    'pyqtgraph.opengl',
    'pyqtgraph.exporters',
    'pyqtgraph.colormap',

    # ── Config / serial ──────────────────────────────────────────────
    'yaml',
    'serial',
    'serial.tools.list_ports',
    'serial.tools.list_ports_osx',   # macOS-specific port enumeration

    # ── Cryptography (license validator) ─────────────────────────────
    'cryptography.hazmat.primitives.asymmetric.ed25519',
    'cryptography.hazmat.backends.openssl',

    # ── AI assistant — llama-cpp-python (optional) ───────────────────
    'llama_cpp',
    'llama_cpp.llama',
    'llama_cpp.llama_cpp',
]

# ── Data files ────────────────────────────────────────────────────────────────
datas = [
    # App assets
    (os.path.join(_root, 'assets', 'microsanj-logo.svg'),       'assets'),
    (os.path.join(_root, 'assets', 'microsanj-logo-print.svg'), 'assets'),
    (os.path.join(_root, 'assets', 'microsanj-bug.svg'),        'assets'),
    (os.path.join(_root, 'assets', 'app-icon.png'),             'assets'),
    (os.path.join(_root, 'assets', 'app-icon.icns'),            'assets'),
    # Demo images — loaded by hardware/cameras/simulated.py for realistic demo frames.
    # Without these the simulated camera falls back to the parametric IC model.
    (os.path.join(_root, 'assets', 'demo_background.png'),      'assets'),
    (os.path.join(_root, 'assets', 'demo_signal.png'),          'assets'),

    # Camera ICD / IID files (NI IMAQdx camera configuration descriptors).
    # Used by hardware/cameras/ni_imaqdx.py on Windows.  Bundled on macOS too
    # so a single installer covers all platforms.
    *( [(os.path.join(_root, 'assets', 'camera_icd'), 'assets/camera_icd')]
       if os.path.isdir(os.path.join(_root, 'assets', 'camera_icd')) else [] ),

    # FLIR Boson Python SDK — pure-Python source files shipped in the package.
    # PyInstaller imports the .py modules automatically via hiddenimports above,
    # but the SDK's __init__.py reads sibling paths at runtime so we also need
    # the source tree available as data.
    (os.path.join(_root, 'hardware', 'cameras', 'boson'),
     os.path.join('hardware', 'cameras', 'boson')),

    # Documentation (read by ai/prompt_templates.py at runtime)
    *( [(os.path.join(_root, 'docs', 'QuickstartGuide.md'), 'docs'),
        (os.path.join(_root, 'docs', 'UserManual.md'),      'docs')]
       if os.path.isdir(os.path.join(_root, 'docs')) else [] ),

    # Default config
    (os.path.join(_root, 'config.yaml'), '.'),

    # Bundled material profiles (only if present and non-empty)
    *( [(os.path.join(_root, 'profiles', 'downloaded'),
         os.path.join('profiles', 'downloaded'))]
       if os.path.isdir(os.path.join(_root, 'profiles', 'downloaded'))
          and any(os.scandir(os.path.join(_root, 'profiles', 'downloaded')))
       else [] ),

    # Third-party data (colormaps, fonts, platform plugins, etc.)
    *collect_data_files('matplotlib'),
    *collect_data_files('PyQt5', include_py_files=False),
    *collect_data_files('h5py'),
    *collect_data_files('pyqtgraph'),   # colormap CSVs, Qt platform plugins
    *_pypylon_datas,                   # pypylon .py helpers + pylon.framework data

    # llama_cpp data files (skipped gracefully if not installed)
    *( collect_data_files('llama_cpp')
       if importlib.util.find_spec('llama_cpp') else [] ),
]

# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    [os.path.join(_root, 'main_app.py')],
    pathex=[_root],
    binaries=[
        # pypylon: pylon.framework dylibs bundled inside the wheel
        *_pypylon_bins,
        # llama_cpp native dylib (skipped if not installed)
        *( collect_dynamic_libs('llama_cpp')
           if importlib.util.find_spec('llama_cpp') else [] ),
    ],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[os.path.join(SPECPATH, 'hooks')],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Windows-only — never present on macOS
        'nifpga',
        'win32api', 'win32con', 'win32gui', 'pywintypes',
        'winreg', 'winsound',
        # tkinter — we use PyQt5 exclusively
        'tkinter',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── EXE (the binary inside the .app bundle) ───────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SanjINSIGHT',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,              # UPX can break macOS code-signing
    console=False,          # GUI app — no terminal window
    argv_emulation=False,
    target_arch=None,       # None = native; 'x86_64' or 'arm64' for cross-build
    codesign_identity=None, # set to Developer ID Application: ... when signing
    entitlements_file=None,
)

# ── COLLECT (assemble into one directory before bundling) ─────────────────────
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='SanjINSIGHT',
)

# ── BUNDLE (.app wrapper) ─────────────────────────────────────────────────────
app = BUNDLE(
    coll,
    name='SanjINSIGHT.app',
    icon=_icon,
    bundle_identifier='com.microsanj.sanjinsight',
    version=__version__,
    info_plist={
        'NSPrincipalClass':         'NSApplication',
        'NSAppleScriptEnabled':     False,
        'NSHighResolutionCapable':  True,
        'LSMinimumSystemVersion':   '10.14',   # macOS Mojave minimum
        'CFBundleDisplayName':      'SanjINSIGHT',
        'CFBundleShortVersionString': __version__,
        'CFBundleVersion':          __version__,
        'NSHumanReadableCopyright': f'Copyright \u00a9 2026 Microsanj, LLC.',
        # Camera / USB access descriptions (required for notarization)
        'NSCameraUsageDescription': 'SanjINSIGHT requires camera access for thermoreflectance acquisition.',
        'NSUSBDeviceDescription':   'SanjINSIGHT requires USB access for connected hardware instruments.',
    },
)
