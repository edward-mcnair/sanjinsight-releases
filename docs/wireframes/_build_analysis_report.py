#!/usr/bin/env python3
"""Analysis & Report wireframe — analysis view + report generation dialog."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.colors import Color
from _wireframe_common import *

OUT = os.path.join(os.path.dirname(__file__), "analysis-report.pdf")
c = Canvas(OUT, pagesize=(W, H))
c.setTitle("Analysis & Report Generation")

# ══════════════════════════════════════════════════════════════════════
# PAGE 1 — Analysis View
# ══════════════════════════════════════════════════════════════════════
filled_rect(c, 0, 0, W, H, fill=BG)
hdr_h = draw_header(c)
status_h = draw_status_bar(c)
content_top = hdr_h
content_bottom = H - status_h

# Sidebar
sb_w = 210
filled_rect(c, 0, content_top, sb_w, content_bottom - content_top, fill=SURFACE)
vline(c, sb_w, content_top, content_bottom)

sy = content_top + 10
# Phase headers (abbreviated)
for phase_label, phase_status in [("CONFIGURATION", "done"), ("IMAGE ACQUISITION", "done")]:
    filled_rect(c, 4, sy, sb_w - 8, 26, fill=SURFACE2, radius=4)
    c.setFillColor(GREEN)
    c.circle(18, Y(sy + 13), 8, stroke=0, fill=1)
    c.setStrokeColor(WHITE); c.setLineWidth(1.5)
    rx, ry_c = 18, Y(sy + 13)
    c.line(rx - 4, ry_c - 1, rx - 1, ry_c - 4)
    c.line(rx - 1, ry_c - 4, rx + 4, ry_c + 3)
    text_at(c, 32, sy + 14, phase_label, size=9, color=TEXT, font="Helvetica-Bold")
    sy += 30

# Phase 3 active
filled_rect(c, 4, sy, sb_w - 8, 26, fill=SURFACE2, radius=4)
c.setFillColor(ACCENT)
c.circle(18, Y(sy + 13), 8, stroke=0, fill=1)
c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 9)
c.drawCentredString(18, Y(sy + 13) - 3, "3")
text_at(c, 32, sy + 14, "MEASUREMENT & ANALYSIS", size=9, color=ACCENT, font="Helvetica-Bold")
sy += 28

nav_items = [("Measurement Plan", False), ("Capture", False), ("Calibration", False),
             ("Analysis", True), ("Sessions", False), ("Library", False)]
for label, sel in nav_items:
    ih = 28
    if sel:
        filled_rect(c, 8, sy, sb_w - 16, ih, fill=ACCENT_DIM, stroke=ACCENT, radius=4)
        filled_rect(c, 4, sy + 4, 3, ih - 8, fill=ACCENT, radius=2)
        text_at(c, 28, sy + ih / 2 + 1, label, size=10, color=WHITE, font="Helvetica-Bold")
    else:
        text_at(c, 28, sy + ih / 2 + 1, label, size=10, color=TEXT)
    sy += ih + 2

# ── Left column — Analysis Controls ──────────────────────────────────
ctrl_x = sb_w + 1
ctrl_w = 190
filled_rect(c, ctrl_x, content_top, ctrl_w, content_bottom - content_top, fill=SURFACE)
vline(c, ctrl_x + ctrl_w, content_top, content_bottom)

cy = content_top + 12
text_at(c, ctrl_x + 10, cy + 10, "Threshold Settings", size=10, color=TEXT, font="Helvetica-Bold")
cy += 22
text_at(c, ctrl_x + 10, cy + 10, "Temp threshold", size=8, color=TEXT_DIM)
spinbox(c, ctrl_x + 10, cy + 16, ctrl_w - 20, 22, "85.0", suffix=" \u00b0C")
cy += 42
text_at(c, ctrl_x + 10, cy + 10, "Min hotspot area", size=8, color=TEXT_DIM)
spinbox(c, ctrl_x + 10, cy + 16, ctrl_w - 20, 22, "25", suffix=" px")
cy += 48

text_at(c, ctrl_x + 10, cy + 10, "Verdict Rules", size=10, color=TEXT, font="Helvetica-Bold")
cy += 22
for color, label, threshold in [(GREEN, "PASS", "< 85 \u00b0C"), (WARNING, "WARNING", "85\u2013100 \u00b0C"), (ERROR, "FAIL", "> 100 \u00b0C")]:
    status_dot(c, ctrl_x + 18, cy + 8, color, r=4)
    text_at(c, ctrl_x + 28, cy + 10, label, size=8, color=color, font="Helvetica-Bold")
    text_at(c, ctrl_x + ctrl_w - 10, cy + 10, threshold, size=8, color=TEXT_DIM, anchor="right")
    cy += 20

cy += 10
button(c, ctrl_x + 10, cy, ctrl_w - 20, 30, "Run Analysis",
       fill=Color(0.0, 0.55, 0.30), text_color=WHITE,
       border=Color(0.0, 0.65, 0.35), font_size=10, radius=5)
cy += 40

# More Options toggle
filled_rect(c, ctrl_x + 10, cy, ctrl_w - 20, 24, fill=SURFACE2, stroke=BORDER, radius=4)
text_at(c, ctrl_x + ctrl_w / 2, cy + 13,
        "\u25bc  More Options", size=9, color=ACCENT,
        font="Helvetica-Bold", anchor="center")
cy += 32
text_at(c, ctrl_x + 14, cy + 8, "(Per-channel analysis,", size=7, color=TEXT_SUB)
text_at(c, ctrl_x + 14, cy + 18, " morphology, thresholds)", size=7, color=TEXT_SUB)

# ── Center column — Thermal Map ──────────────────────────────────────
map_x = ctrl_x + ctrl_w + 1
results_w = 250
map_w = rp_x = W - results_w
map_w = rp_x - map_x

import random
random.seed(7)

# Thermal map area
map_m = 12
map_left = map_x + map_m
map_top_y = content_top + map_m
map_right = map_x + map_w - map_m - 30  # leave room for colorbar
map_bot_y = content_bottom - 50

# Background
filled_rect(c, map_left, map_top_y, map_right - map_left, map_bot_y - map_top_y,
            fill=Color(0.05, 0.08, 0.10), stroke=BORDER, radius=4)

# Simulated thermal gradient — blue edges, warm center, red hotspot
# Base blue-green
for row in range(10):
    for col in range(14):
        bx = map_left + 4 + col * ((map_right - map_left - 8) // 14)
        by = map_top_y + 4 + row * ((map_bot_y - map_top_y - 8) // 10)
        bw = (map_right - map_left - 8) // 14
        bh = (map_bot_y - map_top_y - 8) // 10

        # Distance from center
        cx_r = 7.0
        cy_r = 5.0
        dist = ((col - cx_r) ** 2 + (row - cy_r) ** 2) ** 0.5
        max_dist = 8.0
        t = max(0, 1 - dist / max_dist) + random.uniform(-0.05, 0.05)
        t = max(0, min(1, t))

        # Color: blue → green → yellow → red
        if t < 0.33:
            r = 0.05
            g = 0.15 + t * 2 * 0.5
            b = 0.4 - t * 0.8
        elif t < 0.66:
            r = (t - 0.33) * 3 * 0.8
            g = 0.6
            b = 0.05
        else:
            r = 0.8 + (t - 0.66) * 0.6
            g = 0.6 - (t - 0.66) * 1.5
            b = 0.05

        filled_rect(c, bx, by, bw, bh, fill=Color(min(1, r), max(0, g), max(0, b)))

# Hotspot (bright red spot)
hs_x = map_left + int((map_right - map_left) * 0.6)
hs_y = map_top_y + int((map_bot_y - map_top_y) * 0.45)
for r_size in range(20, 0, -2):
    intensity = 1.0 - r_size / 25
    c.setFillColor(Color(1.0, intensity * 0.3, 0.05))
    c.circle(hs_x, Y(hs_y), r_size, stroke=0, fill=1)

# Crosshair on hotspot
crosshair(c, hs_x, hs_y, size=25)

# Verdict overlay badge
badge_w_v = 110
filled_rect(c, map_right - badge_w_v - 4, map_top_y + 4, badge_w_v, 24,
            fill=Color(0.4, 0.28, 0.0, 0.85), stroke=WARNING, radius=4)
text_at(c, map_right - badge_w_v / 2 - 4, map_top_y + 18, "WARNING",
        size=10, color=WARNING, font="Helvetica-Bold", anchor="center")

# Scale bar
sb_y = map_bot_y - 16
c.setStrokeColor(WHITE); c.setLineWidth(2)
c.line(map_left + 20, Y(sb_y), map_left + 80, Y(sb_y))
text_at(c, map_left + 50, sb_y + 12, "100 \u00b5m", size=7, color=WHITE, anchor="center")

# Color bar (vertical, right of map)
cb_x = map_right + 4
cb_top = map_top_y + 10
cb_h = map_bot_y - map_top_y - 40
for i in range(20):
    frac = i / 19
    # blue → green → yellow → red
    if frac < 0.33:
        r = 0.05; g = frac * 3 * 0.6; b = 0.5 - frac * 1.2
    elif frac < 0.66:
        r = (frac - 0.33) * 3; g = 0.6; b = 0.05
    else:
        r = 0.9; g = 0.6 - (frac - 0.66) * 1.8; b = 0.05
    sy_cb = cb_top + cb_h - (i + 1) * (cb_h / 20)
    filled_rect(c, cb_x, sy_cb, 14, cb_h / 20, fill=Color(min(1, r), max(0, g), max(0, b)))

# Tick labels
for temp, frac in [("25", 0.0), ("50", 0.25), ("75", 0.5), ("100", 0.75), ("110", 1.0)]:
    ty = cb_top + cb_h * (1 - frac)
    text_at(c, cb_x + 18, ty + 3, f"{temp}\u00b0C", size=6, color=TEXT_DIM)

# Colormap selector below map
dropdown(c, map_left, map_bot_y + 8, 140, 20, "Thermal Delta")

# ── Right column — Results ───────────────────────────────────────────
res_x = W - results_w
vline(c, res_x, content_top, content_bottom)
filled_rect(c, res_x, content_top, results_w, content_bottom - content_top, fill=SURFACE)

ry = content_top + 10

# Verdict banner
filled_rect(c, res_x + 8, ry, results_w - 16, 60, fill=Color(0.35, 0.25, 0.0),
            stroke=WARNING, radius=6)
text_at(c, res_x + results_w / 2, ry + 22, "WARNING",
        size=18, color=WARNING, font="Helvetica-Bold", anchor="center")
text_at(c, res_x + results_w / 2, ry + 42, "2 hotspots  |  Peak: 98.3 \u00b0C",
        size=9, color=TEXT_DIM, anchor="center")
ry += 72

# Summary
text_at(c, res_x + 10, ry + 10, "Summary", size=10, color=TEXT, font="Helvetica-Bold")
ry += 20
for label, val in [("N hotspots", "2"), ("Peak temperature", "98.3 \u00b0C"),
                    ("Mean temperature", "42.7 \u00b0C"), ("Max area", "847 px")]:
    text_at(c, res_x + 14, ry + 10, label, size=8, color=TEXT_DIM)
    text_at(c, res_x + results_w - 14, ry + 10, val, size=9, color=TEXT,
            font="Helvetica-Bold", anchor="right")
    ry += 18
ry += 10

# Hotspot table
text_at(c, res_x + 10, ry + 10, "Hotspot Table", size=10, color=TEXT, font="Helvetica-Bold")
ry += 20

# Header row
filled_rect(c, res_x + 8, ry, results_w - 16, 18, fill=SURFACE2, radius=2)
cols = [("#", 20), ("X", 35), ("Y", 35), ("Area", 40), ("Peak T", 50), ("Status", 50)]
hx = res_x + 14
for col_label, col_w in cols:
    text_at(c, hx, ry + 11, col_label, size=7, color=TEXT_DIM, font="Helvetica-Bold")
    hx += col_w
ry += 20

# Data rows
rows_data = [
    ("1", "342", "518", "847", "98.3\u00b0C", WARNING, "WARN"),
    ("2", "156", "203", "234", "87.1\u00b0C", WARNING, "WARN"),
]
for row_vals in rows_data:
    hx = res_x + 14
    for i, (col_label, col_w) in enumerate(cols):
        if i == 5:
            status_dot(c, hx + 4, ry + 8, row_vals[5], r=3)
            text_at(c, hx + 12, ry + 10, row_vals[6], size=7, color=row_vals[5])
        else:
            text_at(c, hx, ry + 10, row_vals[i], size=7, color=TEXT)
        hx += col_w
    ry += 16

ry += 16
# Export section
text_at(c, res_x + 10, ry + 10, "Export", size=10, color=TEXT, font="Helvetica-Bold")
ry += 22
bw_e = (results_w - 32) // 3
button(c, res_x + 8, ry, bw_e, 22, "Save PNG", fill=SURFACE3, text_color=TEXT, border=BORDER, font_size=7, radius=3)
button(c, res_x + 8 + bw_e + 4, ry, bw_e, 22, "Save CSV", fill=SURFACE3, text_color=TEXT, border=BORDER, font_size=7, radius=3)
button(c, res_x + 8 + 2 * (bw_e + 4), ry, bw_e, 22, "Save HDF5", fill=SURFACE3, text_color=TEXT, border=BORDER, font_size=7, radius=3)
ry += 30

# Generate Report button — prominent
button(c, res_x + 8, ry, results_w - 16, 32, "Generate Report...",
       fill=ACCENT_DIM, text_color=ACCENT, border=ACCENT, font_size=10, radius=5)


# ══════════════════════════════════════════════════════════════════════
# PAGE 2 — Report Generation Dialog
# ══════════════════════════════════════════════════════════════════════
c.showPage()
filled_rect(c, 0, 0, W, H, fill=BG)

# Semi-transparent overlay
filled_rect(c, 0, 0, W, H, fill=Color(0, 0, 0, 0.6))

# Dialog
dlg_w = 900
dlg_h = 580
dlg_x = (W - dlg_w) // 2
dlg_y = (H - dlg_h) // 2

filled_rect(c, dlg_x, dlg_y, dlg_w, dlg_h, fill=SURFACE, stroke=BORDER, radius=8)

# Title bar
filled_rect(c, dlg_x, dlg_y, dlg_w, 36, fill=SURFACE2, radius=8)
# Flatten bottom corners of title bar
filled_rect(c, dlg_x, dlg_y + 28, dlg_w, 8, fill=SURFACE2)
text_at(c, dlg_x + 16, dlg_y + 22, "Generate Report", size=13, color=TEXT, font="Helvetica-Bold")
text_at(c, dlg_x + dlg_w - 16, dlg_y + 22, "\u00d7", size=16, color=TEXT_DIM, anchor="right")
hline(c, dlg_x, dlg_x + dlg_w, dlg_y + 36)

# Left column — Options
opt_x = dlg_x + 16
opt_w = 380
oy = dlg_y + 50

text_at(c, opt_x, oy + 12, "Report Content", size=11, color=TEXT, font="Helvetica-Bold")
oy += 22
for item, checked in [("Thermal map image", True), ("Hotspot table", True),
                       ("Measurement parameters", True), ("Device information", True),
                       ("Raw data summary", False), ("Verdict and recommendations", True),
                       ("Calibration details", False)]:
    checkbox(c, opt_x, oy, item, checked=checked, size=9)
    oy += 22

oy += 10
text_at(c, opt_x, oy + 12, "Format", size=11, color=TEXT, font="Helvetica-Bold")
oy += 22

# Radio buttons for format
for i, (fmt, sel) in enumerate([("PDF Report", True), ("PowerPoint", False), ("HTML", False)]):
    rx = opt_x + i * 110
    if sel:
        c.setFillColor(ACCENT)
        c.circle(rx + 6, Y(oy + 7), 6, stroke=0, fill=1)
        c.setFillColor(WHITE)
        c.circle(rx + 6, Y(oy + 7), 2.5, stroke=0, fill=1)
    else:
        c.setStrokeColor(BORDER); c.setLineWidth(1.5)
        c.setFillColor(SURFACE)
        c.circle(rx + 6, Y(oy + 7), 6, stroke=1, fill=1)
    text_at(c, rx + 16, oy + 9, fmt, size=9, color=ACCENT if sel else TEXT)
oy += 28

text_at(c, opt_x, oy + 12, "Metadata", size=11, color=TEXT, font="Helvetica-Bold")
oy += 22

text_at(c, opt_x, oy + 12, "Operator", size=8, color=TEXT_DIM)
filled_rect(c, opt_x + 70, oy + 2, 200, 20, fill=Color(0.12, 0.12, 0.14), stroke=BORDER, radius=3)
text_at(c, opt_x + 78, oy + 14, "E. McNair", size=8, color=TEXT)
oy += 26

text_at(c, opt_x, oy + 12, "Customer", size=8, color=TEXT_DIM)
filled_rect(c, opt_x + 70, oy + 2, 200, 20, fill=Color(0.12, 0.12, 0.14), stroke=BORDER, radius=3)
text_at(c, opt_x + 78, oy + 14, "", size=8, color=TEXT_SUB)
oy += 26

text_at(c, opt_x, oy + 12, "Notes", size=8, color=TEXT_DIM)
filled_rect(c, opt_x + 70, oy + 2, 200, 40, fill=Color(0.12, 0.12, 0.14), stroke=BORDER, radius=3)
oy += 54

# Buttons
button(c, opt_x + 120, oy, 80, 28, "Cancel",
       fill=SURFACE3, text_color=TEXT, border=BORDER, font_size=9)
button(c, opt_x + 210, oy, 100, 28, "Generate",
       fill=Color(0.0, 0.55, 0.30), text_color=WHITE,
       border=Color(0.0, 0.65, 0.35), font_size=9, radius=5)

# Right column — Report Preview
prev_x = dlg_x + opt_w + 40
prev_w = dlg_w - opt_w - 56
prev_top = dlg_y + 50
prev_h = dlg_h - 70

# Preview page (white)
filled_rect(c, prev_x, prev_top, prev_w, prev_h,
            fill=Color(0.95, 0.95, 0.95), stroke=BORDER, radius=4)

# Simulated report content
py = prev_top + 16
# Logo placeholder
filled_rect(c, prev_x + 12, py, 60, 16, fill=Color(0.3, 0.3, 0.3), radius=2)
text_at(c, prev_x + 22, py + 10, "microsanj", size=6, color=Color(0.8, 0.8, 0.8))
text_at(c, prev_x + prev_w - 12, py + 10, "Thermal Analysis Report",
        size=10, color=Color(0.15, 0.15, 0.15), font="Helvetica-Bold", anchor="right")
py += 22
# Line
c.setStrokeColor(Color(0.0, 0.45, 0.60)); c.setLineWidth(2)
c.line(prev_x + 12, Y(py), prev_x + prev_w - 12, Y(py))
py += 10

# Device info
for line in ["Device: GaN HEMT PA 78GHz", "Date: 2026-03-25  |  Operator: E. McNair",
             "Goal: Temperature Map  |  Materials: GaN, Au, SiC"]:
    text_at(c, prev_x + 12, py + 8, line, size=7, color=Color(0.2, 0.2, 0.2))
    py += 14
py += 6

# Mini thermal map placeholder
map_ph = 140
filled_rect(c, prev_x + 12, py, prev_w - 24, map_ph,
            fill=Color(0.15, 0.25, 0.35), radius=3)
# Gradient simulation
for i in range(8):
    for j in range(12):
        bx = prev_x + 14 + j * ((prev_w - 28) // 12)
        by = py + 2 + i * (map_ph // 8)
        dist = ((j - 6) ** 2 + (i - 4) ** 2) ** 0.5
        t = max(0, 1 - dist / 7)
        filled_rect(c, bx, by, (prev_w - 28) // 12, map_ph // 8,
                    fill=Color(t * 0.9, 0.3 + t * 0.3, 0.5 - t * 0.4))
py += map_ph + 8

# Verdict
text_at(c, prev_x + 12, py + 8, "Verdict: WARNING \u2014 2 hotspots detected",
        size=8, color=Color(0.6, 0.4, 0.0), font="Helvetica-Bold")
py += 16

# Table placeholder (gray lines)
for i in range(4):
    c.setStrokeColor(Color(0.75, 0.75, 0.75)); c.setLineWidth(0.5)
    c.line(prev_x + 12, Y(py), prev_x + prev_w - 12, Y(py))
    py += 12

py += 8
text_at(c, prev_x + 12, py + 8, "Measurement Parameters", size=8,
        color=Color(0.2, 0.2, 0.2), font="Helvetica-Bold")
py += 14
for _ in range(3):
    filled_rect(c, prev_x + 12, py, prev_w * 0.6, 6, fill=Color(0.8, 0.8, 0.8), radius=1)
    py += 10

# Footer
text_at(c, prev_x + prev_w / 2, prev_top + prev_h - 12,
        "Generated by SanjINSIGHT v1.5.0", size=6,
        color=Color(0.5, 0.5, 0.5), anchor="center")

text_at(c, W / 2, H - 16, "REPORT GENERATION DIALOG",
        size=8, color=TEXT_SUB, font="Helvetica-Bold", anchor="center")

c.save()
print(f"Wrote {OUT}")
