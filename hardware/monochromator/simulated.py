"""
hardware/monochromator/simulated.py

Simulated monochromator for development and testing without hardware.

Behaviour
---------
- Grating movement is instantaneous (no real delay).
- Default wavelength: 532.0 nm, range 300–900 nm.
- Shutter starts closed.
- ``scan_wavelengths`` honours ``dwell_ms`` clamped to 10 ms per step so that
  sweep tests run quickly without hanging the test suite.

Config keys (under hardware.monochromator)
------------------------------------------
    initial_wavelength_nm:  532.0   starting wavelength (nm)
    min_nm:                 300.0   override simulated minimum
    max_nm:                 900.0   override simulated maximum
"""

import time
import logging

from .base import MonochromatorDriver, MonochromatorStatus

log = logging.getLogger(__name__)

_SIM_DWELL_MS = 10  # cap per-step simulated dwell


class SimulatedMonochromator(MonochromatorDriver):
    """Software-only monochromator for UI development and automated tests."""

    DRIVER_TYPE = "simulated"

    def __init__(self, cfg: dict | None = None):
        super().__init__()
        cfg = cfg or {}
        self._wavelength_nm: float = float(
            cfg.get("initial_wavelength_nm", 532.0))
        self._min_nm: float = float(cfg.get("min_nm", 300.0))
        self._max_nm: float = float(cfg.get("max_nm", 900.0))
        self._shutter_open: bool = False
        self._cancel_sweep: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        self._connected = True
        log.info(
            "[SIM] Monochromator connected  "
            "(wavelength=%.1f nm, range=%.0f–%.0f nm)",
            self._wavelength_nm, self._min_nm, self._max_nm,
        )

    def disconnect(self) -> None:
        self._cancel_sweep = True
        self._shutter_open = False
        self._connected = False
        log.info("[SIM] Monochromator disconnected")

    # ------------------------------------------------------------------
    # Wavelength control
    # ------------------------------------------------------------------

    def set_wavelength(self, nm: float) -> None:
        self._assert_connected()
        self._validate_wavelength(nm)
        self._wavelength_nm = nm
        log.debug("[SIM] Wavelength → %.3f nm", nm)

    def get_wavelength(self) -> float:
        self._assert_connected()
        return self._wavelength_nm

    # ------------------------------------------------------------------
    # Shutter control
    # ------------------------------------------------------------------

    def set_shutter(self, open: bool) -> None:
        self._assert_connected()
        self._shutter_open = open
        log.debug("[SIM] Shutter → %s", "OPEN" if open else "CLOSE")

    def get_shutter(self) -> bool:
        self._assert_connected()
        return self._shutter_open

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> MonochromatorStatus:
        return MonochromatorStatus(
            wavelength_nm=self._wavelength_nm,
            shutter_open=self._shutter_open,
            connected=self._connected,
            error_msg=None,
        )

    # ------------------------------------------------------------------
    # Sweep
    # ------------------------------------------------------------------

    def scan_wavelengths(
        self,
        start_nm:  float,
        end_nm:    float,
        step_nm:   float,
        dwell_ms:  float,
        callback,
    ) -> None:
        self._assert_connected()
        if step_nm <= 0:
            raise ValueError(f"step_nm must be positive, got {step_nm}")
        self._validate_wavelength(start_nm)
        self._validate_wavelength(end_nm)

        steps = []
        nm = start_nm
        while nm <= end_nm + 1e-9:
            steps.append(round(nm, 4))
            nm += step_nm
        total = len(steps)

        # Cap simulated dwell so tests don't take forever
        effective_dwell_s = min(dwell_ms, _SIM_DWELL_MS) / 1000.0

        self._cancel_sweep = False
        for i, target_nm in enumerate(steps):
            if self._cancel_sweep:
                log.debug("[SIM] Sweep cancelled at step %d/%d", i, total)
                break
            self._wavelength_nm = target_nm
            time.sleep(effective_dwell_s)
            try:
                callback(target_nm, i, total)
            except StopIteration:
                log.debug("[SIM] Sweep cancelled by callback at %.1f nm", target_nm)
                break

        log.debug("[SIM] Sweep complete")

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def wavelength_range(self) -> tuple[float, float]:
        return (self._min_nm, self._max_nm)

    @property
    def name(self) -> str:
        return "Simulated Monochromator"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _assert_connected(self) -> None:
        if not self._connected:
            raise RuntimeError(
                "Simulated monochromator is not connected. Call connect() first.")

    def _validate_wavelength(self, nm: float) -> None:
        if not (self._min_nm <= nm <= self._max_nm):
            raise ValueError(
                f"Wavelength {nm:.3f} nm is outside the valid range "
                f"({self._min_nm:.0f}–{self._max_nm:.0f} nm)."
            )
