#!/usr/bin/env python3
"""
Multi-page wireframe: every sidebar section with Basic / Advanced split.
Each page shows the main content area for one section, with:
  - Basic controls at top (always visible)
  - "Advanced" toggle
  - Advanced controls expanded below
  - TR / IR / TR+IR badges on controls
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.colors import Color
from _wireframe_common import *

OUT = os.path.join(os.path.dirname(__file__),
                   "section-layouts-basic-advanced.pdf")

# Modality badge colors
TR_COLOR = Color(0.24, 0.55, 0.93)    # blue
IR_COLOR = Color(0.93, 0.40, 0.24)    # orange-red
BOTH_COLOR = Color(0.55, 0.45, 0.80)  # purple

# ── Layout constants ─────────────────────────────────────────────────
SIDEBAR_W = 210
CONTENT_X = SIDEBAR_W + 1
CONTENT_W = W - SIDEBAR_W
HDR_H = 44
STATUS_H = 28
CONTENT_TOP = HDR_H
CONTENT_BOT = H - STATUS_H
CONTENT_H = CONTENT_BOT - CONTENT_TOP

# Panel inside content area
PNL_MARGIN = 20
PNL_X = CONTENT_X + PNL_MARGIN
PNL_W = CONTENT_W - 2 * PNL_MARGIN
PNL_TOP = CONTENT_TOP + PNL_MARGIN


def _draw_chrome(c, active_section, phase_idx):
    """Draw header, status bar, and sidebar with active_section highlighted."""
    filled_rect(c, 0, 0, W, H, fill=BG)
    draw_header(c)
    draw_status_bar(c)

    # Sidebar background
    filled_rect(c, 0, CONTENT_TOP, SIDEBAR_W, CONTENT_H, fill=SURFACE)
    vline(c, SIDEBAR_W, CONTENT_TOP, CONTENT_BOT)

    phases = [
        ("CONFIGURATION", [
            "Modality", "Stimulus", "Timing", "Temperature",
            "Acquisition Settings"
        ]),
        ("IMAGE ACQUISITION", [
            "Live View", "Focus & Stage", "Signal Check"
        ]),
        ("MEASUREMENT & ANALYSIS", [
            "Capture", "Calibration", "Analysis", "Sessions", "Library"
        ]),
    ]
    system_items = ["Camera", "Stage", "Prober", "Settings"]

    sy = CONTENT_TOP + 10
    for pi, (phase_title, items) in enumerate(phases):
        # Phase header
        filled_rect(c, 4, sy, SIDEBAR_W - 8, 26, fill=SURFACE2, radius=4)
        indicator_x = 18
        indicator_cy = sy + 13
        is_active_phase = (pi == phase_idx)

        if pi < phase_idx:  # complete
            c.setFillColor(GREEN)
            c.circle(indicator_x, Y(indicator_cy), 8, stroke=0, fill=1)
            c.setStrokeColor(WHITE); c.setLineWidth(1.5)
            cx_r, cy_r = indicator_x, Y(indicator_cy)
            c.line(cx_r - 4, cy_r - 1, cx_r - 1, cy_r - 4)
            c.line(cx_r - 1, cy_r - 4, cx_r + 4, cy_r + 3)
        elif is_active_phase:
            c.setFillColor(ACCENT)
            c.circle(indicator_x, Y(indicator_cy), 8, stroke=0, fill=1)
            c.setFillColor(WHITE)
            c.setFont("Helvetica-Bold", 9)
            c.drawCentredString(indicator_x, Y(indicator_cy) - 3, str(pi + 1))
        else:
            c.setStrokeColor(TEXT_SUB); c.setLineWidth(1.5)
            c.setFillColor(SURFACE2)
            c.circle(indicator_x, Y(indicator_cy), 8, stroke=1, fill=1)
            c.setFillColor(TEXT_SUB)
            c.setFont("Helvetica", 9)
            c.drawCentredString(indicator_x, Y(indicator_cy) - 3, str(pi + 1))

        title_c = ACCENT if is_active_phase else (TEXT if pi < phase_idx else TEXT_DIM)
        text_at(c, 32, indicator_cy + 1, phase_title, size=9.5,
                color=title_c, font="Helvetica-Bold")
        sy += 28

        for item_label in items:
            item_h = 26
            if item_label == active_section:
                filled_rect(c, 8, sy, SIDEBAR_W - 16, item_h,
                            fill=ACCENT_DIM, stroke=ACCENT, radius=4)
                filled_rect(c, 4, sy + 4, 3, item_h - 8,
                            fill=ACCENT, radius=2)
                text_at(c, 28, sy + item_h / 2 + 1, item_label,
                        size=10, color=WHITE, font="Helvetica-Bold")
            else:
                future = pi > phase_idx
                text_at(c, 28, sy + item_h / 2 + 1, item_label,
                        size=10, color=TEXT_DIM if future else TEXT)
            sy += item_h + 1
        sy += 6

    # Separator
    sy += 2
    hline(c, 12, SIDEBAR_W - 12, sy)
    sy += 8

    # SYSTEM
    filled_rect(c, 4, sy, SIDEBAR_W - 8, 26, fill=SURFACE2, radius=4)
    text_at(c, 32, sy + 14, "SYSTEM", size=9.5,
            color=TEXT_SUB, font="Helvetica-Bold")
    sy += 28
    for item_label in system_items:
        item_h = 26
        if item_label == active_section:
            filled_rect(c, 8, sy, SIDEBAR_W - 16, item_h,
                        fill=ACCENT_DIM, stroke=ACCENT, radius=4)
            filled_rect(c, 4, sy + 4, 3, item_h - 8,
                        fill=ACCENT, radius=2)
            text_at(c, 28, sy + item_h / 2 + 1, item_label,
                    size=10, color=WHITE, font="Helvetica-Bold")
        else:
            text_at(c, 28, sy + item_h / 2 + 1, item_label,
                    size=10, color=TEXT_DIM)
        sy += item_h + 1


def _label_row(c, x, y, label, value_w=None, value_text=None):
    """Draw a label and optional value on the right."""
    text_at(c, x, y, label, size=8.5, color=TEXT_DIM)
    if value_text:
        text_at(c, x + (value_w or 160), y, value_text,
                size=9, color=TEXT, font="Helvetica-Bold", anchor="right")


def _badge_tr_ir(c, x, y, mode="both"):
    """Draw TR / IR availability badges. Returns total width."""
    if mode == "tr":
        return badge(c, x, y, "TR", fill=TR_COLOR, text_color=WHITE)
    elif mode == "ir":
        return badge(c, x, y, "IR", fill=IR_COLOR, text_color=WHITE)
    else:
        w1 = badge(c, x, y, "TR", fill=TR_COLOR, text_color=WHITE)
        w2 = badge(c, x + w1 + 3, y, "IR", fill=IR_COLOR, text_color=WHITE)
        return w1 + 3 + w2


def _preset_row(c, x, y, labels, w_each=52, h=22, gap=4):
    """Row of preset buttons."""
    for i, lbl in enumerate(labels):
        bx = x + i * (w_each + gap)
        button(c, bx, y, w_each, h, lbl, font_size=7, radius=3)
    return y + h + 6


def _page_title(c, title, subtitle=""):
    """Title bar inside content area."""
    filled_rect(c, CONTENT_X, CONTENT_TOP, CONTENT_W, 36, fill=SURFACE2)
    text_at(c, PNL_X, CONTENT_TOP + 22, title, size=13,
            color=TEXT, font="Helvetica-Bold")
    if subtitle:
        text_at(c, CONTENT_X + CONTENT_W - PNL_MARGIN, CONTENT_TOP + 22,
                subtitle, size=9, color=TEXT_DIM, anchor="right")
    hline(c, CONTENT_X, W, CONTENT_TOP + 36)
    return CONTENT_TOP + 42


# ═════════════════════════════════════════════════════════════════════
# PAGE 1 — Modality
# ═════════════════════════════════════════════════════════════════════
def page_modality(c):
    _draw_chrome(c, "Modality", 0)
    y = _page_title(c, "Modality", "Camera & measurement mode")

    # ── BASIC ──
    y += 4
    text_at(c, PNL_X, y + 10, "Active Camera", size=9, color=TEXT_DIM)
    _badge_tr_ir(c, PNL_X + 100, y + 4, "both")
    y += 18
    dropdown(c, PNL_X, y, 340, 28, "Basler acA1920-155um  [TR]  —  connected")
    y += 36

    text_at(c, PNL_X, y + 10, "Measurement Mode", size=9, color=TEXT_DIM)
    y += 18
    # Mode is auto-detected from camera
    filled_rect(c, PNL_X, y, 160, 28, fill=SURFACE3, stroke=ACCENT, radius=4)
    text_at(c, PNL_X + 80, y + 15, "THERMOREFLECTANCE",
            size=9, color=ACCENT, font="Helvetica-Bold", anchor="center")
    filled_rect(c, PNL_X + 168, y, 100, 28, fill=SURFACE3,
                stroke=BORDER, radius=4)
    text_at(c, PNL_X + 218, y + 15, "IR LOCK-IN",
            size=9, color=TEXT_DIM, anchor="center")
    y += 36

    text_at(c, PNL_X, y + 4, "Mode is determined by the connected camera.",
            size=8, color=TEXT_SUB)
    text_at(c, PNL_X, y + 16,
            "TR cameras use visible-light thermoreflectance.  "
            "IR cameras use infrared lock-in thermography.",
            size=8, color=TEXT_SUB)
    y += 32

    # Camera info readout
    filled_rect(c, PNL_X, y, PNL_W * 0.55, 100, fill=SURFACE2,
                stroke=BORDER, radius=4)
    info_items = [
        ("Model", "acA1920-155um"),
        ("Serial", "24126789"),
        ("Resolution", "1920 x 1200"),
        ("Bit Depth", "12-bit"),
        ("Max FPS", "155"),
    ]
    iy = y + 8
    for lbl, val in info_items:
        text_at(c, PNL_X + 12, iy + 10, lbl, size=8, color=TEXT_DIM)
        text_at(c, PNL_X + 180, iy + 10, val, size=9, color=TEXT,
                font="Helvetica-Bold", anchor="right")
        iy += 16
    y += 110

    # ── ADVANCED ──
    y = advanced_toggle(c, PNL_X, y, PNL_W * 0.55, expanded=True)

    # Advanced controls
    filled_rect(c, PNL_X, y, PNL_W * 0.55, 90, fill=SURFACE,
                stroke=Color(0, 0.5, 0.4, 0.3), radius=4)
    ay = y + 8
    text_at(c, PNL_X + 12, ay + 10, "Color Mode", size=8.5, color=TEXT_DIM)
    _badge_tr_ir(c, PNL_X + 250, ay + 4, "tr")
    ay += 14
    checkbox(c, PNL_X + 12, ay, "Enable RGB color output (Bayer demosaic)",
             checked=False, size=8.5)
    ay += 20
    text_at(c, PNL_X + 12, ay + 10, "Pixel Format", size=8.5, color=TEXT_DIM)
    text_at(c, PNL_X + 180, ay + 10, "Mono12", size=9, color=TEXT,
            font="Helvetica-Bold", anchor="right")
    ay += 16
    text_at(c, PNL_X + 12, ay + 10, "Binning", size=8.5, color=TEXT_DIM)
    dropdown(c, PNL_X + 100, ay + 2, 80, 22, "1x1")


# ═════════════════════════════════════════════════════════════════════
# PAGE 2 — Stimulus
# ═════════════════════════════════════════════════════════════════════
def page_stimulus(c):
    _draw_chrome(c, "Stimulus", 0)
    y = _page_title(c, "Stimulus", "Electronic bias & source control")

    # Two-column layout
    col_w = (PNL_W - 20) / 2
    lx = PNL_X
    rx = PNL_X + col_w + 20

    # ── LEFT: Bias Source (BASIC) ──
    text_at(c, lx, y + 12, "Bias Source", size=11,
            color=TEXT, font="Helvetica-Bold")
    _badge_tr_ir(c, lx + 100, y + 6, "both")
    y_l = y + 22

    text_at(c, lx, y_l + 10, "Source Mode", size=8.5, color=TEXT_DIM)
    y_l += 16
    # Radio buttons
    filled_rect(c, lx, y_l, 70, 24, fill=SURFACE3, stroke=ACCENT, radius=4)
    text_at(c, lx + 35, y_l + 13, "Voltage", size=8.5, color=ACCENT,
            anchor="center", font="Helvetica-Bold")
    filled_rect(c, lx + 74, y_l, 70, 24, fill=SURFACE3,
                stroke=BORDER, radius=4)
    text_at(c, lx + 109, y_l + 13, "Current", size=8.5, color=TEXT_DIM,
            anchor="center")
    y_l += 32

    text_at(c, lx, y_l + 10, "Output Level", size=8.5, color=TEXT_DIM)
    y_l += 16
    spinbox(c, lx, y_l, 120, 26, "1.800", suffix=" V")
    y_l += 34

    text_at(c, lx, y_l + 10, "Quick Presets", size=8.5, color=TEXT_DIM)
    y_l += 16
    y_l = _preset_row(c, lx, y_l, ["0 V", "0.5 V", "1 V", "1.8 V", "3.3 V", "5 V"],
                       w_each=44, gap=3)

    # Output buttons
    button(c, lx, y_l, col_w * 0.48, 28, "Output ON",
           fill=ACCENT, text_color=BLACK, border=ACCENT)
    button(c, lx + col_w * 0.52, y_l, col_w * 0.48, 28, "Output OFF",
           fill=SURFACE3, text_color=ERROR, border=ERROR)
    y_l += 38

    # Status readout
    filled_rect(c, lx, y_l, col_w, 70, fill=SURFACE2,
                stroke=BORDER, radius=4)
    stats = [("VOLTAGE", "1.800 V"), ("CURRENT", "12.4 mA"),
             ("POWER", "22.3 mW"), ("COMPLIANCE", "OK")]
    sy = y_l + 6
    for lbl, val in stats:
        text_at(c, lx + 8, sy + 10, lbl, size=7, color=TEXT_DIM)
        text_at(c, lx + col_w - 8, sy + 10, val, size=8, color=TEXT,
                font="Helvetica-Bold", anchor="right")
        sy += 15
    y_l += 78

    # Advanced
    y_l = advanced_toggle(c, lx, y_l, col_w, expanded=True)
    filled_rect(c, lx, y_l, col_w, 100, fill=SURFACE,
                stroke=Color(0, 0.5, 0.4, 0.3), radius=4)
    ay = y_l + 8
    text_at(c, lx + 8, ay + 10, "Output Port", size=8.5, color=TEXT_DIM)
    ay += 14
    dropdown(c, lx + 8, ay, col_w - 16, 22, "VO INT — pulsed +/-10 V")
    ay += 28
    text_at(c, lx + 8, ay + 10, "Compliance Limit", size=8.5, color=TEXT_DIM)
    ay += 14
    spinbox(c, lx + 8, ay, 120, 22, "0.100", suffix=" A")
    ay += 28
    checkbox(c, lx + 8, ay, "20 mA range mode", checked=True, size=8.5)

    # ── RIGHT: Status readouts ──
    text_at(c, rx, y + 12, "Measured Output", size=11,
            color=TEXT, font="Helvetica-Bold")
    y_r = y + 24

    filled_rect(c, rx, y_r, col_w, 120, fill=SURFACE2,
                stroke=BORDER, radius=4)
    readings = [
        ("VOLTAGE", "1.800 V", TEXT),
        ("CURRENT", "12.4 mA", TEXT),
        ("POWER", "22.3 mW", TEXT),
        ("COMPLIANCE", "OK", GREEN),
        ("OUTPUT", "ON", ACCENT),
    ]
    ry = y_r + 8
    for lbl, val, clr in readings:
        text_at(c, rx + 12, ry + 10, lbl, size=8, color=TEXT_DIM)
        text_at(c, rx + col_w - 12, ry + 10, val, size=10, color=clr,
                font="Helvetica-Bold", anchor="right")
        ry += 20
    y_r = y_r + 130

    # Gate channel (conditional)
    text_at(c, rx, y_r + 10, "Gate Channel", size=9,
            color=TEXT_DIM, font="Helvetica-Bold")
    text_at(c, rx + col_w - 4, y_r + 10,
            "AMCAD BILT only", size=7, color=TEXT_SUB, anchor="right")
    y_r += 20
    filled_rect(c, rx, y_r, col_w, 50, fill=SURFACE2,
                stroke=BORDER, radius=4)
    text_at(c, rx + 12, y_r + 18, "Vg", size=8, color=TEXT_DIM)
    text_at(c, rx + col_w - 12, y_r + 18, "0.000 V", size=9,
            color=TEXT, font="Helvetica-Bold", anchor="right")
    text_at(c, rx + 12, y_r + 36, "Ig", size=8, color=TEXT_DIM)
    text_at(c, rx + col_w - 12, y_r + 36, "0.0 uA", size=9,
            color=TEXT, font="Helvetica-Bold", anchor="right")


# ═════════════════════════════════════════════════════════════════════
# PAGE 3 — Timing
# ═════════════════════════════════════════════════════════════════════
def page_timing(c):
    _draw_chrome(c, "Timing", 0)
    y = _page_title(c, "Timing", "Modulation & synchronization control")

    # ── BASIC ──
    # Status readouts
    filled_rect(c, PNL_X, y + 4, PNL_W * 0.55, 90, fill=SURFACE2,
                stroke=BORDER, radius=4)
    stats = [
        ("FREQUENCY", "1.000 kHz"), ("DUTY CYCLE", "50.0%"),
        ("SYNC", "LOCKED"), ("STIMULUS", "OFF"), ("FRAME COUNT", "0"),
    ]
    sy = y + 12
    for lbl, val in stats:
        text_at(c, PNL_X + 12, sy + 10, lbl, size=8, color=TEXT_DIM)
        clr = GREEN if val in ("LOCKED",) else (
              ACCENT if val == "OFF" else TEXT)
        text_at(c, PNL_X + PNL_W * 0.55 - 12, sy + 10, val, size=10,
                color=clr, font="Helvetica-Bold", anchor="right")
        sy += 15
    y += 102

    _badge_tr_ir(c, PNL_X + PNL_W * 0.55 - 50, y - 96, "both")

    text_at(c, PNL_X, y + 10, "Frequency Presets", size=9, color=TEXT_DIM)
    y += 18
    y = _preset_row(c, PNL_X, y,
                    ["1 Hz", "10 Hz", "100 Hz", "1 kHz", "10 kHz"],
                    w_each=60, gap=4)

    text_at(c, PNL_X, y + 10, "Duty Cycle Presets", size=9, color=TEXT_DIM)
    y += 18
    y = _preset_row(c, PNL_X, y,
                    ["10%", "25%", "50%", "75%", "90%"],
                    w_each=50, gap=4)

    # Start / Stop / Output
    button(c, PNL_X, y, 130, 30, "Start Modulation",
           fill=ACCENT, text_color=BLACK, border=ACCENT)
    button(c, PNL_X + 138, y, 80, 30, "Stop",
           fill=SURFACE3, text_color=ERROR, border=ERROR)
    button(c, PNL_X + 230, y, 90, 30, "Output ON",
           fill=SURFACE3, text_color=WARNING, border=WARNING)
    button(c, PNL_X + 328, y, 90, 30, "Output OFF",
           fill=SURFACE3, text_color=TEXT_DIM, border=BORDER)
    y += 42

    # Preset management
    text_at(c, PNL_X, y + 10, "Configuration Preset", size=9, color=TEXT_DIM)
    y += 18
    dropdown(c, PNL_X, y, 200, 26, "Default (1 kHz / 50%)")
    button(c, PNL_X + 208, y, 50, 26, "Load", font_size=8)
    button(c, PNL_X + 264, y, 55, 26, "Save...", font_size=8)
    y += 38

    # ── ADVANCED ──
    y = advanced_toggle(c, PNL_X, y, PNL_W * 0.55, expanded=True)

    filled_rect(c, PNL_X, y, PNL_W * 0.55, 140, fill=SURFACE,
                stroke=Color(0, 0.5, 0.4, 0.3), radius=4)
    ay = y + 8
    text_at(c, PNL_X + 12, ay + 10, "Exact Frequency", size=8.5,
            color=TEXT_DIM)
    ay += 14
    spinbox(c, PNL_X + 12, ay, 160, 24, "1000.0", suffix=" Hz")
    ay += 30

    text_at(c, PNL_X + 12, ay + 10, "Exact Duty Cycle", size=8.5,
            color=TEXT_DIM)
    ay += 14
    spinbox(c, PNL_X + 12, ay, 120, 24, "50.00", suffix=" %")
    ay += 30

    # Trigger mode (BNC745 only)
    text_at(c, PNL_X + 12, ay + 10, "Trigger Mode", size=8.5, color=TEXT_DIM)
    text_at(c, PNL_X + PNL_W * 0.55 - 20, ay + 10,
            "BNC 745 only", size=7, color=TEXT_SUB, anchor="right")
    ay += 14
    filled_rect(c, PNL_X + 12, ay, 90, 22, fill=SURFACE3,
                stroke=ACCENT, radius=3)
    text_at(c, PNL_X + 57, ay + 12, "Continuous", size=8, color=ACCENT,
            anchor="center", font="Helvetica-Bold")
    filled_rect(c, PNL_X + 106, ay, 90, 22, fill=SURFACE3,
                stroke=BORDER, radius=3)
    text_at(c, PNL_X + 151, ay + 12, "Single-shot", size=8,
            color=TEXT_DIM, anchor="center")


# ═════════════════════════════════════════════════════════════════════
# PAGE 4 — Temperature
# ═════════════════════════════════════════════════════════════════════
def page_temperature(c):
    _draw_chrome(c, "Temperature", 0)
    y = _page_title(c, "Temperature", "TEC setpoint & monitoring")

    _badge_tr_ir(c, PNL_X + PNL_W * 0.55 - 50, y, "both")

    # ── BASIC ──
    y += 6
    # Status readout
    filled_rect(c, PNL_X, y, PNL_W * 0.55, 80, fill=SURFACE2,
                stroke=BORDER, radius=4)
    stats = [("ACTUAL", "25.02 C"), ("SETPOINT", "25.00 C"),
             ("OUTPUT", "3.2%"), ("STATUS", "Stable")]
    sy = y + 8
    for lbl, val in stats:
        text_at(c, PNL_X + 12, sy + 10, lbl, size=8, color=TEXT_DIM)
        clr = GREEN if val == "Stable" else TEXT
        text_at(c, PNL_X + PNL_W * 0.55 - 12, sy + 10, val, size=10,
                color=clr, font="Helvetica-Bold", anchor="right")
        sy += 16
    y += 88

    # Temperature plot placeholder
    filled_rect(c, PNL_X, y, PNL_W * 0.55, 80, fill=SURFACE2,
                stroke=BORDER, radius=4)
    text_at(c, PNL_X + PNL_W * 0.275, y + 42, "Temperature History",
            size=9, color=TEXT_DIM, anchor="center")
    # Simulated trace
    c.setStrokeColor(ACCENT)
    c.setLineWidth(1)
    import math
    pts = []
    for i in range(60):
        px = PNL_X + 10 + i * (PNL_W * 0.55 - 20) / 60
        py = y + 45 + math.sin(i * 0.3) * 8 + (0 if i < 40 else (i - 40) * 0.5)
        pts.append((px, Y(py)))
    for i in range(len(pts) - 1):
        c.line(pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1])
    y += 88

    # Setpoint control
    text_at(c, PNL_X, y + 10, "Target Temperature", size=9, color=TEXT_DIM)
    y += 18
    spinbox(c, PNL_X, y, 120, 28, "25.00", suffix=" C")
    button(c, PNL_X + 128, y, 56, 28, "Set",
           fill=ACCENT, text_color=BLACK, border=ACCENT)
    y += 36

    text_at(c, PNL_X, y + 10, "Quick Presets", size=9, color=TEXT_DIM)
    y += 18
    y = _preset_row(c, PNL_X, y,
                    ["-20 C", "0 C", "25 C", "50 C", "85 C"],
                    w_each=52, gap=4)

    # Enable / Disable
    button(c, PNL_X, y, 100, 28, "Enable",
           fill=ACCENT, text_color=BLACK, border=ACCENT)
    button(c, PNL_X + 108, y, 100, 28, "Disable",
           fill=SURFACE3, text_color=ERROR, border=ERROR)
    y += 40

    # ── ADVANCED ──
    y = advanced_toggle(c, PNL_X, y, PNL_W * 0.55, expanded=True)

    filled_rect(c, PNL_X, y, PNL_W * 0.55, 100, fill=SURFACE,
                stroke=Color(0, 0.5, 0.4, 0.3), radius=4)
    ay = y + 8
    text_at(c, PNL_X + 12, ay + 10, "Safety Limits", size=9,
            color=TEXT, font="Helvetica-Bold")
    ay += 18
    text_at(c, PNL_X + 12, ay + 10, "Min Temp", size=8.5, color=TEXT_DIM)
    spinbox(c, PNL_X + 100, ay + 2, 100, 22, "-20.0", suffix=" C")
    ay += 26
    text_at(c, PNL_X + 12, ay + 10, "Max Temp", size=8.5, color=TEXT_DIM)
    spinbox(c, PNL_X + 100, ay + 2, 100, 22, "85.0", suffix=" C")
    ay += 26
    text_at(c, PNL_X + 12, ay + 10, "Warning +/-", size=8.5, color=TEXT_DIM)
    spinbox(c, PNL_X + 100, ay + 2, 100, 22, "5.0", suffix=" C")


# ═════════════════════════════════════════════════════════════════════
# PAGE 5 — Acquisition Settings
# ═════════════════════════════════════════════════════════════════════
def page_acquisition_settings(c):
    _draw_chrome(c, "Acquisition Settings", 0)
    y = _page_title(c, "Acquisition Settings", "Capture parameters")

    _badge_tr_ir(c, PNL_X + PNL_W * 0.55 - 50, y, "both")

    # ── BASIC ──
    y += 6
    text_at(c, PNL_X, y + 10, "Frames per Phase", size=9, color=TEXT_DIM)
    y += 18
    spinbox(c, PNL_X, y, 140, 28, "100", suffix=" frames")
    text_at(c, PNL_X + 150, y + 16,
            "More frames = better SNR, longer capture time",
            size=7, color=TEXT_SUB)
    y += 36

    text_at(c, PNL_X, y + 10, "Inter-Phase Delay", size=9, color=TEXT_DIM)
    y += 18
    spinbox(c, PNL_X, y, 140, 28, "0.10", suffix=" s")
    text_at(c, PNL_X + 150, y + 16,
            "Settling time between cold and hot captures",
            size=7, color=TEXT_SUB)
    y += 36

    text_at(c, PNL_X, y + 10, "Exposure", size=9, color=TEXT_DIM)
    _badge_tr_ir(c, PNL_X + 80, y + 4, "tr")
    text_at(c, PNL_X + PNL_W * 0.55, y + 10, "5.00 ms",
            size=9, color=TEXT, font="Helvetica-Bold", anchor="right")
    y += 18
    slider_bar(c, PNL_X, y + 2, PNL_W * 0.55 - 80, pos=0.35)
    spinbox(c, PNL_X + PNL_W * 0.55 - 70, y - 4, 70, 22, "5000", suffix=" us")
    y += 16
    y = _preset_row(c, PNL_X, y,
                    ["50 us", "1 ms", "5 ms", "20 ms", "100 ms"],
                    w_each=52, gap=4)

    # IR note
    filled_rect(c, PNL_X, y, PNL_W * 0.55, 24, fill=SURFACE2, radius=4)
    _badge_tr_ir(c, PNL_X + 8, y + 4, "ir")
    text_at(c, PNL_X + 40, y + 14,
            "Exposure is fixed on IR cameras (microbolometer auto-exposes)",
            size=7.5, color=TEXT_SUB)
    y += 32

    text_at(c, PNL_X, y + 10, "Colormap", size=9, color=TEXT_DIM)
    y += 18
    dropdown(c, PNL_X, y, 200, 26, "Thermal Delta")
    y += 36

    # ── ADVANCED ──
    y = advanced_toggle(c, PNL_X, y, PNL_W * 0.55, expanded=True)

    filled_rect(c, PNL_X, y, PNL_W * 0.55, 110, fill=SURFACE,
                stroke=Color(0, 0.5, 0.4, 0.3), radius=4)
    ay = y + 8
    text_at(c, PNL_X + 12, ay + 10, "Gain", size=8.5, color=TEXT_DIM)
    _badge_tr_ir(c, PNL_X + 60, ay + 4, "tr")
    ay += 14
    slider_bar(c, PNL_X + 12, ay + 2, 200, pos=0.0)
    text_at(c, PNL_X + 230, ay + 4, "0.0 dB", size=8, color=TEXT)
    text_at(c, PNL_X + 300, ay + 4, "0 dB = best SNR", size=7, color=TEXT_SUB)
    ay += 18

    checkbox(c, PNL_X + 12, ay, "Dark frame subtraction", size=8.5)
    ay += 20
    checkbox(c, PNL_X + 12, ay, "Pre-capture validation",
             checked=True, size=8.5)
    ay += 20
    checkbox(c, PNL_X + 12, ay, "Auto-focus before each capture", size=8.5)
    ay += 20
    text_at(c, PNL_X + 12, ay + 10, "Display Mode", size=8.5, color=TEXT_DIM)
    ay += 14
    filled_rect(c, PNL_X + 12, ay, 90, 20, fill=SURFACE3,
                stroke=ACCENT, radius=3)
    text_at(c, PNL_X + 57, ay + 11, "Auto contrast", size=7.5,
            color=ACCENT, anchor="center", font="Helvetica-Bold")
    filled_rect(c, PNL_X + 106, ay, 80, 20, fill=SURFACE3,
                stroke=BORDER, radius=3)
    text_at(c, PNL_X + 146, ay + 11, "12-bit fixed", size=7.5,
            color=TEXT_DIM, anchor="center")


# ═════════════════════════════════════════════════════════════════════
# PAGE 6 — Live View
# ═════════════════════════════════════════════════════════════════════
def page_live_view(c):
    _draw_chrome(c, "Live View", 1)
    y = _page_title(c, "Live View", "Camera preview & image quality")

    # Preview takes most of the space
    preview_h = 340
    filled_rect(c, PNL_X, y + 4, PNL_W * 0.65, preview_h,
                fill=Color(0.12, 0.14, 0.13), stroke=BORDER, radius=4)
    crosshair(c, PNL_X + PNL_W * 0.325, y + 4 + preview_h / 2, size=30)
    text_at(c, PNL_X + PNL_W * 0.325, y + 24,
            "Live Camera Preview", size=12, color=TEXT_DIM, anchor="center")

    # Camera info overlay
    filled_rect(c, PNL_X + 8, y + preview_h - 20, 240, 18,
                fill=Color(0, 0, 0, 0.5), radius=3)
    text_at(c, PNL_X + 14, y + preview_h - 10,
            "Basler acA1920-155um  |  30 fps  |  5.0 ms  |  0.0 dB",
            size=7, color=TEXT_DIM)

    # Mode badge
    badge_w = 140
    filled_rect(c, PNL_X + PNL_W * 0.65 - badge_w - 8, y + 12,
                badge_w, 20, fill=Color(0, 0, 0, 0.5), radius=3)
    text_at(c, PNL_X + PNL_W * 0.65 - badge_w / 2 - 8, y + 23,
            "THERMOREFLECTANCE", size=8, color=ACCENT,
            font="Helvetica-Bold", anchor="center")

    # Right panel: image quality metrics
    rp_x = PNL_X + PNL_W * 0.65 + 12
    rp_w = PNL_W * 0.35 - 12
    ry = y + 4
    text_at(c, rp_x, ry + 12, "Image Quality", size=10,
            color=TEXT, font="Helvetica-Bold")
    ry += 20

    # Histogram placeholder
    filled_rect(c, rp_x, ry, rp_w, 60, fill=SURFACE2,
                stroke=BORDER, radius=4)
    text_at(c, rp_x + rp_w / 2, ry + 32, "Exposure Histogram",
            size=8, color=TEXT_DIM, anchor="center")
    # Fake histogram bars
    import random; random.seed(99)
    c.setFillColor(ACCENT)
    for i in range(30):
        bh = random.randint(3, 40)
        bx = rp_x + 8 + i * (rp_w - 16) / 30
        c.rect(bx, Y(ry + 50), (rp_w - 16) / 32, bh, stroke=0, fill=1)
    ry += 68

    metrics = [
        ("Focus Score", "82 / 100", TEXT),
        ("Mean Intensity", "67%", TEXT),
        ("Saturation", "0 px", GREEN),
        ("Noise Floor", "12.4 DN", TEXT),
    ]
    for lbl, val, clr in metrics:
        text_at(c, rp_x, ry + 10, lbl, size=8, color=TEXT_DIM)
        text_at(c, rp_x + rp_w, ry + 10, val, size=9, color=clr,
                font="Helvetica-Bold", anchor="right")
        ry += 18

    # Signal quality strip
    ry += 4
    filled_rect(c, rp_x, ry, rp_w / 2 - 4, 30, fill=SURFACE2,
                stroke=BORDER, radius=4)
    text_at(c, rp_x + 6, ry + 12, "EXPOSURE", size=6.5, color=TEXT_DIM)
    text_at(c, rp_x + 6, ry + 24, "GOOD", size=9, color=GREEN,
            font="Helvetica-Bold")
    filled_rect(c, rp_x + rp_w / 2 + 4, ry, rp_w / 2 - 4, 30,
                fill=SURFACE2, stroke=BORDER, radius=4)
    text_at(c, rp_x + rp_w / 2 + 10, ry + 12, "SAT.", size=6.5,
            color=TEXT_DIM)
    text_at(c, rp_x + rp_w / 2 + 10, ry + 24, "0%", size=9,
            color=GREEN, font="Helvetica-Bold")

    y += preview_h + 12

    # Quick action buttons below preview
    text_at(c, PNL_X, y + 10, "Quick Actions", size=9, color=TEXT_DIM)
    _badge_tr_ir(c, PNL_X + 100, y + 4, "both")
    y += 18
    button(c, PNL_X, y, 100, 28, "Autofocus",
           fill=SURFACE3, border=BORDER)
    button(c, PNL_X + 108, y, 140, 28, "Optimize Throughput",
           fill=SURFACE3, border=BORDER)
    _badge_tr_ir(c, PNL_X + 256, y + 6, "tr")
    button(c, PNL_X + 300, y, 80, 28, "Run FFC",
           fill=SURFACE3, border=BORDER)
    _badge_tr_ir(c, PNL_X + 388, y + 6, "ir")
    y += 36

    # ── ADVANCED ──
    y = advanced_toggle(c, PNL_X, y, PNL_W, expanded=True)
    filled_rect(c, PNL_X, y, PNL_W, 50, fill=SURFACE,
                stroke=Color(0, 0.5, 0.4, 0.3), radius=4)
    ay = y + 8
    checkbox(c, PNL_X + 12, ay, "Show crosshair overlay", checked=True,
             size=8.5)
    checkbox(c, PNL_X + 220, ay, "Show grid overlay", size=8.5)
    checkbox(c, PNL_X + 380, ay, "False color LUT", size=8.5)
    ay += 22
    text_at(c, PNL_X + 12, ay + 10, "Frame Stats", size=8.5, color=TEXT_DIM)
    text_at(c, PNL_X + 110, ay + 10,
            "MIN: 412   MAX: 3891   MEAN: 2744   SAT: 0",
            size=8, color=ACCENT, font="Helvetica-Bold")
    button(c, PNL_X + PNL_W - 100, ay + 2, 88, 22, "Save Frame...",
           font_size=7.5)


# ═════════════════════════════════════════════════════════════════════
# PAGE 7 — Focus & Stage
# ═════════════════════════════════════════════════════════════════════
def page_focus_stage(c):
    _draw_chrome(c, "Focus & Stage", 1)
    y = _page_title(c, "Focus & Stage", "Positioning & autofocus")

    col_w = (PNL_W - 20) / 2
    lx = PNL_X
    rx = PNL_X + col_w + 20

    _badge_tr_ir(c, lx + PNL_W - 50, y, "both")

    # ── LEFT: Stage ──
    text_at(c, lx, y + 12, "Stage Position", size=11,
            color=TEXT, font="Helvetica-Bold")
    y_l = y + 22

    filled_rect(c, lx, y_l, col_w, 60, fill=SURFACE2,
                stroke=BORDER, radius=4)
    pos_items = [("X", "1240.0 um"), ("Y", "890.0 um"), ("Z", "500.0 um")]
    py = y_l + 8
    for lbl, val in pos_items:
        text_at(c, lx + 12, py + 10, lbl, size=9, color=TEXT_DIM,
                font="Helvetica-Bold")
        text_at(c, lx + col_w - 12, py + 10, val, size=10, color=ACCENT,
                font="Helvetica-Bold", anchor="right")
        py += 16
    y_l += 68

    # Jog pad
    text_at(c, lx, y_l + 10, "XY Jog", size=9, color=TEXT_DIM)
    text_at(c, lx + 50, y_l + 10, "Step:", size=8, color=TEXT_SUB)
    dropdown(c, lx + 80, y_l + 2, 80, 20, "100 um")
    y_l += 20

    # Jog pad grid (simplified)
    jp_x = lx + 30
    jp_y = y_l + 6
    btn_s = 36
    gap = 2
    dirs = [
        (1, 0, "\u2196"), (2, 0, "\u2191"), (3, 0, "\u2197"),
        (1, 1, "\u2190"), (2, 1, ""),       (3, 1, "\u2192"),
        (1, 2, "\u2199"), (2, 2, "\u2193"), (3, 2, "\u2198"),
    ]
    for col, row, arrow in dirs:
        bx = jp_x + (col - 1) * (btn_s + gap)
        by = jp_y + row * (btn_s + gap)
        if arrow:
            button(c, bx, by, btn_s, btn_s, arrow, font_size=14)
    y_l = jp_y + 3 * (btn_s + gap) + 8

    # Z jog
    text_at(c, lx + 160, jp_y + 10, "Z Jog", size=9, color=TEXT_DIM)
    button(c, lx + 190, jp_y + 20, 40, 36, "\u25b2", font_size=14)
    button(c, lx + 190, jp_y + 60, 40, 36, "\u25bc", font_size=14)

    # Home / Stop
    button(c, lx, y_l, 90, 28, "Home All",
           fill=SURFACE3, border=BORDER)
    button(c, lx + 98, y_l, 70, 28, "STOP",
           fill=ESTOP_BG, text_color=ESTOP_FG,
           border=Color(0.67, 0, 0))
    y_l += 40

    # ── RIGHT: Autofocus ──
    text_at(c, rx, y + 12, "Autofocus", size=11,
            color=TEXT, font="Helvetica-Bold")
    y_r = y + 22

    # Status
    filled_rect(c, rx, y_r, col_w, 60, fill=SURFACE2,
                stroke=BORDER, radius=4)
    af_items = [("STATE", "IDLE"), ("BEST Z", "— um"),
                ("SCORE", "— "), ("TIME", "— s")]
    ary = y_r + 6
    for lbl, val in af_items:
        text_at(c, rx + 12, ary + 10, lbl, size=8, color=TEXT_DIM)
        text_at(c, rx + col_w - 12, ary + 10, val, size=9, color=TEXT,
                font="Helvetica-Bold", anchor="right")
        ary += 12
    y_r += 68

    # Z range
    text_at(c, rx, y_r + 10, "Z Range", size=9, color=TEXT_DIM)
    y_r += 18
    text_at(c, rx, y_r + 10, "Start", size=8.5, color=TEXT_DIM)
    spinbox(c, rx + 40, y_r + 2, 90, 22, "-200", suffix=" um")
    text_at(c, rx + 150, y_r + 10, "End", size=8.5, color=TEXT_DIM)
    spinbox(c, rx + 180, y_r + 2, 90, 22, "200", suffix=" um")
    y_r += 30

    text_at(c, rx, y_r + 10, "Strategy", size=9, color=TEXT_DIM)
    y_r += 18
    dropdown(c, rx, y_r, 160, 26, "sweep")
    y_r += 34

    # Run / Abort / Progress
    button(c, rx, y_r, 130, 30, "Run Autofocus",
           fill=ACCENT, text_color=BLACK, border=ACCENT)
    button(c, rx + 138, y_r, 70, 30, "Abort",
           fill=SURFACE3, text_color=ERROR, border=ERROR)
    y_r += 38
    filled_rect(c, rx, y_r, col_w, 8, fill=SURFACE3, radius=4)
    filled_rect(c, rx, y_r, col_w * 0.0, 8, fill=ACCENT, radius=4)
    y_r += 16

    # Focus curve placeholder
    filled_rect(c, rx, y_r, col_w, 80, fill=SURFACE2,
                stroke=BORDER, radius=4)
    text_at(c, rx + col_w / 2, y_r + 42, "Focus Curve",
            size=9, color=TEXT_DIM, anchor="center")
    y_r += 88

    # ── ADVANCED (right side) ──
    y_r = advanced_toggle(c, rx, y_r, col_w, expanded=True)
    filled_rect(c, rx, y_r, col_w, 90, fill=SURFACE,
                stroke=Color(0, 0.5, 0.4, 0.3), radius=4)
    ay = y_r + 6
    text_at(c, rx + 12, ay + 10, "Focus Metric", size=8.5, color=TEXT_DIM)
    dropdown(c, rx + 100, ay + 2, 130, 20, "laplacian")
    ay += 24
    text_at(c, rx + 12, ay + 10, "Coarse Step", size=8.5, color=TEXT_DIM)
    spinbox(c, rx + 100, ay + 2, 80, 20, "50", suffix=" um")
    ay += 24
    text_at(c, rx + 12, ay + 10, "Fine Step", size=8.5, color=TEXT_DIM)
    spinbox(c, rx + 100, ay + 2, 80, 20, "5", suffix=" um")
    ay += 24
    text_at(c, rx + 12, ay + 10, "Avg Frames", size=8.5, color=TEXT_DIM)
    spinbox(c, rx + 100, ay + 2, 60, 20, "2")


# ═════════════════════════════════════════════════════════════════════
# PAGE 8 — Signal Check
# ═════════════════════════════════════════════════════════════════════
def page_signal_check(c):
    _draw_chrome(c, "Signal Check", 1)
    y = _page_title(c, "Signal Check", "Verify thermal signal before measurement")

    _badge_tr_ir(c, PNL_X + PNL_W - 50, y, "both")

    # ── BASIC ──
    y += 6
    text_at(c, PNL_X, y + 12,
            "Run a quick cold/hot sequence to verify detectable thermal signal.",
            size=9, color=TEXT_DIM)
    y += 22

    button(c, PNL_X, y, 150, 34, "Verify Signal",
           fill=ACCENT, text_color=BLACK, border=ACCENT, font_size=11)
    button(c, PNL_X + 160, y + 3, 70, 28, "COLD",
           fill=SURFACE3, border=BORDER, font_size=9)
    button(c, PNL_X + 236, y + 3, 70, 28, "HOT",
           fill=SURFACE3, border=BORDER, font_size=9)
    y += 44

    # Result strip
    col_w = (PNL_W - 20) / 3
    filled_rect(c, PNL_X, y, col_w, 50, fill=SURFACE2,
                stroke=BORDER, radius=4)
    text_at(c, PNL_X + 8, y + 14, "SNR", size=8, color=TEXT_DIM)
    text_at(c, PNL_X + 8, y + 36, "32.4 dB", size=16, color=GREEN,
            font="Helvetica-Bold")

    filled_rect(c, PNL_X + col_w + 10, y, col_w, 50, fill=SURFACE2,
                stroke=BORDER, radius=4)
    text_at(c, PNL_X + col_w + 18, y + 14, "Peak dR/R",
            size=8, color=TEXT_DIM)
    text_at(c, PNL_X + col_w + 18, y + 36, "2.3e-3", size=16,
            color=TEXT, font="Helvetica-Bold")

    filled_rect(c, PNL_X + 2 * (col_w + 10), y, col_w, 50, fill=SURFACE2,
                stroke=BORDER, radius=4)
    text_at(c, PNL_X + 2 * (col_w + 10) + 8, y + 14, "Verdict",
            size=8, color=TEXT_DIM)
    text_at(c, PNL_X + 2 * (col_w + 10) + 8, y + 36, "SIGNAL OK",
            size=14, color=GREEN, font="Helvetica-Bold")
    y += 60

    # Preview images
    img_w = (PNL_W - 30) / 4
    img_h = 140
    labels = ["COLD", "HOT", "DIFFERENCE", "dR/R"]
    for i, lbl in enumerate(labels):
        ix = PNL_X + i * (img_w + 10)
        filled_rect(c, ix, y, img_w, img_h, fill=SURFACE2,
                    stroke=BORDER, radius=4)
        text_at(c, ix + img_w / 2, y + img_h / 2,
                lbl, size=9, color=TEXT_DIM, anchor="center")
    y += img_h + 10

    # ── ADVANCED ──
    y = advanced_toggle(c, PNL_X, y, PNL_W, expanded=True)
    filled_rect(c, PNL_X, y, PNL_W, 60, fill=SURFACE,
                stroke=Color(0, 0.5, 0.4, 0.3), radius=4)
    ay = y + 8
    checkbox(c, PNL_X + 12, ay, "Show per-channel breakdown (RGB)",
             size=8.5)
    _badge_tr_ir(c, PNL_X + 270, ay - 2, "tr")
    ay += 22
    text_at(c, PNL_X + 12, ay + 10, "ROI", size=8.5, color=TEXT_DIM)
    button(c, PNL_X + 50, ay + 2, 80, 20, "Edit ROI...", font_size=7.5)
    text_at(c, PNL_X + 140, ay + 10, "Full frame (1920 x 1200)",
            size=8, color=TEXT_SUB)
    ay += 22
    checkbox(c, PNL_X + 12, ay, "Noise spectrum analysis", size=8.5)


# ═════════════════════════════════════════════════════════════════════
# PAGE 9 — Capture
# ═════════════════════════════════════════════════════════════════════
def page_capture(c):
    _draw_chrome(c, "Capture", 2)
    y = _page_title(c, "Capture", "Single acquisition & grid scan")

    _badge_tr_ir(c, PNL_X + PNL_W - 50, y, "both")

    # ── BASIC ──
    y += 4
    # Sub-tabs: Single / Grid
    filled_rect(c, PNL_X, y, 80, 26, fill=SURFACE3,
                stroke=ACCENT, radius=4)
    text_at(c, PNL_X + 40, y + 14, "Single", size=9, color=ACCENT,
            anchor="center", font="Helvetica-Bold")
    filled_rect(c, PNL_X + 84, y, 80, 26, fill=SURFACE3,
                stroke=BORDER, radius=4)
    text_at(c, PNL_X + 124, y + 14, "Grid", size=9, color=TEXT_DIM,
            anchor="center")
    y += 34

    # Summary of settings from Configuration phase
    filled_rect(c, PNL_X, y, PNL_W * 0.55, 80, fill=SURFACE2,
                stroke=BORDER, radius=4)
    text_at(c, PNL_X + 8, y + 14, "Current Configuration",
            size=9, color=TEXT, font="Helvetica-Bold")
    cfg_items = [
        ("Frames", "100 / phase"), ("Exposure", "5.0 ms"),
        ("Frequency", "1.0 kHz"), ("Bias", "1.800 V"),
    ]
    cy = y + 22
    for lbl, val in cfg_items:
        text_at(c, PNL_X + 12, cy + 10, lbl, size=8, color=TEXT_DIM)
        text_at(c, PNL_X + PNL_W * 0.55 - 12, cy + 10, val, size=8,
                color=TEXT, font="Helvetica-Bold", anchor="right")
        cy += 13
    y += 88

    # Run button
    button(c, PNL_X, y, 180, 38, "RUN SEQUENCE",
           fill=ACCENT, text_color=BLACK, border=ACCENT, font_size=12)
    button(c, PNL_X + 190, y + 4, 70, 30, "ABORT",
           fill=SURFACE3, text_color=ERROR, border=ERROR, font_size=9)
    y += 46

    # Progress
    filled_rect(c, PNL_X, y, PNL_W * 0.55, 10, fill=SURFACE3, radius=5)
    filled_rect(c, PNL_X, y, PNL_W * 0.55 * 0.0, 10, fill=ACCENT, radius=5)
    y += 18

    # Result images (5 panes)
    img_w = (PNL_W - 40) / 5
    img_h = 110
    labels = ["COLD", "HOT", "DIFF", "dR/R", "dT"]
    for i, lbl in enumerate(labels):
        ix = PNL_X + i * (img_w + 8)
        filled_rect(c, ix, y, img_w, img_h, fill=SURFACE2,
                    stroke=BORDER, radius=4)
        text_at(c, ix + img_w / 2, y + img_h / 2,
                lbl, size=9, color=TEXT_DIM, anchor="center")
    y += img_h + 10

    # Export
    button(c, PNL_X, y, 80, 26, "Export", font_size=8)
    text_at(c, PNL_X + 90, y + 14, "SNR: —", size=9, color=TEXT_DIM)
    y += 36

    # ── ADVANCED ──
    y = advanced_toggle(c, PNL_X, y, PNL_W, expanded=True)
    filled_rect(c, PNL_X, y, PNL_W, 60, fill=SURFACE,
                stroke=Color(0, 0.5, 0.4, 0.3), radius=4)
    ay = y + 8
    text_at(c, PNL_X + 12, ay + 10, "Recipe", size=8.5, color=TEXT_DIM)
    dropdown(c, PNL_X + 70, ay + 2, 180, 22, "(none)")
    button(c, PNL_X + 258, ay + 2, 80, 22, "Load Recipe...", font_size=7.5)
    ay += 28
    text_at(c, PNL_X + 12, ay + 10, "Session Notes", size=8.5, color=TEXT_DIM)
    filled_rect(c, PNL_X + 100, ay, PNL_W - 112, 22, fill=SURFACE,
                stroke=BORDER, radius=3)
    text_at(c, PNL_X + 108, ay + 12, "Enter notes...",
            size=8, color=TEXT_SUB)


# ═════════════════════════════════════════════════════════════════════
# PAGE 10 — Calibration
# ═════════════════════════════════════════════════════════════════════
def page_calibration(c):
    _draw_chrome(c, "Calibration", 2)
    y = _page_title(c, "Calibration",
                    "Temperature sweep for thermoreflectance coefficient")

    col_w = (PNL_W - 20) / 2
    lx = PNL_X
    rx = PNL_X + col_w + 20

    _badge_tr_ir(c, lx + PNL_W - 50, y, "both")

    # ── LEFT: Setup ──
    text_at(c, lx, y + 12, "Temperature Sequence (C)",
            size=10, color=TEXT, font="Helvetica-Bold")
    y_l = y + 22

    # Quick presets
    text_at(c, lx, y_l + 10, "Presets", size=8.5, color=TEXT_DIM)
    y_l += 16
    y_l = _preset_row(c, lx, y_l,
                      ["3-pt", "5-pt", "7-pt"],
                      w_each=46, gap=4)
    y_l = _preset_row(c, lx, y_l,
                      ["TR Std", "IR Std"],
                      w_each=60, gap=4)

    # Temperature list
    temps = ["20.00 C", "40.00 C", "60.00 C", "80.00 C", "100.00 C", "120.00 C"]
    for t in temps:
        filled_rect(c, lx, y_l, col_w * 0.7, 22, fill=SURFACE2,
                    stroke=BORDER, radius=3)
        text_at(c, lx + 8, y_l + 12, t, size=8.5, color=TEXT)
        text_at(c, lx + col_w * 0.7 - 8, y_l + 12, "x",
                size=9, color=TEXT_DIM, anchor="right")
        y_l += 24

    # Add temp
    spinbox(c, lx, y_l, 90, 22, "25.00", suffix=" C")
    button(c, lx + 98, y_l, 60, 22, "+ Add", font_size=8)
    y_l += 30

    text_at(c, lx, y_l + 10,
            "Est. time: ~11 min 30 s  (6 steps x [35 s ramp + 60 s settle])",
            size=7.5, color=TEXT_SUB)
    y_l += 22

    # Start / Abort
    button(c, lx, y_l, 130, 30, "Start Calibration",
           fill=ACCENT, text_color=BLACK, border=ACCENT)
    button(c, lx + 138, y_l, 70, 30, "Abort",
           fill=SURFACE3, text_color=ERROR, border=ERROR)
    y_l += 38
    filled_rect(c, lx, y_l, col_w, 8, fill=SURFACE3, radius=4)

    # ── RIGHT: Results ──
    text_at(c, rx, y + 12, "Results", size=10,
            color=TEXT, font="Helvetica-Bold")
    y_r = y + 24

    # C_TR map placeholder
    filled_rect(c, rx, y_r, col_w, 140, fill=SURFACE2,
                stroke=BORDER, radius=4)
    text_at(c, rx + col_w / 2, y_r + 60,
            "C_TR Coefficient Map", size=10,
            color=TEXT_DIM, anchor="center")
    text_at(c, rx + col_w / 2, y_r + 78,
            "(after calibration)", size=8,
            color=TEXT_SUB, anchor="center")
    y_r += 148

    # R-squared map
    filled_rect(c, rx, y_r, col_w, 100, fill=SURFACE2,
                stroke=BORDER, radius=4)
    text_at(c, rx + col_w / 2, y_r + 42, "R-squared Quality Map",
            size=10, color=TEXT_DIM, anchor="center")
    y_r += 108

    # Save / Load
    button(c, rx, y_r, 110, 26, "Save Cal...", font_size=8)
    button(c, rx + 118, y_r, 110, 26, "Load Cal...", font_size=8)
    y_r += 34

    # ── ADVANCED (below left column) ──
    y_l += 16
    y_l = advanced_toggle(c, lx, y_l, col_w, expanded=True)
    filled_rect(c, lx, y_l, col_w, 68, fill=SURFACE,
                stroke=Color(0, 0.5, 0.4, 0.3), radius=4)
    ay = y_l + 6
    text_at(c, lx + 12, ay + 10, "Averages", size=8.5, color=TEXT_DIM)
    spinbox(c, lx + 100, ay + 2, 80, 20, "100")
    ay += 24
    text_at(c, lx + 12, ay + 10, "Dwell Time", size=8.5, color=TEXT_DIM)
    spinbox(c, lx + 100, ay + 2, 80, 20, "60", suffix=" s")
    ay += 24
    text_at(c, lx + 12, ay + 10, "LED Wavelength", size=8.5, color=TEXT_DIM)
    _badge_tr_ir(c, lx + col_w - 40, ay + 4, "tr")
    dropdown(c, lx + 120, ay + 2, 100, 20, "530 nm")


# ═════════════════════════════════════════════════════════════════════
# PAGE 11 — Analysis
# ═════════════════════════════════════════════════════════════════════
def page_analysis(c):
    _draw_chrome(c, "Analysis", 2)
    y = _page_title(c, "Analysis", "Thermal analysis & hotspot detection")

    _badge_tr_ir(c, PNL_X + PNL_W - 50, y, "both")

    col_w_l = PNL_W * 0.22
    col_w_c = PNL_W * 0.45
    col_w_r = PNL_W * 0.28
    lx = PNL_X
    cx = lx + col_w_l + 10
    rx_col = cx + col_w_c + 10

    # ── LEFT: Controls (BASIC) ──
    text_at(c, lx, y + 12, "Controls", size=10,
            color=TEXT, font="Helvetica-Bold")
    y_l = y + 24

    text_at(c, lx, y_l + 10, "Threshold", size=8.5, color=TEXT_DIM)
    y_l += 16
    spinbox(c, lx, y_l, col_w_l, 24, "0.50", suffix=" C")
    y_l += 32

    button(c, lx, y_l, col_w_l, 32, "Run Analysis",
           fill=ACCENT, text_color=BLACK, border=ACCENT, font_size=10)
    y_l += 42

    # Advanced
    y_l = advanced_toggle(c, lx, y_l, col_w_l, expanded=True)
    filled_rect(c, lx, y_l, col_w_l, 100, fill=SURFACE,
                stroke=Color(0, 0.5, 0.4, 0.3), radius=4)
    ay = y_l + 6
    text_at(c, lx + 8, ay + 10, "Min Area (px)", size=8, color=TEXT_DIM)
    spinbox(c, lx + 8, ay + 14, col_w_l - 16, 20, "25")
    ay += 38
    checkbox(c, lx + 8, ay, "Per-channel", size=8)
    _badge_tr_ir(c, lx + 100, ay - 2, "tr")
    ay += 20
    checkbox(c, lx + 8, ay, "Auto-threshold", size=8, checked=True)

    # ── CENTER: Overlay canvas ──
    text_at(c, cx, y + 12, "Thermal Overlay", size=10,
            color=TEXT, font="Helvetica-Bold")
    canvas_top = y + 24
    canvas_h = CONTENT_BOT - canvas_top - PNL_MARGIN - 40
    filled_rect(c, cx, canvas_top, col_w_c, canvas_h, fill=SURFACE2,
                stroke=BORDER, radius=4)
    text_at(c, cx + col_w_c / 2, canvas_top + canvas_h / 2,
            "Thermal Overlay Image", size=12,
            color=TEXT_DIM, anchor="center")

    # Export buttons below canvas
    ey = canvas_top + canvas_h + 6
    button(c, cx, ey, 100, 22, "Save PNG...", font_size=7.5)
    button(c, cx + 108, ey, 100, 22, "Export CSV...", font_size=7.5)
    button(c, cx + 216, ey, 110, 22, "Add to Report", font_size=7.5)

    # ── RIGHT: Results ──
    text_at(c, rx_col, y + 12, "Results", size=10,
            color=TEXT, font="Helvetica-Bold")
    y_r = y + 24

    # Verdict banner
    filled_rect(c, rx_col, y_r, col_w_r, 50, fill=Color(0, 0.25, 0.15),
                stroke=GREEN, radius=4)
    text_at(c, rx_col + col_w_r / 2, y_r + 22, "PASS",
            size=18, color=GREEN, font="Helvetica-Bold", anchor="center")
    text_at(c, rx_col + col_w_r / 2, y_r + 40,
            "3 hotspots  |  Peak: 4.2 C", size=8, color=TEXT_DIM,
            anchor="center")
    y_r += 58

    # Hotspot table
    text_at(c, rx_col, y_r + 10, "Hotspots", size=9,
            color=TEXT, font="Helvetica-Bold")
    y_r += 18
    # Table header
    filled_rect(c, rx_col, y_r, col_w_r, 18, fill=SURFACE2, radius=2)
    headers = ["#", "Peak", "Mean", "Area"]
    hx_offsets = [8, 24, 60, 96]
    for hdr, hx in zip(headers, hx_offsets):
        text_at(c, rx_col + hx, y_r + 11, hdr, size=7, color=TEXT_DIM,
                font="Helvetica-Bold")
    y_r += 20
    # Table rows
    rows = [("1", "4.2 C", "3.1 C", "142 px"),
            ("2", "2.8 C", "2.0 C", "87 px"),
            ("3", "1.5 C", "1.1 C", "45 px")]
    for row in rows:
        for val, hx in zip(row, hx_offsets):
            text_at(c, rx_col + hx, y_r + 10, val, size=7.5, color=TEXT)
        y_r += 16


# ═════════════════════════════════════════════════════════════════════
# PAGE 12 — Camera (SYSTEM)
# ═════════════════════════════════════════════════════════════════════
def page_camera_system(c):
    _draw_chrome(c, "Camera", 2)
    y = _page_title(c, "Camera", "SYSTEM  —  Hardware control & diagnostics")

    col_w = (PNL_W - 20) / 2
    lx = PNL_X
    rx = PNL_X + col_w + 20

    # ── LEFT: Exposure & Gain (BASIC) ──
    text_at(c, lx, y + 12, "Exposure", size=10,
            color=TEXT, font="Helvetica-Bold")
    _badge_tr_ir(c, lx + 80, y + 6, "tr")
    y_l = y + 22
    slider_bar(c, lx, y_l + 2, col_w - 80, pos=0.35)
    spinbox(c, lx + col_w - 70, y_l - 4, 70, 22, "5000", suffix=" us")
    y_l += 18
    y_l = _preset_row(c, lx, y_l,
                      ["50 us", "1 ms", "5 ms", "20 ms", "100 ms"],
                      w_each=52, gap=4)

    text_at(c, lx, y_l + 10, "Gain", size=10,
            color=TEXT, font="Helvetica-Bold")
    _badge_tr_ir(c, lx + 45, y_l + 4, "tr")
    y_l += 18
    slider_bar(c, lx, y_l + 2, col_w - 80, pos=0.0)
    text_at(c, lx + col_w - 60, y_l + 4, "0.0 dB", size=9, color=TEXT)
    y_l += 20

    # Quick actions
    text_at(c, lx, y_l + 10, "Quick Actions", size=10,
            color=TEXT, font="Helvetica-Bold")
    y_l += 18
    button(c, lx, y_l, 100, 28, "Autofocus", fill=SURFACE3, border=BORDER)
    button(c, lx + 108, y_l, 140, 28, "Optimize Throughput",
           fill=SURFACE3, border=BORDER)
    _badge_tr_ir(c, lx + 256, y_l + 6, "tr")
    y_l += 32
    button(c, lx, y_l, 80, 28, "Run FFC", fill=SURFACE3, border=BORDER)
    _badge_tr_ir(c, lx + 88, y_l + 6, "ir")
    y_l += 38

    # Signal quality
    sq_w = col_w / 2 - 4
    filled_rect(c, lx, y_l, sq_w, 30, fill=SURFACE2,
                stroke=BORDER, radius=4)
    text_at(c, lx + 6, y_l + 12, "EXPOSURE", size=6.5, color=TEXT_DIM)
    text_at(c, lx + 6, y_l + 24, "GOOD", size=9, color=GREEN,
            font="Helvetica-Bold")
    filled_rect(c, lx + sq_w + 8, y_l, sq_w, 30, fill=SURFACE2,
                stroke=BORDER, radius=4)
    text_at(c, lx + sq_w + 14, y_l + 12, "SATURATION",
            size=6.5, color=TEXT_DIM)
    text_at(c, lx + sq_w + 14, y_l + 24, "0%", size=9, color=GREEN,
            font="Helvetica-Bold")
    y_l += 40

    # ── ADVANCED ──
    y_l = advanced_toggle(c, lx, y_l, col_w, expanded=True)
    filled_rect(c, lx, y_l, col_w, 100, fill=SURFACE,
                stroke=Color(0, 0.5, 0.4, 0.3), radius=4)
    ay = y_l + 6
    text_at(c, lx + 12, ay + 10, "Display Mode", size=8.5, color=TEXT_DIM)
    ay += 14
    filled_rect(c, lx + 12, ay, 90, 20, fill=SURFACE3,
                stroke=ACCENT, radius=3)
    text_at(c, lx + 57, ay + 11, "Auto contrast", size=7.5,
            color=ACCENT, anchor="center", font="Helvetica-Bold")
    filled_rect(c, lx + 106, ay, 80, 20, fill=SURFACE3,
                stroke=BORDER, radius=3)
    text_at(c, lx + 146, ay + 11, "12-bit fixed", size=7.5,
            color=TEXT_DIM, anchor="center")
    ay += 26
    checkbox(c, lx + 12, ay, "Objective turret control", size=8.5)
    _badge_tr_ir(c, lx + 200, ay - 2, "tr")
    ay += 22
    button(c, lx + 12, ay, 90, 22, "Save Frame...", font_size=7.5)
    ay += 26
    text_at(c, lx + 12, ay + 8, "Frame Stats", size=8, color=TEXT_DIM)
    text_at(c, lx + 90, ay + 8,
            "MIN: 412  MAX: 3891  MEAN: 2744",
            size=8, color=ACCENT, font="Helvetica-Bold")

    # ── RIGHT: Camera info + simulated controls ──
    text_at(c, rx, y + 12, "Camera Information", size=10,
            color=TEXT, font="Helvetica-Bold")
    y_r = y + 24
    filled_rect(c, rx, y_r, col_w, 100, fill=SURFACE2,
                stroke=BORDER, radius=4)
    info = [("Model", "acA1920-155um"), ("Serial", "24126789"),
            ("Driver", "pypylon"), ("Resolution", "1920 x 1200"),
            ("Bit Depth", "12"), ("Max FPS", "155")]
    iy = y_r + 6
    for lbl, val in info:
        text_at(c, rx + 12, iy + 10, lbl, size=8, color=TEXT_DIM)
        text_at(c, rx + col_w - 12, iy + 10, val, size=9, color=TEXT,
                font="Helvetica-Bold", anchor="right")
        iy += 14
    y_r += 108

    # Simulated camera controls
    text_at(c, rx, y_r + 10, "Simulated Camera", size=9,
            color=TEXT_DIM, font="Helvetica-Bold")
    text_at(c, rx + col_w - 4, y_r + 10,
            "Demo mode only", size=7, color=TEXT_SUB, anchor="right")
    y_r += 20
    filled_rect(c, rx, y_r, col_w, 80, fill=SURFACE2,
                stroke=BORDER, radius=4)
    sy = y_r + 8
    text_at(c, rx + 12, sy + 10, "Resolution", size=8.5, color=TEXT_DIM)
    sy += 16
    for i, res in enumerate(["320x240", "640x480", "1280x720", "1920x1080"]):
        bx = rx + 12 + i * 72
        button(c, bx, sy, 68, 20, res, font_size=6.5)
    sy += 26
    text_at(c, rx + 12, sy + 10, "Frame Rate", size=8.5, color=TEXT_DIM)
    slider_bar(c, rx + 90, sy + 6, col_w - 110, pos=0.5)
    text_at(c, rx + col_w - 12, sy + 10, "30 fps", size=8, color=TEXT,
            anchor="right")


# ═════════════════════════════════════════════════════════════════════
# PAGE 13 — Settings (SYSTEM)
# ═════════════════════════════════════════════════════════════════════
def page_settings(c):
    _draw_chrome(c, "Settings", 2)
    y = _page_title(c, "Settings", "SYSTEM  —  Application preferences")

    col_w = PNL_W * 0.55
    lx = PNL_X

    # ── Appearance (BASIC) ──
    y = section_header(c, lx, y + 4, col_w, "Appearance")
    y += 4
    text_at(c, lx + 8, y + 10, "Theme", size=9, color=TEXT_DIM)
    y += 18
    # Segmented control
    seg_w = 80
    for i, (lbl, active) in enumerate([("Auto", True), ("Dark", False),
                                        ("Light", False)]):
        bx = lx + 8 + i * (seg_w + 2)
        fill = ACCENT if active else SURFACE3
        stroke = ACCENT if active else BORDER
        tc = BLACK if active else TEXT_DIM
        button(c, bx, y, seg_w, 26, lbl, fill=fill, text_color=tc,
               border=stroke, font_size=9, radius=4)
    y += 38

    # ── Lab / Operator (BASIC) ──
    y = section_header(c, lx, y, col_w, "Lab / Operator")
    y += 4
    text_at(c, lx + 8, y + 10, "Active Operator", size=9, color=TEXT_DIM)
    y += 18
    dropdown(c, lx + 8, y, 200, 24, "Dr. Smith")
    button(c, lx + 216, y, 50, 24, "Set", font_size=8)
    y += 32
    checkbox(c, lx + 8, y, "Require operator before each scan", size=8.5)
    y += 20
    checkbox(c, lx + 8, y, "Show operator confirmation banner", size=8.5)
    y += 28

    # ── Pre-Capture & Autofocus (BASIC) ──
    y = section_header(c, lx, y, col_w, "Acquisition Behavior")
    y += 4
    checkbox(c, lx + 8, y, "Run pre-capture validation checks", checked=True,
             size=8.5)
    y += 20
    checkbox(c, lx + 8, y,
             "Auto-focus before each capture (requires stage)", size=8.5)
    y += 28

    # ── ADVANCED ──
    y = advanced_toggle(c, lx, y, col_w, expanded=True)
    filled_rect(c, lx, y, col_w, 170, fill=SURFACE,
                stroke=Color(0, 0.5, 0.4, 0.3), radius=4)

    ay = y + 4
    ay = section_header(c, lx + 8, ay, col_w - 16, "Software Updates")
    checkbox(c, lx + 16, ay + 4, "Auto-check for updates", checked=True,
             size=8.5)
    ay += 22
    text_at(c, lx + 16, ay + 10, "Channel", size=8.5, color=TEXT_DIM)
    dropdown(c, lx + 80, ay + 2, 120, 20, "Stable")
    ay += 28

    ay = section_header(c, lx + 8, ay, col_w - 16, "AI Assistant")
    checkbox(c, lx + 16, ay + 4, "Enable AI assistant", size=8.5)
    ay += 22
    text_at(c, lx + 16, ay + 10, "Model", size=8.5, color=TEXT_DIM)
    dropdown(c, lx + 80, ay + 2, 160, 20, "Default")
    ay += 28

    ay = section_header(c, lx + 8, ay, col_w - 16, "Security")
    text_at(c, lx + 16, ay + 6, "Admin-only features hidden in basic view",
            size=7.5, color=TEXT_SUB)

    # ── Right side: License & Support ──
    rx = lx + col_w + 30
    rw = PNL_W - col_w - 30
    ry = CONTENT_TOP + 50
    text_at(c, rx, ry + 10, "License", size=10,
            color=TEXT, font="Helvetica-Bold")
    ry += 22
    button(c, rx, ry, 140, 28, "Manage License", font_size=9)
    ry += 44
    text_at(c, rx, ry + 10, "Support", size=10,
            color=TEXT, font="Helvetica-Bold")
    ry += 22
    button(c, rx, ry, 100, 28, "About", font_size=9)
    ry += 32
    button(c, rx, ry, 160, 28, "Copy Version Info", font_size=9)


# ═════════════════════════════════════════════════════════════════════
# BUILD PDF
# ═════════════════════════════════════════════════════════════════════

c = Canvas(OUT, pagesize=(W, H))
c.setTitle("SanjINSIGHT Section Layouts — Basic / Advanced")
c.setAuthor("SanjINSIGHT UX")

pages = [
    page_modality,
    page_stimulus,
    page_timing,
    page_temperature,
    page_acquisition_settings,
    page_live_view,
    page_focus_stage,
    page_signal_check,
    page_capture,
    page_calibration,
    page_analysis,
    page_camera_system,
    page_settings,
]

for i, draw_fn in enumerate(pages):
    draw_fn(c)
    if i < len(pages) - 1:
        c.showPage()

c.save()
print(f"Wrote {OUT}  ({len(pages)} pages)")
