"""
ui/widgets/optimization_suggestions.py

Non-intrusive real-time optimisation suggestions strip.

Displays actionable tips below the ReadinessWidget based on live
MetricsService data.  Each suggestion has an optional action button
that emits ``action_requested`` — the caller decides what to do.

Tips are informational-only and never auto-apply changes.
"""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal

from ui.theme import PALETTE, FONT


# ── Suggestion rules ──────────────────────────────────────────────────────────

def _evaluate(snapshot: dict) -> list[dict]:
    """Pure-function rules engine.  Returns list of suggestion dicts."""
    tips: list[dict] = []
    cam = snapshot.get("camera", {})
    tec = snapshot.get("tec", [])

    # Saturation risk
    sat = cam.get("saturation_pct", 0)
    if sat > 1.0:
        tips.append({
            "code": "auto_expose",
            "icon": "⚠",
            "message": f"Saturation at {sat:.1f}% — reduce exposure to avoid clipping.",
            "action": "Auto-Expose",
            "priority": 1,
        })

    # Under-exposure
    under = cam.get("underexposure_pct", 0)
    if under > 30.0:
        tips.append({
            "code": "auto_expose",
            "icon": "⚠",
            "message": f"Under-exposure at {under:.0f}% — increase exposure for better SNR.",
            "action": "Auto-Expose",
            "priority": 2,
        })

    # Poor focus
    focus = cam.get("focus_score", 999)
    if focus < 120 and cam.get("connected", False):
        tips.append({
            "code": "autofocus",
            "icon": "🔍",
            "message": f"Focus score {focus:.0f} — consider running autofocus.",
            "action": "Autofocus",
            "priority": 3,
        })

    # Frame drift
    drift = cam.get("drift_score", 0)
    if drift > 0.02:
        tips.append({
            "code": "drift_wait",
            "icon": "↔",
            "message": "Frame drift detected — system may still be settling.",
            "action": None,
            "priority": 5,
        })

    # TEC not stable
    for ch in (tec if isinstance(tec, list) else []):
        if ch.get("enabled") and not ch.get("stable"):
            bt = ch.get("time_in_band_s", 0)
            idx = ch.get("idx", 0)
            tips.append({
                "code": "tec_wait",
                "icon": "🌡",
                "message": f"TEC CH{idx} stabilising ({bt:.0f}s in band).",
                "action": None,
                "priority": 4,
            })
            break   # one TEC tip is enough

    tips.sort(key=lambda t: t["priority"])
    return tips[:3]   # max 3 visible tips


class OptimizationSuggestionsWidget(QWidget):
    """Compact suggestion strip below the readiness banner."""

    action_requested = pyqtSignal(str)  # emitted with suggestion code

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setVisible(False)

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 2, 0, 2)
        self._root.setSpacing(2)
        self._tip_widgets: list[QWidget] = []

    def update_metrics(self, snapshot: dict) -> None:
        """Slot connected to MetricsService.metrics_updated."""
        tips = _evaluate(snapshot)

        # Clear old tips
        for w in self._tip_widgets:
            w.deleteLater()
        self._tip_widgets.clear()

        if not tips:
            self.setVisible(False)
            return

        for tip in tips:
            row = self._build_tip(tip)
            self._root.addWidget(row)
            self._tip_widgets.append(row)
        self.setVisible(True)

    def _build_tip(self, tip: dict) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(8, 2, 8, 2)
        lay.setSpacing(6)

        dim = PALETTE.get("textDim", "#888")
        text = PALETTE.get("text", "#eee")
        accent = PALETTE.get("accent", "#00bcd4")

        icon_lbl = QLabel(tip.get("icon", "💡"))
        icon_lbl.setFixedWidth(18)
        icon_lbl.setStyleSheet(f"font-size: {FONT['label']}pt;")
        lay.addWidget(icon_lbl)

        msg_lbl = QLabel(tip["message"])
        msg_lbl.setWordWrap(True)
        msg_lbl.setStyleSheet(
            f"color: {dim}; font-size: {FONT['caption']}pt;")
        lay.addWidget(msg_lbl, 1)

        action = tip.get("action")
        if action:
            btn = QPushButton(action)
            btn.setFixedHeight(20)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {accent}; "
                f"border: none; font-size: {FONT['caption']}pt; "
                f"font-weight: 600; padding: 0 4px; }}"
                f"QPushButton:hover {{ color: {text}; }}")
            code = tip["code"]
            btn.clicked.connect(lambda _, c=code: self.action_requested.emit(c))
            lay.addWidget(btn)

        return row

    def _apply_styles(self) -> None:
        """Re-apply theme styles (called after theme switch)."""
        # Rebuild on next metrics update
        pass
