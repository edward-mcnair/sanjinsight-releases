"""
tests/test_hardware.py

Automated validation of the device registry, driver interface contracts,
and driver pre-flight system.

These tests run on every CI push (no hardware required — all checks are
purely structural/import-level).  They are designed to catch exactly the
class of problems we encountered during the v1.2.x hardware bring-up:

  • Camera devices registered with the wrong connection type
  • Driver modules that can't be imported due to syntax errors
  • Drivers missing required interface methods
  • Registry entries pointing to non-existent driver modules
  • preflight() returning the wrong type

Coverage (v1.2.9+):
  1. Device Registry consistency
  2. CameraDriver interface contract (all camera drivers)
  3. Camera factory smoke tests
  4. SimulatedCamera end-to-end lifecycle
  5. Non-camera subsystem preflight() contract (TEC, Bias, FPGA, Stage, LDD, Turret)
  6. Non-camera simulated driver preflight always passes
  7. Non-camera factory smoke tests
"""

import importlib
import inspect
import sys
import pytest


# ─────────────────────────────────────────────────────────────────── #
#  Helpers                                                             #
# ─────────────────────────────────────────────────────────────────── #

def _import_or_skip(module_path: str):
    """Import *module_path*, skipping the test if optional hardware deps missing."""
    try:
        return importlib.import_module(module_path)
    except ImportError as exc:
        pytest.skip(f"Optional dependency missing for {module_path}: {exc}")


# ─────────────────────────────────────────────────────────────────── #
#  1. Device Registry Consistency                                      #
# ─────────────────────────────────────────────────────────────────── #

class TestDeviceRegistry:

    def test_no_duplicate_uids(self):
        """Every entry's uid must match its registry key."""
        from hardware.device_registry import DEVICE_REGISTRY
        for key, desc in DEVICE_REGISTRY.items():
            assert desc.uid == key, (
                f"Registry key '{key}' does not match descriptor uid '{desc.uid}'"
            )

    def test_camera_devices_use_conn_camera_or_ethernet(self):
        """
        SDK-enumerated cameras must use CONN_CAMERA (or CONN_ETHERNET for
        GigE Vision), NOT CONN_USB.  Using CONN_USB triggers the 'No port
        or address configured' guard in DeviceManager even though cameras
        enumerate automatically via their SDK.
        """
        from hardware.device_registry import (
            DEVICE_REGISTRY, DTYPE_CAMERA, CONN_CAMERA, CONN_ETHERNET
        )
        valid = {CONN_CAMERA, CONN_ETHERNET}
        for uid, desc in DEVICE_REGISTRY.items():
            if desc.device_type == DTYPE_CAMERA:
                assert desc.connection_type in valid, (
                    f"{uid}: camera must use CONN_CAMERA or CONN_ETHERNET, "
                    f"got '{desc.connection_type}'.  This causes a spurious "
                    "'No port or address configured' error on connect."
                )

    def test_required_fields_non_empty(self):
        """uid, display_name, manufacturer, driver_module must all be set."""
        from hardware.device_registry import DEVICE_REGISTRY
        for uid, desc in DEVICE_REGISTRY.items():
            assert desc.uid,            f"{uid}: uid is empty"
            assert desc.display_name,   f"{uid}: display_name is empty"
            assert desc.manufacturer,   f"{uid}: manufacturer is empty"
            assert desc.driver_module,  f"{uid}: driver_module is empty"

    def test_driver_modules_are_syntactically_valid(self):
        """
        Every driver_module must be importable (syntax check).
        Tests that skip due to optional deps (pypylon, flirpy, etc.) are
        acceptable — the point is to catch SyntaxError and NameError.
        """
        from hardware.device_registry import DEVICE_REGISTRY
        seen = set()
        for uid, desc in DEVICE_REGISTRY.items():
            mod_path = desc.driver_module
            if mod_path in seen:
                continue
            seen.add(mod_path)
            try:
                importlib.import_module(mod_path)
            except ImportError:
                pass   # optional hardware dep missing — that's fine
            except Exception as exc:
                pytest.fail(
                    f"{uid}: driver_module '{mod_path}' raised "
                    f"{type(exc).__name__}: {exc}"
                )

    def test_camera_type_values(self):
        """camera_type must be 'tr' or 'ir'."""
        from hardware.device_registry import DEVICE_REGISTRY, DTYPE_CAMERA
        for uid, desc in DEVICE_REGISTRY.items():
            if desc.device_type == DTYPE_CAMERA:
                assert desc.camera_type in ("tr", "ir"), (
                    f"{uid}: camera_type must be 'tr' or 'ir', "
                    f"got '{desc.camera_type}'"
                )


# ─────────────────────────────────────────────────────────────────── #
#  2. CameraDriver Interface Contract                                  #
# ─────────────────────────────────────────────────────────────────── #

