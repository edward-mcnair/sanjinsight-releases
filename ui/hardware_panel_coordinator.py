"""
ui/hardware_panel_coordinator.py

Owns the five hardware-category sidebar panels and their DeviceStatusCard
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
from ui.widgets.device_status_card import DeviceStatusCard
from ui.widgets.hardware_category_panel import HardwareCategoryPanel

log = logging.getLogger(__name__)


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
        """Build the five category panels and return them keyed by category.

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
            ("stimulus", "Stimulus",
             "No stimulus devices connected.\n"
             "Connect an FPGA, bias source, or LED controller "
             "in Device Manager, or start Demo Mode to explore "
             "the interface."),
            ("probes", "Probes",
             "No probe hardware connected.\n"
             "Connect a prober in Device Manager, or start "
             "Demo Mode to explore the interface."),
            ("sensors", "Sensors",
             "No sensors connected.\n"
             "Connect a TEC controller or temperature sensor "
             "in Device Manager, or start Demo Mode to explore "
             "the interface."),
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
        stim  = self._panels["stimulus"]
        prb   = self._panels["probes"]
        sens  = self._panels["sensors"]

        self._route_table = {
            # ── Cameras ──────────────────────────────────────────────
            "camera":          (cam,  IC.CAMERA,      "Camera",              "Modality"),
            "tr_camera":       (cam,  IC.CAMERA,      "TR Camera",           "Modality"),
            "ir_camera":       (cam,  IC.CAMERA,      "IR Camera",           "Modality"),
            # ── Stages ───────────────────────────────────────────────
            "stage":           (stg,  IC.STAGE,       "Stage",               "Focus & Stage"),
            "newport_npc3":    (stg,  IC.STAGE,       "Newport NPC3 Piezo Controller",       "Focus & Stage"),
            # ── Stimulus ─────────────────────────────────────────────
            "fpga":            (stim, IC.FPGA,        "Timing / FPGA",       "Stimulus"),
            "ni_9637":         (stim, IC.FPGA,        "NI 9637",             "Stimulus"),
            "ni_sbrio":        (stim, IC.FPGA,        "NI sbRIO",            "Stimulus"),
            "bias":            (stim, IC.BIAS,        "Bias Source",         "Stimulus"),
            "rigol_dp832":     (stim, IC.BIAS,        "Rigol DP832",         "Stimulus"),
            "gpio":            (stim, IC.ILLUMINATION, "GPIO / LED Selector", "Stimulus"),
            "ldd":             (stim, IC.ILLUMINATION, "Optical Source",      "Stimulus"),
            # ── Probes ───────────────────────────────────────────────
            "prober":          (prb,  IC.PROBER,      "Prober",              "Focus & Stage"),
            "turret":          (prb,  IC.PROBER,      "Objective Turret",    "Focus & Stage"),
            # ── Sensors ──────────────────────────────────────────────
            "tec0":            (sens, IC.TEMPERATURE,  "TEC 1",              "Temperature"),
            "tec1":            (sens, IC.TEMPERATURE,  "TEC 2",              "Temperature"),
            "tec2":            (sens, IC.TEMPERATURE,  "TEC 3",              "Temperature"),
            "tec_meerstetter": (sens, IC.TEMPERATURE,  "Meerstetter TEC",    "Temperature"),
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
        """Push exposure/gain/FPS from a camera frame to any active card."""
        for ckey in ("camera", "tr_camera", "ir_camera"):
            card = self._cards.get(ckey)
            if card is None:
                continue
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

    def update_tec_readouts(self, index: int, status) -> None:
        """Push live TEC data to the matching sensor card."""
        key = f"tec{index}"
        card = self._cards.get(key)
        ok = status.error is None
        if card is None or not ok:
            return
        card.update_info("Temperature", f"{status.actual_temp:.2f} °C")
        card.update_info("Setpoint", f"{status.target_temp:.1f} °C")
        pwr = getattr(status, "output_power", None)
        card.update_info("Output", f"{pwr:.0f}%" if pwr is not None else "On")
        dt = abs(status.actual_temp - status.target_temp)
        if dt < 0.05:
            card.update_info("Stability", "Stable (< 0.05 °C)")
        elif dt < 0.5:
            card.update_info("Stability", f"Settling ({dt:.2f} °C)")
        else:
            card.update_info("Stability", f"Ramping ({dt:.1f} °C)")

    def update_fpga_readouts(self, status) -> None:
        """Push live FPGA data to the timing card."""
        card = self._cards.get("fpga")
        if card is None:
            return
        ok = status.error is None and status.running
        freq = getattr(status, "frequency", None)
        duty = getattr(status, "duty_cycle", None)
        if freq is not None:
            card.update_info("Frequency", f"{freq:,.0f} Hz")
            if freq > 0:
                period_us = 1e6 / freq
                if period_us >= 1000:
                    card.update_info("Period", f"{period_us/1000:.2f} ms")
                else:
                    card.update_info("Period", f"{period_us:.1f} us")
        if duty is not None:
            card.update_info("Duty Cycle", f"{duty:.1f}%")
        card.update_info("State", "Running" if ok else "Stopped")

    def update_bias_readouts(self, status) -> None:
        """Push live bias source data to the bias card."""
        card = self._cards.get("bias")
        if card is None:
            return
        ok = status.error is None and status.output_on
        if ok:
            card.update_info("Voltage", f"{status.actual_voltage:.3f} V")
            card.update_info("Current", f"{status.actual_current*1000:.2f} mA")
            card.update_info("Output", "On")
        else:
            card.update_info("Output", "Off")

    def update_stage_readouts(self, status) -> None:
        """Push live stage position data to the stage card."""
        card = self._cards.get("stage")
        if card is None:
            return
        if status.error is not None:
            return
        pos = status.position
        card.update_info("Position X", f"{pos.x:.1f} um")
        card.update_info("Position Y", f"{pos.y:.1f} um")
        card.update_info("Position Z", f"{pos.z:.1f} um")
        moving = getattr(status, "is_moving", False)
        card.update_info("Moving", "Yes" if moving else "No")

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
            card = DeviceStatusCard(key, display_name, icon=icon)
            card.configure_clicked.connect(
                lambda _lbl=nav_label: self.navigate_requested.emit(_lbl))
            self._populate_card_rows(card, key)
            self._cards[key] = card
        return self._cards[key]

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
        cam = None
        try:
            if key in ("camera", "tr_camera"):
                cam = app_state.tr_cam or app_state.cam
            elif key == "ir_camera":
                cam = app_state.ir_cam
        except Exception:
            pass
        info = getattr(cam, "info", None)
        card.add_info("Model", getattr(info, "model", "—") or "—")
        card.add_info("Serial", getattr(info, "serial", "—") or "—")
        card.add_info("Driver", getattr(info, "driver", "—") or "—")
        w = getattr(info, "width", 0) or 0
        h = getattr(info, "height", 0) or 0
        card.add_info("Resolution", f"{w} x {h}" if w else "—")
        card.add_info("Bit Depth",
                      f"{info.bit_depth}-bit" if info and info.bit_depth else "—")
        card.add_info("Max FPS",
                      f"{info.max_fps:.0f}" if info and info.max_fps else "—")
        card.add_info("Type",
                      info.camera_type.upper() if info and info.camera_type else "—")
        card.add_info("Pixel Format",
                      info.pixel_format if info and info.pixel_format else "—")
        card.add_section("Live Readouts")
        card.add_info("Exposure", "—", monospace=True)
        card.add_info("Gain", "—", monospace=True)
        card.add_info("Live FPS", "—", monospace=True)

    def _populate_tec_rows(self, card: DeviceStatusCard, key: str) -> None:
        card.add_info("Controller", key.replace("_", " ").title())
        card.add_section("Live Readouts")
        card.add_info("Temperature", "—", monospace=True)
        card.add_info("Setpoint", "—", monospace=True)
        card.add_info("Output", "—", monospace=True)
        card.add_info("Stability", "—")

    def _populate_fpga_rows(self, card: DeviceStatusCard) -> None:
        card.add_info("Role", "Timing / FPGA")
        card.add_section("Live Readouts")
        card.add_info("Frequency", "—", monospace=True)
        card.add_info("Duty Cycle", "—", monospace=True)
        card.add_info("Period", "—", monospace=True)
        card.add_info("State", "Idle")

    def _populate_bias_rows(self, card: DeviceStatusCard) -> None:
        card.add_info("Role", "Bias Source")
        card.add_section("Live Readouts")
        card.add_info("Voltage", "—", monospace=True)
        card.add_info("Current", "—", monospace=True)
        card.add_info("Compliance", "—", monospace=True)
        card.add_info("Output", "Off")

    def _populate_stage_rows(self, card: DeviceStatusCard, key: str) -> None:
        _stage_controllers = {
            "newport_npc3": "Newport NPC3 Piezo Controller",
            "stage":        "Stage Controller",
        }
        card.add_info("Controller", _stage_controllers.get(key, key.replace("_", " ").title()))
        card.add_section("Position")
        card.add_info("Position X", "—", monospace=True)
        card.add_info("Position Y", "—", monospace=True)
        card.add_info("Position Z", "—", monospace=True)
        card.add_info("Moving", "No")

    def _populate_gpio_rows(self, card: DeviceStatusCard) -> None:
        card.add_info("Role", "GPIO / LED Selector")
        card.add_section("Live Readouts")
        card.add_info("Active LED", "—")
        card.add_info("Wavelength", "—")

    def _populate_ldd_rows(self, card: DeviceStatusCard) -> None:
        card.add_info("Role", "Optical Source")
        card.add_section("Live Readouts")
        card.add_info("Output", "—")
        card.add_info("Current", "—")

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

    # ── Live readout reset (called on reconnect) ─────────────────────

    def _reset_live_readouts(self, card: DeviceStatusCard, key: str) -> None:
        """Clear live fields to '—' so stale values don't persist."""
        if "camera" in key:
            card.update_info("Exposure", "—")
            card.update_info("Gain", "—")
            card.update_info("Live FPS", "—")
        elif key.startswith("tec"):
            card.update_info("Temperature", "—")
            card.update_info("Setpoint", "—")
            card.update_info("Output", "—")
            card.update_info("Stability", "—")
        elif "fpga" in key or key in ("ni_9637", "ni_sbrio"):
            card.update_info("Frequency", "—")
            card.update_info("Duty Cycle", "—")
            card.update_info("Period", "—")
            card.update_info("State", "Idle")
        elif "bias" in key or key == "rigol_dp832":
            card.update_info("Voltage", "—")
            card.update_info("Current", "—")
            card.update_info("Compliance", "—")
            card.update_info("Output", "Off")
        elif "stage" in key or key == "newport_npc3":
            card.update_info("Position X", "—")
            card.update_info("Position Y", "—")
            card.update_info("Position Z", "—")
            card.update_info("Moving", "No")
