"""
acquisition/live_tab.py

LiveTab — real-time thermoreflectance display.

Layout
------
Top bar     : Run / Stop / Freeze / Capture controls + status indicators
Left panel  : Settings (trigger mode, accumulation, frames/half, display fps, ROI)
Centre      : Full live ΔR/R map (fills remaining space)
Right panel : Numerical readouts — SNR meter, pixel probe, histogram,
              min/max/mean updated every frame
"""

from __future__ import annotations
import collections
import time
import numpy as np

from ui.button_utils import RunningButton, apply_hand_cursor
from ui.font_utils   import mono_font, sans_font
from ui.icons import set_btn_icon
from ui.theme import FONT, PALETTE, MONO_FONT
from ui.guidance import get_section_cards, GuidanceCard, WorkflowFooter
from ui.guidance.steps import next_steps_after

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDoubleSpinBox, QSpinBox, QGroupBox, QGridLayout,
    QComboBox, QSplitter, QSizePolicy, QScrollArea,
    QFileDialog, QMessageBox, QSlider, QRubberBand)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QRect, QSize, QPoint
from PyQt5.QtGui  import (QImage, QPixmap, QPainter, QPen, QColor,
                           QBrush, QFont, QLinearGradient)

from .live       import LiveProcessor, LiveConfig, LiveFrame
from .processing import to_display, apply_colormap, setup_cmap_combo
import config as cfg_mod


# ------------------------------------------------------------------ #
#  SNR bar widget                                                     #
# ------------------------------------------------------------------ #

class SnrBar(QWidget):
    """Vertical SNR bargraph with dB scale."""

    def __init__(self):
        super().__init__()
        self.setFixedWidth(64)       # was 44 — wider to prevent label clipping
        self.setMinimumHeight(140)   # was 80 — 75% taller
        self._value = 0.0
        self._min   = -20.0
        self._max   =  40.0

    def set_value(self, v: float):
        self._value = float(v)
        self.update()

    def paintEvent(self, e):
        p  = QPainter(self)
        W, H = self.width(), self.height()
        pad_top, pad_bot, pad_l = 8, 24, 6

        bar_h   = H - pad_top - pad_bot
        bar_w   = 14
        bar_x   = pad_l

        # Background — use PALETTE so it adapts to light/dark theme
        bg_c  = QColor(PALETTE['bg'])
        dim_c = QColor(PALETTE['border'])
        p.fillRect(0, 0, W, H, bg_c)

        # Gradient fill (green → yellow → red from top = good)
        grad = QLinearGradient(0, pad_top, 0, pad_top + bar_h)
        grad.setColorAt(0.0,  QColor(0,   210, 120))
        grad.setColorAt(0.4,  QColor(80,  200, 40))
        grad.setColorAt(0.7,  QColor(220, 200, 0))
        grad.setColorAt(1.0,  QColor(200, 40,  20))

        # Track
        p.setBrush(QColor(PALETTE['surface']))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(bar_x, pad_top, bar_w, bar_h, 2, 2)

        # Fill
        frac = (self._value - self._min) / (self._max - self._min)
        frac = max(0.0, min(1.0, frac))
        fill_h = int(bar_h * frac)
        fill_y = pad_top + bar_h - fill_h

        # Clip gradient to filled portion
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(bar_x, fill_y, bar_w, fill_h, 2, 2)

        # Scale ticks
        p.setPen(dim_c)
        p.setFont(mono_font(10))
        for db in [40, 20, 0, -20]:
            tf = (db - self._min) / (self._max - self._min)
            ty = int(pad_top + bar_h * (1.0 - tf))
            p.drawLine(bar_x + bar_w + 1, ty, bar_x + bar_w + 4, ty)
            p.setPen(QColor(PALETTE['textSub']))
            p.drawText(bar_x + bar_w + 5, ty + 4, str(db))
            p.setPen(dim_c)

        # Value label — rect form keeps text inside the widget at all heights
        p.setFont(mono_font(11))
        p.setPen(QColor(0, 200, 130) if frac > 0.4 else QColor(200, 80, 40))
        p.drawText(0, H - pad_bot + 4, W, pad_bot - 6, Qt.AlignCenter,
                   f"{self._value:.1f}dB")
        p.end()


# ------------------------------------------------------------------ #
#  Histogram widget                                                   #
# ------------------------------------------------------------------ #

