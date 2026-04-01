"""
ui/tabs/health_tab.py

Hardware Health Dashboard for SanjINSIGHT.

Displays rolling 60-minute time-series plots for:
  • TEC temperature per channel (°C)
  • FPGA duty cycle (%)
  • Camera frame rate (fps)

The tab is read-only — it observes hardware signals from HardwareService
and writes no hardware state.

Usage
-----
    tab = HealthTab(hw_service=hw_service, parent=None)
    # Wire signals in MainWindow:
    hw_service.tec_status.connect(tab.on_tec_status)
    hw_service.fpga_status.connect(tab.on_fpga_status)
    hw_service.camera_frame.connect(tab.on_camera_frame)
"""

from __future__ import annotations

import collections
import logging
import time
from typing import Dict, Deque

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy,
)
from PyQt5.QtCore import Qt, QTimer

import numpy as np

log = logging.getLogger(__name__)

# Window length in seconds (60 minutes)
_WINDOW_S = 3600
# Matplotlib is imported lazily inside _build_plots() to avoid
# import-time overhead on startup.


class _RollingBuffer:
    """
    Fixed-duration ring buffer of (timestamp, value) pairs.
    Keeps only the last *window_s* seconds of data.
    """

    def __init__(self, window_s: float = _WINDOW_S) -> None:
        self._window = window_s
        self._ts:  Deque[float] = collections.deque()
        self._val: Deque[float] = collections.deque()

    def push(self, value: float, ts: float = 0.0) -> None:
        t = ts or time.monotonic()
        self._ts.append(t)
        self._val.append(value)
        cutoff = t - self._window
        while self._ts and self._ts[0] < cutoff:
            self._ts.popleft()
            self._val.popleft()

    def arrays(self) -> tuple:
        """Return (timestamps_array, values_array) as numpy float64 arrays."""
        if not self._ts:
            return np.array([], dtype=np.float64), np.array([], dtype=np.float64)
        base = self._ts[0]
        return (
            np.array(self._ts, dtype=np.float64) - base,
            np.array(self._val, dtype=np.float64),
        )

    def latest(self) -> float:
        return self._val[-1] if self._val else float("nan")

    def __len__(self) -> int:
        return len(self._ts)


