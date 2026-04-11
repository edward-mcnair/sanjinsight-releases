"""
ui/hardware_panel_coordinator.py

Owns the six hardware-category sidebar panels and their DeviceStatusCard
proxy widgets.  Extracted from ``main_app.py`` so that MainWindow only
needs to forward signals rather than managing card lifecycles itself.

Responsibilities
----------------
* Panel creation + empty-state wiring (Device Manager / Demo Mode signals)
* Device key → panel routing table
* Lazy DeviceStatusCard creation / caching
* Static-info refresh on connect, live-readout reset on reconnect
* Live-readout update methods called from status-signal handlers

The coordinator does **not** own the status-signal handlers themselves
(``_on_frame``, ``_on_tec``, etc.) — those stay in MainWindow because they
serve many purposes beyond card updates.  MainWindow calls the coordinator's
``update_*`` helpers from those handlers.
"""
from __future__ import annotations

import logging
from typing import Callable, Dict, Optional

from PyQt5.QtCore import pyqtSignal, QObject

from hardware.app_state import app_state
from ui.icons import IC
from ui.theme import PALETTE
from ui.widgets.device_status_card import DeviceStatusCard
from ui.widgets.hardware_category_panel import HardwareCategoryPanel

log = logging.getLogger(__name__)

# ── State accent palette (kept minimal) ────────────────────────────────
# These are read from PALETTE at call time so theme switches are honored.

def _c_healthy() -> str:
    return PALETTE.get("success", "#30d158")

def _c_warning() -> str:
    return PALETTE.get("warning", "#ff9f0a")

def _c_neutral() -> str:
    return ""  # clears accent — default tile appearance

def _c_error() -> str:
    return PALETTE.get("danger", "#ff453a")


# ── Routing table entry ─────────────────────────────────────────────────
# (panel_key, icon, fallback_display_name, nav_label)
# panel_key is resolved to the actual HardwareCategoryPanel at runtime.

_ROUTE = tuple  # type alias for readability


