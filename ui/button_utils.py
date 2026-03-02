"""
ui/button_utils.py

Shared button-state helpers used across all acquisition tabs and dialogs.

RunningButton
-------------
Wraps an existing QPushButton to provide:

  • A QTimer-driven braille-dot spinner animation in the button text while
    an operation is in progress (e.g. "⠙  Scanning…").
  • A "running" dynamic property so the global stylesheet can style the
    active state differently (amber border + background for generic buttons,
    teal for #primary buttons).
  • Automatic PointingHandCursor so users immediately know the button is
    interactive.

The wrapped button is NOT subclassed, so all existing signal connections,
objectNames, and setEnabled() calls remain fully functional.

Usage
-----
    # At construction time (in __init__):
    from ui.button_utils import RunningButton, apply_hand_cursor

    self._run_btn = QPushButton("▶  Start Scan")
    self._runner  = RunningButton(self._run_btn, idle_text="▶  Start Scan")

    # Apply hand cursor to other non-wrapped buttons:
    apply_hand_cursor(self._abort_btn, self._export_btn)

    # When the operation starts:
    self._runner.set_running(True, label="Scanning")
    self._run_btn.setEnabled(False)

    # When the operation completes or is aborted:
    self._runner.set_running(False)
    self._run_btn.setEnabled(True)
"""

from __future__ import annotations

from PyQt5.QtCore    import Qt, QTimer
from PyQt5.QtWidgets import QPushButton


# ── Spinner frames (braille dot rotation, 100 ms/frame → ~1 s cycle) ─────────

_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def _repaint_style(widget) -> None:
    """Force Qt's style engine to re-read dynamic properties on *widget*."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


# ── RunningButton ──────────────────────────────────────────────────────────────

class RunningButton:
    """
    Attaches an animated "running" state to an existing QPushButton.

    Does NOT subclass QPushButton, so all existing connections and styles
    (setObjectName, setEnabled, etc.) are fully preserved.
    """

    def __init__(self, btn: QPushButton, idle_text: str):
        """
        Parameters
        ----------
        btn       : the QPushButton to wrap
        idle_text : button label when idle (e.g. "▶  Start Scan")
        """
        self._btn   = btn
        self._idle  = idle_text
        self._label = "Working"
        self._frame = 0

        # Hand cursor — signals to the user that this button is clickable
        btn.setCursor(Qt.PointingHandCursor)

        # Timer drives the spinner text animation
        self._timer = QTimer(btn)
        self._timer.setInterval(100)          # 100 ms per frame
        self._timer.timeout.connect(self._tick)

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def button(self) -> QPushButton:
        """Return the wrapped QPushButton."""
        return self._btn

    def set_running(self, running: bool, label: str = "Working") -> None:
        """
        Start or stop the spinner and update the "running" CSS property.

        Parameters
        ----------
        running : True to start, False to stop
        label   : progress label shown alongside the spinner (e.g. "Scanning")
        """
        if running:
            self._label = label
            self._frame = 0
            self._btn.setProperty("running", True)
            _repaint_style(self._btn)
            self._timer.start()
        else:
            self._timer.stop()
            self._btn.setText(self._idle)
            self._btn.setProperty("running", False)
            _repaint_style(self._btn)

    @property
    def is_running(self) -> bool:
        return self._timer.isActive()

    # ── Private ───────────────────────────────────────────────────────────────

    def _tick(self) -> None:
        frame = _FRAMES[self._frame % len(_FRAMES)]
        self._btn.setText(f"{frame}  {self._label}…")
        self._frame += 1


# ── Cursor convenience ────────────────────────────────────────────────────────

def apply_hand_cursor(*buttons: QPushButton) -> None:
    """Set PointingHandCursor on one or more QPushButtons."""
    for btn in buttons:
        btn.setCursor(Qt.PointingHandCursor)