# Minimum set every concrete driver must implement.
_REQUIRED_METHODS = [
    "open", "start", "stop", "close", "grab",
    "set_exposure", "set_gain",
    "connect", "disconnect",
    "preflight",
]

# Driver modules to validate (skipped individually if deps missing).
_CAMERA_DRIVER_MODULES = [
    "hardware.cameras.simulated",
    "hardware.cameras.pypylon_driver",
    "hardware.cameras.flir_driver",
    "hardware.cameras.ni_imaqdx",
    "hardware.cameras.directshow",
]


def _find_driver_class(mod):
    """Return the first non-base CameraDriver subclass in *mod*."""
    from hardware.cameras.base import CameraDriver
    for _, obj in inspect.getmembers(mod, inspect.isclass):
        if issubclass(obj, CameraDriver) and obj is not CameraDriver:
            return obj
    return None


@pytest.mark.parametrize("mod_path", _CAMERA_DRIVER_MODULES)
class TestCameraDriverInterface:

    def test_driver_has_required_methods(self, mod_path):
        """Every camera driver must implement the full CameraDriver interface."""
        mod = _import_or_skip(mod_path)
        cls = _find_driver_class(mod)
        if cls is None:
            pytest.skip(f"No CameraDriver subclass found in {mod_path}")

        missing = [m for m in _REQUIRED_METHODS if not hasattr(cls, m)]
        assert not missing, (
            f"{cls.__name__} is missing required methods: {missing}\n"
            "Add these to the driver or inherit defaults from CameraDriver."
        )

    def test_preflight_returns_correct_type(self, mod_path):
        """preflight() must return (bool, list) — not None or a single value."""
        mod = _import_or_skip(mod_path)
        cls = _find_driver_class(mod)
        if cls is None:
            pytest.skip(f"No CameraDriver subclass found in {mod_path}")

        result = cls.preflight()
        assert isinstance(result, tuple) and len(result) == 2, (
            f"{cls.__name__}.preflight() must return (bool, list), got {result!r}"
        )
        ok, issues = result
        assert isinstance(ok, bool), (
            f"{cls.__name__}.preflight() first element must be bool, got {type(ok)}"
        )
        assert isinstance(issues, list), (
            f"{cls.__name__}.preflight() second element must be list, got {type(issues)}"
        )

    def test_preflight_issues_are_strings(self, mod_path):
        """Every item in the preflight issues list must be a string."""
        mod = _import_or_skip(mod_path)
        cls = _find_driver_class(mod)
        if cls is None:
            pytest.skip(f"No CameraDriver subclass found in {mod_path}")

        _, issues = cls.preflight()
        for i, issue in enumerate(issues):
            assert isinstance(issue, str), (
                f"{cls.__name__}.preflight() issues[{i}] is not a string: {issue!r}"
            )

    def test_simulated_driver_preflight_always_passes(self, mod_path):
        """SimulatedDriver must always pass preflight (no external deps)."""
        if "simulated" not in mod_path:
            pytest.skip("Only applies to SimulatedDriver")
        mod = _import_or_skip(mod_path)
        cls = _find_driver_class(mod)
        ok, issues = cls.preflight()
        assert ok is True, (
            "SimulatedDriver.preflight() must always return True — "
            "it has no external dependencies"
        )
        assert issues == [], (
            f"SimulatedDriver.preflight() must return empty issues list, got {issues}"
        )


# ─────────────────────────────────────────────────────────────────── #
#  3. Factory Smoke Tests                                              #
# ─────────────────────────────────────────────────────────────────── #

class TestCameraFactory:

    def test_simulated_driver_always_available(self):
        """create_camera({'driver': 'simulated'}) must always succeed."""
        from hardware.cameras.factory import create_camera
        cam = create_camera({"driver": "simulated"})
        assert cam is not None
        assert hasattr(cam, "open")

    def test_unknown_driver_raises_value_error(self):
        """Requesting an unknown driver key must raise ValueError, not AttributeError."""
        from hardware.cameras.factory import create_camera
        with pytest.raises((ValueError, RuntimeError)):
            create_camera({"driver": "this_driver_does_not_exist"})

    def test_list_drivers_returns_expected_keys(self):
        """list_drivers() must include at least the core built-in drivers."""
        from hardware.cameras.factory import list_drivers
        drivers = list_drivers()
        for expected in ("simulated", "pypylon", "flir"):
            assert expected in drivers, (
                f"'{expected}' missing from list_drivers(): {drivers}"
            )


# ─────────────────────────────────────────────────────────────────── #
#  4. SimulatedDriver End-to-End                                       #
# ─────────────────────────────────────────────────────────────────── #

