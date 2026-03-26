#!/usr/bin/env python3
"""New Project Wizard — 4-page setup wizard derived from customer questionnaire."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.colors import Color
from _wireframe_common import *

OUT = os.path.join(os.path.dirname(__file__), "new-project-wizard.pdf")
c = Canvas(OUT, pagesize=(W, H))
c.setTitle("New Project Wizard")

BLUE = Color(0.20, 0.50, 0.85)
BLUE_DIM = Color(0.12, 0.30, 0.50)

def draw_stepper(c, active_step, top_y):
    """Draw 4-step horizontal stepper bar."""
    bar_h = 50
    filled_rect(c, 0, top_y, W, bar_h, fill=SURFACE2)
    hline(c, 0, W, top_y + bar_h)

    labels = ["Device Info", "Test Conditions", "Measurement Goal", "Review"]
    step_w = W / 4
    for i, label in enumerate(labels):
        cx = step_w * i + step_w / 2
        cy = top_y + 20

        # Circle
        if i < active_step:
            # completed
            c.setFillColor(GREEN)
            c.circle(cx, Y(cy), 12, stroke=0, fill=1)
            c.setStrokeColor(WHITE); c.setLineWidth(1.5)
            rx, ry = cx, Y(cy)
            c.line(rx - 5, ry - 1, rx - 2, ry - 4)
            c.line(rx - 2, ry - 4, rx + 5, ry + 3)
        elif i == active_step:
            c.setFillColor(ACCENT)
            c.circle(cx, Y(cy), 12, stroke=0, fill=1)
            c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 10)
            c.drawCentredString(cx, Y(cy) - 3.5, str(i + 1))
        else:
            c.setStrokeColor(TEXT_SUB); c.setLineWidth(1.5)
            c.setFillColor(SURFACE2)
            c.circle(cx, Y(cy), 12, stroke=1, fill=1)
            c.setFillColor(TEXT_SUB); c.setFont("Helvetica", 10)
            c.drawCentredString(cx, Y(cy) - 3.5, str(i + 1))

        # Label
        text_at(c, cx, top_y + 40, label, size=9,
                color=ACCENT if i == active_step else (TEXT if i < active_step else TEXT_SUB),
                font="Helvetica-Bold" if i == active_step else "Helvetica",
                anchor="center")

        # Connecting line
        if i < 3:
            lx1 = cx + 16
            lx2 = step_w * (i + 1) + step_w / 2 - 16
            c.setStrokeColor(GREEN if i < active_step else BORDER)
            c.setLineWidth(2)
            c.line(lx1, Y(cy), lx2, Y(cy))

    return top_y + bar_h

def draw_wizard_footer(c, step, total=4, is_last=False):
    """Draw bottom navigation buttons."""
    fy = H - 60
    filled_rect(c, 0, fy, W, 32, fill=SURFACE2)
    hline(c, 0, W, fy)

    text_at(c, 30, fy + 18, "Skip Setup", size=9, color=TEXT_SUB)

    if step > 0:
        button(c, W - 280, fy + 4, 80, 24, "Back",
               fill=SURFACE3, text_color=TEXT, border=BORDER, font_size=9)
    if is_last:
        button(c, W - 180, fy + 4, 150, 24, "Create Project",
               fill=Color(0.0, 0.55, 0.30), text_color=WHITE,
               border=Color(0.0, 0.65, 0.35), font_size=9)
    else:
        button(c, W - 180, fy + 4, 80, 24, "Next",
               fill=ACCENT_DIM, text_color=ACCENT, border=ACCENT, font_size=9)

def segmented_buttons(c, x, y, labels, selected=0, w_each=100, h=26):
    """Draw segmented button group."""
    for i, lbl in enumerate(labels):
        bx = x + i * w_each
        if i == selected:
            filled_rect(c, bx, y, w_each, h, fill=ACCENT_DIM, stroke=ACCENT, radius=4 if i==0 or i==len(labels)-1 else 0)
            text_at(c, bx + w_each / 2, y + h / 2 + 1, lbl, size=8,
                    color=ACCENT, font="Helvetica-Bold", anchor="center")
        else:
            filled_rect(c, bx, y, w_each, h, fill=SURFACE3, stroke=BORDER, radius=4 if i==0 or i==len(labels)-1 else 0)
            text_at(c, bx + w_each / 2, y + h / 2 + 1, lbl, size=8,
                    color=TEXT, anchor="center")

def material_chips(c, x, y, materials, selected_indices):
    """Draw material selection chips."""
    cx = x
    for i, mat in enumerate(materials):
        tw = len(mat) * 7 + 16
        sel = i in selected_indices
        if sel:
            filled_rect(c, cx, y, tw, 22, fill=ACCENT_DIM, stroke=ACCENT, radius=11)
            text_at(c, cx + tw / 2, y + 12, mat, size=8, color=ACCENT,
                    font="Helvetica-Bold", anchor="center")
        else:
            filled_rect(c, cx, y, tw, 22, fill=SURFACE3, stroke=BORDER, radius=11)
            text_at(c, cx + tw / 2, y + 12, mat, size=8, color=TEXT, anchor="center")
        cx += tw + 6

def text_input(c, x, y, w, h, value="", placeholder=""):
    """Draw a text input field."""
    filled_rect(c, x, y, w, h, fill=SURFACE, stroke=BORDER, radius=3)
    if value:
        text_at(c, x + 8, y + h / 2 + 1, value, size=8, color=TEXT)
    elif placeholder:
        text_at(c, x + 8, y + h / 2 + 1, placeholder, size=8, color=TEXT_SUB)


# ══════════════════════════════════════════════════════════════════════
# PAGE 1 — Device Info
# ══════════════════════════════════════════════════════════════════════
filled_rect(c, 0, 0, W, H, fill=BG)
step_bottom = draw_stepper(c, 0, 0)
draw_wizard_footer(c, 0)

content_x = 200
content_w = 800
py = step_bottom + 20

text_at(c, content_x, py + 14, "Device Information", size=14, color=TEXT, font="Helvetica-Bold")
py += 30

# Device name
text_at(c, content_x, py + 12, "Device Name / ID", size=9, color=TEXT_DIM)
text_input(c, content_x + 140, py + 2, 300, 22, value="GaN HEMT PA 78GHz")
py += 32

# Device type
text_at(c, content_x, py + 12, "Device Type", size=9, color=TEXT_DIM)
segmented_buttons(c, content_x + 140, py + 2,
                  ["Packaged", "Wafer", "Die", "Module", "MCM", "MMIC"],
                  selected=2, w_each=85)
py += 32

# Sample format
text_at(c, content_x, py + 12, "Sample Format", size=9, color=TEXT_DIM)
segmented_buttons(c, content_x + 140, py + 2,
                  ["Chip on PCB", "Chip on Carrier", "Bare Wafer"],
                  selected=2, w_each=120)
py += 32

# Materials
text_at(c, content_x, py + 12, "Device Materials", size=9, color=TEXT_DIM)
material_chips(c, content_x + 140, py + 2,
               ["Au", "Al", "Cu", "Si", "GaAs", "GaN", "InP", "SiC"],
               selected_indices={0, 5, 7})
py += 32

# Dimensions
text_at(c, content_x, py + 12, "Device Dimensions", size=9, color=TEXT_DIM)
spinbox(c, content_x + 140, py + 2, 80, 22, "4.2", suffix=" mm")
text_at(c, content_x + 228, py + 12, "\u00d7", size=10, color=TEXT_DIM)
spinbox(c, content_x + 244, py + 2, 80, 22, "2.8", suffix=" mm")
py += 32

# ROI
text_at(c, content_x, py + 12, "ROI Dimensions", size=9, color=TEXT_DIM)
spinbox(c, content_x + 140, py + 2, 80, 22, "2.4", suffix=" mm")
text_at(c, content_x + 228, py + 12, "\u00d7", size=10, color=TEXT_DIM)
spinbox(c, content_x + 244, py + 2, 80, 22, "1.8", suffix=" mm")
py += 40

# Surface Conditions
text_at(c, content_x, py + 14, "Surface Conditions", size=14, color=TEXT, font="Helvetica-Bold")
py += 30

text_at(c, content_x, py + 12, "Passivation", size=9, color=TEXT_DIM)
segmented_buttons(c, content_x + 140, py + 2,
                  ["None", "Oxide / Nitride", "Polymer"],
                  selected=0, w_each=120)
py += 32

text_at(c, content_x, py + 12, "Obstructions", size=9, color=TEXT_DIM)
checkbox(c, content_x + 140, py + 2, "Air bridges", checked=False, size=9)
checkbox(c, content_x + 310, py + 2, "Heat sinks", checked=False, size=9)
checkbox(c, content_x + 460, py + 2, "Mold compound", checked=False, size=9)
checkbox(c, content_x + 630, py + 2, "None", checked=True, size=9)

text_at(c, W / 2, H - 30, "PAGE 1 of 4  \u2014  New Project Wizard",
        size=8, color=TEXT_SUB, font="Helvetica-Bold", anchor="center")

# ══════════════════════════════════════════════════════════════════════
# PAGE 2 — Test Conditions
# ══════════════════════════════════════════════════════════════════════
c.showPage()
filled_rect(c, 0, 0, W, H, fill=BG)
step_bottom = draw_stepper(c, 1, 0)
draw_wizard_footer(c, 1)

py = step_bottom + 20

text_at(c, content_x, py + 14, "Electrical Bias", size=14, color=TEXT, font="Helvetica-Bold")
py += 30

text_at(c, content_x, py + 12, "Bias Mode", size=9, color=TEXT_DIM)
segmented_buttons(c, content_x + 140, py + 2,
                  ["Voltage Source", "Current Source", "No Bias"],
                  selected=1, w_each=120)
py += 32

text_at(c, content_x, py + 12, "Max Voltage", size=9, color=TEXT_DIM)
spinbox(c, content_x + 140, py + 2, 100, 22, "10.0", suffix=" V")
text_at(c, content_x + 280, py + 12, "Max Current", size=9, color=TEXT_DIM)
spinbox(c, content_x + 400, py + 2, 100, 22, "25.0", suffix=" mA")
py += 32

text_at(c, content_x, py + 12, "Compliance", size=9, color=TEXT_DIM)
spinbox(c, content_x + 140, py + 2, 100, 22, "30.0", suffix=" mA")
text_at(c, content_x + 280, py + 12, "Bias Pins", size=9, color=TEXT_DIM)
dropdown(c, content_x + 400, py + 2, 100, 22, "3")
py += 32

checkbox(c, content_x, py + 2, "Pulsed operation", checked=True, size=9)
text_at(c, content_x + 200, py + 12, "Frequency", size=9, color=TEXT_DIM)
spinbox(c, content_x + 280, py + 2, 100, 22, "1000", suffix=" Hz")
text_at(c, content_x + 420, py + 12, "Duty", size=9, color=TEXT_DIM)
spinbox(c, content_x + 460, py + 2, 80, 22, "50", suffix=" %")
py += 44

text_at(c, content_x, py + 14, "Thermal Environment", size=14, color=TEXT, font="Helvetica-Bold")
py += 30

text_at(c, content_x, py + 12, "Chuck Temp Range", size=9, color=TEXT_DIM)
spinbox(c, content_x + 140, py + 2, 80, 22, "25", suffix=" \u00b0C")
text_at(c, content_x + 228, py + 12, "to", size=9, color=TEXT_DIM)
spinbox(c, content_x + 248, py + 2, 80, 22, "125", suffix=" \u00b0C")
py += 32

text_at(c, content_x, py + 12, "Temperature Steps", size=9, color=TEXT_DIM)
spinbox(c, content_x + 140, py + 2, 80, 22, "6")
py += 32

checkbox(c, content_x, py + 2, "Ambient measurement only (no chuck)", checked=False, size=9)
py += 40

text_at(c, content_x, py + 14, "Connection Type", size=14, color=TEXT, font="Helvetica-Bold")
py += 30

segmented_buttons(c, content_x, py + 2,
                  ["Wire Bond / PCB", "DC Probe (needle)", "Probe Card"],
                  selected=1, w_each=150)

text_at(c, W / 2, H - 30, "PAGE 2 of 4  \u2014  New Project Wizard",
        size=8, color=TEXT_SUB, font="Helvetica-Bold", anchor="center")

# ══════════════════════════════════════════════════════════════════════
# PAGE 3 — Measurement Goal
# ══════════════════════════════════════════════════════════════════════
c.showPage()
filled_rect(c, 0, 0, W, H, fill=BG)
step_bottom = draw_stepper(c, 2, 0)
draw_wizard_footer(c, 2)

py = step_bottom + 20

text_at(c, content_x, py + 14, "What do you want to measure?", size=14, color=TEXT, font="Helvetica-Bold")
py += 35

# Goal cards — 2x2 grid
card_w = 360
card_h = 100
gap = 20
goals = [
    ("Hotspot Detection", "Quick failure analysis. Find thermal\nhotspots and anomalies.", "~5 min", False),
    ("Temperature Map", "Calibrated absolute temperature\nmeasurement with uncertainty.", "~30 min", True),
    ("Device Characterization", "Sweep voltage/current and temperature\nfor full thermal characterization.", "~2 hrs", False),
    ("Custom", "Configure everything manually.\nFull control over all parameters.", "Flexible", False),
]

for i, (title, desc, time_est, selected) in enumerate(goals):
    row, col = divmod(i, 2)
    gx = content_x + col * (card_w + gap)
    gy = py + row * (card_h + gap)

    border_color = ACCENT if selected else BORDER
    bg = Color(0.0, 0.20, 0.16) if selected else SURFACE
    filled_rect(c, gx, gy, card_w, card_h, fill=bg, stroke=border_color, radius=8)

    # Title
    text_at(c, gx + 16, gy + 22, title, size=12, color=ACCENT if selected else TEXT,
            font="Helvetica-Bold")

    # Description (2 lines)
    lines = desc.split("\n")
    for j, line in enumerate(lines):
        text_at(c, gx + 16, gy + 40 + j * 14, line, size=9, color=TEXT_DIM)

    # Time badge
    badge(c, gx + card_w - 80, gy + 10, time_est,
          fill=ACCENT_DIM if selected else SURFACE3,
          text_color=ACCENT if selected else TEXT_DIM)

    # Radio indicator
    if selected:
        c.setFillColor(ACCENT)
        c.circle(gx + card_w - 20, Y(gy + card_h - 16), 6, stroke=0, fill=1)
        c.setFillColor(WHITE)
        c.circle(gx + card_w - 20, Y(gy + card_h - 16), 2.5, stroke=0, fill=1)
    else:
        c.setStrokeColor(BORDER); c.setLineWidth(1.5)
        c.setFillColor(SURFACE)
        c.circle(gx + card_w - 20, Y(gy + card_h - 16), 6, stroke=1, fill=1)

py += 2 * (card_h + gap) + 20

text_at(c, content_x, py + 14, "Comparison & Reporting", size=14, color=TEXT, font="Helvetica-Bold")
py += 30

checkbox(c, content_x, py + 2, "Compare against existing data", checked=False, size=9)
py += 24
checkbox(c, content_x, py + 2, "Formal report required", checked=True, size=9)

text_at(c, W / 2, H - 30, "PAGE 3 of 4  \u2014  New Project Wizard",
        size=8, color=TEXT_SUB, font="Helvetica-Bold", anchor="center")

# ══════════════════════════════════════════════════════════════════════
# PAGE 4 — Review & Create
# ══════════════════════════════════════════════════════════════════════
c.showPage()
filled_rect(c, 0, 0, W, H, fill=BG)
step_bottom = draw_stepper(c, 3, 0)
draw_wizard_footer(c, 3, is_last=True)

py = step_bottom + 20

text_at(c, content_x, py + 14, "Review Project Configuration", size=14, color=TEXT, font="Helvetica-Bold")
py += 35

# Two-column summary
col1_x = content_x
col2_x = content_x + 400
col_w = 350

# Left — Device & Setup
filled_rect(c, col1_x, py, col_w, 180, fill=SURFACE, stroke=BORDER, radius=6)
text_at(c, col1_x + 12, py + 18, "Device & Setup", size=11, color=TEXT, font="Helvetica-Bold")
hline(c, col1_x + 8, col1_x + col_w - 8, py + 26)

review_items_l = [
    ("Device", "GaN HEMT PA 78GHz (Die)"),
    ("Materials", "GaN, Au, SiC"),
    ("Passivation", "None"),
    ("ROI", "2.4 \u00d7 1.8 mm"),
    ("Connection", "DC Probe (needle), 3-pin"),
    ("Obstructions", "None"),
]
ry = py + 36
for label, value in review_items_l:
    text_at(c, col1_x + 16, ry + 10, label, size=8, color=TEXT_DIM)
    text_at(c, col1_x + col_w - 16, ry + 10, value, size=9, color=TEXT,
            font="Helvetica-Bold", anchor="right")
    ry += 22

# Right — Measurement
filled_rect(c, col2_x, py, col_w, 180, fill=SURFACE, stroke=BORDER, radius=6)
text_at(c, col2_x + 12, py + 18, "Measurement", size=11, color=TEXT, font="Helvetica-Bold")
hline(c, col2_x + 8, col2_x + col_w - 8, py + 26)

review_items_r = [
    ("Goal", "Temperature Map"),
    ("Bias", "0\u201325 mA (current, pulsed 1kHz 50%)"),
    ("Temperature", "25\u2013125 \u00b0C, 6 steps"),
    ("Est. Time", "~30 min per temperature"),
    ("Report", "Formal report required"),
    ("Comparison", "None"),
]
ry = py + 36
for label, value in review_items_r:
    text_at(c, col2_x + 16, ry + 10, label, size=8, color=TEXT_DIM)
    text_at(c, col2_x + col_w - 16, ry + 10, value, size=9, color=TEXT,
            font="Helvetica-Bold", anchor="right")
    ry += 22

py += 200

# Auto-Configuration Preview
text_at(c, content_x, py + 14, "Auto-Configuration Preview", size=14, color=TEXT, font="Helvetica-Bold")
text_at(c, content_x, py + 30, "These settings will be applied automatically based on your selections:",
        size=9, color=TEXT_DIM)
py += 42

filled_rect(c, content_x, py, col_w * 2 + 50, 150, fill=Color(0.0, 0.18, 0.14),
            stroke=ACCENT_DIM, radius=6)

auto_items = [
    ("Modality", "Thermoreflectance [TR]", "(auto-detected from camera)"),
    ("Suggested Wavelength", "530 nm (green LED)", "optimal for Au/GaN"),
    ("Calibration Preset", "7-point TR Standard", ""),
    ("Compliance Limit", "30 mA", "(from bias limits)"),
    ("Temperature Sequence", "25, 40, 60, 80, 100, 125 \u00b0C", ""),
]
ay = py + 16
for label, value, note in auto_items:
    text_at(c, content_x + 16, ay + 10, label, size=9, color=TEXT_DIM)
    text_at(c, content_x + 220, ay + 10, value, size=10, color=ACCENT, font="Helvetica-Bold")
    if note:
        text_at(c, content_x + 500, ay + 10, note, size=8, color=TEXT_SUB)
    ay += 24

text_at(c, W / 2, H - 30, "PAGE 4 of 4  \u2014  New Project Wizard",
        size=8, color=TEXT_SUB, font="Helvetica-Bold", anchor="center")

c.save()
print(f"Wrote {OUT}")
