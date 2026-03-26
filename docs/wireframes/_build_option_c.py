#!/usr/bin/env python3
"""Option C — Guided Stepper wireframe."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.colors import Color
from _wireframe_common import *

OUT = os.path.join(os.path.dirname(__file__), "option-c-guided-workflow.pdf")

c = Canvas(OUT, pagesize=(W, H))
c.setTitle("Option C — Guided Stepper Workflow")
c.setAuthor("SanjINSIGHT UX")

# ── Background ────────────────────────────────────────────────────────
filled_rect(c, 0, 0, W, H, fill=BG)

# ── Header ────────────────────────────────────────────────────────────
hdr_h = draw_header(c)

# ── Stepper / progress bar ───────────────────────────────────────────
step_h = 50
step_top = hdr_h
filled_rect(c, 0, step_top, W, step_h, fill=SURFACE)
hline(c, 0, W, step_top + step_h)

steps = [
    ("Configure", "complete"),
    ("Align & Verify", "current"),
    ("Measure & Analyze", "future"),
]

# Layout: three steps evenly spaced with connecting lines
step_cx = [200, 600, 1000]
step_cy = step_top + step_h // 2

# Connecting lines
for i in range(len(steps) - 1):
    x1 = step_cx[i] + 14
    x2 = step_cx[i + 1] - 14
    line_y = step_cy
    color = ACCENT if steps[i][1] == "complete" else TEXT_SUB
    c.setStrokeColor(color)
    c.setLineWidth(2)
    c.line(x1, Y(line_y), x2, Y(line_y))

# Step circles and labels
for i, (label, status) in enumerate(steps):
    cx = step_cx[i]
    cy = step_cy

    if status == "complete":
        c.setFillColor(GREEN)
        c.circle(cx, Y(cy), 12, stroke=0, fill=1)
        # Checkmark
        c.setStrokeColor(WHITE)
        c.setLineWidth(2)
        rx, ry = cx, Y(cy)
        c.line(rx - 5, ry - 1, rx - 1, ry - 5)
        c.line(rx - 1, ry - 5, rx + 5, ry + 4)
    elif status == "current":
        # Outer ring
        c.setStrokeColor(ACCENT)
        c.setLineWidth(2.5)
        c.setFillColor(BG)
        c.circle(cx, Y(cy), 12, stroke=1, fill=1)
        # Inner dot
        c.setFillColor(ACCENT)
        c.circle(cx, Y(cy), 6, stroke=0, fill=1)
    else:
        c.setStrokeColor(TEXT_SUB)
        c.setLineWidth(1.5)
        c.setFillColor(SURFACE)
        c.circle(cx, Y(cy), 12, stroke=1, fill=1)
        c.setFillColor(TEXT_SUB)
        c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(cx, Y(cy) - 4, "3")

    # Label
    lbl_color = GREEN if status == "complete" else (
        ACCENT if status == "current" else TEXT_SUB)
    font = "Helvetica-Bold" if status == "current" else "Helvetica"
    text_at(c, cx, cy + 20, label, size=10, color=lbl_color,
            font=font, anchor="center")

    # Sub-label
    if status == "complete":
        text_at(c, cx, cy - 18, "Complete", size=7,
                color=GREEN, anchor="center")
    elif status == "current":
        text_at(c, cx, cy - 18, "In Progress", size=7,
                color=ACCENT, anchor="center")

# ── Contextual toolbar ───────────────────────────────────────────────
tb_h = 38
tb_top = step_top + step_h
filled_rect(c, 0, tb_top, W, tb_h, fill=SURFACE2)
hline(c, 0, W, tb_top + tb_h, color=BORDER)

# Toolbar buttons
tb_buttons = [
    ("Autofocus", False),
    ("Optimize", False),
    ("Navigate", False),
    ("Verify Signal", False),
]
tbx = 16
for label, active in tb_buttons:
    bw = len(label) * 8 + 24
    button(c, tbx, tb_top + 6, bw, 26, label,
           fill=SURFACE3, text_color=TEXT, border=BORDER,
           font_size=9, radius=4)
    tbx += bw + 8

# "Next Phase" button (right-aligned, accent)
next_w = 130
button(c, W - 16 - next_w, tb_top + 6, next_w, 26,
       "Next Phase  -->",
       fill=ACCENT_DIM, text_color=WHITE, border=ACCENT,
       font_size=9, radius=4)

# Phase label in toolbar
text_at(c, W - 16 - next_w - 120, tb_top + 22,
        "Phase 2 of 3", size=8, color=TEXT_DIM, anchor="right")

content_top = tb_top + tb_h
status_h = draw_status_bar(c)
content_bottom = H - status_h
content_h = content_bottom - content_top

# ── Main content: split view ─────────────────────────────────────────
checklist_w = 340
live_w = W - checklist_w

# Left — Live camera view
filled_rect(c, 0, content_top, live_w, content_h,
            fill=Color(0.08, 0.08, 0.09))

prev_m = 14
prev_x = prev_m
prev_top_y = content_top + prev_m
prev_w = live_w - 2 * prev_m
prev_h = content_h - 2 * prev_m

filled_rect(c, prev_x, prev_top_y, prev_w, prev_h,
            fill=Color(0.12, 0.14, 0.13), stroke=BORDER, radius=4)

text_at(c, prev_x + prev_w / 2, prev_top_y + 20,
        "Live Camera Preview", size=14, color=TEXT_DIM,
        font="Helvetica-Bold", anchor="center")

# Noise
import random
random.seed(42)
c.setStrokeColor(Color(0.15, 0.18, 0.16))
c.setLineWidth(0.3)
for _ in range(50):
    lx = prev_x + random.randint(10, prev_w - 10)
    ly = prev_top_y + random.randint(40, prev_h - 10)
    lw = random.randint(20, 70)
    c.line(lx, Y(ly), lx + lw, Y(ly))

crosshair(c, prev_x + prev_w / 2, prev_top_y + prev_h / 2, size=35)

# Camera badge
filled_rect(c, prev_x + 8, prev_top_y + prev_h - 28, 200, 20,
            fill=Color(0, 0, 0, 0.5), radius=3)
text_at(c, prev_x + 14, prev_top_y + prev_h - 16,
        "Basler acA1920-155um [TR]  |  30 fps  |  5.0 ms",
        size=7, color=TEXT_DIM)

# ── Right — Guided checklist panel ───────────────────────────────────
cl_x = live_w
vline(c, cl_x, content_top, content_bottom)
filled_rect(c, cl_x, content_top, checklist_w, content_h, fill=SURFACE)

# Panel header
filled_rect(c, cl_x, content_top, checklist_w, 40, fill=SURFACE2)
text_at(c, cl_x + 14, content_top + 24, "Alignment Checklist",
        size=12, color=TEXT, font="Helvetica-Bold")

# Progress indicator in header
progress_text = "2 of 4 complete"
text_at(c, cl_x + checklist_w - 14, content_top + 24, progress_text,
        size=9, color=TEXT_DIM, anchor="right")

# Progress bar
hline(c, cl_x, cl_x + checklist_w, content_top + 40, color=BORDER)
prog_bar_y = content_top + 40
filled_rect(c, cl_x, prog_bar_y, checklist_w, 4, fill=SURFACE3)
filled_rect(c, cl_x, prog_bar_y, int(checklist_w * 0.5), 4, fill=ACCENT)

# Checklist items
checklist = [
    {
        "label": "Device Positioned",
        "status": "complete",
        "detail": "X 1240  Y 890  Z 0 um",
        "expanded": False,
    },
    {
        "label": "Focus Achieved",
        "status": "complete",
        "detail": "Quality: 87 / 100",
        "expanded": False,
    },
    {
        "label": "Exposure Verified",
        "status": "current",
        "detail": "Mean intensity: 67%  |  0 saturated pixels",
        "expanded": True,
    },
    {
        "label": "Signal Confirmed",
        "status": "pending",
        "detail": "Run a single acquisition to verify thermal signal",
        "expanded": False,
    },
]

cy = content_top + 52
for item in checklist:
    item_h = 80 if item["expanded"] else 44

    # Item background
    if item["status"] == "current":
        filled_rect(c, cl_x + 6, cy, checklist_w - 12, item_h,
                    fill=Color(0.00, 0.25, 0.20, 0.3),
                    stroke=ACCENT, radius=6)
    else:
        filled_rect(c, cl_x + 6, cy, checklist_w - 12, item_h,
                    fill=SURFACE2, stroke=BORDER, radius=6)

    # Status icon
    icon_x = cl_x + 24
    icon_cy = cy + 22
    if item["status"] == "complete":
        c.setFillColor(GREEN)
        c.circle(icon_x, Y(icon_cy), 9, stroke=0, fill=1)
        c.setStrokeColor(WHITE)
        c.setLineWidth(1.5)
        rx, ry = icon_x, Y(icon_cy)
        c.line(rx - 4, ry - 0.5, rx - 1, ry - 3.5)
        c.line(rx - 1, ry - 3.5, rx + 4, ry + 3)
    elif item["status"] == "current":
        c.setStrokeColor(ACCENT)
        c.setLineWidth(2)
        c.setFillColor(BG)
        c.circle(icon_x, Y(icon_cy), 9, stroke=1, fill=1)
        c.setFillColor(ACCENT)
        c.circle(icon_x, Y(icon_cy), 4, stroke=0, fill=1)
    else:
        c.setStrokeColor(TEXT_SUB)
        c.setLineWidth(1.5)
        c.setFillColor(SURFACE2)
        c.circle(icon_x, Y(icon_cy), 9, stroke=1, fill=1)

    # Label
    lbl_color = TEXT if item["status"] != "pending" else TEXT_DIM
    text_at(c, cl_x + 42, icon_cy + 1, item["label"],
            size=10, color=lbl_color, font="Helvetica-Bold")

    # Detail text
    detail_color = ACCENT if item["status"] == "current" else TEXT_DIM
    text_at(c, cl_x + 42, icon_cy + 16, item["detail"],
            size=8, color=detail_color)

    # Expanded content for current item
    if item["expanded"]:
        ey = cy + 50
        # Exposure histogram mini
        filled_rect(c, cl_x + 20, ey, checklist_w - 40, 22,
                    fill=SURFACE, stroke=BORDER, radius=3)
        c.setFillColor(ACCENT_DIM)
        bar_count = 24
        bw = (checklist_w - 48) / bar_count
        random.seed(13)
        for b in range(bar_count):
            bh = random.randint(2, 18)
            bx = cl_x + 24 + b * bw
            by = Y(ey + 20)
            c.rect(bx, by, bw - 1, bh, stroke=0, fill=1)

    cy += item_h + 6

# ── Action area at bottom of checklist ───────────────────────────────
action_y = content_bottom - 70
hline(c, cl_x + 10, cl_x + checklist_w - 10, action_y)

# Guidance text
text_at(c, cl_x + 14, action_y + 18,
        "Complete all checks before proceeding to",
        size=8, color=TEXT_DIM)
text_at(c, cl_x + 14, action_y + 32,
        "measurement. Checks are non-destructive",
        size=8, color=TEXT_DIM)
text_at(c, cl_x + 14, action_y + 46,
        "and read-only — no settings are modified.",
        size=8, color=TEXT_DIM)

# "Verify Signal" prominent button
button(c, cl_x + 14, action_y + 56, checklist_w - 28, 30,
       "Verify Thermal Signal",
       fill=ACCENT_DIM, text_color=WHITE, border=ACCENT,
       font_size=11, radius=5)

# ── Title annotation ──────────────────────────────────────────────────
text_at(c, live_w / 2, content_bottom - 10,
        "OPTION C  —  Guided Stepper Workflow", size=8,
        color=TEXT_SUB, font="Helvetica-Bold", anchor="center")

c.save()
print(f"Wrote {OUT}")