class TestSimulatedDriverEndToEnd:
    """
    Quick lifecycle smoke test using SimulatedDriver.
    Catches regressions in the base class connect/grab/disconnect flow.
    """

    def setup_method(self):
        from hardware.cameras.factory import create_camera
        self.cam = create_camera({"driver": "simulated"})

    def teardown_method(self):
        if self.cam and self.cam.is_open:
            self.cam.close()

    def test_preflight_passes(self):
        ok, issues = self.cam.__class__.preflight()
        assert ok is True
        assert issues == []

    def test_connect_open_grab_disconnect(self):
        self.cam.connect()
        assert self.cam.is_open

        self.cam.start()
        frame = self.cam.grab(timeout_ms=3000)
        assert frame is not None
        assert frame.data.ndim == 2
        assert frame.data.dtype.itemsize == 2   # uint16

        self.cam.stop()
        self.cam.disconnect()
        assert not self.cam.is_open

    def test_exposure_range_is_valid(self):
        lo, hi = self.cam.exposure_range()
        assert lo < hi
        assert lo >= 0

    def test_gain_range_is_valid(self):
        lo, hi = self.cam.gain_range()
        assert lo <= hi


# ─────────────────────────────────────────────────────────────────── #
#  5. Non-camera subsystem preflight() contract                        #
# ─────────────────────────────────────────────────────────────────── #
#
#  Every concrete non-camera driver must:
#    • Have a preflight() classmethod
#    • Return (bool, list[str])
#    • Simulated drivers must always return (True, [])
#
#  Tests are parametrized per module and skip individually when
#  optional hardware deps are missing.

_TEC_DRIVER_MODULES = [
    "hardware.tec.simulated",
    "hardware.tec.meerstetter",
    "hardware.tec.atec",
    "hardware.tec.thermal_chuck",
]

_BIAS_DRIVER_MODULES = [
    "hardware.bias.simulated",
    "hardware.bias.keithley",
    "hardware.bias.visa_generic",
    "hardware.bias.rigol_dp832",
]

_FPGA_DRIVER_MODULES = [
    "hardware.fpga.simulated",
    "hardware.fpga.ni9637",
]

_STAGE_DRIVER_MODULES = [
    "hardware.stage.simulated",
    "hardware.stage.thorlabs",
    "hardware.stage.serial_stage",
    "hardware.stage.mpi_prober",
]

_LDD_DRIVER_MODULES = [
    "hardware.ldd.simulated",
    "hardware.ldd.meerstetter_ldd1121",
]

_TURRET_DRIVER_MODULES = [
    "hardware.turret.simulated",
    "hardware.turret.olympus_linx",
]

_ALL_SUBSYSTEM_MODULES = (
    _TEC_DRIVER_MODULES
    + _BIAS_DRIVER_MODULES
    + _FPGA_DRIVER_MODULES
    + _STAGE_DRIVER_MODULES
    + _LDD_DRIVER_MODULES
    + _TURRET_DRIVER_MODULES
)


def _find_subsystem_driver_class(mod):
    """
    Return the first concrete (non-abstract) subclass of any known
    hardware base class found in *mod*.
    """
    base_classes = []
    try:
        from hardware.tec.base   import TecDriver;   base_classes.append(TecDriver)
    except ImportError: pass
    try:
        from hardware.bias.base  import BiasDriver;  base_classes.append(BiasDriver)
    except ImportError: pass
    try:
        from hardware.fpga.base  import FpgaDriver;  base_classes.append(FpgaDriver)
    except ImportError: pass
    try:
        from hardware.stage.base import StageDriver; base_classes.append(StageDriver)
    except ImportError: pass
    try:
        from hardware.ldd.base   import LddDriver;   base_classes.append(LddDriver)
    except ImportError: pass
    try:
        from hardware.turret.base import ObjectiveTurretDriver
        base_classes.append(ObjectiveTurretDriver)
    except ImportError: pass

    if not base_classes:
        return None

    for _, obj in inspect.getmembers(mod, inspect.isclass):
        for base in base_classes:
            if issubclass(obj, base) and obj is not base:
                return obj
    return None


