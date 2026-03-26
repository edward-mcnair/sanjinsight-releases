#!/usr/bin/env python3
"""Option A — Phase Tabs wireframe."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.colors import Color
from _wireframe_common import *

OUT = os.path.join(os.path.dirname(__file__), "option-a-phase-tabs.pdf")

c = Canvas(OUT, pagesize=(W, H))
c.setTitle("Option A — Phase Tabs")
c.setAuthor("SanjINSIGHT UX")

# ── Background ────────────────────────────────────────────────────────
filled_rect(c, 0, 0, W, H, fill=BG)

# ── Header ────────────────────────────────────────────────────────────
hdr_h = draw_header(c)

# ── Phase tab bar ─────────────────────────────────────────────────────
tab_h = 42
tab_top = hdr_h
filled_rect(c, 0, tab_top, W, tab_h, fill=SURFACE)
hline(c, 0, W, tab_top + tab_h)

tab_w = W / 3
tabs = [
    ("1   CONFIGURE", False),
    ("2   ALIGN & VERIFY", True),
    ("3   MEASURE & ANALYZE", False),
]
for i, (label, active) in enumerate(tabs):
    tx = i * tab_w
    if active:
        filled_rect(c, tx, tab_top, tab_w, tab_h, fill=SURFACE2)
        # Active underline
        filled_rect(c, tx, tab_top + tab_h - 3, tab_w, 3, fill=ACCENT)
        text_at(c, tx + tab_w / 2, tab_top + tab_h / 2 + 1, label,
                size=12, color=ACCENT, font="Helvetica-Bold", anchor="center")
    else:
        text_at(c, tx + tab_w / 2, tab_top + tab_h / 2 + 1, label,
                size=11, color=TEXT_DIM, font="Helvetica", anchor="center")
    # Tab divider
    if i > 0:
        vline(c, tx, tab_top + 8, tab_top + tab_h - 8)

content_top = tab_top + tab_h
status_h = draw_status_bar(c)
content_bottom = H - status_h

# ── Main content: Align & Verify ─────────────────────────────────────
content_h = content_bottom - content_top
left_w = int(W * 0.58)
right_w = W - left_w

# Left — Live preview
filled_rect(c, 0, content_top, left_w, content_h, fill=Color(0.08, 0.08, 0.09))
# Camera preview placeholder
prev_margin = 16
prev_x = prev_margin
prev_top = content_top + prev_margin
prev_w = left_w - 2 * prev_margin
prev_h = content_h - 2 * prev_margin
filled_rect(c, prev_x, prev_top, prev_w, prev_h,
            fill=Color(0.12, 0.14, 0.13), stroke=BORDER, radius=4)
text_at(c, prev_x + prev_w / 2, prev_top + 20,
        "Live Camera Preview", size=14, color=TEXT_DIM,
        font="Helvetica-Bold", anchor="center")

# Simulated image noise pattern (decorative lines)
c.setStrokeColor(Color(0.15, 0.18, 0.16))
c.setLineWidth(0.3)
import random
random.seed(42)
for _ in range(60):
    lx = prev_x + random.randint(10, prev_w - 10)
    ly_top = prev_top + random.randint(40, prev_h - 10)
    lw = random.randint(20, 80)
    c.line(lx, Y(ly_top), lx + lw, Y(ly_top))

# Crosshair
crosshair(c, prev_x + prev_w / 2, prev_top + prev_h / 2, size=40)

# Resolution / FPS badge
filled_rect(c, prev_x + 8, prev_top + prev_h - 28, 160, 20,
            fill=Color(0, 0, 0, 0.5), radius=3)
text_at(c, prev_x + 14, prev_top + prev_h - 16,
        "1920 x 1200  |  30 fps  |  5.0 ms", size=7, color=TEXT_DIM)

# Right — Tool panels
vline(c, left_w, content_top, content_bottom, color=BORDER)
panel_x = left_w + 1
panel_w = right_w - 1
panel_margin = 10
pw = panel_w - 2 * panel_margin
px = panel_x + panel_margin

# Panel heights
panels = [
    ("Focus", 110, [
        ("button", "Autofocus", ACCENT),
        ("meter", "Focus Quality", 82),
    ]),
    ("Stage", 115, [
        ("xyz", None, None),
    ]),
    ("Exposure", 100, [
        ("histogram", None, None),
        ("slider", "Exposure", 5000),
    ]),
    ("Signal Check", 120, [
        ("mini_preview", None, None),
        ("button", "Verify Signal", ACCENT),
    ]),
]

py = content_top + panel_margin
for title, ph, contents in panels:
    # Panel card
    filled_rect(c, px, py, pw, ph, fill=SURFACE, stroke=BORDER, radius=5)
    # Title
    text_at(c, px + 10, py + 16, title, size=10,
            color=TEXT, font="Helvetica-Bold")
    hline(c, px + 8, px + pw - 8, py + 24, color=BORDER)

    inner_y = py + 32
    for kind, *args in contents:
        if kind == "button":
            label, clr = args
            button(c, px + 10, inner_y, pw - 20, 26, label,
                   fill=ACCENT_DIM, text_color=WHITE, border=ACCENT,
                   font_size=9, radius=4)
            inner_y += 32
        elif kind == "meter":
            label, value = args
            # Label
            text_at(c, px + 10, inner_y + 10, label, size=8, color=TEXT_DIM)
            text_at(c, px + pw - 10, inner_y + 10, f"{value}/100",
                    size=9, color=ACCENT, font="Helvetica-Bold",
                    anchor="right")
            # Bar background
            bar_y = inner_y + 18
            bar_w = pw - 20
            filled_rect(c, px + 10, bar_y, bar_w, 8,
                        fill=SURFACE2, radius=4)
            # Bar fill
            filled_rect(c, px + 10, bar_y, int(bar_w * value / 100), 8,
                        fill=ACCENT, radius=4)
            inner_y += 34
        elif kind == "xyz":
            # XYZ jog mockup
            dirs = [("X", "< >"), ("Y", "< >"), ("Z", "< >")]
            for j, (axis, arrows) in enumerate(dirs):
                ax = px + 10 + j * (pw - 20) // 3
                text_at(c, ax + 4, inner_y + 10, axis, size=9,
                        color=ACCENT, font="Helvetica-Bold")
                filled_rect(c, ax + 16, inner_y + 2, 50, 16,
                            fill=SURFACE2, stroke=BORDER, radius=3)
                text_at(c, ax + 41, inner_y + 12, arrows,
                        size=8, color=TEXT_DIM, anchor="center")
            # Position readout
            inner_y += 24
            text_at(c, px + 10, inner_y + 10,
                    "Position:  X 1240   Y 890   Z 0  um",
                    size=8, color=TEXT_DIM)
            inner_y += 24
            # Step size
            text_at(c, px + 10, inner_y + 10, "Step:", size=8,
                    color=TEXT_SUB)
            for k, s in enumerate(["1", "10", "100"]):
                sx = px + 50 + k * 36
                sel = (k == 1)
                button(c, sx, inner_y + 2, 30, 16, s + " um",
                       fill=ACCENT_DIM if sel else SURFACE3,
                       text_color=WHITE if sel else TEXT_DIM,
                       border=ACCENT if sel else BORDER,
                       font_size=7, radius=3)
            inner_y += 22
        elif kind == "histogram":
            # Simple histogram shape
            filled_rect(c, px + 10, inner_y, pw - 20, 30,
                        fill=SURFACE2, stroke=BORDER, radius=3)
            # Fake histogram bars
            c.setFillColor(ACCENT_DIM)
            bar_count = 32
            bw = (pw - 24) / bar_count
            random.seed(7)
            for b in range(bar_count):
                bh = random.randint(3, 26)
                bx = px + 12 + b * bw
                by = Y(inner_y + 28)
                c.rect(bx, by, bw - 1, bh, stroke=0, fill=1)
            inner_y += 36
        elif kind == "slider":
            label, val = args
            text_at(c, px + 10, inner_y + 10, f"{label}: {val} us",
                    size=8, color=TEXT_DIM)
            # Slider track
            filled_rect(c, px + 110, inner_y + 4, pw - 130, 6,
                        fill=SURFACE2, radius=3)
            # Slider thumb
            thumb_x = px + 110 + int((pw - 130) * 0.35)
            c.setFillColor(ACCENT)
            c.circle(thumb_x, Y(inner_y + 7), 5, stroke=0, fill=1)
            inner_y += 20
        elif kind == "mini_preview":
            # Small DR/R preview
            filled_rect(c, px + 10, inner_y, (pw - 20) * 0.55, 42,
                        fill=Color(0.10, 0.12, 0.11), stroke=BORDER,
                        radius=3)
            text_at(c, px + 14, inner_y + 12, "DR/R Preview",
                    size=7, color=TEXT_DIM)
            # Fake hotspot
            c.setFillColor(Color(1, 0.4, 0.1, 0.4))
            c.circle(px + 60, Y(inner_y + 28), 8, stroke=0, fill=1)
            # SNR readout
            snr_x = px + 10 + int((pw - 20) * 0.58)
            text_at(c, snr_x, inner_y + 14, "SNR", size=8,
                    color=TEXT_DIM)
            text_at(c, snr_x, inner_y + 28, "24.3 dB", size=12,
                    color=GREEN, font="Helvetica-Bold")
            inner_y += 50

    py += ph + 6

# ── Inset wireframes (bottom-right of live preview) ───────────────────
inset_w = 180
inset_h = 100
inset_gap = 8

# Configure inset
ix = prev_x + 10
iy = prev_top + prev_h - inset_h - 10
draw_inset_configure(c, ix, iy, inset_w, inset_h)

# Measure inset
ix2 = ix + inset_w + inset_gap
draw_inset_measure(c, ix2, iy, inset_w, inset_h)

# ── Title annotation ─────────────────────────────────────────────────
text_at(c, W / 2, H - status_h - 10,
        "OPTION A  —  Phase Tabs", size=8, color=TEXT_SUB,
        font="Helvetica-Bold", anchor="center")

c.save()
print(f"Wrote {OUT}")
