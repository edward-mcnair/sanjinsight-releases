#!/usr/bin/env python3
"""Option B — Phase-Aware Sidebar wireframe."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.colors import Color
from _wireframe_common import *

OUT = os.path.join(os.path.dirname(__file__), "option-b-phase-sidebar.pdf")

c = Canvas(OUT, pagesize=(W, H))
c.setTitle("Option B — Phase-Aware Sidebar")
c.setAuthor("SanjINSIGHT UX")

# ── Background ────────────────────────────────────────────────────────
filled_rect(c, 0, 0, W, H, fill=BG)

# ── Header ────────────────────────────────────────────────────────────
hdr_h = draw_header(c)

# ── Status bar ────────────────────────────────────────────────────────
status_h = draw_status_bar(c)
content_top = hdr_h
content_bottom = H - status_h
content_h = content_bottom - content_top

# ── Left sidebar ─────────────────────────────────────────────────────
sidebar_w = 210
filled_rect(c, 0, content_top, sidebar_w, content_h, fill=SURFACE)
vline(c, sidebar_w, content_top, content_bottom)

# Phase groups
phases = [
    {
        "number": "1",
        "title": "CONFIGURE",
        "status": "complete",   # checkmark
        "items": [
            ("Modality", False),
            ("Stimulus", False),
            ("Timing", False),
            ("Temperature", False),
            ("Settings", False),
        ],
    },
    {
        "number": "2",
        "title": "ALIGN & VERIFY",
        "status": "current",    # filled dot
        "items": [
            ("Live View", True),      # selected
            ("Focus & Stage", False),
            ("Signal Check", False),
        ],
    },
    {
        "number": "3",
        "title": "MEASURE & ANALYZE",
        "status": "future",     # empty circle
        "items": [
            ("Capture", False),
            ("Calibration", False),
            ("Analysis", False),
            ("Sessions", False),
            ("Library", False),
        ],
    },
]

sy = content_top + 12
for phase in phases:
    # Phase header background
    filled_rect(c, 4, sy, sidebar_w - 8, 28, fill=SURFACE2, radius=4)

    # Status indicator
    indicator_x = 18
    indicator_cy = sy + 14
    if phase["status"] == "complete":
        # Green checkmark circle
        c.setFillColor(GREEN)
        c.circle(indicator_x, Y(indicator_cy), 8, stroke=0, fill=1)
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(indicator_x, Y(indicator_cy) - 3.5, "^")
        # Actually draw a simple check mark
        c.setStrokeColor(WHITE)
        c.setLineWidth(1.5)
        cx, cy_r = indicator_x, Y(indicator_cy)
        c.line(cx - 4, cy_r - 1, cx - 1, cy_r - 4)
        c.line(cx - 1, cy_r - 4, cx + 4, cy_r + 3)
    elif phase["status"] == "current":
        # Teal filled dot
        c.setFillColor(ACCENT)
        c.circle(indicator_x, Y(indicator_cy), 8, stroke=0, fill=1)
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(indicator_x, Y(indicator_cy) - 3, phase["number"])
    else:
        # Empty circle
        c.setStrokeColor(TEXT_SUB)
        c.setLineWidth(1.5)
        c.setFillColor(SURFACE2)
        c.circle(indicator_x, Y(indicator_cy), 8, stroke=1, fill=1)
        c.setFillColor(TEXT_SUB)
        c.setFont("Helvetica", 9)
        c.drawCentredString(indicator_x, Y(indicator_cy) - 3, phase["number"])

    # Phase title
    title_color = ACCENT if phase["status"] == "current" else (
        TEXT if phase["status"] == "complete" else TEXT_DIM)
    text_at(c, 32, indicator_cy + 1, phase["title"], size=10,
            color=title_color, font="Helvetica-Bold")

    sy += 32

    # Nav items
    for item_label, selected in phase["items"]:
        item_h = 30
        if selected:
            # Selected item background
            filled_rect(c, 8, sy, sidebar_w - 16, item_h,
                        fill=ACCENT_DIM, stroke=ACCENT, radius=4)
            # Active indicator bar
            filled_rect(c, 4, sy + 4, 3, item_h - 8, fill=ACCENT, radius=2)
            text_at(c, 28, sy + item_h / 2 + 1, item_label,
                    size=10, color=WHITE, font="Helvetica-Bold")
        else:
            future = phase["status"] == "future"
            text_at(c, 28, sy + item_h / 2 + 1, item_label,
                    size=10, color=TEXT_DIM if future else TEXT)

        sy += item_h + 2

    sy += 8  # gap between phases

# ── Main content: Live View ──────────────────────────────────────────
main_x = sidebar_w + 1
inspector_w = 260
main_w = W - sidebar_w - inspector_w
main_h = content_h

# Live preview area
filled_rect(c, main_x, content_top, main_w, main_h,
            fill=Color(0.08, 0.08, 0.09))

prev_m = 16
prev_x = main_x + prev_m
prev_top = content_top + prev_m
prev_w = main_w - 2 * prev_m
prev_h = main_h - 2 * prev_m

filled_rect(c, prev_x, prev_top, prev_w, prev_h,
            fill=Color(0.12, 0.14, 0.13), stroke=BORDER, radius=4)

text_at(c, prev_x + prev_w / 2, prev_top + 20,
        "Live Camera Preview", size=14, color=TEXT_DIM,
        font="Helvetica-Bold", anchor="center")

# Simulated noise
import random
random.seed(42)
c.setStrokeColor(Color(0.15, 0.18, 0.16))
c.setLineWidth(0.3)
for _ in range(50):
    lx = prev_x + random.randint(10, prev_w - 10)
    ly_top = prev_top + random.randint(40, prev_h - 10)
    lw = random.randint(20, 70)
    c.line(lx, Y(ly_top), lx + lw, Y(ly_top))

crosshair(c, prev_x + prev_w / 2, prev_top + prev_h / 2, size=35)

# Camera info badge
filled_rect(c, prev_x + 8, prev_top + prev_h - 28, 200, 20,
            fill=Color(0, 0, 0, 0.5), radius=3)
text_at(c, prev_x + 14, prev_top + prev_h - 16,
        "Basler acA1920-155um [TR]  |  30 fps  |  5.0 ms",
        size=7, color=TEXT_DIM)

# Mode badge (top right of preview)
badge_w = 140
filled_rect(c, prev_x + prev_w - badge_w - 8, prev_top + 8,
            badge_w, 22, fill=Color(0, 0, 0, 0.5), radius=3)
text_at(c, prev_x + prev_w - badge_w / 2 - 8, prev_top + 21,
        "THERMOREFLECTANCE", size=8, color=ACCENT,
        font="Helvetica-Bold", anchor="center")

# ── Right inspector panel ────────────────────────────────────────────
insp_x = W - inspector_w
vline(c, insp_x, content_top, content_bottom)
filled_rect(c, insp_x, content_top, inspector_w, content_h, fill=SURFACE)

# Inspector header
filled_rect(c, insp_x, content_top, inspector_w, 34, fill=SURFACE2)
text_at(c, insp_x + 12, content_top + 20, "Inspector",
        size=11, color=TEXT, font="Helvetica-Bold")
# Collapse button
text_at(c, insp_x + inspector_w - 16, content_top + 20, ">",
        size=12, color=TEXT_DIM, anchor="right")
hline(c, insp_x, insp_x + inspector_w, content_top + 34)

# Context-relevant tools for Live View
iy = content_top + 44
tools = [
    ("Quick Actions", [
        ("btn", "Autofocus"),
        ("btn", "Optimize Throughput"),
        ("btn", "Run FFC"),
    ]),
    ("Image Quality", [
        ("stat", "Focus Score", "82 / 100"),
        ("stat", "Mean Intensity", "67%"),
        ("stat", "Saturation", "0 px"),
        ("stat", "Noise Floor", "12.4 DN"),
    ]),
    ("Active Hardware", [
        ("hw", "TEC-1089", "25.0 C  Stable", True),
        ("hw", "FPGA", "1.0 kHz  50%", True),
        ("hw", "Bias", "0.000 V", True),
        ("hw", "Stage", "1240 / 890 / 0", True),
    ]),
]

for section_title, items in tools:
    text_at(c, insp_x + 12, iy + 12, section_title,
            size=9, color=TEXT_DIM, font="Helvetica-Bold")
    iy += 20
    for item in items:
        if item[0] == "btn":
            button(c, insp_x + 12, iy, inspector_w - 24, 24, item[1],
                   fill=SURFACE3, text_color=TEXT, border=BORDER,
                   font_size=8, radius=3)
            iy += 28
        elif item[0] == "stat":
            text_at(c, insp_x + 12, iy + 10, item[1],
                    size=8, color=TEXT_DIM)
            text_at(c, insp_x + inspector_w - 12, iy + 10, item[2],
                    size=9, color=TEXT, font="Helvetica-Bold",
                    anchor="right")
            iy += 18
        elif item[0] == "hw":
            _, name, detail, ok = item
            status_dot(c, insp_x + 18, iy + 8, GREEN if ok else ERROR, r=3)
            text_at(c, insp_x + 28, iy + 10, name, size=8, color=TEXT)
            text_at(c, insp_x + inspector_w - 12, iy + 10, detail,
                    size=8, color=TEXT_DIM, anchor="right")
            iy += 18
    iy += 10
    hline(c, insp_x + 10, insp_x + inspector_w - 10, iy)
    iy += 10

# ── Title annotation ──────────────────────────────────────────────────
text_at(c, main_x + main_w / 2, content_bottom - 10,
        "OPTION B  —  Phase-Aware Sidebar", size=8, color=TEXT_SUB,
        font="Helvetica-Bold", anchor="center")

c.save()
print(f"Wrote {OUT}")