class Histogram(QWidget):
    """Compact ΔR/R histogram."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(70)
        self._bins  = None
        self._edges = None

    def update_data(self, data: np.ndarray):
        try:
            flat = data.ravel()
            # Sample at most 20 000 values — running np.percentile + np.histogram
            # on a full frame at every call (even throttled to 3 Hz) still costs
            # significant time on large arrays; sampling is imperceptible visually.
            stride = max(1, len(flat) // 20_000)
            sample = flat[::stride]
            lo   = float(np.percentile(sample, 0.5))
            hi   = float(np.percentile(sample, 99.5))
            if hi == lo:
                hi = lo + 1e-9
            self._bins, edges = np.histogram(sample, bins=64, range=(lo, hi))
            self._edges = edges
        except Exception:
            self._bins = None
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        W, H = self.width(), self.height()
        p.fillRect(0, 0, W, H, QColor(PALETTE['bg']))

        if self._bins is None:
            p.setPen(QColor(PALETTE['border']))
            p.drawText(self.rect(), Qt.AlignCenter, "No data")
            p.end()
            return

        mx   = float(self._bins.max()) or 1.0
        nb   = len(self._bins)
        bw   = W / nb
        pad  = 4

        for i, v in enumerate(self._bins):
            bh  = int((v / mx) * (H - pad))
            bx  = int(i * bw)
            by  = H - bh

            # Colour by position: blue(negative) → black(zero) → red(positive)
            t   = i / nb          # 0..1
            if t < 0.5:
                r, g, b = 0, 0, int((1 - t * 2) * 160)
            else:
                r, g, b = int((t - 0.5) * 2 * 200), 0, 0

            p.fillRect(bx, by, max(1, int(bw) - 1), bh, QColor(r, g, b))

        # Zero line
        p.setPen(QPen(QColor(PALETTE['canvasGrid']), 1, Qt.DotLine))
        lo = self._edges[0]
        hi = self._edges[-1]
        if lo < 0 < hi:
            zx = int((-lo) / (hi - lo) * W)
            p.drawLine(zx, 0, zx, H)

        p.end()


# ------------------------------------------------------------------ #
#  Probe sparkline widget                                             #
# ------------------------------------------------------------------ #

class TempPlot(QWidget):
    """
    Compact sparkline showing the last N pixel-probe ΔR/R readings.

    Push a new value with push(); clear the history with clear().
    The zero line is drawn as a faint dotted reference when data
    spans both positive and negative values.
    """

    def __init__(self, capacity: int = 64):
        super().__init__()
        self.setFixedHeight(80)
        self.setMinimumWidth(60)
        self._buf: collections.deque = collections.deque(maxlen=capacity)

    def push(self, value: float) -> None:
        self._buf.append(value)
        self.update()

    def clear(self) -> None:
        self._buf.clear()
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        W, H = self.width(), self.height()
        PAD = 4
        p.fillRect(0, 0, W, H, QColor(PALETTE['bg']))

        if len(self._buf) < 2:
            p.setPen(QColor(PALETTE['border']))
            p.setFont(mono_font(9))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "Move cursor\nover image")
            p.end()
            return

        data = list(self._buf)
        lo   = min(data)
        hi   = max(data)
        span = hi - lo
        if span < 1e-15:
            lo -= 1e-9
            hi += 1e-9
            span = hi - lo

        plot_h = H - 2 * PAD
        plot_w = W - 2 * PAD

        def _y(v):
            return int(H - PAD - (v - lo) / span * plot_h)

        # Zero reference line
        if lo < 0.0 < hi:
            zy = _y(0.0)
            p.setPen(QPen(QColor(PALETTE['border']), 1, Qt.DotLine))
            p.drawLine(PAD, zy, W - PAD, zy)

        # Sparkline
        n   = len(data)
        pts = [
            (int(PAD + i / (n - 1) * plot_w), _y(v))
            for i, v in enumerate(data)
        ]
        pen = QPen(QColor(PALETTE['accent']), 1, Qt.SolidLine)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        for i in range(1, len(pts)):
            p.drawLine(pts[i-1][0], pts[i-1][1], pts[i][0], pts[i][1])

        # Current-value dot
        cx, cy = pts[-1]
        p.setBrush(QColor(PALETTE['accent']))
        p.setPen(Qt.NoPen)
        p.drawEllipse(cx - 3, cy - 3, 6, 6)

        # Current value label (top-left)
        p.setPen(QColor(PALETTE['accent']))
        p.setFont(mono_font(8))
        p.drawText(PAD + 2, PAD + 10, f"{data[-1]:.4e}")

        p.end()


# ------------------------------------------------------------------ #
#  Live map canvas                                                    #
# ------------------------------------------------------------------ #

class LiveCanvas(QWidget):
    """Displays the live ΔR/R map. Optionally shows a crosshair probe."""

    probe_moved    = pyqtSignal(int, int)   # pixel x, y under cursor
    context_action = pyqtSignal(str)        # "start" | "stop" | "freeze" | "capture"
    roi_changed    = pyqtSignal(object)     # None, or (x0, y0, x1, y1) in data coords

    def __init__(self):
        super().__init__()
        self.setMinimumSize(200, 150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet(f"background:{PALETTE['canvas']};")
        self.setMouseTracking(True)

        self._pixmap    = None
        self._frozen    = False
        self._cmap      = "Thermal Delta"
        self._data      = None
        self._probe_pos = None   # (px, py) in widget coords

        # ── Zoom & pan state ──────────────────────────────────────────
        self._zoom      = 1.0    # 1.0 = fit-to-window
        self._pan_x     = 0.0   # horizontal offset from centred position (px)
        self._pan_y     = 0.0   # vertical offset
        self._drag_start     = None   # QPoint when middle-button drag starts
        self._drag_pan_start = (0.0, 0.0)

        # ── ROI selection (Ctrl+drag) ─────────────────────────────────
        self._roi_data       = None   # (x0,y0,x1,y1) in data coords, or None
        self._roi_start_w    = None   # QPoint in widget coords (drag origin)
        self._rb             = QRubberBand(QRubberBand.Rectangle, self)

        # ── Percentile-limit cache ────────────────────────────────────
        # Recomputed at most every 300 ms to avoid full-array percentile
        # on every frame (very expensive at 15 Hz on Windows).
        self._limit_cache    = 1e-9   # cached abs-99.5-percentile limit
        self._limit_ts       = 0.0    # time.monotonic() of last computation

    def set_cmap(self, cmap: str):
        self._cmap = cmap
        # Redraw immediately so a frozen / stopped view updates at once.
        if self._data is not None:
            self._rebuild(self._data)
            self.update()

    def update_frame(self, frame: LiveFrame):
        if self._frozen or frame.drr is None:
            return
        self._data = frame.drr
        self._rebuild(frame.drr)
        self.update()

    def freeze(self, yes: bool):
        self._frozen = yes

    def _rebuild(self, data: np.ndarray):
        d = data.astype(np.float32)
        if self._cmap in ("Thermal Delta", "signed"):
            # Recompute the abs-99.5-percentile limit at most every 300 ms.
            # Computing np.percentile on the full frame at 15 Hz saturates a
            # CPU core on Windows; sampling ≤20 000 values is visually
            # indistinguishable and ~10–50× faster on typical frame sizes.
            now = time.monotonic()
            if now - self._limit_ts > 0.3:
                flat   = np.abs(d).ravel()
                stride = max(1, len(flat) // 20_000)
                sample = flat[::stride]
                self._limit_cache = float(np.percentile(sample, 99.5)) or 1e-9
                self._limit_ts    = now
            limit  = self._limit_cache
            normed = np.clip(d / limit, -1.0, 1.0)
            r = (np.clip( normed, 0, 1) * 255).astype(np.uint8)
            b = (np.clip(-normed, 0, 1) * 255).astype(np.uint8)
            g = np.zeros_like(r)
            rgb = np.stack([r, g, b], axis=-1)
        else:
            disp = to_display(d, mode="percentile")
            rgb  = apply_colormap(disp, self._cmap)

        h, w = rgb.shape[:2]
        buf = rgb.tobytes()   # keep ref alive for QImage
        qi = QImage(buf, w, h, w * 3, QImage.Format_RGB888)
        self._pixmap = QPixmap.fromImage(qi)

    def _draw_rect(self):
        """Return (ox, oy, dw, dh) — the destination rect for the current pixmap."""
        if self._pixmap is None:
            return None
        W, H = self.width(), self.height()
        PAD = 6
        pw, ph = self._pixmap.width(), max(self._pixmap.height(), 1)
        fit_scale = min((W - 2*PAD) / max(pw, 1), (H - 2*PAD) / max(ph, 1))
        dw = max(1, int(pw * fit_scale * self._zoom))
        dh = max(1, int(ph * fit_scale * self._zoom))
        ox = (W - dw) // 2 + int(self._pan_x)
        oy = (H - dh) // 2 + int(self._pan_y)
        return ox, oy, dw, dh

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(PALETTE['canvas']))

        if self._pixmap is None:
            p.setPen(QColor(PALETTE['canvasGrid']))
            p.setFont(sans_font(18))
            from hardware.app_state import app_state
            is_ir = getattr(app_state, "active_camera_type", "tr") == "ir"
            label = "Live Thermal" if is_ir else "Live ΔR/R"
            p.drawText(self.rect(), Qt.AlignCenter,
                       f"{label}\n\nPress  ▶  Start  to begin")
            if self._frozen:
                self._draw_frozen_badge(p)
            p.end()
            return

        r = self._draw_rect()
        ox, oy, dw, dh = r
        scaled = self._pixmap.scaled(dw, dh, Qt.IgnoreAspectRatio,
                                     Qt.SmoothTransformation)
        p.drawPixmap(ox, oy, scaled)

        # Crosshair probe
        if self._probe_pos:
            px, py = self._probe_pos
            c = QColor(PALETTE['accent']); c.setAlpha(160)
            pen = QPen(c, 1, Qt.DashLine)
            p.setPen(pen)
            p.drawLine(px, oy, px, oy + dh)
            p.drawLine(ox, py, ox + dw, py)

        # ROI rectangle overlay (when ROI is set and rubber band not visible)
        if self._roi_data and not self._rb.isVisible():
            r = self._draw_rect()
            if r:
                ox, oy, dw, dh = r
                x0d, y0d, x1d, y1d = self._roi_data
                pw = self._data.shape[1] if self._data is not None else max(dw, 1)
                ph = self._data.shape[0] if self._data is not None else max(dh, 1)
                rx0 = ox + int(x0d / pw * dw)
                ry0 = oy + int(y0d / ph * dh)
                rx1 = ox + int(x1d / pw * dw)
                ry1 = oy + int(y1d / ph * dh)
                p.setPen(QPen(QColor(255, 200, 0, 180), 2, Qt.DashLine))
                p.setBrush(QColor(255, 200, 0, 18))
                p.drawRect(QRect(QPoint(rx0, ry0), QPoint(rx1, ry1)))
                p.setBrush(Qt.NoBrush)
                p.setPen(QColor(255, 200, 0, 220))
                p.setFont(sans_font(10))
                p.drawText(rx0 + 4, ry0 + 14, "ROI")

        # Zoom level indicator (when zoomed in)
        if abs(self._zoom - 1.0) > 0.05:
            p.setPen(QColor(180, 180, 180, 200))
            p.setFont(sans_font(11))
            p.drawText(8, self.height() - 8, f"×{self._zoom:.2f}")

        if self._frozen:
            self._draw_frozen_badge(p)
        p.end()

    def _draw_frozen_badge(self, p: QPainter):
        c = QColor(PALETTE['accent']); c.setAlpha(200)
        p.setBrush(c)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(8, 8, 70, 22, 4, 4)
        p.setPen(QColor(PALETTE['text']))
        p.setFont(QFont("Helvetica-Bold", 14))
        p.drawText(8, 8, 70, 22, Qt.AlignCenter, "FROZEN")

    def wheelEvent(self, e):
        """Scroll wheel → zoom in/out, centred on cursor."""
        if self._pixmap is None:
            return
        delta   = e.angleDelta().y()
        factor  = 1.15 if delta > 0 else 1.0 / 1.15
        new_zoom = max(0.25, min(16.0, self._zoom * factor))

        # Zoom toward the cursor position
        r = self._draw_rect()
        if r and new_zoom != self._zoom:
            ox, oy, dw, dh = r
            cx, cy = e.x(), e.y()
            new_dw = max(1, int(dw * new_zoom / max(self._zoom, 1e-9)))
            new_dh = max(1, int(dh * new_zoom / max(self._zoom, 1e-9)))
            # img_frac = (cx - ox) / dw; keep img_frac * new_dw + new_ox == cx
            new_ox = cx - int((cx - ox) * new_zoom / max(self._zoom, 1e-9))
            new_oy = cy - int((cy - oy) * new_zoom / max(self._zoom, 1e-9))
            W, H = self.width(), self.height()
            self._pan_x = new_ox - (W - new_dw) // 2
            self._pan_y = new_oy - (H - new_dh) // 2

        self._zoom = new_zoom
        self.update()
        e.accept()

    def mousePressEvent(self, e):
        """Middle-click → pan drag; Ctrl+left-click → ROI selection."""
        if e.button() == Qt.MiddleButton:
            self._drag_start     = e.pos()
            self._drag_pan_start = (self._pan_x, self._pan_y)
            self.setCursor(Qt.ClosedHandCursor)
        elif e.button() == Qt.LeftButton and (e.modifiers() & Qt.ControlModifier):
            self._roi_start_w = e.pos()
            self._rb.setGeometry(QRect(e.pos(), QSize()))
            self._rb.show()
        else:
            super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MiddleButton:
            self._drag_start = None
            self.setCursor(Qt.ArrowCursor)
        elif e.button() == Qt.LeftButton and self._roi_start_w is not None:
            self._rb.hide()
            # Convert rubber-band rect to data coordinates
            rb_rect = QRect(self._roi_start_w, e.pos()).normalized()
            r = self._draw_rect()
            if r and self._data is not None and rb_rect.width() > 4:
                ox, oy, dw, dh = r
                ph, pw = self._data.shape[:2]
                def clamp(v, lo, hi): return max(lo, min(hi, v))
                x0 = clamp(int((rb_rect.left()   - ox) / dw * pw), 0, pw - 1)
                y0 = clamp(int((rb_rect.top()    - oy) / dh * ph), 0, ph - 1)
                x1 = clamp(int((rb_rect.right()  - ox) / dw * pw), 0, pw - 1)
                y1 = clamp(int((rb_rect.bottom() - oy) / dh * ph), 0, ph - 1)
                if x1 > x0 and y1 > y0:
                    self._roi_data = (x0, y0, x1, y1)
                    self.roi_changed.emit(self._roi_data)
                    self.update()
            self._roi_start_w = None
        else:
            super().mouseReleaseEvent(e)

    def reset_zoom(self):
        """Reset zoom and pan to fit-to-window (zoom=1.0)."""
        self._zoom  = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self.update()

    def clear_roi(self):
        """Clear the current ROI selection."""
        self._roi_data = None
        self.roi_changed.emit(None)
        self.update()

    def mouseMoveEvent(self, e):
        # Middle-button drag → pan
        if e.buttons() & Qt.MiddleButton and self._drag_start is not None:
            dx = e.x() - self._drag_start.x()
            dy = e.y() - self._drag_start.y()
            self._pan_x = self._drag_pan_start[0] + dx
            self._pan_y = self._drag_pan_start[1] + dy
            self.update()
            return

        # Ctrl+left-drag → ROI rubber band
        if e.buttons() & Qt.LeftButton and self._roi_start_w is not None:
            self._rb.setGeometry(
                QRect(self._roi_start_w, e.pos()).normalized())
            return

        self._probe_pos = (e.x(), e.y())
        if self._pixmap and self._data is not None:
            # Map widget coords → data coords (honouring zoom/pan)
            r = self._draw_rect()
            if r:
                ox, oy, dw, dh = r
                dx = int((e.x() - ox) / dw * self._data.shape[1])
                dy = int((e.y() - oy) / dh * self._data.shape[0])
                dx = max(0, min(dx, self._data.shape[1] - 1))
                dy = max(0, min(dy, self._data.shape[0] - 1))
                self.probe_moved.emit(dx, dy)
        self.update()

    def leaveEvent(self, e):
        self._probe_pos = None
        self.update()

    def save_snapshot(self, path: str):
        if self._pixmap:
            self._pixmap.save(path)

    def contextMenuEvent(self, e):
        from PyQt5.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background:{PALETTE['surface']}; color:{PALETTE['text']}; border:1px solid {PALETTE['border']}; }}"
            f"QMenu::item:selected {{ background:{PALETTE['surface2']}; }}"
            f"QMenu::separator {{ height:1px; background:{PALETTE['border']}; margin:3px 8px; }}")
        menu.addAction("▶  Start Live",       lambda: self.context_action.emit("start"))
        menu.addAction("■  Stop Live",         lambda: self.context_action.emit("stop"))
        menu.addAction("❄  Freeze / Resume",   lambda: self.context_action.emit("freeze"))
        menu.addSeparator()
        menu.addAction("🔍  Reset Zoom (fit)", self.reset_zoom)
        act_clear_roi = menu.addAction("⬜  Clear ROI")
        act_clear_roi.setEnabled(self._roi_data is not None)
        act_clear_roi.triggered.connect(self.clear_roi)
        menu.addSeparator()
        act_save = menu.addAction("📷  Save Snapshot…")
        act_save.setEnabled(self._pixmap is not None)
        act_save.triggered.connect(lambda: self.context_action.emit("capture"))
        menu.exec_(e.globalPos())


# ------------------------------------------------------------------ #
#  Live tab                                                           #
# ------------------------------------------------------------------ #

class LiveTab(QWidget):

    def __init__(self):
        super().__init__()
        self._proc    = None
        self._frozen  = False
        self._last_frame: LiveFrame = None
        self._roi: tuple = None    # (x0,y0,x1,y1) in data coords, or None

        # ── Per-class update throttle ─────────────────────────────────
        # Canvas/SNR rebuild at 15 Hz max; stats+histogram at 3 Hz max.
        # Timestamps are reset on _stop() so the first frame of a new run
        # always triggers an immediate canvas + stats update.
        self._last_canvas_ts = 0.0   # time.monotonic() of last canvas rebuild
        self._last_stats_ts  = 0.0   # time.monotonic() of last stats/hist refresh
        # Badge stylesheet is set once (when going "live") then left alone
        # — setStyleSheet() triggers a full repaint on every call.
        self._badges_active  = False

        # Poll timer — reads queue and updates UI
        self._timer = QTimer()
        self._timer.setInterval(50)   # 20 Hz tick (actual render rate is throttled)
        self._timer.timeout.connect(self._poll)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_toolbar())

        # ── Guidance cards — scrollable area ──────────────────────
        _cards = get_section_cards("live_view")
        def _body(cid):
            for c in _cards:
                if c["card_id"] == cid:
                    return c["body"]
            return ""

        self._cards_widget = QWidget()
        cards_lay = QVBoxLayout(self._cards_widget)
        cards_lay.setContentsMargins(0, 0, 0, 0)
        cards_lay.setSpacing(4)

        self._overview_card = GuidanceCard(
            "live_view.overview",
            "Getting Started with Live View",
            _body("live_view.overview"))
        self._overview_card.setVisible(False)
        cards_lay.addWidget(self._overview_card)

        self._guide_card1 = GuidanceCard(
            "live_view.verify",
            "Verify Your Sample Is Visible",
            _body("live_view.verify"),
            step_number=1)
        self._guide_card1.setVisible(False)
        cards_lay.addWidget(self._guide_card1)

        self._cards_scroll = QScrollArea()
        self._cards_scroll.setObjectName("LeftPanelScroll")
        self._cards_scroll.setWidgetResizable(True)
        self._cards_scroll.setFrameShape(QScrollArea.NoFrame)
        self._cards_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._cards_scroll.setMaximumHeight(280)
        self._cards_scroll.setWidget(self._cards_widget)
        self._cards_scroll.setVisible(False)
        root.addWidget(self._cards_scroll)

        for c in (self._overview_card, self._guide_card1):
            c.dismissed.connect(self._update_cards_scroll_visibility)

        _NEXT = [(s.nav_target, s.label, s.hint)
                 for s in next_steps_after("Live View", count=3)]
        self._workflow_footer = WorkflowFooter(_NEXT)
        self._workflow_footer.setVisible(False)

        self._body_splitter = QSplitter(Qt.Horizontal)
        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QScrollArea.NoFrame)
        settings_scroll.setWidget(self._build_settings())
        self._body_splitter.addWidget(settings_scroll)
        self._body_splitter.addWidget(self._build_canvas())
        readouts_scroll = QScrollArea()
        readouts_scroll.setWidgetResizable(True)
        readouts_scroll.setFrameShape(QScrollArea.NoFrame)
        readouts_scroll.setWidget(self._build_readouts())
        self._body_splitter.addWidget(readouts_scroll)
        self._body_splitter.setSizes([220, 900, 200])
        root.addWidget(self._body_splitter, 1)
        root.addWidget(self._workflow_footer)

        # Wire canvas colormap now that _canvas exists
        self._canvas.set_cmap(self._saved_cmap)
        self._cmap_combo.currentTextChanged.connect(self._canvas.set_cmap)

    # ── Workspace mode ────────────────────────────────────────────────

    def set_workspace_mode(self, mode: str) -> None:
        is_guided = (mode == "guided")
        self._guide_card1.setVisible(is_guided)
        self._workflow_footer.setVisible(is_guided)
        self._overview_card.setVisible(not is_guided)
        any_visible = any(c.isVisible() for c in (
            self._overview_card, self._guide_card1))
        self._cards_scroll.setVisible(any_visible)

    def _update_cards_scroll_visibility(self, _card_id: str = "") -> None:
        any_visible = any(c.isVisible() for c in (
            self._overview_card, self._guide_card1))
        self._cards_scroll.setVisible(any_visible)

    # ---------------------------------------------------------------- #
    #  Toolbar                                                          #
    # ---------------------------------------------------------------- #

    def _apply_styles(self) -> None:
        """Re-apply PALETTE-driven styles on theme switch."""
        P   = PALETTE
        sur = P['surface']
        su2 = P['surface2']
        bdr = P['border']
        sub = P['textSub']
        acc = P['accent']
        if hasattr(self, "_toolbar"):
            self._toolbar.setStyleSheet(
                f".QWidget {{ background:{sur}; border-bottom:1px solid {bdr}; }}")
        # Toolbar button icons
        if hasattr(self, "_start_btn"):
            set_btn_icon(self._start_btn, "fa5s.play", P["accent"])
            set_btn_icon(self._stop_btn, "fa5s.stop", P["danger"])
            set_btn_icon(self._freeze_btn, "fa5s.snowflake", P["info"])
            set_btn_icon(self._ffc_btn, "mdi.grid-off", P["warning"])
        # Canvas background
        if hasattr(self, "_canvas"):
            self._canvas.setStyleSheet(
                f"background:{P['canvas']};")
        # Status badges: re-apply with fresh palette so they switch correctly
        _badge_base = (
            f"padding:0 8px; border-radius:3px; "
            f"font-family:{MONO_FONT}; font-size:{FONT['label']}pt;")
        if hasattr(self, "_fps_lbl"):
            # Colour depends on whether live is running — re-apply idle state
            self._fps_lbl.setStyleSheet(
                f"background:{su2}; color:{acc}; {_badge_base}")
        if hasattr(self, "_cycle_lbl"):
            self._cycle_lbl.setStyleSheet(
                f"background:{su2}; color:{sub}; {_badge_base}")
        if hasattr(self, "_state_lbl"):
            self._state_lbl.setStyleSheet(
                f"background:{su2}; color:{sub}; {_badge_base}")

    def _build_toolbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(46)
        self._toolbar = bar
        bar.setStyleSheet(
            f".QWidget {{ background:{PALETTE['surface']}; border-bottom:1px solid {PALETTE['border']}; }}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(8)

        self._start_btn  = QPushButton("Start")
        set_btn_icon(self._start_btn, "fa5s.play", PALETTE['accent'])
        self._stop_btn   = QPushButton("Stop")
        set_btn_icon(self._stop_btn, "fa5s.stop", PALETTE['danger'])
        self._freeze_btn = QPushButton("Freeze")
        set_btn_icon(self._freeze_btn, "fa5s.snowflake", PALETTE['info'])
        self._capture_btn= QPushButton("Capture")
        set_btn_icon(self._capture_btn, "fa5s.camera")
        self._reset_btn  = QPushButton("Reset EMA")
        set_btn_icon(self._reset_btn, "fa5s.undo")

        self._ffc_btn = QPushButton("FFC")
        set_btn_icon(self._ffc_btn, "mdi.grid-off", PALETTE['warning'])
        self._ffc_btn.setToolTip(
            "Run Flat-Field Correction — recalibrate pixel offsets\n"
            "for the IR thermal camera (closes internal shutter briefly)")
        self._ffc_btn.setVisible(False)   # shown only for FFC-capable cameras

        self._start_btn.setObjectName("primary")
        self._stop_btn.setObjectName("danger")
        self._stop_btn.setEnabled(False)

        self._btn_runner = RunningButton(self._start_btn, idle_text="Start")
        apply_hand_cursor(self._stop_btn, self._freeze_btn,
                          self._capture_btn, self._reset_btn, self._ffc_btn)

        for b in [self._start_btn, self._stop_btn, self._freeze_btn,
                  self._capture_btn, self._reset_btn, self._ffc_btn]:
            b.setFixedHeight(30)
            lay.addWidget(b)

        lay.addSpacing(20)

        # Status indicators
        self._fps_lbl    = self._badge("— fps",   PALETTE['surface2'])
        self._cycle_lbl  = self._badge("cycle —", PALETTE['surface2'])
        self._state_lbl  = self._badge("IDLE",    PALETTE['surface2'])

        for l in [self._fps_lbl, self._cycle_lbl, self._state_lbl]:
            lay.addWidget(l)

        lay.addStretch()

        # Colormap selector in toolbar
        lay.addWidget(QLabel("Colormap:"))
        self._cmap_combo = QComboBox()
        self._cmap_combo.setMinimumWidth(160)
        self._cmap_combo.setFixedHeight(28)
        saved_cmap = cfg_mod.get_pref("display.colormap", "Thermal Delta")
        setup_cmap_combo(self._cmap_combo, saved_cmap)
        # _canvas is created after the toolbar; connection deferred to __init__
        self._saved_cmap = saved_cmap
        self._cmap_combo.currentTextChanged.connect(
            lambda c: cfg_mod.set_pref("display.colormap", c))
        lay.addWidget(self._cmap_combo)

        self._start_btn.clicked.connect(self._start)
        self._stop_btn.clicked.connect(self._stop)
        self._freeze_btn.clicked.connect(self._toggle_freeze)
        self._capture_btn.clicked.connect(self._capture)
        self._reset_btn.clicked.connect(self._reset_ema)
        self._ffc_btn.clicked.connect(self._do_ffc)

        return bar

    def _badge(self, text, color) -> QLabel:
        l = QLabel(text)
        l.setFixedHeight(24)
        l.setStyleSheet(
            f"background:{color}; color:{PALETTE['textSub']}; padding:0 8px; "
            f"border-radius:3px; font-family:{MONO_FONT}; font-size:{FONT['label']}pt;")
        return l

    # ---------------------------------------------------------------- #
    #  Settings panel                                                   #
    # ---------------------------------------------------------------- #

    def _build_settings(self) -> QWidget:
        w   = QWidget()
        w.setMinimumWidth(200)
        w.setMaximumWidth(260)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 4, 8)
        lay.setSpacing(8)

        # Trigger
        trig_box = QGroupBox("Trigger")
        tl = QGridLayout(trig_box)
        tl.setSpacing(5)
        tl.setColumnStretch(1, 1)

        self._trig_mode = QComboBox()
        self._trig_mode.addItems(["fpga", "software"])
        self._trig_delay = QDoubleSpinBox()
        self._trig_delay.setRange(0, 100)
        self._trig_delay.setValue(5.0)
        self._trig_delay.setSuffix(" ms")
        self._trig_delay.setMinimumWidth(70)

        tl.addWidget(self._sub("Mode"),  0, 0)
        tl.addWidget(self._trig_mode,    0, 1)
        tl.addWidget(self._sub("Delay"), 1, 0)
        tl.addWidget(self._trig_delay,   1, 1)
        lay.addWidget(trig_box)

        # Acquisition
        acq_box = QGroupBox("Acquisition")
        al = QGridLayout(acq_box)
        al.setSpacing(5)
        al.setColumnStretch(1, 1)

        self._frames_per_half = QSpinBox()
        self._frames_per_half.setRange(1, 64)
        self._frames_per_half.setValue(4)
        self._frames_per_half.setMinimumWidth(70)

        self._accum = QSpinBox()
        self._accum.setRange(1, 256)
        self._accum.setValue(16)
        self._accum.setMinimumWidth(70)
        self._accum.setToolTip(
            "EMA depth — higher = smoother signal, slower transient response")

        self._disp_fps = QDoubleSpinBox()
        self._disp_fps.setRange(1, 30)
        self._disp_fps.setValue(10)
        self._disp_fps.setSuffix(" fps")
        self._disp_fps.setMinimumWidth(70)

        from ui.help import help_label
        al.addWidget(help_label("Frames/half", "n_frames"),  0, 0)
        al.addWidget(self._frames_per_half,                   0, 1)
        al.addWidget(help_label("EMA depth", "accumulation"), 1, 0)
        al.addWidget(self._accum,                             1, 1)
        al.addWidget(self._sub("Display fps"),                2, 0)
        al.addWidget(self._disp_fps,                          2, 1)
        lay.addWidget(acq_box)

        # EMA depth slider (visual)
        depth_box = QGroupBox("Accumulation depth")
        dl = QVBoxLayout(depth_box)
        self._accum_slider = QSlider(Qt.Horizontal)
        self._accum_slider.setRange(1, 128)
        self._accum_slider.setValue(16)
        self._accum_slider.setTickPosition(QSlider.TicksBelow)
        self._accum_slider.setTickInterval(16)
        self._accum_slider.valueChanged.connect(self._accum.setValue)
        self._accum.valueChanged.connect(self._accum_slider.setValue)
        self._accum_lbl = QLabel("16 frames")
        self._accum_lbl.setStyleSheet(
            f"font-family:{MONO_FONT}; font-size:{FONT['heading']}pt; color:{PALETTE['textSub']};")
        self._accum.valueChanged.connect(
            lambda v: self._accum_lbl.setText(f"{v} frames"))
        dl.addWidget(self._accum_slider)
        dl.addWidget(self._accum_lbl)
        lay.addWidget(depth_box)

        # Apply button
        self._apply_btn = QPushButton("Apply Settings")
        set_btn_icon(self._apply_btn, "fa5s.sync-alt")
        self._apply_btn.setFixedHeight(30)
        self._apply_btn.clicked.connect(self._apply_config)
        lay.addWidget(self._apply_btn)

        lay.addStretch()
        return w

    # ---------------------------------------------------------------- #
    #  Canvas (centre)                                                  #
    # ---------------------------------------------------------------- #

    def _build_canvas(self) -> QWidget:
        w   = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)

        self._canvas = LiveCanvas()
        self._canvas.probe_moved.connect(self._on_probe)
        self._canvas.context_action.connect(self._on_canvas_context)
        self._canvas.roi_changed.connect(self._on_roi_changed)
        lay.addWidget(self._canvas)
        return w

    def _on_canvas_context(self, action: str):
        """Dispatch context menu actions from LiveCanvas."""
        if action == "start":
            if self._start_btn.isEnabled():
                self._start()
        elif action == "stop":
            if self._stop_btn.isEnabled():
                self._stop()
        elif action == "freeze":
            self._toggle_freeze()
        elif action == "capture":
            self._capture()

    def _on_roi_changed(self, roi):
        """Update stored ROI whenever the canvas rubber-band selection changes."""
        self._roi = roi

    # ---------------------------------------------------------------- #
    #  Readouts panel (right)                                           #
    # ---------------------------------------------------------------- #

    def _build_readouts(self) -> QWidget:
        w   = QWidget()
        w.setMinimumWidth(180)
        w.setMaximumWidth(220)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 8, 8, 8)
        lay.setSpacing(8)

        lay.addWidget(self._sub("SNR"))
        self._snr_bar = SnrBar()
        lay.addWidget(self._snr_bar)
        lay.addSpacing(10)

        # Numerical stats
        stats_box = QGroupBox("Frame Stats")
        sl = QGridLayout(stats_box)
        sl.setSpacing(4)
        self._stat_vals = {}
        for r, (key, lbl) in enumerate([
            ("min",   "Min ΔR/R"),
            ("max",   "Max ΔR/R"),
            ("mean",  "Mean ΔR/R"),
            ("std",   "Std Dev"),
            ("snr",   "SNR (dB)"),
            ("cycle", "Cycles"),
            ("fps",   "Live fps"),
        ]):
            sl.addWidget(self._sub(lbl), r, 0)
            v = QLabel("—")
            v.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['sublabel']}pt; color:{PALETTE['textDim']};")
            v.setAlignment(Qt.AlignRight)
            sl.addWidget(v, r, 1)
            self._stat_vals[key] = v
        lay.addWidget(stats_box)

        # Probe readout
        probe_box = QGroupBox("Pixel Probe")
        pl = QGridLayout(probe_box)
        pl.setSpacing(4)
        self._probe_xy  = QLabel("—")
        self._probe_drr = QLabel("—")
        self._probe_dt  = QLabel("—")
        for l in [self._probe_xy, self._probe_drr, self._probe_dt]:
            l.setStyleSheet(
                f"font-family:{MONO_FONT}; font-size:{FONT['sublabel']}pt; color:{PALETTE['textDim']};")
        pl.addWidget(self._sub("Position"), 0, 0)
        pl.addWidget(self._probe_xy,         0, 1)
        pl.addWidget(self._sub("ΔR/R"),     1, 0)
        pl.addWidget(self._probe_drr,        1, 1)
        pl.addWidget(self._sub("ΔT (°C)"),  2, 0)
        pl.addWidget(self._probe_dt,         2, 1)
        lay.addWidget(probe_box)

        # Probe sparkline — history of ΔR/R at cursor position
        lay.addWidget(self._sub("Probe History  (ΔR/R)"))
        self._probe_plot = TempPlot(capacity=64)
        self._probe_plot.setToolTip(
            "Rolling sparkline of the last 64 ΔR/R readings at the\n"
            "pixel under the cursor. Move the cursor over the live map\n"
            "to start recording. The faint dotted line marks zero.")
        lay.addWidget(self._probe_plot)

        # Histogram
        lay.addWidget(self._sub("ΔR/R Histogram"))
        self._histogram = Histogram()
        lay.addWidget(self._histogram)

        lay.addStretch()
        return w

    # ---------------------------------------------------------------- #
    #  Public API                                                       #
    # ---------------------------------------------------------------- #

    def set_calibration(self, cal):
        """Update calibration for live ΔT display."""
        if self._proc:
            self._proc._cal = cal

    # ---------------------------------------------------------------- #
    #  Controls                                                         #
    # ---------------------------------------------------------------- #

    def _build_config(self) -> LiveConfig:
        return LiveConfig(
            frames_per_half  = self._frames_per_half.value(),
            accumulation     = self._accum.value(),
            trigger_mode     = self._trig_mode.currentText(),
            trigger_delay_ms = self._trig_delay.value(),
            display_fps      = self._disp_fps.value(),
        )

    def _start(self):
        try:
            from hardware.app_state import app_state
            _cam   = app_state.cam
            _fpga  = app_state.fpga
            _cal   = app_state.active_calibration
        except Exception:
            _cam = _fpga = _cal = None

        cfg = self._build_config()
        self._proc = LiveProcessor(_cam, _fpga, cfg, calibration=_cal)
        self._proc.start()

        self._timer.start()
        self._btn_runner.set_running(True, "Streaming")
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._frozen = False
        self._canvas.freeze(False)
        self._set_state("RUNNING", PALETTE['accent'])

    def _stop(self):
        self._timer.stop()
        if self._proc:
            self._proc.stop()
            self._proc = None
        self._btn_runner.set_running(False)
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._set_state("STOPPED", PALETTE['textSub'])
        # Reset throttle timestamps so the next _start() renders the very
        # first frame immediately instead of waiting for the 333 ms window.
        self._last_canvas_ts = 0.0
        self._last_stats_ts  = 0.0
        self._badges_active  = False

    def restart_if_running(self):
        """Re-start the live processor if currently running.

        Called by MainWindow when the user switches cameras via the
        CameraContextBar so the Live feed picks up the new camera without
        the user having to manually Stop → Start.
        """
        if self._proc is not None:
            self._stop()
            self._start()

    def _toggle_freeze(self):
        self._frozen = not self._frozen
        self._canvas.freeze(self._frozen)
        self._freeze_btn.setText("▶  Resume" if self._frozen else "❄  Freeze")
        self._set_state("FROZEN" if self._frozen else "RUNNING",
                        PALETTE['warning'] if self._frozen else PALETTE['accent'])

    def _capture(self):
        """Save the current frozen/live frame to disk."""
        if self._last_frame is None or self._last_frame.drr is None:
            QMessageBox.warning(self, "No Frame", "No live frame to capture.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Live Frame", "live_frame.npy",
            "NumPy files (*.npy);;PNG images (*.png);;All files (*)")
        if not path:
            return
        import numpy as np
        if path.endswith(".png"):
            self._canvas.save_snapshot(path)
        else:
            np.save(path, self._last_frame.drr)
            if self._last_frame.dt_map is not None:
                np.save(path.replace(".npy", "_dt.npy"),
                        self._last_frame.dt_map)
        QMessageBox.information(self, "Saved", f"Frame saved to:\n{path}")

    def _reset_ema(self):
        if self._proc:
            self._proc.reset_ema()

    @staticmethod
    def _active_ffc_camera():
        """Return the FFC-capable camera only if IR modality is active."""
        from hardware.app_state import app_state
        if getattr(app_state, "active_camera_type", "tr") != "ir":
            return None
        cam = app_state.cam  # cam points to whichever camera is active
        if cam is not None and getattr(cam, "supports_ffc", lambda: False)():
            return cam
        # Also check ir_cam slot directly
        cam = getattr(app_state, "ir_cam", None)
        if cam is not None and getattr(cam, "supports_ffc", lambda: False)():
            return cam
        return None

    def _do_ffc(self):
        """Run Flat-Field Correction on the active IR camera."""
        cam = self._active_ffc_camera()
        if cam is None:
            return

        self._ffc_btn.setEnabled(False)
        self._ffc_btn.setText("Running…")

        import threading
        def _run():
            try:
                ok = cam.do_ffc()
            except Exception:
                ok = False
            from PyQt5.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._ffc_done(ok))

        threading.Thread(target=_run, daemon=True).start()

    def _ffc_done(self, success: bool):
        self._ffc_btn.setEnabled(True)
        self._ffc_btn.setText("FFC")
        if success:
            self._ffc_btn.setToolTip(
                "FFC complete — pixel offsets recalibrated")
        else:
            self._ffc_btn.setToolTip(
                "FFC failed — check camera connection")

    def refresh_camera_mode(self):
        """Show/hide FFC button — only visible when IR modality is active."""
        self._ffc_btn.setVisible(self._active_ffc_camera() is not None)

    def _apply_config(self):
        if self._proc:
            self._proc.update_config(self._build_config())

    # ---------------------------------------------------------------- #
    #  Poll timer — reads queue and refreshes UI                       #
    # ---------------------------------------------------------------- #

    def _poll(self):
        if self._proc is None:
            return

        # Drain the frame queue to the most-recent frame.  If the producer
        # runs faster than the poll timer the queue grows; rendering the
        # oldest pending frame each tick makes the display lag further and
        # further behind.  By discarding all-but-last we always show the
        # latest data and keep the queue from growing without bound.
        frame = None
        while True:
            f = self._proc.get_frame(timeout=0.0)
            if f is None:
                break
            frame = f
        if frame is None:
            return

        self._last_frame = frame
        now = time.monotonic()

        # ── Canvas + SNR bar: at most 15 Hz (~67 ms between rebuilds) ──
        # The pixmap rebuild (percentile → RGB conversion → QImage) is the
        # single most expensive operation; throttling to 15 Hz halves the
        # CPU load vs the previous 20 Hz while remaining visually smooth.
        if now - self._last_canvas_ts >= 0.067:
            self._last_canvas_ts = now
            self._canvas.update_frame(frame)
            self._snr_bar.set_value(frame.snr_db)

        # ── Stats + histogram + toolbar badges: at most 3 Hz ───────────
        # Numerical stats (min/max/mean/std), the histogram, and fps/cycle
        # badges don't need to refresh faster than a few times per second.
        # Throttling them to 3 Hz removes several NumPy reductions and
        # multiple QLabel repaints from the hot path.
        if now - self._last_stats_ts >= 0.333:
            self._last_stats_ts = now

            # Histogram
            if frame.drr is not None:
                self._histogram.update_data(frame.drr)

            # Stats panel — restrict to ROI sub-array if one is active
            drr = frame.drr
            if drr is not None:
                if self._roi is not None:
                    x0, y0, x1, y1 = self._roi
                    sub  = drr[y0:y1, x0:x1]
                    flat = sub.ravel() if sub.size > 0 else drr.ravel()
                else:
                    flat = drr.ravel()
                self._stat_vals["min"].setText(f"{float(flat.min()):.4e}")
                self._stat_vals["max"].setText(f"{float(flat.max()):.4e}")
                self._stat_vals["mean"].setText(f"{float(flat.mean()):.4e}")
                self._stat_vals["std"].setText(f"{float(flat.std()):.4e}")
            self._stat_vals["snr"].setText(f"{frame.snr_db:.1f}")
            self._stat_vals["cycle"].setText(str(frame.cycle))
            self._stat_vals["fps"].setText(f"{frame.fps:.1f}")

            # Toolbar badges — setStyleSheet() triggers a full repaint; only
            # call it the first time a run goes "live" (not every 333 ms).
            if not self._badges_active:
                self._fps_lbl.setStyleSheet(
                    f"background:{PALETTE['surface2']}; color:{PALETTE['accent']}; padding:0 8px; "
                    f"border-radius:3px; font-family:{MONO_FONT}; font-size:{FONT['label']}pt;")
                self._cycle_lbl.setStyleSheet(
                    f"background:{PALETTE['surface2']}; color:{PALETTE['textDim']}; padding:0 8px; "
                    f"border-radius:3px; font-family:{MONO_FONT}; font-size:{FONT['label']}pt;")
                self._badges_active = True

            # Only setText when the string actually changes (avoids redundant
            # label repaints on ticks where fps/cycle haven't moved).
            fps_str   = f"{frame.fps:.1f} fps"
            cycle_str = f"cycle {frame.cycle}"
            if self._fps_lbl.text() != fps_str:
                self._fps_lbl.setText(fps_str)
            if self._cycle_lbl.text() != cycle_str:
                self._cycle_lbl.setText(cycle_str)

    def _on_probe(self, dx: int, dy: int):
        """Update pixel probe readout and sparkline from mouse position."""
        if self._last_frame is None:
            return
        drr = self._last_frame.drr
        if drr is None:
            return
        dy = max(0, min(dy, drr.shape[0] - 1))
        dx = max(0, min(dx, drr.shape[1] - 1))
        self._probe_xy.setText(f"({dx}, {dy})")
        pixel = drr[dy, dx]
        val = float(pixel) if np.ndim(pixel) == 0 else float(pixel.flat[0])
        self._probe_drr.setText(f"{val:.5e}")
        self._probe_plot.push(val)

        dt = self._last_frame.dt_map
        if dt is not None and 0 <= dy < dt.shape[0] and 0 <= dx < dt.shape[1]:
            v = dt[dy, dx]
            v = float(v) if np.ndim(v) == 0 else float(v.flat[0])
            self._probe_dt.setText(
                "masked" if not np.isfinite(v) else f"{v:.3f} °C")
        else:
            self._probe_dt.setText("—")

    # ---------------------------------------------------------------- #
    #  State badge helper                                               #
    # ---------------------------------------------------------------- #

    def _set_state(self, text: str, color: str):
        self._state_lbl.setText(text)
        self._state_lbl.setStyleSheet(
            f"background:{PALETTE['surface2']}; color:{color}; padding:0 8px; "
            f"border-radius:3px; font-family:{MONO_FONT}; font-size:{FONT['label']}pt; "
            f"border:1px solid {color};")

    def _sub(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setObjectName("sublabel")
        return l