class HardwarePanelCoordinator(QObject):
    """Mediator between hardware signals and sidebar category panels.

    Signals
    -------
    navigate_requested(str)
        Emitted when a card's "Configure" button is clicked.
        Payload is the sidebar nav label to select.
    open_device_manager()
        Forwarded from any panel's empty-state button.
    start_demo_mode()
        Forwarded from any panel's empty-state button.
    """

    navigate_requested = pyqtSignal(str)
    open_device_manager = pyqtSignal()
    start_demo_mode = pyqtSignal()

    def __init__(self, *, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._cards: Dict[str, DeviceStatusCard] = {}
        self._panels: Dict[str, HardwareCategoryPanel] = {}
        self._route_table: Dict[str, _ROUTE] = {}
        self._display_name_resolver: Optional[Callable[[str], str]] = None

    # ── Setup (called once from MainWindow.__init__) ─────────────────

    def create_panels(self) -> Dict[str, HardwareCategoryPanel]:
        """Build the six category panels and return them keyed by category.

        Caller (MainWindow) inserts the returned widgets into the sidebar.
        """
        defs = [
            ("cameras", "Cameras",
             "No cameras connected.\n"
             "Connect a camera in Device Manager, or start "
             "Demo Mode to explore the interface."),
            ("stages", "Stages",
             "No stages connected.\n"
             "Connect a stage in Device Manager, or start "
             "Demo Mode to explore the interface."),
            ("thermal_control", "Thermal Control",
             "No thermal control hardware connected.\n"
             "Connect a TEC controller in Device Manager, or "
             "start Demo Mode to explore the interface."),
            ("stimulus_timing", "Stimulus & Timing",
             "No stimulus or timing devices connected.\n"
             "Connect an FPGA, bias source, or LED controller "
             "in Device Manager, or start Demo Mode to explore "
             "the interface."),
            ("probes", "Probes",
             "No probe hardware connected.\n"
             "Connect a prober in Device Manager, or start "
             "Demo Mode to explore the interface."),
            ("sensors", "Sensors",
             "No sensors connected.\n"
             "Connect a temperature sensor or environmental "
             "monitor in Device Manager, or start Demo Mode "
             "to explore the interface."),
        ]
        for cat, label, desc in defs:
            panel = HardwareCategoryPanel(
                cat, label, empty_description=desc)
            panel.open_device_manager.connect(self.open_device_manager.emit)
            panel.start_demo_mode.connect(self.start_demo_mode.emit)
            self._panels[cat] = panel
        return dict(self._panels)

    def build_route_table(self) -> None:
        """Populate the device-key → (panel, icon, fallback_name, nav_label) map.

        Must be called after :meth:`create_panels`.
        """
        cam   = self._panels["cameras"]
        stg   = self._panels["stages"]
        therm = self._panels["thermal_control"]
        stim  = self._panels["stimulus_timing"]
        prb   = self._panels["probes"]
        sens  = self._panels["sensors"]

        self._route_table = {
            # ── Cameras ──────────────────────────────────────────────
            "camera":          (cam,  IC.CAMERA,      "Camera",              "Measurement Setup"),
            "tr_camera":       (cam,  IC.CAMERA,      "TR Camera",           "Measurement Setup"),
            "ir_camera":       (cam,  IC.CAMERA,      "IR Camera",           "Measurement Setup"),
            # ── Stages ───────────────────────────────────────────────
            "stage":           (stg,  IC.STAGE,       "Stage",               "Focus & Stage"),
            "newport_npc3":    (stg,  IC.STAGE,       "Newport NPC3 Piezo Controller",       "Focus & Stage"),
            # ── Thermal Control ──────────────────────────────────────
            "tec0":            (therm, IC.TEMPERATURE,  "TEC 1",              "Temperature"),
            "tec1":            (therm, IC.TEMPERATURE,  "TEC 2",              "Temperature"),
            "tec2":            (therm, IC.TEMPERATURE,  "TEC 3",              "Temperature"),
            "tec_meerstetter": (therm, IC.TEMPERATURE,  "Meerstetter TEC",    "Temperature"),
            # ── Stimulus & Timing ────────────────────────────────────
            "fpga":            (stim, IC.FPGA,        "Timing / FPGA",       "Stimulus & Timing"),
            "ni_9637":         (stim, IC.FPGA,        "NI 9637",             "Stimulus & Timing"),
            "ni_sbrio":        (stim, IC.FPGA,        "NI sbRIO",            "Stimulus & Timing"),
            "bias":            (stim, IC.BIAS,        "Bias Source",         "Stimulus & Timing"),
            "rigol_dp832":     (stim, IC.BIAS,        "Rigol DP832",         "Stimulus & Timing"),
            "gpio":            (stim, IC.ILLUMINATION, "GPIO / LED Selector", "Stimulus & Timing"),
            "ldd":             (stim, IC.ILLUMINATION, "Optical Source",      "Stimulus & Timing"),
            # ── Probes ───────────────────────────────────────────────
            "prober":          (prb,  IC.PROBER,      "Prober",              "Focus & Stage"),
            "turret":          (prb,  IC.PROBER,      "Objective Turret",    "Focus & Stage"),
        }

    def set_display_name_resolver(self, fn: Callable[[str], str]) -> None:
        """Register a fallback callable that maps device keys to short names.

        Typically ``MainWindow._device_display``.
        """
        self._display_name_resolver = fn

    # ── Panel access ─────────────────────────────────────────────────

    def panel(self, category: str) -> Optional[HardwareCategoryPanel]:
        return self._panels.get(category)

    # ── Connect / disconnect handling ────────────────────────────────

    def on_device_connected(self, key: str, ok: bool) -> None:
        """React to a device connect/disconnect event.

        Creates or updates the DeviceStatusCard and registers/unregisters
        it with the appropriate category panel.
        """
        route = self._route_table.get(key)
        if route is None:
            return
        panel, icon, fallback_name, nav_label = route

        display_name = self._resolve_display_name(key, fallback_name)

        try:
            if ok:
                card = self._get_or_create_card(key, icon, display_name, nav_label)
                card.set_connected(True)
                card.set_display_name(display_name)
                self._refresh_static_info(card, key)
                self._reset_live_readouts(card, key)
                if not panel.has_device(key):
                    panel.register_device(key, card, display_name)
                else:
                    panel.set_device_name(key, display_name)
            else:
                card = self._cards.get(key)
                if card is not None:
                    card.set_connected(False)
                panel.unregister_device(key)
        except Exception:
            log.debug("hw panel update failed for %s", key, exc_info=True)

    # ── Live readout updates (called from MainWindow handlers) ───────

    def update_camera_readouts(self, frame) -> None:
        """Push exposure/gain/FPS and live preview from a camera frame."""
        for ckey in ("camera", "tr_camera", "ir_camera"):
            card = self._cards.get(ckey)
            if card is None:
                continue
            # Live preview thumbnail
            card.update_preview(frame.data)
            # Text readouts
            exp = frame.exposure_us
            if exp >= 1000:
                card.update_info("Exposure", f"{exp/1000:.1f} ms ({exp:.0f} us)")
            else:
                card.update_info("Exposure", f"{exp:.0f} us")
            g = getattr(frame, "gain_db", None)
            if g is not None:
                card.update_info("Gain", f"{g:.1f} dB")
            fps = getattr(frame, "fps", None)
            if fps:
                card.update_info("Live FPS", f"{fps:.1f}")
                card.set_summary(f"Streaming at {fps:.0f} FPS",
                                 _c_healthy())

    def update_tec_readouts(self, index: int, status) -> None:
        """Push live TEC data to the matching thermal control card."""
        key = f"tec{index}"
        card = self._cards.get(key)
        ok = status.error is None
        if card is None or not ok:
            return
        card.update_info("Temperature", f"{status.actual_temp:.2f}")
        card.update_info("Setpoint", f"{status.target_temp:.1f}")
        pwr = getattr(status, "output_power", None)
        card.update_info("Output", f"{pwr:.0f}" if pwr is not None else "On")
        # Sink temp — only meaningful for Meerstetter (non-zero)
        sink = getattr(status, "sink_temp", 0.0)
        if sink != 0.0:
            card.update_info("Sink Temp", f"{sink:.1f} \u00b0C")
        dt = abs(status.actual_temp - status.target_temp)
        if dt < 0.05:
            card.update_info("Stability", "Stable")
            card.set_tile_accent("Stability", _c_healthy())
            card.set_summary(f"Stable at {status.actual_temp:.1f} \u00b0C",
                             _c_healthy())
        elif dt < 0.5:
            card.update_info("Stability", "Settling")
            card.set_tile_accent("Stability", _c_warning())
            card.set_summary(
                f"Settling \u2014 {status.actual_temp:.1f} \u2192 "
                f"{status.target_temp:.1f} \u00b0C",
                _c_warning())
        else:
            card.update_info("Stability", "Ramping")
            card.set_tile_accent("Stability", _c_warning())
            card.set_summary(f"Ramping to {status.target_temp:.1f} \u00b0C",
                             _c_warning())

    def update_fpga_readouts(self, status) -> None:
        """Push live FPGA data to the timing card."""
        card = self._cards.get("fpga")
        if card is None:
            return
        ok = status.error is None
        running = status.running if ok else False
        sync = getattr(status, "sync_locked", False)

        card.update_info("Running", "Yes" if running else "No")
        card.set_tile_accent("Running",
                             _c_healthy() if running else _c_neutral())

        card.update_info("Sync Locked", "Yes" if sync else "No")
        card.set_tile_accent("Sync Locked",
                             _c_healthy() if sync else _c_neutral())

        freq = getattr(status, "freq_hz", None)
        duty = getattr(status, "duty_cycle", None)
        if freq is not None:
            if freq >= 1000:
                card.update_info("Frequency", f"{freq/1000:.1f} k")
            else:
                card.update_info("Frequency", f"{freq:,.0f}")
            if freq > 0:
                period_us = 1e6 / freq
                if period_us >= 1000:
                    card.update_info("Period", f"{period_us/1000:.2f} ms")
                else:
                    card.update_info("Period", f"{period_us:.1f} \u00b5s")
        if duty is not None:
            card.update_info("Duty Cycle", f"{duty:.1f}")

        trig = getattr(status, "trigger_mode", None)
        if trig:
            card.update_info("Trigger Mode", trig.replace("_", " ").title())

        if running:
            if freq:
                card.set_summary(f"Running at {freq:,.0f} Hz",
                                 _c_healthy())
            else:
                card.set_summary("Running", _c_healthy())
        else:
            card.set_summary("Stopped", _c_neutral())

    def update_bias_readouts(self, status) -> None:
        """Push live bias source data to the bias card."""
        card = self._cards.get("bias")
        if card is None:
            return
        ok = status.error is None
        output_on = ok and status.output_on

        card.update_info("Output", "On" if output_on else "Off")
        card.set_tile_accent("Output",
                             _c_healthy() if output_on else _c_neutral())
        card.update_info("Voltage",
                         f"{status.actual_voltage:.3f}" if ok else "\u2014")
        card.update_info("Current",
                         f"{status.actual_current * 1000:.2f}" if ok else "\u2014")
        pwr = getattr(status, "actual_power", None)
        if pwr is not None and ok:
            card.update_info("Power", f"{pwr:.3f}")
        card.update_info("Mode", status.mode if ok else "\u2014")
        if ok and status.compliance:
            card.update_info("Compliance",
                             f"{status.compliance:.3f} A"
                             if status.mode == "voltage"
                             else f"{status.compliance:.3f} V")

        if output_on:
            card.set_summary(
                f"Output: {status.actual_voltage:.2f} V / "
                f"{status.actual_current * 1000:.1f} mA",
                _c_healthy())
        else:
            card.set_summary("Output off", _c_neutral())

    def update_stage_readouts(self, status) -> None:
        """Push live stage position data to the stage card."""
        card = self._cards.get("stage")
        if card is None:
            return
        if status.error is not None:
            return
        pos = status.position
        card.update_info("Position X", f"{pos.x:.1f}")
        card.update_info("Position Y", f"{pos.y:.1f}")
        card.update_info("Position Z", f"{pos.z:.1f}")
        moving = getattr(status, "moving", False)
        card.update_info("Moving", "Yes" if moving else "No")
        card.set_tile_accent("Moving",
                             _c_warning() if moving else _c_neutral())
        homed = getattr(status, "homed", False)
        card.update_info("Homed", "Yes" if homed else "No")
        if moving:
            card.set_summary("Moving\u2026", _c_warning())
        else:
            card.set_summary(
                f"Idle at ({pos.x:.1f}, {pos.y:.1f}, "
                f"{pos.z:.1f}) \u00b5m")

    def update_gpio_readouts(self, status) -> None:
        """Push live GPIO / LED controller data to the gpio card."""
        card = self._cards.get("gpio")
        if card is None:
            return
        if status.error is not None:
            return
        led = getattr(status, "active_led", -1)
        if led >= 0:
            card.update_info("Active LED", f"Ch {led}")
            card.set_tile_accent("Active LED", _c_healthy())
            card.set_summary(f"LED channel {led} active", _c_healthy())
        else:
            card.update_info("Active LED", "None")
            card.set_tile_accent("Active LED", _c_neutral())
            card.set_summary("No LED active")
        fw = getattr(status, "firmware_version", "")
        if fw:
            card.update_info("Firmware", fw)

    def update_ldd_readouts(self, status) -> None:
        """Push live laser diode driver data to the ldd card."""
        card = self._cards.get("ldd")
        if card is None:
            return
        ok = status.error is None
        enabled = ok and getattr(status, "enabled", False)
        card.update_info("Output", "On" if enabled else "Off")
        card.set_tile_accent("Output",
                             _c_healthy() if enabled else _c_neutral())
        cur = getattr(status, "actual_current_a", None)
        if cur is not None and ok:
            card.update_info("Current", f"{cur:.3f}")
        temp = getattr(status, "diode_temp_c", None)
        if temp is not None and ok:
            card.update_info("Diode Temp", f"{temp:.1f}")
        if enabled and cur is not None:
            card.set_summary(f"Driving at {cur:.3f} A", _c_healthy())
        else:
            card.set_summary("Output off", _c_neutral())

    # ── Internal ─────────────────────────────────────────────────────

    def _resolve_display_name(self, key: str, fallback: str) -> str:
        """Return the real hardware model name, or *fallback*."""
        try:
            if key in ("camera", "tr_camera"):
                cam = app_state.tr_cam or app_state.cam
                if cam and hasattr(cam, "info") and cam.info.model:
                    return cam.info.model
            elif key == "ir_camera":
                cam = app_state.ir_cam
                if cam and hasattr(cam, "info") and cam.info.model:
                    return cam.info.model
        except Exception:
            pass
        # Generic fallback from error_narration short names
        if self._display_name_resolver:
            resolved = self._display_name_resolver(key)
            if resolved != key and resolved != key.replace("_", " ").title():
                return resolved
        return fallback

    def _get_or_create_card(
        self, key: str, icon: str, display_name: str, nav_label: str,
    ) -> DeviceStatusCard:
        """Return a cached card, or create and populate a new one."""
        if key not in self._cards:
            layout = self._device_layout_mode(key)
            card = DeviceStatusCard(key, display_name, icon=icon,
                                    layout=layout)
            card.configure_clicked.connect(
                lambda _lbl=nav_label: self.navigate_requested.emit(_lbl))
            self._populate_card_rows(card, key)
            self._cards[key] = card
        return self._cards[key]

    @staticmethod
    def _device_layout_mode(key: str) -> str:
        """Return the card layout mode for a given device key."""
        if "camera" in key:
            return "camera"
        if "stage" in key or key == "newport_npc3":
            return "dashboard"
        if key.startswith("tec") or key == "tec_meerstetter":
            return "dashboard"
        if "fpga" in key or key in ("ni_9637", "ni_sbrio"):
            return "dashboard"
        if "bias" in key or key == "rigol_dp832":
            return "dashboard"
        if key in ("gpio", "ldd"):
            return "dashboard"
        return "generic"

    # ── Card row population (static structure) ───────────────────────

    def _populate_card_rows(self, card: DeviceStatusCard, key: str) -> None:
        """Add device-type-specific info rows to a new card."""
        if "camera" in key:
            self._populate_camera_rows(card, key)
        elif key.startswith("tec") or key == "tec_meerstetter":
            self._populate_tec_rows(card, key)
        elif "fpga" in key or key in ("ni_9637", "ni_sbrio"):
            self._populate_fpga_rows(card)
        elif "bias" in key or key == "rigol_dp832":
            self._populate_bias_rows(card)
        elif "stage" in key or key == "newport_npc3":
            self._populate_stage_rows(card, key)
        elif key == "gpio":
            self._populate_gpio_rows(card)
        elif key == "ldd":
            self._populate_ldd_rows(card)
        elif key in ("prober", "turret"):
            self._populate_prober_rows(card)

    def _populate_camera_rows(self, card: DeviceStatusCard, key: str) -> None:
        # Enable live preview (camera layout creates it automatically)
        card.enable_live_preview()

        # ── Metric tiles (live readouts — prominent) ─────────────
        card.add_tile("Exposure", "\u2014")
        card.add_tile("Gain", "\u2014")
        card.add_tile("Live FPS", "\u2014")

        # ── Info card (static metadata — secondary) ──────────────
        cam = None
        try:
            if key in ("camera", "tr_camera"):
                cam = app_state.tr_cam or app_state.cam
            elif key == "ir_camera":
                cam = app_state.ir_cam
        except Exception:
            pass
        info = getattr(cam, "info", None)
        card.add_info("Model", getattr(info, "model", "\u2014") or "\u2014")
        card.add_info("Serial", getattr(info, "serial", "\u2014") or "\u2014")
        card.add_info("Driver", getattr(info, "driver", "\u2014") or "\u2014")
        w = getattr(info, "width", 0) or 0
        h = getattr(info, "height", 0) or 0
        card.add_info("Resolution", f"{w} x {h}" if w else "\u2014")
        card.add_info("Bit Depth",
                      f"{info.bit_depth}-bit" if info and info.bit_depth else "\u2014")
        card.add_info("Max FPS",
                      f"{info.max_fps:.0f}" if info and info.max_fps else "\u2014")
        card.add_info("Type",
                      info.camera_type.upper() if info and info.camera_type else "\u2014")
        card.add_info("Pixel Format",
                      info.pixel_format if info and info.pixel_format else "\u2014")

        card.set_summary("Connected")

    def _populate_tec_rows(self, card: DeviceStatusCard, key: str) -> None:
        # ── Hero tiles (live readouts) ───────────────────────────
        card.add_tile("Temperature", "\u2014", "\u00b0C")
        card.add_tile("Setpoint", "\u2014", "\u00b0C")
        card.add_tile("Output", "\u2014", "%")
        card.add_tile("Stability", "\u2014")

        # ── Info card (static metadata) ──────────────────────────
        card.add_info("Controller", key.replace("_", " ").title())
        card.add_info("Port", "\u2014")
        card.add_info("Temp Range", "\u2014")
        card.add_info("Sink Temp", "\u2014")

        card.set_summary("Connected")

    def _populate_fpga_rows(self, card: DeviceStatusCard) -> None:
        # ── Hero tiles (live readouts) ───────────────────────────
        card.add_tile("Frequency", "\u2014", "Hz")
        card.add_tile("Duty Cycle", "\u2014", "%")
        card.add_tile("Running", "No")
        card.add_tile("Sync Locked", "No")

        # ── Info card (static metadata) ──────────────────────────
        card.add_info("Driver", "\u2014")
        card.add_info("Resource", "\u2014")
        card.add_info("Trigger Mode", "\u2014")
        card.add_info("Period", "\u2014", monospace=True)

        card.set_summary("Connected")

    def _populate_bias_rows(self, card: DeviceStatusCard) -> None:
        # ── Hero tiles (live readouts) ───────────────────────────
        card.add_tile("Voltage", "\u2014", "V")
        card.add_tile("Current", "\u2014", "mA")
        card.add_tile("Power", "\u2014", "W")
        card.add_tile("Output", "Off")

        # ── Info card (static metadata) ──────────────────────────
        card.add_info("Driver", "\u2014")
        card.add_info("Address", "\u2014")
        card.add_info("Mode", "\u2014")
        card.add_info("Compliance", "\u2014")

        card.set_summary("Connected")

    def _populate_stage_rows(self, card: DeviceStatusCard, key: str) -> None:
        _stage_controllers = {
            "newport_npc3": "Newport NPC3 Piezo Controller",
            "stage":        "Stage Controller",
        }
        # ── Hero tiles (position readouts) ───────────────────────
        card.add_tile("Position X", "\u2014", "µm")
        card.add_tile("Position Y", "\u2014", "µm")
        card.add_tile("Position Z", "\u2014", "µm")
        card.add_tile("Moving", "No")

        # ── Info card (static metadata) ──────────────────────────
        card.add_info("Controller",
                      _stage_controllers.get(
                          key, key.replace("_", " ").title()))
        card.add_info("Port", "\u2014")
        card.add_info("Travel Range", "\u2014")
        card.add_info("Homed", "\u2014")

        card.set_summary("Idle")

    def _populate_gpio_rows(self, card: DeviceStatusCard) -> None:
        # ── Hero tile (live readout) ─────────────────────────────
        card.add_tile("Active LED", "None")

        # ── Info card (static metadata) ──────────────────────────
        card.add_info("Firmware", "\u2014")
        card.add_info("Port", "\u2014")
        card.add_info("LED Channels", "\u2014")

        card.set_summary("Connected")

    def _populate_ldd_rows(self, card: DeviceStatusCard) -> None:
        # ── Hero tiles (live readouts) ───────────────────────────
        card.add_tile("Current", "\u2014", "A")
        card.add_tile("Diode Temp", "\u2014", "\u00b0C")
        card.add_tile("Output", "Off")

        # ── Info card (static metadata) ──────────────────────────
        card.add_info("Driver", "\u2014")
        card.add_info("Address", "\u2014")

        card.set_summary("Connected")

    def _populate_prober_rows(self, card: DeviceStatusCard) -> None:
        card.add_info("Role", "Probe Station")
        card.add_section("Live Readouts")
        card.add_info("Status", "—")
        card.add_info("Chuck Temp", "—")

    # ── Static info refresh (called on connect) ──────────────────────

    def _refresh_static_info(self, card: DeviceStatusCard, key: str) -> None:
        """Update static card fields from the live driver."""
        try:
            if "camera" in key:
                self._refresh_camera_static(card, key)
            elif "fpga" in key or key in ("ni_9637", "ni_sbrio"):
                self._refresh_fpga_static(card)
            elif "bias" in key or key == "rigol_dp832":
                self._refresh_bias_static(card)
            elif key == "gpio":
                self._refresh_gpio_static(card)
            elif key == "ldd":
                self._refresh_ldd_static(card)
            elif "stage" in key or key == "newport_npc3":
                self._refresh_stage_static(card)
            elif key.startswith("tec"):
                self._refresh_tec_static(card, key)
        except Exception:
            log.debug("card static refresh failed for %s", key, exc_info=True)

    def _refresh_camera_static(self, card: DeviceStatusCard, key: str) -> None:
        cam = None
        if key in ("camera", "tr_camera"):
            cam = app_state.tr_cam or app_state.cam
        elif key == "ir_camera":
            cam = app_state.ir_cam
        info = getattr(cam, "info", None)
        if not info:
            return
        card.update_info("Model", info.model or "—")
        card.update_info("Serial", info.serial or "—")
        card.update_info("Driver", info.driver or "—")
        if info.width and info.height:
            card.update_info("Resolution", f"{info.width} x {info.height}")
        if info.bit_depth:
            card.update_info("Bit Depth", f"{info.bit_depth}-bit")
        if info.max_fps:
            card.update_info("Max FPS", f"{info.max_fps:.0f}")
        card.update_info("Type", info.camera_type.upper() if info.camera_type else "—")
        if getattr(info, "pixel_format", None):
            card.update_info("Pixel Format", info.pixel_format)

    def _refresh_fpga_static(self, card: DeviceStatusCard) -> None:
        import config as cfg
        hw = cfg.get("hardware", {})
        fpga_cfg = hw.get("fpga", {})
        drv = fpga_cfg.get("driver", "")
        if drv:
            card.update_info("Driver", drv)
        res = fpga_cfg.get("resource", "") or fpga_cfg.get("address", "")
        if res:
            card.update_info("Resource", res)

    def _refresh_bias_static(self, card: DeviceStatusCard) -> None:
        import config as cfg
        hw = cfg.get("hardware", {})
        bias_cfg = hw.get("bias", {})
        drv = bias_cfg.get("driver", "")
        if drv:
            card.update_info("Driver", drv)
        addr = (bias_cfg.get("address", "")
                or bias_cfg.get("resource", "")
                or bias_cfg.get("host", ""))
        if addr:
            card.update_info("Address", str(addr))

    def _refresh_gpio_static(self, card: DeviceStatusCard) -> None:
        import config as cfg
        hw = cfg.get("hardware", {})
        gpio_cfg = hw.get("arduino", {}) or hw.get("gpio", {})
        port = gpio_cfg.get("port", "")
        if port:
            card.update_info("Port", port)
        channels = gpio_cfg.get("led_channels", [])
        if channels:
            summary = ", ".join(
                ch.get("label", f"{ch.get('wavelength_nm', '?')} nm")
                for ch in channels[:4])
            card.update_info("LED Channels", summary)
        # Firmware is pushed live via update_gpio_readouts

    def _refresh_ldd_static(self, card: DeviceStatusCard) -> None:
        import config as cfg
        hw = cfg.get("hardware", {})
        ldd_cfg = hw.get("ldd_meerstetter", {}) or hw.get("ldd", {})
        drv = ldd_cfg.get("driver", "")
        if drv:
            card.update_info("Driver", drv)
        addr = ldd_cfg.get("address", "")
        if addr:
            card.update_info("Address", str(addr))

    def _refresh_stage_static(self, card: DeviceStatusCard) -> None:
        import config as cfg
        hw = cfg.get("hardware", {})
        stage_cfg = hw.get("stage", {})
        port = stage_cfg.get("port", "")
        if port:
            card.update_info("Port", port)
        # Travel range from the live driver
        stage = app_state.stage
        if stage and hasattr(stage, "travel_range"):
            try:
                tr = stage.travel_range()
                parts = []
                for axis in ("x", "y", "z"):
                    rng = tr.get(axis)
                    if rng:
                        lo, hi = rng
                        parts.append(f"{axis.upper()}: {lo:.0f}\u2013{hi:.0f}")
                if parts:
                    card.update_info("Travel Range",
                                     " / ".join(parts) + " \u00b5m")
            except Exception:
                pass

    def _refresh_tec_static(self, card: DeviceStatusCard, key: str) -> None:
        import config as cfg
        hw = cfg.get("hardware", {})
        # Try keyed section first, then generic tec
        tec_cfg = hw.get(key, {}) or hw.get("tec", {}) or hw.get("tec_meerstetter", {})
        port = tec_cfg.get("port", "")
        if port:
            card.update_info("Port", port)
        # Temperature range from the live driver
        idx = 0
        try:
            idx = int(key.replace("tec", "").replace("_meerstetter", "") or "0")
        except ValueError:
            pass
        tecs = app_state.tecs
        if tecs and idx < len(tecs):
            tec = tecs[idx]
            if hasattr(tec, "temp_range"):
                try:
                    lo, hi = tec.temp_range()
                    card.update_info("Temp Range",
                                     f"{lo:.0f} to {hi:.0f} \u00b0C")
                except Exception:
                    pass

    # ── Live readout reset (called on reconnect) ─────────────────────

    def _reset_live_readouts(self, card: DeviceStatusCard, key: str) -> None:
        """Clear live fields to '\u2014' so stale values don't persist."""
        if "camera" in key:
            card.update_info("Exposure", "\u2014")
            card.update_info("Gain", "\u2014")
            card.update_info("Live FPS", "\u2014")
        elif key.startswith("tec"):
            card.update_info("Temperature", "\u2014")
            card.update_info("Setpoint", "\u2014")
            card.update_info("Output", "\u2014")
            card.update_info("Stability", "\u2014")
            card.update_info("Sink Temp", "\u2014")
        elif "fpga" in key or key in ("ni_9637", "ni_sbrio"):
            card.update_info("Frequency", "\u2014")
            card.update_info("Duty Cycle", "\u2014")
            card.update_info("Running", "No")
            card.update_info("Sync Locked", "No")
            card.update_info("Period", "\u2014")
            card.update_info("Trigger Mode", "\u2014")
        elif "bias" in key or key == "rigol_dp832":
            card.update_info("Voltage", "\u2014")
            card.update_info("Current", "\u2014")
            card.update_info("Power", "\u2014")
            card.update_info("Output", "Off")
            card.update_info("Mode", "\u2014")
            card.update_info("Compliance", "\u2014")
        elif "stage" in key or key == "newport_npc3":
            card.update_info("Position X", "\u2014")
            card.update_info("Position Y", "\u2014")
            card.update_info("Position Z", "\u2014")
            card.update_info("Moving", "No")
            card.update_info("Homed", "\u2014")
        elif key == "gpio":
            card.update_info("Active LED", "None")
        elif key == "ldd":
            card.update_info("Current", "\u2014")
            card.update_info("Diode Temp", "\u2014")
            card.update_info("Output", "Off")
