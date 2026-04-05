"""
hardware/stage/mpi_prober.py

Driver for MPI (Micro Probe Inc. / FormFactor) wafer probe station stages.

The probe station has a motorized XYZ chuck that moves the wafer under
fixed microscope optics and probe needle heads.  Separate to the optical
microscope scanning stage (Thorlabs BSC203), this stage is stored in
app_state.prober and displayed in the Prober tab.

Protocol (MPI ASCII — RS-232):
  All commands are ASCII strings terminated with \\r\\n.
  Responses are ASCII lines, typically terminated with \\r\\n.

  Position query  → "POS?\\r\\n"        response: "X Y Z"  (μm, space-separated)
  Absolute move   → "MOVETO X Y Z\\r\\n" where X Y Z are floats in μm
  Relative move   → "MOVEBY X Y Z\\r\\n"
  Stop            → "STOP\\r\\n"
  Home            → "HOME <axes>\\r\\n"  e.g. "HOME XYZ"
  Contact         → "CONTACT\\r\\n"      lower needles for electrical contact
  Lift            → "LIFT\\r\\n"         raise needles to safe travel height
  Die step        → "DIESTEP COL ROW\\r\\n"   move to wafer map (col, row)
  Wafer map size  → "MAPSIZE?\\r\\n"     response: "NCOLS NROWS"
  Status          → "STATUS?\\r\\n"      response: "IDLE" | "MOVING" | "ERROR"

  Note: Command syntax may vary between MPI controller firmware versions.
  The command templates are configurable via config keys (see below) to
  accommodate field variations.

Config keys (under hardware.prober):
    port:           "COM6"      Serial port
    baud:           115200      Baud rate
    timeout:        5.0         Serial timeout
    settle_ms:      200         ms to wait after a move before reading position
    travel_x_um:    200000.0    Chuck X travel in μm (200 mm wafer default)
    travel_y_um:    200000.0    Chuck Y travel in μm
    travel_z_um:    50000.0     Chuck Z travel in μm (50 mm)

    # Command overrides (use {x}, {y}, {z}, {col}, {row} placeholders)
    cmd_pos_query:  "POS?"
    cmd_move_abs:   "MOVETO {x:.1f} {y:.1f} {z:.1f}"
    cmd_move_rel:   "MOVEBY {x:.1f} {y:.1f} {z:.1f}"
    cmd_stop:       "STOP"
    cmd_home:       "HOME {axes}"
    cmd_contact:    "CONTACT"
    cmd_lift:       "LIFT"
    cmd_die_step:   "DIESTEP {col} {row}"
    cmd_map_size:   "MAPSIZE?"
    cmd_status:     "STATUS?"
"""

import logging
import time
import threading
from .base import StageDriver, StagePosition, StageStatus
from hardware.port_lock import PortLock, serial_connect, serial_disconnect

log = logging.getLogger(__name__)


