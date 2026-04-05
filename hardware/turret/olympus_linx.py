"""
hardware/turret/olympus_linx.py

Driver for the Olympus motorized objective turret via Arduino/LINX interface.

In the Microsanj LabVIEW system, LINX (MakerHub LabVIEW LINX) drives an Arduino
that controls the Olympus IX motorized nose-piece.  This driver communicates with
that same Arduino via a simple ASCII serial protocol:

  Select position → "TURRET <n>\\r\\n"      where n is 1–6
  Query position  → "TURRET?\\r\\n"         response: "<n>\\r\\n"
  Query status    → "STATUS?\\r\\n"         response: "IDLE\\r\\n" | "MOVING\\r\\n"
  Number of slots → "SLOTS?\\r\\n"          response: "<n>\\r\\n"

The Arduino sketch acknowledges moves with "OK\\r\\n" and reports errors with
"ERR <message>\\r\\n".

If the Arduino uses a different command set, all strings are overridable in
config (see Config keys below).

The objective specifications (magnification, NA, working distance, pixel size)
are loaded from ai/instrument_knowledge.OBJECTIVE_SPECS and matched by position
number.  The config can override or supplement these with local values.

Config keys (under hardware.turret):
    driver:         "olympus_linx"
    port:           "COM7"          Serial port to Arduino
    baud:           115200          Baud rate (Arduino default)
    timeout:        5.0             Serial timeout in seconds
    move_settle_ms: 1500            ms to wait after move command before querying

    # Command overrides
    cmd_move:       "TURRET {pos}"
    cmd_query_pos:  "TURRET?"
    cmd_query_stat: "STATUS?"
    cmd_query_slots:"SLOTS?"

    # Objective definitions (override instrument_knowledge defaults)
    # objectives:
    #   - position: 1
    #     magnification: 10
    #     numerical_aperture: 0.25
    #     working_dist_mm: 10.6
    #     label: "10× / 0.25 NA"
    #   - position: 2
    #     ...
"""

import logging
import time
import threading
from .base import ObjectiveTurretDriver, ObjectiveSpec, TurretStatus
from hardware.port_lock import PortLock, serial_connect, serial_disconnect

log = logging.getLogger(__name__)


