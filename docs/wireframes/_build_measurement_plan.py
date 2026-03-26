#!/usr/bin/env python3
"""Measurement Plan Builder wireframe — nested sweep automation."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.colors import Color
from _wireframe_common import *

OUT = os.path.join(os.path.dirname(__file__), "measurement-plan-builder.pdf")
c = Canvas(OUT, pagesize=(W, H))
c.setTitle("Measurement Plan Builder")

# ── Background ────────────────────────────────────────────────────────
filled_rect(c, 0, 0, W, H, fill=BG)
hdr_h = draw_header(c)
status_h = draw_status_bar(c)
content_top = hdr_h
content_bottom = H - status_h

# ── Sidebar (simplified) ─────────────────────────────────────────────
sb_w = 210
filled_rect(c, 0, content_top, sb_w, content_bottom - content_top, fill=SURFACE)
vline(c, sb_w, content_top, content_bottom)

sy = content_top + 10

# Phase 1 — complete
filled_rect(c, 4, sy, sb_w - 8, 26, fill=SURFACE2, radius=4)
c.setFillColor(GREEN)
c.circle(18, Y(sy + 13), 8, stroke=0, fill=1)
c.setStrokeColor(WHITE); c.setLineWidth(1.5)
cx_r, cy_r = 18, Y(sy + 13)
c.line(cx_r - 4, cy_r - 1, cx_r - 1, cy_r - 4)
c.line(cx_r - 1, cy_r - 4, cx_r + 4, cy_r + 3)
text_at(c, 32, sy + 14, "CONFIGURATION", size=9, color=TEXT, font="Helvetica-Bold")
sy += 30

# Phase 2 — complete
filled_rect(c, 4, sy, sb_w - 8, 26, fill=SURFACE2, radius=4)
c.setFillColor(GREEN)
c.circle(18, Y(sy + 13), 8, stroke=0, fill=1)
c.setStrokeColor(WHITE); c.setLineWidth(1.5)
cx_r, cy_r = 18, Y(sy + 13)
c.line(cx_r - 4, cy_r - 1, cx_r - 1, cy_r - 4)
c.line(cx_r - 1, cy_r - 4, cx_r + 4, cy_r + 3)
text_at(c, 32, sy + 14, "IMAGE ACQUISITION", size=9, color=TEXT, font="Helvetica-Bold")
sy += 30

# Phase 3 — active
filled_rect(c, 4, sy, sb_w - 8, 26, fill=SURFACE2, radius=4)
c.setFillColor(ACCENT)
c.circle(18, Y(sy + 13), 8, stroke=0, fill=1)
c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 9)
c.drawCentredString(18, Y(sy + 13) - 3, "3")
text_at(c, 32, sy + 14, "MEASUREMENT & ANALYSIS", size=9, color=ACCENT, font="Helvetica-Bold")
sy += 28

items_m = [
    ("Measurement Plan", True),
    ("Capture", False),
    ("Calibration", False),
    ("Analysis", False),
    ("Sessions", False),
    ("Library", False),
]
for label, sel in items_m:
    ih = 28
    if sel:
        filled_rect(c, 8, sy, sb_w - 16, ih, fill=ACCENT_DIM, stroke=ACCENT, radius=4)
        filled_rect(c, 4, sy + 4, 3, ih - 8, fill=ACCENT, radius=2)
        text_at(c, 28, sy + ih / 2 + 1, label, size=10, color=WHITE, font="Helvetica-Bold")
    else:
        text_at(c, 28, sy + ih / 2 + 1, label, size=10, color=TEXT)
    sy += ih + 2

sy += 10
hline(c, 12, sb_w - 12, sy)
sy += 8
filled_rect(c, 4, sy, sb_w - 8, 26, fill=SURFACE2, radius=4)
text_at(c, 32, sy + 14, "SYSTEM", size=9, color=TEXT_SUB, font="Helvetica-Bold")
sy += 28
for lbl in ["Camera", "Stage", "Prober", "Settings"]:
    text_at(c, 28, sy + 15, lbl, size=10, color=TEXT_DIM)
    sy += 30

# ── Right panel — Plan Controls ──────────────────────────────────────
rp_w = 240
rp_x = W - rp_w
vline(c, rp_x, content_top, content_bottom)
filled_rect(c, rp_x, content_top, rp_w, content_bottom - content_top, fill=SURFACE)

# Execution header
filled_rect(c, rp_x, content_top, rp_w, 34, fill=SURFACE2)
text_at(c, rp_x + 12, content_top + 20, "Execution", size=11, color=TEXT, font="Helvetica-Bold")
hline(c, rp_x, rp_x + rp_w, content_top + 34)

ry = content_top + 44
button(c, rp_x + 12, ry, rp_w - 24, 36, "Start Plan",
       fill=Color(0.0, 0.55, 0.30), text_color=WHITE, border=Color(0.0, 0.65, 0.35),
       font_size=12, radius=6)
ry += 44
button(c, rp_x + 12, ry, rp_w - 24, 26, "Validate Plan",
       fill=SURFACE3, text_color=TEXT, border=BORDER, font_size=9, radius=4)
ry += 36

text_at(c, rp_x + 12, ry + 10, "Estimated time", size=8, color=TEXT_DIM)
text_at(c, rp_x + rp_w - 12, ry + 10, "~2h 45m", size=10, color=WARNING, font="Helvetica-Bold", anchor="right")
ry += 20
text_at(c, rp_x + 12, ry + 10, "Estimated storage", size=8, color=TEXT_DIM)
text_at(c, rp_x + rp_w - 12, ry + 10, "~8.4 GB", size=10, color=TEXT, font="Helvetica-Bold", anchor="right")
ry += 20
text_at(c, rp_x + 12, ry + 10, "Total measurements", size=8, color=TEXT_DIM)
text_at(c, rp_x + rp_w - 12, ry + 10, "432", size=10, color=ACCENT, font="Helvetica-Bold", anchor="right")
ry += 30

hline(c, rp_x + 10, rp_x + rp_w - 10, ry)
ry += 10
text_at(c, rp_x + 12, ry + 10, "Options", size=9, color=TEXT, font="Helvetica-Bold")
ry += 20
checkbox(c, rp_x + 12, ry, "Store raw frames", checked=False, size=9)
ry += 22
checkbox(c, rp_x + 12, ry, "Auto-calibrate at each temp", checked=True, size=9)
ry += 22
checkbox(c, rp_x + 12, ry, "Pause on failure", checked=True, size=9)
ry += 22
checkbox(c, rp_x + 12, ry, "Generate report on completion", checked=True, size=9)

# ── Main content — Plan Builder ──────────────────────────────────────
mx = sb_w + 1
mw = rp_x - sb_w - 1
filled_rect(c, mx, content_top, mw, content_bottom - content_top, fill=BG)

# Plan header
py = content_top + 12
text_at(c, mx + 16, py + 12, "Measurement Plan", size=16, color=TEXT, font="Helvetica-Bold")
text_at(c, mx + 16, py + 28, "Define nested measurement sweeps for automated device characterization",
        size=9, color=TEXT_DIM)

# Recipe buttons
button(c, mx + mw - 270, py + 2, 100, 24, "Load Recipe",
       fill=SURFACE3, text_color=TEXT, border=BORDER, font_size=8, radius=4)
button(c, mx + mw - 160, py + 2, 110, 24, "Save as Recipe",
       fill=SURFACE3, text_color=ACCENT, border=ACCENT_DIM, font_size=8, radius=4)

py += 44
hline(c, mx + 12, mx + mw - 12, py)
py += 10

# ── Nested Sweep Tree ────────────────────────────────────────────────
indent = 28
level_colors = [
    Color(0.14, 0.16, 0.18),
    Color(0.16, 0.18, 0.20),
    Color(0.18, 0.20, 0.22),
    Color(0.20, 0.22, 0.24),
]

def draw_level(y, level, title, type_val, summary, count, expanded=True):
    """Draw one sweep level card."""
    lx = mx + 16 + level * indent
    lw = mw - 32 - level * indent
    card_h = 70 if expanded else 32

    # Connecting line from parent
    if level > 0:
        line_x = mx + 16 + (level - 1) * indent + 8
        c.setStrokeColor(BORDER)
        c.setLineWidth(1)
        c.line(line_x, Y(y - 10), line_x, Y(y + 16))
        c.line(line_x, Y(y + 16), lx, Y(y + 16))

    filled_rect(c, lx, y, lw, card_h, fill=level_colors[min(level, 3)],
                stroke=BORDER, radius=6)

    # Drag handle
    text_at(c, lx + 10, y + 18, "\u2261", size=14, color=TEXT_SUB)

    # Level badge
    badge_w = badge(c, lx + 28, y + 8, f"Level {level + 1}",
                    fill=ACCENT_DIM, text_color=ACCENT, font_size=7, h=14)

    # Title
    text_at(c, lx + 28 + badge_w + 8, y + 18, title,
            size=11, color=TEXT, font="Helvetica-Bold")

    # Count badge on right
    count_str = f"{count}"
    badge(c, lx + lw - 80, y + 8, f"{count_str} iterations",
          fill=SURFACE3, text_color=TEXT_DIM, font_size=7, h=14)

    # Remove button
    text_at(c, lx + lw - 14, y + 18, "\u00d7", size=14, color=TEXT_SUB, anchor="center")

    if expanded:
        # Type dropdown + parameters
        text_at(c, lx + 28, y + 36, "Type:", size=8, color=TEXT_DIM)
        dropdown(c, lx + 60, y + 28, 140, 20, type_val)

        text_at(c, lx + 210, y + 36, summary, size=8, color=TEXT_DIM)

    return y + card_h + 6

# Level 1: Die Position
py = draw_level(py, 0, "Die Position", "Position Grid",
                "Cols: 3   Rows: 4   Step: 500 \u00b5m", 12)

# Level 2: Temperature
py = draw_level(py, 1, "Temperature Sweep", "Temperature Sweep",
                "25 \u2192 125 \u00b0C   Step: 20 \u00b0C   Dwell: 60 s", 6)

# Level 3: Voltage Sweep
py = draw_level(py, 2, "Current Sweep", "Current Sweep",
                "0 \u2192 25 mA   Step: 5 mA   Compliance: 10 V", 6)

# Acquire block (terminal node)
aq_x = mx + 16 + 3 * indent
aq_w = mw - 32 - 3 * indent

# Connecting line
line_x = mx + 16 + 2 * indent + 8
c.setStrokeColor(BORDER)
c.setLineWidth(1)
c.line(line_x, Y(py - 10), line_x, Y(py + 16))
c.line(line_x, Y(py + 16), aq_x, Y(py + 16))

filled_rect(c, aq_x, py, aq_w, 50, fill=Color(0.0, 0.25, 0.20),
            stroke=ACCENT_DIM, radius=6)
text_at(c, aq_x + 12, py + 18, "\u25b6  Acquire", size=11,
        color=ACCENT, font="Helvetica-Bold")
text_at(c, aq_x + 12, py + 36, "100 frames  |  5 ms exposure  |  \u0394R/R  |  float64 averaging",
        size=8, color=TEXT_DIM)
py += 60

# [+ Add Level] button
button(c, mx + 16, py, 120, 28, "+ Add Level",
       fill=SURFACE2, text_color=ACCENT, border=ACCENT_DIM, font_size=9, radius=4)

# Summary bar
py += 40
filled_rect(c, mx + 12, py, mw - 24, 30, fill=SURFACE2, stroke=BORDER, radius=4)
text_at(c, mx + mw / 2, py + 17,
        "12 positions \u00d7 6 temperatures \u00d7 6 currents = 432 measurements",
        size=10, color=TEXT, font="Helvetica-Bold", anchor="center")

# ── Label ─────────────────────────────────────────────────────────────
text_at(c, mx + mw / 2, content_bottom - 10,
        "MEASUREMENT PLAN BUILDER  \u2014  Nested Sweep Automation",
        size=8, color=TEXT_SUB, font="Helvetica-Bold", anchor="center")

c.save()
print(f"Wrote {OUT}")
