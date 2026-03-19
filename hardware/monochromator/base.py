"""
hardware/monochromator/base.py

Abstract base class for all monochromator drivers.

A monochromator selects a narrow band of wavelengths from a broadband light
source (typically a xenon or halogen lamp) and delivers it to the sample.
In thermoreflectance applications this provides a tuneable, highly
monochromatic pump or probe beam.

Supported hardware
------------------
    Newport / Oriel Cornerstone 130, 260, 74000  — serial ASCII protocol
    Simulated                                     — in-process stand-in

To add a new monochromator
--------------------------
    1. Create hardware/monochromator/my_driver.py and subclass MonochromatorDriver
    2. Add it to hardware/monochromator/factory.py
    3. Set driver: "my_driver" under hardware.monochromator in config.yaml
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Optional


# ---------------------------------------------------------------------------
# Status snapshot
# ---------------------------------------------------------------------------

@dataclass
class MonochromatorStatus:
    """Immutable snapshot of monochromator state."""
    wavelength_nm: float         = 532.0
    shutter_open:  bool          = False
    connected:     bool          = False
    error_msg:     Optional[str] = None


# ---------------------------------------------------------------------------
# Abstract driver
# ---------------------------------------------------------------------------

class MonochromatorDriver(ABC):
    """
    Abstract monochromator driver.

    Lifecycle::

        driver = CornerstoneMonochromator(port="COM5")
        driver.connect()
        driver.set_shutter(True)
        driver.set_wavelength(532.0)
        status = driver.get_status()
        driver.scan_wavelengths(300, 800, 10, 200, callback)
        driver.disconnect()

    All wavelength values are in nanometres (nm).
    All blocking commands must raise ``RuntimeError`` on hardware failure;
    callers translate that into UI error messages.
    """

    #: Unique short identifier for this driver class, e.g. "simulated".
    DRIVER_TYPE: str = "base"

    def __init__(self):
        self._connected: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    def connect(self) -> None:
        """
        Open connection to the monochromator and initialise it.

        Raises
        ------
        RuntimeError
            If the port cannot be opened or the instrument does not respond.
        """

    @abstractmethod
    def disconnect(self) -> None:
        """Close shutter, stop any running sweep, and release the port."""

    # ------------------------------------------------------------------
    # Wavelength control
    # ------------------------------------------------------------------

    @abstractmethod
    def set_wavelength(self, nm: float) -> None:
        """
        Move the grating to ``nm`` nanometres and block until complete.

        Parameters
        ----------
        nm:
            Target wavelength in nanometres.  Must be within
            ``self.wavelength_range``.

        Raises
        ------
        ValueError
            If ``nm`` is outside the instrument's valid range.
        RuntimeError
            If the move command fails or the instrument reports an error.
        """

    @abstractmethod
    def get_wavelength(self) -> float:
        """
        Query and return the current wavelength in nanometres.

        Returns
        -------
        float
            Current grating position in nm.
        """

    # ------------------------------------------------------------------
    # Shutter control
    # ------------------------------------------------------------------

    @abstractmethod
    def set_shutter(self, open: bool) -> None:
        """
        Open (``True``) or close (``False``) the internal shutter.

        Raises
        ------
        RuntimeError
            If the shutter command fails.
        """

    @abstractmethod
    def get_shutter(self) -> bool:
        """
        Query the shutter state.

        Returns
        -------
        bool
            ``True`` if the shutter is open, ``False`` if closed.
        """

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @abstractmethod
    def get_status(self) -> MonochromatorStatus:
        """
        Return a complete status snapshot.

        This is the primary method polled by the UI status timer.
        Implementations should query the instrument as needed and populate
        all fields; they must not raise — put any error text in
        ``MonochromatorStatus.error_msg`` instead.
        """

    # ------------------------------------------------------------------
    # Wavelength sweep
    # ------------------------------------------------------------------

    @abstractmethod
    def scan_wavelengths(
        self,
        start_nm:  float,
        end_nm:    float,
        step_nm:   float,
        dwell_ms:  float,
        callback:  Callable[[float, int, int], None],
    ) -> None:
        """
        Sweep the grating from ``start_nm`` to ``end_nm`` in ``step_nm``
        increments, dwelling ``dwell_ms`` milliseconds at each step.

        Parameters
        ----------
        start_nm:
            First wavelength in nanometres.
        end_nm:
            Last wavelength in nanometres (inclusive if reachable by step).
        step_nm:
            Increment between steps in nanometres; must be positive.
        dwell_ms:
            Time to wait at each wavelength, in milliseconds.
        callback:
            Called at each step with ``(current_nm, step_index, total_steps)``.
            If the callback raises ``StopIteration`` the sweep is cancelled
            cleanly.

        Raises
        ------
        ValueError
            If start/end/step values are out of range or logically invalid.
        RuntimeError
            If a hardware command fails mid-sweep.

        Notes
        -----
        This method is blocking.  Run it inside a ``QThread`` or
        ``concurrent.futures`` thread from the UI layer.
        """

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def wavelength_range(self) -> tuple[float, float]:
        """
        Return ``(min_nm, max_nm)`` representing the instrument's valid
        wavelength range.  Subclasses override this if the range is queried
        from the instrument at connect time.
        """
        return (0.0, 9999.0)

    @property
    def name(self) -> str:
        """Human-readable driver name, e.g. "Cornerstone 260"."""
        return self.__class__.__name__

    @property
    def is_connected(self) -> bool:
        return self._connected

    @classmethod
    def preflight(cls) -> tuple[bool, list[str]]:
        """
        Verify that this driver's optional dependencies are importable before
        trying to open hardware.

        Returns
        -------
        (ok, issues)
            ``ok`` is ``True`` when all dependencies are available.
            ``issues`` is a list of human-readable problem descriptions.
        """
        return (True, [])

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} "
            f"connected={self._connected}>"
        )