class OlympusLinxTurret(ObjectiveTurretDriver):
    """
    Olympus IX objective turret via Arduino/LINX serial interface.
    """

    @classmethod
    def preflight(cls) -> tuple:
        issues = []
        try:
            import serial  # noqa: F401
        except ImportError:
            issues.append(
                "pyserial not found — Olympus turret serial support unavailable.\n"
                "Try reinstalling SanjINSIGHT.  If the problem persists, "
                "contact Microsanj support."
            )
        return (len(issues) == 0, issues)

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._port       = cfg.get("port",      "COM7")
        self._baud       = int(cfg.get("baud",  115200))
        self._timeout    = float(cfg.get("timeout", 5.0))
        self._settle_ms  = float(cfg.get("move_settle_ms", 1500))

        self._cmds = {
            "move":        cfg.get("cmd_move",        "TURRET {pos}"),
            "query_pos":   cfg.get("cmd_query_pos",   "TURRET?"),
            "query_stat":  cfg.get("cmd_query_stat",  "STATUS?"),
            "query_slots": cfg.get("cmd_query_slots", "SLOTS?"),
        }

        self._ser        = None
        self._port_lock  = PortLock(self._port)
        self._lock       = threading.Lock()
        self._cur_pos    = 0    # 0 = unknown until queried
        self._n_slots    = 6   # Olympus IX default; queried on connect

        # Load objective specs from instrument_knowledge, then apply config overrides
        self._objectives = self._load_objectives(cfg.get("objectives", []))

    # ---------------------------------------------------------------- #
    #  Lifecycle                                                        #
    # ---------------------------------------------------------------- #

    def connect(self) -> None:
        self._ser = serial_connect(
            self._port, self._port_lock,
            baudrate=self._baud,
            timeout=self._timeout,
            write_timeout=self._timeout,
            device_name="Olympus turret (LINX)",
        )
        time.sleep(0.2)   # Arduino resets on serial connect
        self._connected = True

        # Query number of slots and initial position
        try:
            resp = self._query(self._cmds["query_slots"])
            self._n_slots = int(resp.strip())
        except Exception:
            pass  # use default (6)

        try:
            resp = self._query(self._cmds["query_pos"])
            self._cur_pos = int(resp.strip())
        except Exception:
            self._cur_pos = 0

    def disconnect(self) -> None:
        serial_disconnect(self._ser, self._port_lock,
                          device_name="Olympus turret (LINX)")
        self._ser = None
        self._connected = False

    # ---------------------------------------------------------------- #
    #  Control                                                          #
    # ---------------------------------------------------------------- #

    def move_to(self, position: int) -> None:
        if position < 1 or position > self._n_slots:
            raise ValueError(
                f"Turret position {position} out of range "
                f"(1–{self._n_slots}).")
        with self._lock:
            cmd = self._cmds["move"].format(pos=position)
            resp = self._query(cmd)
            if "ERR" in resp.upper():
                raise RuntimeError(
                    f"Turret move to position {position} failed: {resp}")
        # Wait for motion to complete
        time.sleep(self._settle_ms / 1000.0)
        # Confirm position
        with self._lock:
            try:
                resp = self._query(self._cmds["query_pos"])
                self._cur_pos = int(resp.strip())
            except Exception:
                self._cur_pos = position   # assume success
        log.info("Olympus turret → position %d  (%s)",
                 self._cur_pos,
                 getattr(self.get_objective(), 'label', '?'))

    # ---------------------------------------------------------------- #
    #  Readback                                                         #
    # ---------------------------------------------------------------- #

    def get_status(self) -> TurretStatus:
        with self._lock:
            try:
                stat_resp = self._query(self._cmds["query_stat"]).strip().upper()
                is_moving = "MOVING" in stat_resp
                pos_resp  = self._query(self._cmds["query_pos"])
                self._cur_pos = int(pos_resp.strip())
                return TurretStatus(
                    position    = self._cur_pos,
                    is_moving   = is_moving,
                    n_positions = self._n_slots,
                )
            except Exception as e:
                return TurretStatus(
                    position    = self._cur_pos,
                    n_positions = self._n_slots,
                    error       = str(e),
                )

    def get_position(self) -> int:
        with self._lock:
            try:
                resp = self._query(self._cmds["query_pos"])
                self._cur_pos = int(resp.strip())
            except Exception:
                pass
        return self._cur_pos

    def n_positions(self) -> int:
        return self._n_slots

    # ---------------------------------------------------------------- #
    #  Internal helpers                                                 #
    # ---------------------------------------------------------------- #

    def _send(self, command: str) -> None:
        if self._ser is None:
            raise RuntimeError("Turret not connected.")
        self._ser.write((command + "\r\n").encode("ascii"))
        self._ser.flush()

    def _query(self, command: str) -> str:
        self._send(command)
        time.sleep(0.05)
        raw = self._ser.readline()
        return raw.decode("ascii", errors="replace").strip()

    @staticmethod
    def _load_objectives(overrides: list) -> list:
        """
        Load objective specs from instrument_knowledge, then apply config overrides.
        Returns a list of ObjectiveSpec instances sorted by position.
        """
        # Import default specs from instrument_knowledge
        try:
            from ai.instrument_knowledge import OBJECTIVE_SPECS
            specs = {s.position: s for s in OBJECTIVE_SPECS}
        except (ImportError, AttributeError):
            specs = {}

        # Apply config overrides / additions
        for entry in overrides:
            pos = int(entry.get("position", 0))
            if pos == 0:
                continue
            specs[pos] = ObjectiveSpec(
                position           = pos,
                magnification      = int(entry.get("magnification", 10)),
                numerical_aperture = float(entry.get("numerical_aperture", 0.25)),
                working_dist_mm    = float(entry.get("working_dist_mm", 10.0)),
                label              = entry.get("label",
                                               f"{entry.get('magnification', 10)}× obj"),
            )

        # If no specs loaded, generate sensible Olympus IX defaults
        if not specs:
            defaults = [
                (1,  4,  0.10, 18.5, " 4× / 0.10 NA"),
                (2, 10,  0.25, 10.6, "10× / 0.25 NA"),
                (3, 20,  0.45,  8.2, "20× / 0.45 NA"),
                (4, 50,  0.80,  0.37,"50× / 0.80 NA"),
                (5,100,  0.95,  0.21,"100× / 0.95 NA"),
            ]
            for pos, mag, na, wd, lbl in defaults:
                specs[pos] = ObjectiveSpec(
                    position=pos, magnification=mag,
                    numerical_aperture=na, working_dist_mm=wd, label=lbl)

        return sorted(specs.values(), key=lambda s: s.position)