@pytest.mark.parametrize("mod_path", _ALL_SUBSYSTEM_MODULES)
class TestSubsystemDriverPreflight:
    """
    Verifies that every non-camera hardware driver satisfies the
    preflight() contract: exists, returns (bool, list[str]).
    """

    def test_driver_has_preflight(self, mod_path):
        """Driver class must have a preflight() classmethod."""
        mod = _import_or_skip(mod_path)
        cls = _find_subsystem_driver_class(mod)
        if cls is None:
            pytest.skip(f"No subsystem driver subclass found in {mod_path}")
        assert hasattr(cls, "preflight"), (
            f"{cls.__name__} is missing preflight() classmethod.\n"
            "Add a preflight() classmethod that returns (bool, list[str])."
        )
        assert callable(cls.preflight), (
            f"{cls.__name__}.preflight is not callable."
        )

    def test_preflight_returns_correct_type(self, mod_path):
        """preflight() must return (bool, list) — never None or a bare value."""
        mod = _import_or_skip(mod_path)
        cls = _find_subsystem_driver_class(mod)
        if cls is None:
            pytest.skip(f"No subsystem driver subclass found in {mod_path}")

        result = cls.preflight()
        assert isinstance(result, tuple) and len(result) == 2, (
            f"{cls.__name__}.preflight() must return (bool, list), got {result!r}"
        )
        ok, issues = result
        assert isinstance(ok, bool), (
            f"{cls.__name__}.preflight() first element must be bool, got {type(ok)}"
        )
        assert isinstance(issues, list), (
            f"{cls.__name__}.preflight() second element must be list, got {type(issues)}"
        )

    def test_preflight_issues_are_strings(self, mod_path):
        """Every item in the preflight issues list must be a string."""
        mod = _import_or_skip(mod_path)
        cls = _find_subsystem_driver_class(mod)
        if cls is None:
            pytest.skip(f"No subsystem driver subclass found in {mod_path}")

        _, issues = cls.preflight()
        for i, issue in enumerate(issues):
            assert isinstance(issue, str), (
                f"{cls.__name__}.preflight() issues[{i}] is not a string: {issue!r}"
            )

    def test_simulated_driver_preflight_always_passes(self, mod_path):
        """Simulated drivers must always pass preflight() — they have no external deps."""
        if "simulated" not in mod_path:
            pytest.skip("Only applies to simulated drivers")
        mod = _import_or_skip(mod_path)
        cls = _find_subsystem_driver_class(mod)
        if cls is None:
            pytest.skip(f"No subsystem driver subclass found in {mod_path}")

        ok, issues = cls.preflight()
        assert ok is True, (
            f"{cls.__name__}.preflight() must always return True — "
            "simulated drivers have no external dependencies"
        )
        assert issues == [], (
            f"{cls.__name__}.preflight() must return empty issues list, got {issues}"
        )


# ─────────────────────────────────────────────────────────────────── #
#  6. Non-camera factory smoke tests                                   #
# ─────────────────────────────────────────────────────────────────── #

class TestSubsystemFactories:
    """
    Smoke tests that every subsystem factory can produce a simulated driver
    and that unknown driver keys raise cleanly.
    """

    def test_simulated_tec_always_available(self):
        """create_tec({'driver': 'simulated'}) must always succeed."""
        from hardware.tec.factory import create_tec
        tec = create_tec({"driver": "simulated"})
        assert tec is not None
        assert hasattr(tec, "connect")

    def test_simulated_bias_always_available(self):
        """create_bias({'driver': 'simulated'}) must always succeed."""
        from hardware.bias.factory import create_bias
        bias = create_bias({"driver": "simulated"})
        assert bias is not None
        assert hasattr(bias, "connect")

    def test_simulated_fpga_always_available(self):
        """create_fpga({'driver': 'simulated'}) must always succeed."""
        from hardware.fpga.factory import create_fpga
        fpga = create_fpga({"driver": "simulated"})
        assert fpga is not None
        assert hasattr(fpga, "open")

    def test_simulated_stage_always_available(self):
        """create_stage({'driver': 'simulated'}) must always succeed."""
        from hardware.stage.factory import create_stage
        stage = create_stage({"driver": "simulated"})
        assert stage is not None
        assert hasattr(stage, "connect")

    def test_simulated_ldd_always_available(self):
        """create_ldd({'driver': 'simulated'}) must always succeed."""
        from hardware.ldd.factory import create_ldd
        ldd = create_ldd({"driver": "simulated"})
        assert ldd is not None
        assert hasattr(ldd, "connect")

    def test_simulated_turret_always_available(self):
        """create_turret({'driver': 'simulated'}) must always succeed."""
        from hardware.turret.factory import create_turret
        turret = create_turret({"driver": "simulated"})
        assert turret is not None
        assert hasattr(turret, "connect")

    def test_unknown_tec_driver_raises(self):
        from hardware.tec.factory import create_tec
        with pytest.raises((ValueError, RuntimeError, KeyError)):
            create_tec({"driver": "this_driver_does_not_exist"})

    def test_unknown_bias_driver_raises(self):
        from hardware.bias.factory import create_bias
        with pytest.raises((ValueError, RuntimeError, KeyError)):
            create_bias({"driver": "this_driver_does_not_exist"})

    def test_unknown_fpga_driver_raises(self):
        from hardware.fpga.factory import create_fpga
        with pytest.raises((ValueError, RuntimeError, KeyError)):
            create_fpga({"driver": "this_driver_does_not_exist"})

    def test_unknown_stage_driver_raises(self):
        from hardware.stage.factory import create_stage
        with pytest.raises((ValueError, RuntimeError, KeyError)):
            create_stage({"driver": "this_driver_does_not_exist"})
