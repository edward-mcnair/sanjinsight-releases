#!/usr/bin/env python3
"""
Three-page wireframe comparing Guided / Standard / Expert workspace modes.

All three pages show the same workflow moment: user is on the Stimulus
configuration section, with Configuration phase partially complete.
The content area is identical — only the sidebar and disclosure state differ.

Output: workspace-modes.pdf
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.colors import Color
from _wireframe_common import *

OUT = os.path.join(os.path.dirname(__file__), "workspace-modes.pdf")
c = Canvas(OUT, pagesize=(W, H))
c.setTitle("Workspace Modes — Guided / Standard / Expert")

# Extra colors
BLUE_DIM = Color(0.15, 0.25, 0.40)
BLUE = Color(0.30, 0.55, 0.85)
HINT_BG = Color(0.10, 0.18, 0.22)

# ── Shared drawing helpers ────────────────────────────────────────────

def draw_checkmark(c, cx, cy_top):
    """Green circle with white checkmark."""
    c.setFillColor(GREEN)
    c.circle(cx, Y(cy_top), 8, stroke=0, fill=1)
    c.setStrokeColor(WHITE); c.setLineWidth(1.5)
    rx, ry = cx, Y(cy_top)
    c.line(rx - 4, ry - 1, rx - 1, ry - 4)
    c.line(rx - 1, ry - 4, rx + 4, ry + 3)


def draw_active_dot(c, cx, cy_top):
    """Teal filled circle with number."""
    c.setFillColor(ACCENT)
    c.circle(cx, Y(cy_top), 8, stroke=0, fill=1)


def draw_empty_circle(c, cx, cy_top):
    """Empty circle for future phases."""
    c.setStrokeColor(TEXT_SUB)
    c.setLineWidth(1)
    c.setFillColor(SURFACE)
    c.circle(cx, Y(cy_top), 8, stroke=1, fill=1)


def draw_mode_badge(c, x, top_y, label, active_idx, mode_labels):
    """Draw the workspace mode segmented control."""
    sw = 180
    sh = 24
    filled_rect(c, x, top_y, sw, sh, fill=SURFACE2, stroke=BORDER, radius=12)
    seg_w = sw / len(mode_labels)
    for i, ml in enumerate(mode_labels):
        sx = x + i * seg_w
        if i == active_idx:
            filled_rect(c, sx + 2, top_y + 2, seg_w - 4, sh - 4,
                        fill=ACCENT, radius=10)
            text_at(c, sx + seg_w / 2, top_y + sh / 2 + 1, ml,
                    size=8, color=BLACK, font="Helvetica-Bold", anchor="center")
        else:
            text_at(c, sx + seg_w / 2, top_y + sh / 2 + 1, ml,
                    size=8, color=TEXT_DIM, anchor="center")


def draw_stimulus_content(c, mx, content_top, content_bottom, mw, show_more_options=False, show_hints=False):
    """Draw the Stimulus configuration content area (identical across modes)."""
    filled_rect(c, mx, content_top, mw, content_bottom - content_top, fill=BG)

    py = content_top + 12
    text_at(c, mx + 16, py + 12, "Stimulus", size=16, color=TEXT, font="Helvetica-Bold")

    # Modality badges
    bx = mx + 100
    badge(c, bx, py + 4, "TR", fill=ACCENT, text_color=BLACK, font_size=7, h=14)
    badge(c, bx + 32, py + 4, "IR", fill=SURFACE3, text_color=TEXT_DIM, font_size=7, h=14)

    py += 36

    # Hint bar (Guided mode only)
    if show_hints:
        filled_rect(c, mx + 12, py, mw - 24, 28, fill=HINT_BG, stroke=ACCENT_DIM, radius=4)
        text_at(c, mx + 20, py + 8, "\u2139", size=12, color=ACCENT, font="Helvetica-Bold")
        text_at(c, mx + 38, py + 16, "Set your bias source and modulation parameters. "
                "The preflight check will verify compatibility before acquisition.",
                size=8, color=ACCENT)
        py += 36

    hline(c, mx + 12, mx + mw - 12, py)
    py += 10

    # ── PRIMARY CONTROLS ──────────────────────────────────────────────
    lx = mx + 16
    lw = mw * 0.52 if show_more_options else mw - 32

    # Bias Source
    text_at(c, lx, py + 10, "Bias Source", size=10, color=TEXT, font="Helvetica-Bold")
    py += 18
    dropdown(c, lx, py, 200, 22, "Keithley 2400")
    py += 32

    # Enable
    text_at(c, lx, py + 10, "Output Enable", size=10, color=TEXT, font="Helvetica-Bold")
    py += 18
    # Toggle switch
    tw, th = 40, 20
    filled_rect(c, lx, py, tw, th, fill=ACCENT, radius=10)
    c.setFillColor(WHITE)
    c.circle(lx + tw - 10, Y(py + th / 2), 7, stroke=0, fill=1)
    text_at(c, lx + tw + 8, py + 12, "ON", size=9, color=ACCENT, font="Helvetica-Bold")
    py += 30

    # Voltage
    text_at(c, lx, py + 10, "Voltage", size=10, color=TEXT, font="Helvetica-Bold")
    py += 18
    spinbox(c, lx, py, 120, 22, "3.3", suffix=" V")
    py += 32

    # Current Compliance
    text_at(c, lx, py + 10, "Current Compliance", size=10, color=TEXT, font="Helvetica-Bold")
    py += 18
    spinbox(c, lx, py, 120, 22, "100", suffix=" mA")
    py += 32

    # FPGA Modulation
    text_at(c, lx, py + 10, "Modulation", size=10, color=TEXT, font="Helvetica-Bold")
    py += 18
    dropdown(c, lx, py, 200, 22, "Square Wave")
    py += 30

    # Frequency
    text_at(c, lx, py + 10, "Frequency", size=10, color=TEXT, font="Helvetica-Bold")
    py += 18
    spinbox(c, lx, py, 120, 22, "10", suffix=" Hz")
    text_at(c, lx + 130, py + 12, "Lock-in reference", size=8, color=TEXT_DIM)
    py += 32

    # Duty Cycle
    text_at(c, lx, py + 10, "Duty Cycle", size=10, color=TEXT, font="Helvetica-Bold")
    py += 18
    slider_bar(c, lx, py + 4, 200, pos=0.5)
    text_at(c, lx + 210, py + 10, "50%", size=9, color=TEXT, font="Helvetica-Bold")
    py += 26

    if not show_more_options:
        # Show the collapsed "More Options" toggle
        py += 10
        h = 24
        filled_rect(c, lx, py, lw - 16, h, fill=SURFACE2, stroke=BORDER, radius=4)
        text_at(c, lx + (lw - 16) / 2, py + h / 2 + 1,
                "\u25b6  More Options", size=9, color=ACCENT,
                font="Helvetica-Bold", anchor="center")

    # ── MORE OPTIONS (right column) ───────────────────────────────────
    if show_more_options:
        divider_x = mx + mw * 0.54
        rx = divider_x + 16
        rw = mw - (divider_x - mx) - 32

        # Vertical divider
        vline(c, divider_x, content_top + 50, content_bottom - 20, color=ACCENT_DIM, width=1)
        # "More Options" label on divider
        filled_rect(c, divider_x - 36, content_top + 54, 72, 16, fill=BG)
        text_at(c, divider_x, content_top + 64, "More Options",
                size=7, color=ACCENT, font="Helvetica-Bold", anchor="center")

        ry = content_top + 80

        # Output Port
        text_at(c, rx, ry + 10, "Output Port", size=9, color=TEXT, font="Helvetica-Bold")
        ry += 16
        dropdown(c, rx, ry, 160, 20, "Front Panel")
        ry += 28

        # Waveform Shape
        text_at(c, rx, ry + 10, "Waveform Shape", size=9, color=TEXT, font="Helvetica-Bold")
        ry += 16
        for i, wf in enumerate(["Square", "Sine", "Triangle", "Sawtooth"]):
            bx = rx + i * 60
            sel = (i == 0)
            if sel:
                filled_rect(c, bx, ry, 54, 20, fill=ACCENT_DIM, stroke=ACCENT, radius=3)
                text_at(c, bx + 27, ry + 12, wf, size=7, color=ACCENT,
                        font="Helvetica-Bold", anchor="center")
            else:
                filled_rect(c, bx, ry, 54, 20, fill=SURFACE2, stroke=BORDER, radius=3)
                text_at(c, bx + 27, ry + 12, wf, size=7, color=TEXT_DIM, anchor="center")
        ry += 28

        # IV Sweep
        text_at(c, rx, ry + 10, "IV Sweep", size=9, color=TEXT, font="Helvetica-Bold")
        ry += 16
        checkbox(c, rx, ry, "Enable voltage sweep", checked=False, size=9)
        ry += 20
        text_at(c, rx, ry + 10, "Start V", size=8, color=TEXT_DIM)
        spinbox(c, rx + 50, ry + 2, 80, 18, "0.0", suffix=" V")
        ry += 22
        text_at(c, rx, ry + 10, "End V", size=8, color=TEXT_DIM)
        spinbox(c, rx + 50, ry + 2, 80, 18, "5.0", suffix=" V")
        ry += 22
        text_at(c, rx, ry + 10, "Steps", size=8, color=TEXT_DIM)
        spinbox(c, rx + 50, ry + 2, 80, 18, "25")
        ry += 28

        # Soft Start
        text_at(c, rx, ry + 10, "Soft Start", size=9, color=TEXT, font="Helvetica-Bold")
        ry += 16
        checkbox(c, rx, ry, "Ramp output voltage on enable", checked=True, size=9)
        ry += 20
        text_at(c, rx, ry + 10, "Ramp time", size=8, color=TEXT_DIM)
        spinbox(c, rx + 70, ry + 2, 80, 18, "500", suffix=" ms")
        ry += 28

        # Protection
        text_at(c, rx, ry + 10, "Protection", size=9, color=TEXT, font="Helvetica-Bold")
        ry += 16
        checkbox(c, rx, ry, "Over-voltage protection", checked=True, size=9)
        ry += 20
        checkbox(c, rx, ry, "Over-current protection", checked=True, size=9)


# ══════════════════════════════════════════════════════════════════════
#  PAGE 1  —  GUIDED MODE
# ══════════════════════════════════════════════════════════════════════
filled_rect(c, 0, 0, W, H, fill=BG)
hdr_h = draw_header(c)
status_h = draw_status_bar(c)
ct = hdr_h
cb = H - status_h

# ── Sidebar ───────────────────────────────────────────────────────────
sb_w = 210
filled_rect(c, 0, ct, sb_w, cb - ct, fill=SURFACE)
vline(c, sb_w, ct, cb)

sy = ct + 8

# Mode selector
draw_mode_badge(c, 14, sy, "Guided", 0, ["Guided", "Standard", "Expert"])
sy += 34

# Phase 1 — CONFIGURATION (expanded, active)
filled_rect(c, 4, sy, sb_w - 8, 26, fill=SURFACE2, radius=4)
draw_active_dot(c, 18, sy + 13)
c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 9)
c.drawCentredString(18, Y(sy + 13) - 3, "1")
text_at(c, 32, sy + 14, "CONFIGURATION", size=9, color=ACCENT, font="Helvetica-Bold")

# Progress bar under phase header
sy += 28
filled_rect(c, 12, sy, sb_w - 24, 4, fill=SURFACE3, radius=2)
filled_rect(c, 12, sy, (sb_w - 24) * 0.2, 4, fill=GREEN, radius=2)
text_at(c, sb_w - 12, sy + 2, "1/5", size=7, color=TEXT_DIM, anchor="right")
sy += 12

# Sub-items for current phase
items_config = [
    ("Modality", "complete"),
    ("Stimulus", "active"),
    ("Timing", "future"),
    ("Temperature", "future"),
    ("Acquisition", "future"),
]
for label, state in items_config:
    ih = 28
    if state == "active":
        filled_rect(c, 8, sy, sb_w - 16, ih, fill=ACCENT_DIM, stroke=ACCENT, radius=4)
        filled_rect(c, 4, sy + 4, 3, ih - 8, fill=ACCENT, radius=2)
        text_at(c, 28, sy + ih / 2 + 1, label, size=10, color=WHITE, font="Helvetica-Bold")
    elif state == "complete":
        text_at(c, 16, sy + ih / 2 + 1, "\u2713", size=10, color=GREEN, font="Helvetica-Bold")
        text_at(c, 28, sy + ih / 2 + 1, label, size=10, color=TEXT)
    else:
        text_at(c, 16, sy + ih / 2 + 1, "\u25cb", size=8, color=TEXT_SUB)
        text_at(c, 28, sy + ih / 2 + 1, label, size=10, color=TEXT_DIM)
    sy += ih + 2

sy += 10
hline(c, 12, sb_w - 12, sy)
sy += 8

# Phase 2 — collapsed with just header
filled_rect(c, 4, sy, sb_w - 8, 26, fill=SURFACE2, radius=4)
draw_empty_circle(c, 18, sy + 13)
c.setFillColor(TEXT_SUB); c.setFont("Helvetica-Bold", 9)
c.drawCentredString(18, Y(sy + 13) - 3, "2")
text_at(c, 32, sy + 14, "IMAGE ACQUISITION", size=9, color=TEXT_SUB, font="Helvetica-Bold")
text_at(c, sb_w - 16, sy + 14, "\u25b6", size=8, color=TEXT_SUB, anchor="right")
sy += 32

# Phase 3 — collapsed
filled_rect(c, 4, sy, sb_w - 8, 26, fill=SURFACE2, radius=4)
draw_empty_circle(c, 18, sy + 13)
c.setFillColor(TEXT_SUB); c.setFont("Helvetica-Bold", 9)
c.drawCentredString(18, Y(sy + 13) - 3, "3")
text_at(c, 32, sy + 14, "MEASUREMENT", size=9, color=TEXT_SUB, font="Helvetica-Bold")
text_at(c, sb_w - 16, sy + 14, "\u25b6", size=8, color=TEXT_SUB, anchor="right")
sy += 32

hline(c, 12, sb_w - 12, sy)
sy += 8

# System — always visible
filled_rect(c, 4, sy, sb_w - 8, 26, fill=SURFACE2, radius=4)
text_at(c, 18, sy + 14, "\u2699", size=11, color=TEXT_SUB)
text_at(c, 32, sy + 14, "SYSTEM", size=9, color=TEXT_SUB, font="Helvetica-Bold")
text_at(c, sb_w - 16, sy + 14, "\u25b6", size=8, color=TEXT_SUB, anchor="right")

# ── Next Step suggestion at bottom of sidebar ─────────────────────────
ns_y = cb - 60
hline(c, 12, sb_w - 12, ns_y)
ns_y += 8
text_at(c, 14, ns_y + 10, "Next Step", size=8, color=TEXT_DIM, font="Helvetica-Bold")
ns_y += 16
filled_rect(c, 8, ns_y, sb_w - 16, 28, fill=ACCENT_DIM, stroke=ACCENT, radius=4)
text_at(c, sb_w / 2, ns_y + 16, "Configure Timing  \u2192", size=9,
        color=ACCENT, font="Helvetica-Bold", anchor="center")

# ── Content area ──────────────────────────────────────────────────────
mx = sb_w + 1
mw = W - sb_w - 1
draw_stimulus_content(c, mx, ct, cb, mw, show_more_options=False, show_hints=True)

# ── Page label ────────────────────────────────────────────────────────
text_at(c, W / 2, cb - 8, "GUIDED MODE  \u2014  Only current phase expanded  |  Hints visible  |  More Options collapsed",
        size=8, color=TEXT_SUB, font="Helvetica-Bold", anchor="center")

c.showPage()


# ══════════════════════════════════════════════════════════════════════
#  PAGE 2  —  STANDARD MODE
# ══════════════════════════════════════════════════════════════════════
filled_rect(c, 0, 0, W, H, fill=BG)
hdr_h = draw_header(c)
status_h = draw_status_bar(c)
ct = hdr_h
cb = H - status_h

# ── Sidebar ───────────────────────────────────────────────────────────
sb_w = 210
filled_rect(c, 0, ct, sb_w, cb - ct, fill=SURFACE)
vline(c, sb_w, ct, cb)

sy = ct + 8

# Mode selector
draw_mode_badge(c, 14, sy, "Standard", 1, ["Guided", "Standard", "Expert"])
sy += 34

# Phase 1 — CONFIGURATION (expanded, partially complete)
filled_rect(c, 4, sy, sb_w - 8, 26, fill=SURFACE2, radius=4)
draw_active_dot(c, 18, sy + 13)
c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 9)
c.drawCentredString(18, Y(sy + 13) - 3, "1")
text_at(c, 32, sy + 14, "CONFIGURATION", size=9, color=ACCENT, font="Helvetica-Bold")
sy += 28

items_config_std = [
    ("Modality", "complete"),
    ("Stimulus", "active"),
    ("Timing", "future"),
    ("Temperature", "future"),
    ("Acquisition", "future"),
]
for label, state in items_config_std:
    ih = 28
    if state == "active":
        filled_rect(c, 8, sy, sb_w - 16, ih, fill=ACCENT_DIM, stroke=ACCENT, radius=4)
        filled_rect(c, 4, sy + 4, 3, ih - 8, fill=ACCENT, radius=2)
        text_at(c, 28, sy + ih / 2 + 1, label, size=10, color=WHITE, font="Helvetica-Bold")
    elif state == "complete":
        text_at(c, 16, sy + ih / 2 + 1, "\u2713", size=10, color=GREEN, font="Helvetica-Bold")
        text_at(c, 28, sy + ih / 2 + 1, label, size=10, color=TEXT)
    else:
        text_at(c, 28, sy + ih / 2 + 1, label, size=10, color=TEXT_DIM)
    sy += ih + 2

sy += 6

# Phase 2 — IMAGE ACQUISITION (expanded, all items visible)
filled_rect(c, 4, sy, sb_w - 8, 26, fill=SURFACE2, radius=4)
draw_empty_circle(c, 18, sy + 13)
c.setFillColor(TEXT_SUB); c.setFont("Helvetica-Bold", 9)
c.drawCentredString(18, Y(sy + 13) - 3, "2")
text_at(c, 32, sy + 14, "IMAGE ACQUISITION", size=9, color=TEXT_DIM, font="Helvetica-Bold")
sy += 28

for label in ["Live View", "Focus & Stage", "Signal Check"]:
    ih = 28
    text_at(c, 28, sy + ih / 2 + 1, label, size=10, color=TEXT_DIM)
    sy += ih + 2

sy += 6

# Phase 3 — MEASUREMENT & ANALYSIS (expanded)
filled_rect(c, 4, sy, sb_w - 8, 26, fill=SURFACE2, radius=4)
draw_empty_circle(c, 18, sy + 13)
c.setFillColor(TEXT_SUB); c.setFont("Helvetica-Bold", 9)
c.drawCentredString(18, Y(sy + 13) - 3, "3")
text_at(c, 32, sy + 14, "MEASUREMENT", size=9, color=TEXT_DIM, font="Helvetica-Bold")
sy += 28

for label in ["Capture", "Calibration", "Sessions", "Emissivity"]:
    ih = 28
    text_at(c, 28, sy + ih / 2 + 1, label, size=10, color=TEXT_DIM)
    sy += ih + 2

sy += 6
hline(c, 12, sb_w - 12, sy)
sy += 8

# System
filled_rect(c, 4, sy, sb_w - 8, 26, fill=SURFACE2, radius=4)
text_at(c, 18, sy + 14, "\u2699", size=11, color=TEXT_SUB)
text_at(c, 32, sy + 14, "SYSTEM", size=9, color=TEXT_SUB, font="Helvetica-Bold")
sy += 28

for label in ["Camera", "Stage", "Prober", "Settings"]:
    text_at(c, 28, sy + 15, label, size=10, color=TEXT_DIM)
    sy += 28

# ── Content area ──────────────────────────────────────────────────────
mx = sb_w + 1
mw = W - sb_w - 1
draw_stimulus_content(c, mx, ct, cb, mw, show_more_options=False, show_hints=False)

# ── Page label ────────────────────────────────────────────────────────
text_at(c, W / 2, cb - 8, "STANDARD MODE  \u2014  All phases expanded  |  No hints  |  More Options collapsed by default",
        size=8, color=TEXT_SUB, font="Helvetica-Bold", anchor="center")

c.showPage()


# ══════════════════════════════════════════════════════════════════════
#  PAGE 3  —  EXPERT MODE
# ══════════════════════════════════════════════════════════════════════
filled_rect(c, 0, 0, W, H, fill=BG)
hdr_h = draw_header(c)
status_h = draw_status_bar(c)
ct = hdr_h
cb = H - status_h

# ── Sidebar (compact, flat) ───────────────────────────────────────────
sb_w = 170  # narrower sidebar for expert
filled_rect(c, 0, ct, sb_w, cb - ct, fill=SURFACE)
vline(c, sb_w, ct, cb)

sy = ct + 8

# Mode selector (narrower)
draw_mode_badge(c, 8, sy, "Expert", 2, ["G", "S", "Expert"])
sy += 30

# Flat list — no phase headers, just items with compact spacing
expert_items = [
    ("Modality", "complete"),
    ("Stimulus", "active"),
    ("Timing", "future"),
    ("Temperature", "future"),
    ("Acquisition", "future"),
    (None, "divider"),  # thin divider
    ("Live View", "future"),
    ("Focus & Stage", "future"),
    ("Signal Check", "future"),
    (None, "divider"),
    ("Capture", "future"),
    ("Calibration", "future"),
    ("Sessions", "future"),
    ("Emissivity", "future"),
    (None, "divider"),
    ("Camera", "system"),
    ("Stage", "system"),
    ("Prober", "system"),
    ("Settings", "system"),
]

for label, state in expert_items:
    if state == "divider":
        sy += 2
        hline(c, 8, sb_w - 8, sy)
        sy += 4
        continue

    ih = 24  # compact height
    if state == "active":
        filled_rect(c, 6, sy, sb_w - 12, ih, fill=ACCENT_DIM, stroke=ACCENT, radius=3)
        filled_rect(c, 3, sy + 3, 2, ih - 6, fill=ACCENT, radius=1)
        text_at(c, 14, sy + ih / 2 + 1, label, size=9, color=WHITE, font="Helvetica-Bold")
        # Keyboard shortcut hint
        text_at(c, sb_w - 14, sy + ih / 2 + 1, "\u23182", size=7, color=ACCENT_DIM, anchor="right")
    elif state == "complete":
        text_at(c, 10, sy + ih / 2 + 1, "\u2713", size=8, color=GREEN)
        text_at(c, 22, sy + ih / 2 + 1, label, size=9, color=TEXT)
        text_at(c, sb_w - 14, sy + ih / 2 + 1, "\u23181", size=7, color=TEXT_SUB, anchor="right")
    elif state == "system":
        text_at(c, 14, sy + ih / 2 + 1, label, size=9, color=TEXT_SUB)
    else:
        text_at(c, 14, sy + ih / 2 + 1, label, size=9, color=TEXT_DIM)
    sy += ih + 1

# Keyboard shortcut legend at bottom
sy = cb - 44
hline(c, 8, sb_w - 8, sy)
sy += 6
text_at(c, 10, sy + 10, "Shortcuts", size=7, color=TEXT_SUB, font="Helvetica-Bold")
sy += 14
text_at(c, 10, sy + 10, "\u2318 1-9  Navigate", size=7, color=TEXT_SUB)
sy += 12
text_at(c, 10, sy + 10, "\u2318 M   More Options", size=7, color=TEXT_SUB)

# ── Content area (More Options expanded by default) ───────────────────
mx = sb_w + 1
mw = W - sb_w - 1
draw_stimulus_content(c, mx, ct, cb, mw, show_more_options=True, show_hints=False)

# ── Page label ────────────────────────────────────────────────────────
text_at(c, (sb_w + W) / 2, cb - 8,
        "EXPERT MODE  \u2014  Flat compact list  |  No phase headers  |  More Options expanded by default  |  Keyboard shortcuts",
        size=8, color=TEXT_SUB, font="Helvetica-Bold", anchor="center")

c.showPage()


# ══════════════════════════════════════════════════════════════════════
c.save()
print(f"Wrote 3 pages to {OUT}")