class HealthTab(QWidget):
    """
    Read-only hardware health dashboard.

    Connect these slots to the corresponding HardwareService signals:
        hw.tec_status.connect(tab.on_tec_status)
        hw.fpga_status.connect(tab.on_fpga_status)
        hw.camera_frame.connect(tab.on_camera_frame)
    """

    # How often the plots refresh (ms)
    _REFRESH_MS = 5_000

    def __init__(self, hw_service=None, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._hw = hw_service

        # Rolling buffers — keyed by channel index for TEC
        self._tec_bufs:    Dict[int, _RollingBuffer] = {}
        self._fpga_buf     = _RollingBuffer()
        self._fps_buf      = _RollingBuffer()
        self._last_frame_t = 0.0
        self._frame_count  = 0

        self._canvas      = None   # matplotlib FigureCanvasQTAgg
        self._fig         = None
        self._axes        = []

        self._build_ui()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_plots)
        self._refresh_timer.start(self._REFRESH_MS)

    # ── UI construction ───────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # ── Header bar ────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("Hardware Health")
        title.setStyleSheet("font-size: 14pt; font-weight: bold;")
        title.setToolTip(
            "Rolling 60-minute trend plots for TEC temperature, FPGA duty cycle,\n"
            "and camera frame rate. Data is read-only — no hardware state is modified."
        )
        hdr.addWidget(title)
        hdr.addStretch()

        self._status_label = QLabel("Waiting for data…")
        self._status_label.setStyleSheet("color: grey;")
        self._status_label.setToolTip(
            "Total number of data points held in the rolling 60-minute buffers\n"
            "across all channels, plus the timestamp of the last plot refresh."
        )
        hdr.addWidget(self._status_label)

        clear_btn = QPushButton("Clear")
        clear_btn.setFixedWidth(64)
        clear_btn.setToolTip(
            "Wipe all rolling history buffers.\n"
            "Use after a hardware change or cable swap to reset the trend lines."
        )
        clear_btn.clicked.connect(self._clear_buffers)
        hdr.addWidget(clear_btn)
        root.addLayout(hdr)

        # ── Matplotlib canvas (lazy) ───────────────────────────────────
        try:
            self._init_canvas(root)
        except Exception as exc:
            log.warning("HealthTab: matplotlib unavailable: %s", exc)
            fallback = QLabel(
                "Matplotlib is required for the health dashboard.\n"
                "Install it with: pip install matplotlib"
            )
            fallback.setAlignment(Qt.AlignCenter)
            root.addWidget(fallback)

    def _init_canvas(self, parent_layout: QVBoxLayout) -> None:
        """Create matplotlib Figure + FigureCanvasQTAgg and add to layout."""
        import matplotlib
        matplotlib.use("Qt5Agg")
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg

        self._fig = Figure(figsize=(10, 6), tight_layout=True)
        self._axes = [
            self._fig.add_subplot(3, 1, 1),  # TEC temperatures
            self._fig.add_subplot(3, 1, 2),  # FPGA duty cycle
            self._fig.add_subplot(3, 1, 3),  # Camera FPS
        ]

        for ax in self._axes:
            ax.tick_params(labelsize=8)

        self._axes[0].set_ylabel("TEC Temp (°C)", fontsize=8)
        self._axes[1].set_ylabel("FPGA Duty (%)",  fontsize=8)
        self._axes[2].set_ylabel("Camera FPS",     fontsize=8)
        self._axes[2].set_xlabel("Time (min)",      fontsize=8)

        self._canvas = FigureCanvasQTAgg(self._fig)
        self._canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._canvas.setToolTip(
            "Top: TEC temperature per channel (°C).\n"
            "Middle: FPGA modulation duty cycle (%) — dashed line at 80 % limit.\n"
            "Bottom: Camera frame delivery rate (fps).\n"
            "X-axis is elapsed time in minutes since the oldest buffered sample."
        )
        parent_layout.addWidget(self._canvas)

    # ── Public slots (wire to HardwareService signals) ─────────────────

    def on_tec_status(self, index_or_status, status=None):
        """
        Accept both single-arg (status) and two-arg (index, status) forms.
        TecStatus must have .actual_temp attribute.
        """
        if status is None:
            # Called as on_tec_status(status_obj)
            idx, st = 0, index_or_status
        else:
            idx, st = int(index_or_status), status

        if idx not in self._tec_bufs:
            self._tec_bufs[idx] = _RollingBuffer()
        try:
            self._tec_bufs[idx].push(float(st.actual_temp))
        except Exception:
            pass

    def on_fpga_status(self, status):
        """FpgaStatus must have .duty_cycle attribute (0.0–1.0)."""
        try:
            self._fpga_buf.push(float(status.duty_cycle) * 100.0)
        except Exception:
            pass

    def on_camera_frame(self, frame_or_index=None):
        """Call on every camera frame to track fps."""
        now = time.monotonic()
        self._frame_count += 1
        if self._last_frame_t > 0:
            dt = now - self._last_frame_t
            if 0 < dt < 10.0:
                self._fps_buf.push(1.0 / dt)
        self._last_frame_t = now

    # ── Internal helpers ──────────────────────────────────────────────

    def _refresh_plots(self) -> None:
        """Redraw all three subplots with current buffer data."""
        if self._canvas is None or self._fig is None:
            return

        try:
            self._draw_tec_plot()
            self._draw_fpga_plot()
            self._draw_fps_plot()
            self._canvas.draw_idle()

            total = (
                sum(len(b) for b in self._tec_bufs.values())
                + len(self._fpga_buf)
                + len(self._fps_buf)
            )
            self._status_label.setText(
                f"{total} data points  ·  last refresh "
                + time.strftime("%H:%M:%S")
            )
        except Exception as exc:
            log.debug("HealthTab._refresh_plots: %s", exc)

    def _draw_tec_plot(self) -> None:
        ax = self._axes[0]
        ax.cla()
        ax.set_ylabel("TEC Temp (°C)", fontsize=8)
        colors = [PALETTE['info'], PALETTE['danger'], PALETTE['success'], PALETTE['warning']]
        for i, (idx, buf) in enumerate(sorted(self._tec_bufs.items())):
            ts, vals = buf.arrays()
            if len(ts) > 1:
                ax.plot(ts / 60.0, vals,
                        color=colors[i % len(colors)],
                        linewidth=1.2,
                        label=f"TEC {idx}")
        if self._tec_bufs:
            ax.legend(fontsize=7, loc="upper right")
        ax.tick_params(labelsize=8)
        ax.set_xlim(left=0)

    def _draw_fpga_plot(self) -> None:
        ax = self._axes[1]
        ax.cla()
        ax.set_ylabel("FPGA Duty (%)", fontsize=8)
        ts, vals = self._fpga_buf.arrays()
        if len(ts) > 1:
            ax.plot(ts / 60.0, vals, color=PALETTE['systemPurple'], linewidth=1.2)
            # Red danger zone
            ax.axhline(80.0, color=PALETTE['danger'], linewidth=0.8, linestyle="--",
                       label="80 % limit")
            ax.legend(fontsize=7, loc="upper right")
        ax.set_ylim(0, 105)
        ax.tick_params(labelsize=8)
        ax.set_xlim(left=0)

    def _draw_fps_plot(self) -> None:
        ax = self._axes[2]
        ax.cla()
        ax.set_ylabel("Camera FPS", fontsize=8)
        ax.set_xlabel("Time (min)", fontsize=8)
        ts, vals = self._fps_buf.arrays()
        if len(ts) > 1:
            ax.plot(ts / 60.0, vals, color=PALETTE['success'], linewidth=1.2)
        ax.set_ylim(bottom=0)
        ax.tick_params(labelsize=8)
        ax.set_xlim(left=0)

    def _clear_buffers(self) -> None:
        """Wipe all rolling buffers (useful after a hardware change)."""
        self._tec_bufs.clear()
        self._fpga_buf  = _RollingBuffer()
        self._fps_buf   = _RollingBuffer()
        self._last_frame_t = 0.0
        self._frame_count  = 0
        if self._canvas is not None:
            for ax in self._axes:
                ax.cla()
            self._canvas.draw_idle()
        self._status_label.setText("Buffers cleared — waiting for data…")

    def _apply_styles(self) -> None:
        """Called by MainWindow on theme change."""
        try:
            from ui.theme import PALETTE, active_theme
            is_dark = active_theme() == "dark"
            bg = PALETTE['bg']
            fg = PALETTE['text'] if is_dark else PALETTE['text']
            if self._fig is not None:
                self._fig.patch.set_facecolor(bg)
                for ax in self._axes:
                    ax.set_facecolor(bg)
                    ax.tick_params(colors=fg, labelsize=8)
                    ax.spines["bottom"].set_color(fg)
                    ax.spines["left"].set_color(fg)
                    ax.yaxis.label.set_color(fg)
                    ax.xaxis.label.set_color(fg)
                if self._canvas:
                    self._canvas.draw_idle()
        except Exception:
            pass