class MpiProberDriver(StageDriver):
    """
    MPI probe station chuck stage driver.

    Stored in app_state.prober (distinct from app_state.stage which holds
    the optical microscope scanning stage).

    In addition to the standard StageDriver interface, this driver
    supports probe-station-specific operations:
        step_to_die(col, row)  — move to a wafer map die position
        probe_contact()        — lower needles for electrical contact
        probe_lift()           — raise needles to safe travel height
    """

    @classmethod
    def preflight(cls) -> tuple:
        issues = []
        try:
            import serial  # noqa: F401
        except ImportError:
            issues.append(
                "pyserial not found — MPI probe station serial support unavailable.\n"
                "Try reinstalling SanjINSIGHT.  If the problem persists, "
                "contact Microsanj support."
            )
        return (len(issues) == 0, issues)

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._port       = cfg.get("port",       "")
        self._baud       = int(cfg.get("baud",   115200))
        self._timeout    = float(cfg.get("timeout", 5.0))
        self._settle_ms  = float(cfg.get("settle_ms", 200))

        self._travel = {
            "x": (-float(cfg.get("travel_x_um", 200_000.0)) / 2,
                   float(cfg.get("travel_x_um", 200_000.0)) / 2),
            "y": (-float(cfg.get("travel_y_um", 200_000.0)) / 2,
                   float(cfg.get("travel_y_um", 200_000.0)) / 2),
            "z": (0.0, float(cfg.get("travel_z_um", 50_000.0))),
        }

        # Command templates (all configurable)
        self._cmds = {
            "pos_query": cfg.get("cmd_pos_query", "POS?"),
            "move_abs":  cfg.get("cmd_move_abs",  "MOVETO {x:.1f} {y:.1f} {z:.1f}"),
            "move_rel":  cfg.get("cmd_move_rel",  "MOVEBY {x:.1f} {y:.1f} {z:.1f}"),
            "stop":      cfg.get("cmd_stop",      "STOP"),
            "home":      cfg.get("cmd_home",      "HOME {axes}"),
            "contact":   cfg.get("cmd_contact",   "CONTACT"),
            "lift":      cfg.get("cmd_lift",      "LIFT"),
            "die_step":  cfg.get("cmd_die_step",  "DIESTEP {col} {row}"),
            "map_size":  cfg.get("cmd_map_size",  "MAPSIZE?"),
            "status":    cfg.get("cmd_status",    "STATUS?"),
        }

        self._ser        = None
        self._port_lock  = PortLock(self._port)
        self._lock       = threading.Lock()
        self._moving     = False
        self._homed      = False
        self._map_size   = (0, 0)   # (n_cols, n_rows) if wafer map configured

    # ---------------------------------------------------------------- #
    #  Lifecycle                                                        #
    # ---------------------------------------------------------------- #

    def connect(self) -> None:
        self._ser = serial_connect(
            self._port, self._port_lock,
            baudrate=self._baud,
            timeout=self._timeout,
            write_timeout=self._timeout,
            device_name="MPI prober",
        )
        self._connected = True
        # Try to read initial position
        self._refresh_position()
        # Try to read wafer map size
        try:
            resp = self._query(self._cmds["map_size"])
            parts = resp.split()
            if len(parts) >= 2:
                self._map_size = (int(parts[0]), int(parts[1]))
        except Exception:
            pass   # wafer map is optional

    def disconnect(self) -> None:
        if self._ser:
            try:
                self._send(self._cmds["stop"])
            except Exception:
                pass
        serial_disconnect(self._ser, self._port_lock,
                          device_name="MPI prober")
        self._ser = None
        self._connected = False
        self._moving    = False

    # ---------------------------------------------------------------- #
    #  Motion                                                           #
    # ---------------------------------------------------------------- #

    def home(self, axes: str = "xyz") -> None:
        with self._lock:
            cmd = self._cmds["home"].format(axes=axes.upper())
            self._send(cmd)
            self._moving = True
        # Wait for motion complete (poll status)
        self._wait_for_idle(timeout_s=60.0)
        self._homed = True
        self._refresh_position()
        log.info("MPI prober homed: axes=%s", axes)

    def move_to(self,
                x: float = None,
                y: float = None,
                z: float = None,
                speed: float = None,
                wait: bool = True) -> None:
        with self._lock:
            # Resolve None axes to current position
            cur = self._pos
            tx = float(x) if x is not None else cur.x
            ty = float(y) if y is not None else cur.y
            tz = float(z) if z is not None else cur.z
            cmd = self._cmds["move_abs"].format(x=tx, y=ty, z=tz)
            self._send(cmd)
            self._moving = True
        if wait:
            self._wait_for_idle(timeout_s=60.0)
            self._refresh_position()

    def move_by(self,
                x: float = 0.0,
                y: float = 0.0,
                z: float = 0.0,
                speed: float = None,
                wait: bool = True) -> None:
        with self._lock:
            cmd = self._cmds["move_rel"].format(x=float(x), y=float(y), z=float(z))
            self._send(cmd)
            self._moving = True
        if wait:
            self._wait_for_idle(timeout_s=60.0)
            self._refresh_position()

    def stop(self) -> None:
        with self._lock:
            self._send(self._cmds["stop"])
            self._moving = False
        log.info("MPI prober: STOP issued")

    # ---------------------------------------------------------------- #
    #  Readback                                                         #
    # ---------------------------------------------------------------- #

    def get_status(self) -> StageStatus:
        try:
            self._refresh_position()
            status_str = self._query(self._cmds["status"]).strip().upper()
            moving = status_str not in ("IDLE", "READY", "OK", "")
            return StageStatus(
                position = self._pos,
                moving   = moving,
                homed    = self._homed,
            )
        except Exception as e:
            return StageStatus(
                position = self._pos,
                error    = str(e),
            )

    # ---------------------------------------------------------------- #
    #  Prober-specific extensions                                       #
    # ---------------------------------------------------------------- #

    def is_prober(self) -> bool:
        return True

    def step_to_die(self, col: int, row: int) -> None:
        """Move chuck to die at (col, row) in the wafer map."""
        with self._lock:
            cmd = self._cmds["die_step"].format(col=int(col), row=int(row))
            self._send(cmd)
            self._moving = True
        self._wait_for_idle(timeout_s=60.0)
        self._refresh_position()
        log.info("MPI prober: stepped to die (%d, %d)", col, row)

    def probe_contact(self) -> None:
        """Lower probe needles to make electrical contact."""
        with self._lock:
            self._send(self._cmds["contact"])
        time.sleep(0.5)   # allow needles to settle
        log.info("MPI prober: needles CONTACT")

    def probe_lift(self) -> None:
        """Raise probe needles to safe travel height."""
        with self._lock:
            self._send(self._cmds["lift"])
        time.sleep(0.3)
        log.info("MPI prober: needles LIFT")

    def get_wafer_map_size(self) -> tuple:
        return self._map_size

    # ---------------------------------------------------------------- #
    #  Range / speed introspection                                      #
    # ---------------------------------------------------------------- #

    def travel_range(self) -> dict:
        return self._travel

    def default_speed(self) -> dict:
        return {"x": 5000.0, "y": 5000.0, "z": 500.0}

    # ---------------------------------------------------------------- #
    #  Internal helpers                                                 #
    # ---------------------------------------------------------------- #

    def _send(self, command: str) -> None:
        if self._ser is None:
            raise RuntimeError("Prober not connected.")
        raw = (command + "\r\n").encode("ascii")
        self._ser.write(raw)
        self._ser.flush()

    def _query(self, command: str) -> str:
        self._send(command)
        time.sleep(0.05)
        raw = self._ser.readline()
        return raw.decode("ascii", errors="replace").strip()

    def _refresh_position(self) -> None:
        """Read current position from controller into self._pos."""
        try:
            resp = self._query(self._cmds["pos_query"])
            parts = resp.split()
            if len(parts) >= 3:
                self._pos = StagePosition(
                    x=float(parts[0]),
                    y=float(parts[1]),
                    z=float(parts[2]))
        except Exception as e:
            log.debug("Prober position refresh failed: %s", e)

    def _wait_for_idle(self, timeout_s: float = 30.0) -> None:
        """Poll status until IDLE or timeout."""
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            try:
                resp = self._query(self._cmds["status"]).strip().upper()
                if resp in ("IDLE", "READY", "OK", ""):
                    self._moving = False
                    return
            except Exception:
                pass
            time.sleep(self._settle_ms / 1000.0)
        log.warning("MPI prober: motion timeout after %.0f s", timeout_s)
        self._moving = False
