"""
ui/operator/operator_shell.py

OperatorShell — simplified QMainWindow for Technician users.

This is a complete, self-contained replacement for MainWindow.  It never
imports from MainWindow; it connects directly to the same hardware service
and shared app_state that MainWindow uses.

Layout
------
  Top bar  (48 px):
    [Logo]  "Operator Mode"  |  "Jane Smith  [TECH]"  |  shift summary  |  [Lock]

  Body  QSplitter (Horizontal):
    RecipeSelectorPanel  (300 px fixed)
    ScanWorkArea         (stretch)
    ShiftLogPanel        (280 px fixed max)

  Status bar  (22 px):
    Hardware status  ·  Active camera

Connections (wired in _connect_hardware)
-----------
  hw_service.camera_frame  →  scan_work_area.on_live_frame()
  scan_work_area.scan_requested  →  _on_scan_requested()
  scan_work_area.scan_aborted    →  _on_scan_aborted()
  recipe_panel.recipe_selected   →  scan_work_area.set_recipe()

Signals
-------
  lock_requested()   Emitted when the operator presses [Lock].
                     Caller should destroy / hide this window and show LoginScreen.

Inactivity
----------
  activity_event()   →  auth_session.touch()
  Wired from mouseMoveEvent / keyPressEvent so the Phase A inactivity
  timer keeps ticking correctly.

Post-scan pipeline
------------------
  1.  scan_requested  →  _on_scan_requested()  →  hw_service.start_acquisition()
  2.  hw_service.acquisition_complete  →  _on_acquisition_done()
  3.  ThermalAnalysisEngine.run()  →  AnalysisResult
  4.  VerdictOverlay shown; ShiftLogPanel.append_result()
  5.  Auto-PDF via generate_report()  (best-effort, non-blocking)
  6.  scan_work_area.clear_part_id() + set_scanning(False)

Usage
-----
  from ui.operator.operator_shell import OperatorShell

  shell = OperatorShell(
      auth=_auth,
      auth_session=_session,
      hw_service=_hw_service,
      parent=None,
  )
  shell.lock_requested.connect(_on_lock)
  shell.show()
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional

from PyQt5.QtCore    import Qt, pyqtSignal, QTimer
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSplitter, QFrame, QStatusBar,
    QSizePolicy,
)

from ui.theme import FONT, PALETTE
from ui.operator.recipe_selector_panel import RecipeSelectorPanel
from ui.operator.scan_work_area        import ScanWorkArea
from ui.operator.shift_log_panel       import ShiftLogPanel
from ui.operator.verdict_overlay       import VerdictOverlay

log = logging.getLogger(__name__)

_TOP_BG   = "#0a0c18"
_BODY_BG  = "#0b0e1a"
_SEPAR    = "#1e2235"
_ACCENT   = PALETTE.get("accent", "#00d4aa")


# ── Type badge ────────────────────────────────────────────────────────────────

def _user_badge(user) -> str:
    """Short badge text from UserType — e.g. '[TECH]'."""
    try:
        val = user.user_type.value
        return {
            "technician":      "[TECH]",
            "failure_analyst": "[FA]",
            "researcher":      "[RES]",
        }.get(val, "[?]")
    except Exception:
        return ""


# ── Top bar ───────────────────────────────────────────────────────────────────

class _TopBar(QWidget):
    lock_clicked = pyqtSignal()

    def __init__(self, auth_session=None, parent=None):
        super().__init__(parent)
        self.setFixedHeight(48)
        self.setStyleSheet(
            f"background:{_TOP_BG}; border-bottom:1px solid {_SEPAR};")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 16, 0)
        lay.setSpacing(16)

        # ── Logo ───────────────────────────────────────────────────────────
        logo = QLabel("Sanj<span style='color:#00d4aa;'>INSIGHT</span>")
        logo.setTextFormat(Qt.RichText)
        logo.setStyleSheet(
            "font-size:14pt; font-weight:800; color:#ffffff; background:transparent;")
        lay.addWidget(logo)

        # ── Mode label ─────────────────────────────────────────────────────
        mode = QLabel("Operator Mode")
        mode.setStyleSheet(
            f"font-size:{FONT.get('label', 10)}pt; font-weight:600; "
            f"color:{_ACCENT}; background:transparent; "
            "border:1px solid #00d4aa44; border-radius:3px; padding:2px 8px;")
        lay.addWidget(mode)

        lay.addStretch(1)

        # ── User info ──────────────────────────────────────────────────────
        self._user_lbl = QLabel()
        self._user_lbl.setStyleSheet(
            f"font-size:{FONT.get('body', 11)}pt; color:#cccccc; "
            "background:transparent;")
        self._set_user_label(auth_session)
        lay.addWidget(self._user_lbl)

        # ── Shift summary (updated dynamically) ───────────────────────────
        self._shift_lbl = QLabel("0 scans this shift")
        self._shift_lbl.setStyleSheet(
            f"font-size:{FONT.get('sublabel', 9)}pt; color:#555555; "
            "background:transparent;")
        lay.addWidget(self._shift_lbl)

        # ── Lock button ────────────────────────────────────────────────────
        lock_btn = QPushButton("Lock")
        lock_btn.setFixedSize(64, 30)
        lock_btn.setStyleSheet(
            "QPushButton { background:#1a1e30; color:#888888; "
            "border:1px solid #2a3249; border-radius:4px; "
            f"font-size:{FONT.get('label', 10)}pt; }}"
            "QPushButton:hover { background:#2a3249; color:#cccccc; }")
        lock_btn.clicked.connect(self.lock_clicked)
        lay.addWidget(lock_btn)

    def _set_user_label(self, session) -> None:
        if session is not None:
            user  = session.user
            badge = _user_badge(user)
            self._user_lbl.setText(f"{user.display_name}  {badge}")
            self._user_lbl.setStyleSheet(
                f"font-size:{FONT.get('body', 11)}pt; color:#cccccc; "
                "background:transparent;")
        else:
            self._user_lbl.setText("Guest")
            self._user_lbl.setStyleSheet(
                f"font-size:{FONT.get('body', 11)}pt; color:#666666; "
                "background:transparent;")

    def update_user(self, session) -> None:
        """Update the user name label after re-login."""
        self._set_user_label(session)

    def update_shift(self, n_scans: int, n_pass: int) -> None:
        if n_scans == 0:
            self._shift_lbl.setText("0 scans this shift")
        else:
            pct = int(100 * n_pass / n_scans)
            self._shift_lbl.setText(
                f"{n_scans} scan{'s' if n_scans != 1 else ''} · {pct}% pass")


# ── OperatorShell ─────────────────────────────────────────────────────────────

class OperatorShell(QMainWindow):
    """
    Simplified QMainWindow for Technician users.

    Parameters
    ----------
    auth         : Authenticator
    auth_session : AuthSession
    hw_service   : HardwareService  (may be None for UI-only testing)
    parent       : QWidget, optional
    """

    lock_requested = pyqtSignal()

    def __init__(
        self,
        auth=None,
        auth_session=None,
        hw_service=None,
        parent=None,
    ):
        super().__init__(parent)
        self._auth         = auth
        self._auth_session = auth_session
        self._hw_service   = hw_service
        self._active_recipe = None
        self._active_part_id: str = ""
        self._scan_start_time: float = 0.0
        self._pending_acq_result = None  # AcquisitionResult while analysis runs

        self.setWindowTitle("SanjINSIGHT — Operator Mode")
        self.setMinimumSize(1024, 660)

        # ── Central widget ─────────────────────────────────────────────────
        central = QWidget()
        central.setStyleSheet(f"background:{_BODY_BG};")
        self.setCentralWidget(central)
        main_lay = QVBoxLayout(central)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(0)

        # ── Top bar ────────────────────────────────────────────────────────
        self._top_bar = _TopBar(auth_session=auth_session)
        self._top_bar.lock_clicked.connect(self._on_lock)
        main_lay.addWidget(self._top_bar)

        # ── Body splitter ──────────────────────────────────────────────────
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(2)
        splitter.setStyleSheet(
            f"QSplitter::handle {{ background:{_SEPAR}; }}")

        self._recipe_panel = RecipeSelectorPanel()
        self._scan_area    = ScanWorkArea()
        self._shift_log    = ShiftLogPanel()

        splitter.addWidget(self._recipe_panel)
        splitter.addWidget(self._scan_area)
        splitter.addWidget(self._shift_log)

        # Fixed widths for side panels; centre stretches
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([300, 700, 260])

        main_lay.addWidget(splitter, 1)

        # ── Status bar ─────────────────────────────────────────────────────
        sb = QStatusBar()
        sb.setFixedHeight(22)
        sb.setStyleSheet(
            f"QStatusBar {{ background:{_TOP_BG}; color:#555555; "
            f"border-top:1px solid {_SEPAR}; "
            f"font-size:{FONT.get('caption', 8)}pt; }}")
        self.setStatusBar(sb)
        self._status_bar = sb
        self._set_status("Ready")

        # ── Wire internal signals ──────────────────────────────────────────
        self._recipe_panel.recipe_selected.connect(self._on_recipe_selected)
        self._scan_area.scan_requested.connect(self._on_scan_requested)
        self._scan_area.scan_aborted.connect(self._on_scan_aborted)

        # ── Connect hardware ───────────────────────────────────────────────
        if hw_service is not None:
            self._connect_hardware(hw_service)

    # ── Hardware wiring ────────────────────────────────────────────────────────

    def _connect_hardware(self, hw_service) -> None:
        try:
            hw_service.camera_frame.connect(self._scan_area.on_live_frame)
        except Exception as exc:
            log.warning("OperatorShell: could not connect camera_frame: %s", exc)

        try:
            hw_service.acquisition_complete.connect(self._on_acquisition_done)
        except Exception as exc:
            log.warning("OperatorShell: could not connect acquisition_complete: %s", exc)

        try:
            hw_service.acquisition_progress.connect(self._on_acq_progress)
        except Exception as exc:
            log.debug("OperatorShell: no acquisition_progress signal: %s", exc)

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_auth_session(self, session) -> None:
        """Update the auth session (called after re-login from lock screen)."""
        self._auth_session = session
        self._top_bar.update_user(session)

    # ── Inactivity ─────────────────────────────────────────────────────────────

    def activity_event(self) -> None:
        """Call on any user interaction to reset the inactivity clock."""
        if self._auth_session is not None:
            self._auth_session.touch()

    def mouseMoveEvent(self, event) -> None:
        self.activity_event()
        super().mouseMoveEvent(event)

    def keyPressEvent(self, event) -> None:
        self.activity_event()
        super().keyPressEvent(event)

    # ── Lock ───────────────────────────────────────────────────────────────────

    def _on_lock(self) -> None:
        if self._auth is not None:
            self._auth.lock()
        self.lock_requested.emit()

    # ── Recipe selection ───────────────────────────────────────────────────────

    def _on_recipe_selected(self, recipe) -> None:
        self._active_recipe = recipe
        self._scan_area.set_recipe(recipe)
        if recipe is not None:
            self._set_status(f"Recipe: {recipe.label}")
        else:
            self._set_status("Ready")

    # ── Scan lifecycle ─────────────────────────────────────────────────────────

    def _on_scan_requested(self, recipe, part_id: str) -> None:
        self._active_recipe  = recipe
        self._active_part_id = part_id
        self._scan_start_time = time.time()

        log.info("OperatorShell: scan requested — recipe=%s, part=%s",
                 recipe.label if recipe else "?", part_id)

        self._scan_area.set_scanning(True, "Scanning…")
        self._set_status(f"Scanning part: {part_id}")

        if self._hw_service is not None:
            self._start_hardware_scan(recipe, part_id)
        else:
            # No hardware — simulate after 2 s (dev / demo mode)
            QTimer.singleShot(2000, self._simulate_scan_complete)

    def _start_hardware_scan(self, recipe, part_id: str) -> None:
        """Dispatch the acquisition to hw_service using recipe parameters."""
        try:
            import config as _cfg
            from hardware.app_state import app_state

            cam_cfg = getattr(recipe, "camera",     None)
            acq_cfg = getattr(recipe, "acquisition", None)
            bias_cfg = getattr(recipe, "bias",       None)

            # Apply recipe camera settings if hw_service exposes them
            if cam_cfg is not None:
                try:
                    self._hw_service.set_camera_params(
                        exposure_us = cam_cfg.exposure_us,
                        gain_db     = cam_cfg.gain_db,
                    )
                except Exception:
                    pass

            # Start acquisition
            n_frames = cam_cfg.n_frames if cam_cfg else 16
            self._hw_service.start_acquisition(n_frames=n_frames)

        except Exception as exc:
            log.error("OperatorShell: hw scan start failed: %s", exc)
            self._scan_area.set_scanning(False)
            self._set_status(f"Scan error: {exc}")

    def _on_acq_progress(self, frames_done: int, frames_total: int) -> None:
        self._scan_area.set_progress(frames_done, frames_total)

    def _on_acquisition_done(self, acq_result) -> None:
        """Called when hw_service signals acquisition is complete."""
        self._pending_acq_result = acq_result
        self._finish_scan(acq_result)

    def _simulate_scan_complete(self) -> None:
        """Dev-mode: produce a synthetic PASS result."""
        try:
            from acquisition.analysis import AnalysisResult
            result = AnalysisResult(
                verdict="PASS", hotspots=[], n_hotspots=0,
                max_peak_k=0.8, total_area_px=0, area_fraction=0.0,
                map_mean_k=0.0, map_std_k=0.0, threshold_k=5.0,
                overlay_rgb=None, binary_mask=None,
                timestamp=time.time(),
                timestamp_str=__import__("datetime").datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"),
                config=None, notes="", valid=True,
            )
            self._finish_scan(acq_result=None, analysis_result=result)
        except Exception as exc:
            log.error("OperatorShell: simulate_scan_complete failed: %s", exc)
            self._scan_area.set_scanning(False)
            self._set_status("Simulation error")

    def _finish_scan(
        self,
        acq_result=None,
        analysis_result=None,
    ) -> None:
        """Run analysis (if not already done) then show VerdictOverlay."""
        scan_time_s = time.time() - self._scan_start_time

        # ── Run analysis if we have acquisition data but no result yet ─────
        if analysis_result is None and acq_result is not None:
            analysis_result = self._run_analysis(acq_result)

        # ── Fallback result if analysis unavailable ────────────────────────
        if analysis_result is None:
            try:
                from acquisition.analysis import AnalysisResult
                analysis_result = AnalysisResult(
                    verdict="WARNING", hotspots=[], n_hotspots=0,
                    max_peak_k=0.0, total_area_px=0, area_fraction=0.0,
                    map_mean_k=0.0, map_std_k=0.0, threshold_k=5.0,
                    overlay_rgb=None, binary_mask=None,
                    timestamp=time.time(),
                    timestamp_str=datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"),
                    config=None, notes="Analysis unavailable", valid=False,
                )
            except Exception:
                self._scan_area.set_scanning(False)
                return

        verdict = getattr(analysis_result, "verdict", "WARNING")

        # ── Append to shift log ────────────────────────────────────────────
        self._shift_log.append_result(
            verdict      = verdict,
            part_id      = self._active_part_id,
            recipe_label = (self._active_recipe.label
                            if self._active_recipe else ""),
            timestamp    = time.time(),
        )

        # ── Update top-bar shift summary ───────────────────────────────────
        self._top_bar.update_shift(
            self._shift_log.entry_count(),
            self._shift_log.pass_count(),
        )

        # ── Stop scanning state ────────────────────────────────────────────
        self._scan_area.set_scanning(False)
        self._set_status(f"Last: {verdict} — {self._active_part_id}")
        # Store for "View Details" modal
        self._last_analysis_result = analysis_result
        self._last_part_id         = self._active_part_id

        # ── Auto-save session + generate PDF (best-effort) ─────────────────
        QTimer.singleShot(0, lambda: self._save_and_report(
            acq_result, analysis_result, scan_time_s))

        # ── Show verdict overlay ───────────────────────────────────────────
        overlay = VerdictOverlay(
            result      = analysis_result,
            part_id     = self._active_part_id,
            recipe      = self._active_recipe,
            scan_time_s = scan_time_s,
            parent      = self,
        )
        overlay.next_part.connect(self._on_next_part)
        overlay.flagged.connect(self._on_flag_result)
        overlay.view_details.connect(self._on_view_details)
        overlay.exec_()

    def _run_analysis(self, acq_result):
        """Run ThermalAnalysisEngine using the active recipe's thresholds."""
        try:
            from acquisition.analysis import ThermalAnalysisEngine, AnalysisConfig

            recipe_analysis = getattr(self._active_recipe, "analysis", None)
            cfg = AnalysisConfig(
                threshold_k        = getattr(recipe_analysis, "threshold_k",       5.0),
                fail_hotspot_count = getattr(recipe_analysis, "fail_hotspot_count", 3),
                fail_peak_k        = getattr(recipe_analysis, "fail_peak_k",        20.0),
                fail_area_fraction = getattr(recipe_analysis, "fail_area_fraction", 0.05),
                warn_hotspot_count = getattr(recipe_analysis, "warn_hotspot_count", 1),
                warn_peak_k        = getattr(recipe_analysis, "warn_peak_k",        10.0),
                warn_area_fraction = getattr(recipe_analysis, "warn_area_fraction", 0.01),
            ) if recipe_analysis else AnalysisConfig()

            drr = getattr(acq_result, "delta_r_over_r", None)
            if drr is None:
                return None

            engine = ThermalAnalysisEngine(cfg=cfg)
            return engine.run(dt_map=None, drr_map=drr)

        except Exception as exc:
            log.error("OperatorShell._run_analysis: %s", exc)
            return None

    def _save_and_report(
        self, acq_result, analysis_result, scan_time_s: float
    ) -> None:
        """Best-effort session save + PDF report generation."""
        try:
            import config as _cfg
            from pathlib import Path

            sessions_root = Path(
                _cfg.get("paths", {}).get(
                    "sessions_dir",
                    str(Path.home() / ".microsanj" / "sessions"),
                )
            )

            operator = (
                self._auth_session.user.display_name
                if self._auth_session else ""
            )

            if acq_result is not None:
                from acquisition.session import Session
                session = Session.from_result(
                    acq_result,
                    label     = f"{self._active_part_id}_op",
                    operator  = operator,
                    device_id = self._active_part_id,
                    notes_log = [],
                )
                session_path = session.save(str(sessions_root))
                log.info("OperatorShell: session saved to %s", session_path)

                try:
                    from acquisition.report import generate_report
                    pdf = generate_report(
                        session,
                        output_dir = str(Path(session_path).parent),
                        analysis   = analysis_result,
                    )
                    log.info("OperatorShell: PDF report saved to %s", pdf)
                except Exception as exc:
                    log.warning("OperatorShell: PDF generation failed: %s", exc)

        except Exception as exc:
            log.warning("OperatorShell._save_and_report: %s", exc)

    def _on_scan_aborted(self) -> None:
        log.info("OperatorShell: scan aborted by operator")
        if self._hw_service is not None:
            try:
                self._hw_service.abort_acquisition()
            except Exception as exc:
                log.warning("OperatorShell: abort failed: %s", exc)
        self._scan_area.set_scanning(False)
        self._set_status("Scan aborted")

    # ── Post-verdict actions ───────────────────────────────────────────────────

    def _on_next_part(self) -> None:
        self._scan_area.clear_part_id()
        self._set_status("Ready for next part")

    def _on_flag_result(self, part_id: str) -> None:
        log.info("OperatorShell: part '%s' flagged for review", part_id)
        self._set_status(f"Flagged: {part_id}")
        self._scan_area.clear_part_id()

    def _on_view_details(self) -> None:
        """Show a read-only detail dialog for the most recent scan result."""
        result  = getattr(self, "_last_analysis_result", None)
        part_id = getattr(self, "_last_part_id", "")
        if result is None:
            return
        log.info("OperatorShell: view details for part '%s'", part_id)
        self._show_details_dialog(result, part_id)

    def _show_details_dialog(self, result, part_id: str) -> None:
        """Modal with the full hotspot table + metric summary."""
        from PyQt5.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel,
            QTableWidget, QTableWidgetItem, QPushButton,
            QHeaderView,
        )
        from PyQt5.QtGui import QColor

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Scan Details — {part_id}")
        dlg.setMinimumSize(520, 420)
        dlg.setStyleSheet(
            f"QDialog {{ background:{PALETTE.get('surface','#2d2d2d')}; "
            f"color:{PALETTE.get('text','#ebebeb')}; }}"
            f"QLabel  {{ background:transparent; }}"
        )
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(10)

        # ── Title ──────────────────────────────────────────────────────────
        verdict = getattr(result, "verdict", "UNKNOWN")
        _vc = {
            "PASS":    PALETTE.get("success",  "#30d158"),
            "FAIL":    PALETTE.get("danger",   "#ff453a"),
            "WARNING": PALETTE.get("warning",  "#ff9f0a"),
        }.get(verdict, PALETTE.get("textDim", "#999"))
        title_lbl = QLabel(f"{verdict}  —  {part_id}")
        title_lbl.setStyleSheet(
            f"font-size:{FONT.get('heading',15)}pt; font-weight:700; color:{_vc};"
        )
        lay.addWidget(title_lbl)

        # ── Summary row ────────────────────────────────────────────────────
        def _metric(label: str, value: str) -> QLabel:
            w = QLabel(f"<b>{label}</b>  {value}")
            w.setStyleSheet(
                f"font-size:{FONT.get('label',11)}pt; "
                f"color:{PALETTE.get('textDim','#999')};"
            )
            return w

        summary_row = QHBoxLayout()
        summary_row.addWidget(_metric("Max hotspot:",
            f"{getattr(result, 'max_peak_k', 0.0):.1f} °C"))
        summary_row.addWidget(_metric("Hotspots:",
            str(getattr(result, 'n_hotspots', 0))))
        summary_row.addWidget(_metric("Area fraction:",
            f"{getattr(result, 'area_fraction', 0.0)*100:.2f}%"))
        summary_row.addWidget(_metric("Valid:",
            "Yes" if getattr(result, 'valid', True) else "No"))
        summary_row.addStretch()
        lay.addLayout(summary_row)

        # ── Hotspot table ──────────────────────────────────────────────────
        hotspots = getattr(result, "hotspots", []) or []
        if hotspots:
            table = QTableWidget(len(hotspots), 4)
            table.setHorizontalHeaderLabels(["#", "Peak (°C)", "Area (px²)", "Severity"])
            table.verticalHeader().setVisible(False)
            table.setEditTriggers(QTableWidget.NoEditTriggers)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            table.setStyleSheet(
                f"QTableWidget {{ background:{PALETTE.get('bg','#242424')}; "
                f"color:{PALETTE.get('text','#ebebeb')}; border:none; gridline-color:{PALETTE.get('border','#484848')}; }}"
                f"QHeaderView::section {{ background:{PALETTE.get('surface2','#353535')}; "
                f"color:{PALETTE.get('textDim','#999')}; border:none; padding:4px; }}"
            )
            _sev_colors = {
                "critical": PALETTE.get("danger",  "#ff453a"),
                "warning":  PALETTE.get("warning", "#ff9f0a"),
            }
            for row_i, hs in enumerate(hotspots):
                table.setItem(row_i, 0, QTableWidgetItem(str(row_i + 1)))
                table.setItem(row_i, 1, QTableWidgetItem(
                    f"{getattr(hs, 'peak_k', 0.0):.1f}"))
                table.setItem(row_i, 2, QTableWidgetItem(
                    str(getattr(hs, 'area_px', 0))))
                sev  = getattr(hs, "severity", "")
                sev_item = QTableWidgetItem(sev.capitalize() if sev else "—")
                sev_item.setForeground(
                    QColor(_sev_colors.get(sev.lower(), PALETTE.get("text", "#ebebeb"))))
                table.setItem(row_i, 3, sev_item)
            lay.addWidget(table, 1)
        else:
            no_hs = QLabel("No hotspots detected.")
            no_hs.setStyleSheet(
                f"color:{PALETTE.get('textDim','#999')}; font-style:italic; padding:8px;")
            lay.addWidget(no_hs)

        # ── Notes ──────────────────────────────────────────────────────────
        notes = getattr(result, "notes", "")
        if notes:
            notes_lbl = QLabel(f"Notes: {notes}")
            notes_lbl.setWordWrap(True)
            notes_lbl.setStyleSheet(
                f"font-size:{FONT.get('caption',10)}pt; "
                f"color:{PALETTE.get('textSub','#6a6a6a')}; font-style:italic;")
            lay.addWidget(notes_lbl)

        # ── Close button ───────────────────────────────────────────────────
        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(30)
        close_btn.setStyleSheet(
            f"QPushButton {{ background:{PALETTE.get('surface2','#353535')}; "
            f"color:{PALETTE.get('textDim','#999')}; border:1px solid {PALETTE.get('border','#484848')}; "
            f"border-radius:4px; padding:4px 20px; font-size:{FONT.get('body',12)}pt; }}"
            f"QPushButton:hover {{ background:{PALETTE.get('surfaceHover','#404040')}; "
            f"color:{PALETTE.get('text','#ebebeb')}; }}"
        )
        close_btn.clicked.connect(dlg.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)

        dlg.exec_()

    # ── Status bar ─────────────────────────────────────────────────────────────

    def _set_status(self, msg: str) -> None:
        self._status_bar.showMessage(msg)

    # ── Theme ──────────────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        """Re-apply theme if app theme changes (OperatorShell uses fixed dark UI)."""
        pass
