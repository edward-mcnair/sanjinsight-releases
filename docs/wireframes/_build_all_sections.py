#!/usr/bin/env python3
"""
Generate a 13-page detail wireframe PDF for SanjINSIGHT.

Each page shows one nav section's content area with primary controls on the
left (~55%) and the "More Options" panel expanded on the right (~45%).

Output: all-sections-detail.pdf
"""

from pathlib import Path
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.pagesizes import landscape
from reportlab.lib.colors import Color

from _wireframe_common import (
    BG, SURFACE, SURFACE2, SURFACE3, BORDER, TEXT, TEXT_DIM, TEXT_SUB,
    ACCENT, ACCENT_DIM, WARNING, ERROR, GREEN, WHITE, BLACK,
    W, H, Y,
    filled_rect, text_at, hline, vline,
    button, status_dot, badge, checkbox, spinbox, dropdown,
    slider_bar, section_header, advanced_toggle, crosshair,
)

OUT = Path(__file__).with_name("all-sections-detail.pdf")

# Layout constants
LEFT_X = 30          # left column start
LEFT_W = 620         # ~55% of 1200 minus margins
DIV_X  = 660         # vertical divider
RIGHT_X = 680        # right column start
RIGHT_W = 490        # right column width
TITLE_Y = 20         # top of page title
BADGE_Y = 48         # modality badge row
CONTENT_Y = 78       # start of control content

BLUE = Color(0.24, 0.54, 0.94)  # IR badge color


# ── Utility helpers ──────────────────────────────────────────────────────

def new_page(c: Canvas, page_num: int, total: int,
             phase: str, section: str):
    """Set up a fresh page: background, title, page number."""
    # Background
    filled_rect(c, 0, 0, W, H, fill=BG)

    # Title
    text_at(c, LEFT_X, TITLE_Y + 16,
            f"{phase} — {section}",
            size=18, color=TEXT, font="Helvetica-Bold")

    # Page number
    text_at(c, W / 2, H - 12, f"{page_num} / {total}",
            size=7, color=TEXT_SUB, anchor="center")


def draw_more_options_divider(c: Canvas, top_y=CONTENT_Y - 8):
    """Vertical divider with 'More Options' label at top of right column."""
    vline(c, DIV_X, top_y, H - 30, color=BORDER)
    filled_rect(c, DIV_X - 1, top_y, 2, H - 30 - top_y, fill=BORDER)
    # Label
    text_at(c, RIGHT_X, top_y + 12, "More Options  \u25bc",
            size=10, color=ACCENT, font="Helvetica-Bold")
    hline(c, RIGHT_X, RIGHT_X + RIGHT_W, top_y + 20, color=BORDER)
    return top_y + 30


def modality_badges(c: Canvas, x, top_y, tr=True, ir=True):
    """Draw TR / IR applicability badges."""
    cx = x
    if tr:
        bw = badge(c, cx, top_y, "TR", fill=GREEN, text_color=BLACK,
                   font_size=8, h=18, radius=4)
        cx += bw + 6
    if ir:
        badge(c, cx, top_y, "IR", fill=BLUE, text_color=WHITE,
              font_size=8, h=18, radius=4)


def label_value(c: Canvas, x, top_y, label, value,
                label_w=120, val_color=TEXT):
    """Draw a 'Label: Value' pair."""
    text_at(c, x, top_y, label, size=9, color=TEXT_DIM)
    text_at(c, x + label_w, top_y, value, size=9, color=val_color,
            font="Helvetica-Bold")


def read_only_field(c: Canvas, x, top_y, w, h, value):
    """Read-only display field (dimmer border, no arrows)."""
    filled_rect(c, x, top_y, w, h, fill=SURFACE, stroke=BORDER, radius=3)
    text_at(c, x + 8, top_y + h / 2 + 1, value, size=8, color=TEXT_DIM)


def label_above(c: Canvas, x, top_y, label):
    """Small label text above a control."""
    text_at(c, x, top_y, label, size=8, color=TEXT_DIM)
    return top_y + 14


def toggle_button(c: Canvas, x, top_y, w, h, label, on=False):
    """A toggle-style button (green when on)."""
    fill = GREEN if on else SURFACE3
    tc = BLACK if on else TEXT
    button(c, x, top_y, w, h, label, fill=fill, text_color=tc, border=BORDER)


def segmented_buttons(c: Canvas, x, top_y, labels, selected_idx=0,
                      btn_w=110, btn_h=26, gap=0):
    """Row of segmented buttons; selected one gets ACCENT fill."""
    for i, lbl in enumerate(labels):
        bx = x + i * (btn_w + gap)
        sel = (i == selected_idx)
        fill = ACCENT if sel else SURFACE3
        tc = BLACK if sel else TEXT
        bdr = ACCENT if sel else BORDER
        button(c, bx, top_y, btn_w, btn_h, lbl,
               fill=fill, text_color=tc, border=bdr)


def preset_row(c: Canvas, x, top_y, labels, selected_idx=-1,
               btn_w=60, btn_h=24, gap=4):
    """Row of preset buttons."""
    for i, lbl in enumerate(labels):
        bx = x + i * (btn_w + gap)
        sel = (i == selected_idx)
        fill = ACCENT if sel else SURFACE3
        tc = BLACK if sel else TEXT
        button(c, bx, top_y, btn_w, btn_h, lbl,
               fill=fill, text_color=tc, border=BORDER, font_size=8)


def progress_bar(c: Canvas, x, top_y, w, h, pct=0.5):
    """Simple progress bar."""
    filled_rect(c, x, top_y, w, h, fill=SURFACE3, radius=3)
    filled_rect(c, x, top_y, w * pct, h, fill=ACCENT, radius=3)
    text_at(c, x + w / 2, top_y + h / 2 + 1,
            f"{int(pct * 100)}%", size=7, color=WHITE, anchor="center")


def placeholder_image(c: Canvas, x, top_y, w, h, label="",
                      fill=SURFACE2, border=BORDER):
    """Empty placeholder rect with optional label."""
    filled_rect(c, x, top_y, w, h, fill=fill, stroke=border, radius=4)
    if label:
        text_at(c, x + w / 2, top_y + h / 2 + 1, label,
                size=9, color=TEXT_SUB, anchor="center")


def text_field(c: Canvas, x, top_y, w, h, value="", placeholder=""):
    """Wireframe text input field."""
    filled_rect(c, x, top_y, w, h, fill=SURFACE, stroke=BORDER, radius=3)
    txt = value if value else placeholder
    clr = TEXT if value else TEXT_SUB
    text_at(c, x + 8, top_y + h / 2 + 1, txt, size=8, color=clr)


def radio_buttons(c: Canvas, x, top_y, labels, selected_idx=0, gap=18):
    """Vertical radio button list."""
    cy = top_y
    for i, lbl in enumerate(labels):
        sel = (i == selected_idx)
        # outer circle
        r = 5
        cx_c = x + r
        cy_c = Y(cy + r + 2)
        c.setStrokeColor(ACCENT if sel else BORDER)
        c.setLineWidth(1)
        c.setFillColor(BG)
        c.circle(cx_c, cy_c, r, stroke=1, fill=1)
        if sel:
            c.setFillColor(ACCENT)
            c.circle(cx_c, cy_c, 3, stroke=0, fill=1)
        text_at(c, x + r * 2 + 6, cy + r + 2, lbl, size=9, color=TEXT)
        cy += gap
    return cy


def text_area_field(c: Canvas, x, top_y, w, h, value=""):
    """Multi-line text area placeholder."""
    filled_rect(c, x, top_y, w, h, fill=SURFACE, stroke=BORDER, radius=3)
    if value:
        text_at(c, x + 8, top_y + 14, value, size=8, color=TEXT_DIM)
    else:
        text_at(c, x + 8, top_y + 14, "(empty)", size=8, color=TEXT_SUB)


# ── Page drawing functions ───────────────────────────────────────────────

def page_modality(c):
    new_page(c, 1, 13, "\u2460 CONFIGURATION", "Modality")
    modality_badges(c, LEFT_X, BADGE_Y, tr=True, ir=True)
    ry = draw_more_options_divider(c)

    # ── PRIMARY ──
    y = CONTENT_Y
    y = label_above(c, LEFT_X, y, "Camera")
    dropdown(c, LEFT_X, y, 400, 26, "Basler acA1920-155um [TR]")
    y += 38
    y = label_above(c, LEFT_X, y, "Mode (auto-detected)")
    badge(c, LEFT_X, y, "THERMOREFLECTANCE", fill=ACCENT, text_color=BLACK,
          font_size=9, h=22, radius=4, pad_x=12)
    y += 36
    y = label_above(c, LEFT_X, y, "Objective")
    dropdown(c, LEFT_X, y, 280, 26, "20\u00d7 (0.42 NA)")
    y += 38
    y = label_above(c, LEFT_X, y, "FOV Readout")
    text_at(c, LEFT_X, y + 4, "480 \u00d7 360 \u03bcm", size=14,
            color=ACCENT, font="Helvetica-Bold")

    # ── MORE OPTIONS ──
    y = ry
    y = label_above(c, RIGHT_X, y, "Pixel Format")
    dropdown(c, RIGHT_X, y, 260, 24, "Mono12"); y += 34
    y = label_above(c, RIGHT_X, y, "Color Mode")
    checkbox(c, RIGHT_X, y, "Enable RGB output", checked=False); y += 28
    y = label_above(c, RIGHT_X, y, "Sensor Binning")
    dropdown(c, RIGHT_X, y, 260, 24, "1\u00d71 (no binning)"); y += 34
    y = label_above(c, RIGHT_X, y, "Bit Depth")
    read_only_field(c, RIGHT_X, y, 120, 24, "12-bit"); y += 34
    y = label_above(c, RIGHT_X, y, "Sensor Resolution")
    read_only_field(c, RIGHT_X, y, 180, 24, "1920 \u00d7 1200")


def page_stimulus(c):
    new_page(c, 2, 13, "\u2460 CONFIGURATION", "Stimulus")
    modality_badges(c, LEFT_X, BADGE_Y, tr=True, ir=True)
    ry = draw_more_options_divider(c)

    # ── PRIMARY ──
    y = CONTENT_Y
    y = label_above(c, LEFT_X, y, "Source")
    segmented_buttons(c, LEFT_X, y, ["FPGA Modulation", "Bias Source"],
                      selected_idx=0, btn_w=150); y += 38
    y = label_above(c, LEFT_X, y, "Enable")
    toggle_button(c, LEFT_X, y, 140, 28, "Stimulus ON", on=True); y += 42
    y = label_above(c, LEFT_X, y, "Voltage")
    spinbox(c, LEFT_X, y, 160, 26, "1.800", suffix=" V"); y += 38
    y = label_above(c, LEFT_X, y, "Compliance")
    spinbox(c, LEFT_X, y, 160, 26, "30.0", suffix=" mA")

    # ── MORE OPTIONS ──
    y = ry
    y = label_above(c, RIGHT_X, y, "Output Port")
    dropdown(c, RIGHT_X, y, 300, 24, "VO INT \u2014 pulsed \u00b110V"); y += 34
    y = label_above(c, RIGHT_X, y, "Mode")
    radio_buttons(c, RIGHT_X, y,
                  ["Voltage Source", "Current Source"], selected_idx=0, gap=20)
    y += 44
    y = label_above(c, RIGHT_X, y, "Presets")
    preset_row(c, RIGHT_X, y, ["\u00b110V", "+60V"],
               selected_idx=0, btn_w=70); y += 34
    y = label_above(c, RIGHT_X, y, "Waveform")
    dropdown(c, RIGHT_X, y, 200, 24, "Square"); y += 34
    y = label_above(c, RIGHT_X, y, "Slew Rate")
    spinbox(c, RIGHT_X, y, 180, 24, "1000", suffix=" V/\u03bcs"); y += 38
    y = section_header(c, RIGHT_X, y, RIGHT_W, "IV Sweep"); y += 4
    y = label_above(c, RIGHT_X, y, "Start / End / Step Voltage")
    spinbox(c, RIGHT_X, y, 100, 22, "0.0", suffix=" V")
    spinbox(c, RIGHT_X + 108, y, 100, 22, "5.0", suffix=" V")
    spinbox(c, RIGHT_X + 216, y, 100, 22, "0.1", suffix=" V"); y += 30
    button(c, RIGHT_X, y, 140, 26, "Run IV Sweep",
           fill=ACCENT, text_color=BLACK, border=ACCENT)


def page_timing(c):
    new_page(c, 3, 13, "\u2460 CONFIGURATION", "Timing")
    modality_badges(c, LEFT_X, BADGE_Y, tr=True, ir=False)
    ry = draw_more_options_divider(c)

    # ── PRIMARY ──
    y = CONTENT_Y
    y = label_above(c, LEFT_X, y, "Frequency Presets")
    preset_row(c, LEFT_X, y,
               ["1 Hz", "10 Hz", "100 Hz", "1 kHz", "10 kHz"],
               selected_idx=3, btn_w=80, gap=4); y += 36
    y = label_above(c, LEFT_X, y, "Duty Cycle Presets")
    preset_row(c, LEFT_X, y,
               ["10%", "25%", "50%", "75%", "90%"],
               selected_idx=2, btn_w=60, gap=4); y += 38

    button(c, LEFT_X, y, 100, 30, "Start",
           fill=GREEN, text_color=BLACK, border=GREEN)
    button(c, LEFT_X + 110, y, 100, 30, "Stop",
           fill=SURFACE3, text_color=TEXT, border=BORDER); y += 48

    y = label_above(c, LEFT_X, y, "Status Readouts")
    label_value(c, LEFT_X, y, "Frequency:", "1000.0 Hz"); y += 18
    label_value(c, LEFT_X, y, "Duty:", "50.0 %"); y += 18
    text_at(c, LEFT_X, y, "Sync:", size=9, color=TEXT_DIM)
    status_dot(c, LEFT_X + 126, y - 1, GREEN, r=4)
    text_at(c, LEFT_X + 136, y, "LOCKED", size=9, color=GREEN,
            font="Helvetica-Bold")

    # ── MORE OPTIONS ──
    y = ry
    y = label_above(c, RIGHT_X, y, "Exact Frequency")
    spinbox(c, RIGHT_X, y, 180, 24, "1000.0", suffix=" Hz"); y += 34
    y = label_above(c, RIGHT_X, y, "Exact Duty Cycle")
    spinbox(c, RIGHT_X, y, 180, 24, "50.0", suffix=" %"); y += 34
    y = label_above(c, RIGHT_X, y, "Trigger Mode")
    radio_buttons(c, RIGHT_X, y,
                  ["Continuous", "Single"], selected_idx=0, gap=20); y += 44
    y = label_above(c, RIGHT_X, y, "Phase Offset")
    spinbox(c, RIGHT_X, y, 160, 24, "0.0", suffix=" \u00b0"); y += 34
    y = label_above(c, RIGHT_X, y, "Frames per Cycle")
    spinbox(c, RIGHT_X, y, 120, 24, "4"); y += 34
    checkbox(c, RIGHT_X, y, "Enable external trigger input",
             checked=False)


def page_temperature(c):
    new_page(c, 4, 13, "\u2460 CONFIGURATION", "Temperature")
    modality_badges(c, LEFT_X, BADGE_Y, tr=True, ir=True)
    ry = draw_more_options_divider(c)

    # ── PRIMARY ──
    y = CONTENT_Y
    y = label_above(c, LEFT_X, y, "Setpoint")
    spinbox(c, LEFT_X, y, 160, 28, "25.00", suffix=" \u00b0C"); y += 40
    y = label_above(c, LEFT_X, y, "Current Temperature")
    text_at(c, LEFT_X, y + 2, "25.03 \u00b0C", size=16,
            color=ACCENT, font="Helvetica-Bold"); y += 30
    y = label_above(c, LEFT_X, y, "Stability")
    status_dot(c, LEFT_X + 4, y + 4, GREEN, r=5)
    text_at(c, LEFT_X + 16, y + 4, "Stable", size=10,
            color=GREEN, font="Helvetica-Bold"); y += 28
    y = label_above(c, LEFT_X, y, "Quick Setpoints")
    preset_row(c, LEFT_X, y,
               ["0\u00b0C", "25\u00b0C", "50\u00b0C", "85\u00b0C", "-20\u00b0C"],
               selected_idx=1, btn_w=60, gap=4); y += 36

    y = label_above(c, LEFT_X, y, "Temperature Plot")
    # placeholder chart
    pw, ph = LEFT_W - 20, 180
    placeholder_image(c, LEFT_X, y, pw, ph, "")
    # simulated flat line at 25°C
    line_y_top = y + ph * 0.45
    c.setStrokeColor(ACCENT)
    c.setLineWidth(1.5)
    pts = [(LEFT_X + 20 + i * 20, Y(line_y_top + (i % 3 - 1) * 2))
           for i in range(int((pw - 40) / 20))]
    p = c.beginPath()
    p.moveTo(pts[0][0], pts[0][1])
    for px, py in pts[1:]:
        p.lineTo(px, py)
    c.drawPath(p, stroke=1, fill=0)

    # ── MORE OPTIONS ──
    y = ry
    y = label_above(c, RIGHT_X, y, "Ramp Rate")
    spinbox(c, RIGHT_X, y, 160, 24, "5.0", suffix=" \u00b0C/min"); y += 34
    y = label_above(c, RIGHT_X, y, "Settling Tolerance")
    spinbox(c, RIGHT_X, y, 160, 24, "0.1", suffix=" \u00b0C"); y += 34
    y = label_above(c, RIGHT_X, y, "Hold After Settle")
    spinbox(c, RIGHT_X, y, 160, 24, "10", suffix=" s"); y += 40

    y = section_header(c, RIGHT_X, y, RIGHT_W, "Safety"); y += 4
    y = label_above(c, RIGHT_X, y, "Min Temperature")
    spinbox(c, RIGHT_X, y, 160, 24, "-40", suffix=" \u00b0C"); y += 34
    y = label_above(c, RIGHT_X, y, "Max Temperature")
    spinbox(c, RIGHT_X, y, 160, 24, "200", suffix=" \u00b0C"); y += 34
    y = label_above(c, RIGHT_X, y, "Warning Margin")
    spinbox(c, RIGHT_X, y, 160, 24, "10", suffix=" \u00b0C"); y += 40

    section_header(c, RIGHT_X, y, RIGHT_W, "PID Tuning", collapsed=True)


def page_acquisition_settings(c):
    new_page(c, 5, 13, "\u2460 CONFIGURATION", "Acquisition Settings")
    modality_badges(c, LEFT_X, BADGE_Y, tr=True, ir=True)
    ry = draw_more_options_divider(c)

    # ── PRIMARY ──
    y = CONTENT_Y
    y = label_above(c, LEFT_X, y, "Frames to Average")
    spinbox(c, LEFT_X, y, 140, 26, "100"); y += 38
    y = label_above(c, LEFT_X, y, "Inter-phase Delay")
    spinbox(c, LEFT_X, y, 160, 26, "0.100", suffix=" s"); y += 38

    y = label_above(c, LEFT_X, y, "Exposure")
    slider_bar(c, LEFT_X, y + 2, 350, pos=0.25, h=6)
    spinbox(c, LEFT_X + 370, y - 4, 140, 24, "5000", suffix=" \u03bcs")
    y += 28
    y = label_above(c, LEFT_X, y, "Exposure Presets")
    preset_row(c, LEFT_X, y,
               ["50\u03bcs", "1ms", "5ms", "20ms", "100ms"],
               selected_idx=2, btn_w=65, gap=4); y += 38

    y = label_above(c, LEFT_X, y, "Gain")
    slider_bar(c, LEFT_X, y + 2, 350, pos=0.0, h=6)
    spinbox(c, LEFT_X + 370, y - 4, 140, 24, "0.0", suffix=" dB")

    # ── MORE OPTIONS ──
    y = ry
    y = label_above(c, RIGHT_X, y, "Averaging Mode")
    dropdown(c, RIGHT_X, y, 280, 24,
             "Cumulative (float64)"); y += 34
    checkbox(c, RIGHT_X, y, "Dark frame subtraction",
             checked=False); y += 22
    checkbox(c, RIGHT_X, y, "Drift correction",
             checked=True); y += 26
    checkbox(c, RIGHT_X, y, "Frame quality gating",
             checked=True); y += 22
    # indented sub-options
    ix = RIGHT_X + 20
    y = label_above(c, ix, y, "Max Drift")
    spinbox(c, ix, y, 120, 22, "2.0", suffix=" px"); y += 30
    y = label_above(c, ix, y, "Min Focus")
    spinbox(c, ix, y, 100, 22, "40"); y += 30
    y = label_above(c, ix, y, "Saturation Reject")
    spinbox(c, ix, y, 120, 22, "1.0", suffix=" %"); y += 32

    checkbox(c, RIGHT_X, y, "Store raw frames",
             checked=False); y += 4
    text_at(c, RIGHT_X + 20, y + 14, "~84 MB per acquisition",
            size=7, color=TEXT_SUB); y += 28

    y = label_above(c, RIGHT_X, y, "Pre-capture Hooks")
    text_area_field(c, RIGHT_X, y, RIGHT_W - 10, 30); y += 38
    y = label_above(c, RIGHT_X, y, "Post-average Hooks")
    text_area_field(c, RIGHT_X, y, RIGHT_W - 10, 30)


def page_live_view(c):
    new_page(c, 6, 13, "\u2461 IMAGE ACQUISITION", "Live View")
    modality_badges(c, LEFT_X, BADGE_Y, tr=True, ir=True)
    ry = draw_more_options_divider(c)

    # ── PRIMARY ──
    y = CONTENT_Y
    prev_w = LEFT_W - 10
    prev_h = 480
    placeholder_image(c, LEFT_X, y, prev_w, prev_h, "Camera Preview")
    crosshair(c, LEFT_X + prev_w / 2, y + prev_h / 2, size=40, color=ACCENT)

    # Mode badge top-right of preview
    badge(c, LEFT_X + prev_w - 140, y + 8, "THERMOREFLECTANCE",
          fill=ACCENT, text_color=BLACK, font_size=7, h=16, radius=3)

    y += prev_h + 8
    # Camera info
    filled_rect(c, LEFT_X, y, prev_w, 22, fill=SURFACE2,
                stroke=BORDER, radius=3)
    text_at(c, LEFT_X + prev_w / 2, y + 12,
            "Basler acA1920-155um [TR]  |  30 fps  |  5.0 ms",
            size=8, color=TEXT_DIM, anchor="center")
    y += 30

    # Readiness banner
    filled_rect(c, LEFT_X, y, prev_w, 28, fill=Color(0.05, 0.25, 0.15),
                stroke=GREEN, radius=4)
    status_dot(c, LEFT_X + 14, y + 14, GREEN, r=5)
    text_at(c, LEFT_X + 28, y + 15, "READY TO ACQUIRE",
            size=10, color=GREEN, font="Helvetica-Bold")

    # ── MORE OPTIONS ──
    y = ry
    y = label_above(c, RIGHT_X, y, "Display Mode")
    radio_buttons(c, RIGHT_X, y,
                  ["Auto Contrast", "Fixed 12-bit"],
                  selected_idx=0, gap=20); y += 48

    y = section_header(c, RIGHT_X, y, RIGHT_W, "Overlays"); y += 4
    checkbox(c, RIGHT_X, y, "Crosshair", checked=True); y += 22
    checkbox(c, RIGHT_X, y, "Grid overlay", checked=False); y += 22
    checkbox(c, RIGHT_X, y, "Scale bar", checked=True); y += 30

    y = label_above(c, RIGHT_X, y, "False Color LUT")
    dropdown(c, RIGHT_X, y, 200, 24, "Grayscale"); y += 36

    button(c, RIGHT_X, y, 140, 28, "Save Frame...",
           fill=SURFACE3, text_color=TEXT, border=BORDER)


def page_focus_stage(c):
    new_page(c, 7, 13, "\u2461 IMAGE ACQUISITION", "Focus & Stage")
    modality_badges(c, LEFT_X, BADGE_Y, tr=True, ir=True)
    ry = draw_more_options_divider(c)

    # ── PRIMARY — split left half into Focus / Stage ──
    mid = LEFT_X + LEFT_W // 2
    y = CONTENT_Y

    # -- Focus --
    text_at(c, LEFT_X, y + 10, "Focus", size=11, color=TEXT,
            font="Helvetica-Bold")
    y += 24
    button(c, LEFT_X, y, 160, 34, "Autofocus",
           fill=ACCENT, text_color=BLACK, border=ACCENT, font_size=11)
    y += 46
    y = label_above(c, LEFT_X, y, "Focus Score")
    text_at(c, LEFT_X, y + 2, "82 / 100", size=16,
            color=ACCENT, font="Helvetica-Bold")
    # bar
    filled_rect(c, LEFT_X, y + 22, 200, 8, fill=SURFACE3, radius=3)
    filled_rect(c, LEFT_X, y + 22, 164, 8, fill=ACCENT, radius=3)
    y += 42
    button(c, LEFT_X, y, 160, 26, "Optimize Throughput",
           fill=SURFACE3, text_color=TEXT, border=BORDER)
    y += 34
    button(c, LEFT_X, y, 140, 26, "Run FFC",
           fill=SURFACE3, text_color=TEXT, border=BORDER)
    text_at(c, LEFT_X + 150, y + 14, "(IR only)", size=8, color=TEXT_SUB)

    # -- Stage --
    sy = CONTENT_Y
    sx = mid + 10
    text_at(c, sx, sy + 10, "Stage", size=11, color=TEXT,
            font="Helvetica-Bold")
    sy += 24
    label_value(c, sx, sy, "X:", "1240 \u03bcm", label_w=24); sy += 18
    label_value(c, sx, sy, "Y:", "890 \u03bcm", label_w=24); sy += 18
    label_value(c, sx, sy, "Z:", "0 \u03bcm", label_w=24); sy += 28

    # XY jog pad (cross of 4 arrow buttons)
    jc_x = sx + 60  # center
    jc_y = sy + 40
    bs = 32
    button(c, jc_x - bs // 2, jc_y - bs - 2, bs, bs, "\u25b2",
           fill=SURFACE3, text_color=TEXT, border=BORDER)  # up
    button(c, jc_x - bs // 2, jc_y + 4, bs, bs, "\u25bc",
           fill=SURFACE3, text_color=TEXT, border=BORDER)  # down
    button(c, jc_x - bs - 2, jc_y - bs // 2 + 1, bs, bs, "\u25c0",
           fill=SURFACE3, text_color=TEXT, border=BORDER)  # left
    button(c, jc_x + 4, jc_y - bs // 2 + 1, bs, bs, "\u25b6",
           fill=SURFACE3, text_color=TEXT, border=BORDER)  # right

    sy = jc_y + bs + 16
    sy = label_above(c, sx, sy, "Step Size")
    dropdown(c, sx, sy, 140, 24, "10 \u03bcm"); sy += 34
    button(c, sx, sy, 120, 28, "Home All",
           fill=SURFACE3, text_color=TEXT, border=BORDER)

    # ── MORE OPTIONS ──
    y = ry
    y = label_above(c, RIGHT_X, y, "Z Fine Jog")
    button(c, RIGHT_X, y, 40, 24, "\u25b2",
           fill=SURFACE3, text_color=TEXT, border=BORDER)
    button(c, RIGHT_X + 48, y, 40, 24, "\u25bc",
           fill=SURFACE3, text_color=TEXT, border=BORDER)
    spinbox(c, RIGHT_X + 100, y, 100, 24, "1.0", suffix=" \u03bcm")
    y += 36
    y = label_above(c, RIGHT_X, y, "AF Algorithm")
    dropdown(c, RIGHT_X, y, 260, 24, "Laplacian variance"); y += 34
    checkbox(c, RIGHT_X, y, "Backlash compensation",
             checked=False); y += 30

    y = label_above(c, RIGHT_X, y, "Move to Absolute")
    spinbox(c, RIGHT_X, y, 90, 22, "0", suffix=" X")
    spinbox(c, RIGHT_X + 96, y, 90, 22, "0", suffix=" Y")
    spinbox(c, RIGHT_X + 192, y, 90, 22, "0", suffix=" Z")
    button(c, RIGHT_X + 290, y, 50, 22, "Go",
           fill=ACCENT, text_color=BLACK, border=ACCENT)
    y += 34
    y = label_above(c, RIGHT_X, y, "ROI for Autofocus")
    dropdown(c, RIGHT_X, y, 200, 24, "Full frame"); y += 34

    y = label_above(c, RIGHT_X, y, "Home Options")
    button(c, RIGHT_X, y, 100, 24, "Home XY",
           fill=SURFACE3, text_color=TEXT, border=BORDER)
    button(c, RIGHT_X + 110, y, 100, 24, "Home Z",
           fill=SURFACE3, text_color=TEXT, border=BORDER)


def page_signal_check(c):
    new_page(c, 8, 13, "\u2461 IMAGE ACQUISITION", "Signal Check")
    modality_badges(c, LEFT_X, BADGE_Y, tr=True, ir=True)
    ry = draw_more_options_divider(c)

    # ── PRIMARY ──
    y = CONTENT_Y
    button(c, LEFT_X, y, 200, 40, "Verify Signal",
           fill=ACCENT, text_color=BLACK, border=ACCENT, font_size=13)
    y += 56

    y = section_header(c, LEFT_X, y, LEFT_W, "Result"); y += 6
    y = label_above(c, LEFT_X, y, "SNR")
    text_at(c, LEFT_X, y + 2, "23.4 dB", size=22,
            color=GREEN, font="Helvetica-Bold")
    y += 34
    status_dot(c, LEFT_X + 4, y + 4, GREEN, r=5)
    text_at(c, LEFT_X + 18, y + 4, "SIGNAL DETECTED", size=11,
            color=GREEN, font="Helvetica-Bold")
    y += 30

    # Mini previews side by side
    y = label_above(c, LEFT_X, y, "Mini \u0394R/R Preview")
    placeholder_image(c, LEFT_X, y, 240, 160, "\u0394R/R thermal map")
    placeholder_image(c, LEFT_X + 260, y, 240, 160, "Histogram")
    # simulated histogram bars
    hx = LEFT_X + 270
    hy_base = y + 150
    for i in range(12):
        bh = [20, 40, 70, 100, 130, 110, 80, 55, 35, 20, 10, 5][i]
        filled_rect(c, hx + i * 18, hy_base - bh, 14, bh,
                    fill=ACCENT, radius=1)

    # ── MORE OPTIONS ──
    y = ry
    y = section_header(c, RIGHT_X, y, RIGHT_W, "Per-channel Breakdown (RGB)")
    y += 4
    label_value(c, RIGHT_X, y, "R:", "21.2 dB", label_w=24); y += 18
    label_value(c, RIGHT_X, y, "G:", "24.8 dB", label_w=24); y += 18
    label_value(c, RIGHT_X, y, "B:", "19.1 dB", label_w=24); y += 30

    y = label_above(c, RIGHT_X, y, "Noise Spectrum")
    placeholder_image(c, RIGHT_X, y, RIGHT_W - 10, 100,
                      "Noise spectrum chart"); y += 112

    button(c, RIGHT_X, y, 140, 26, "Define ROI",
           fill=SURFACE3, text_color=TEXT, border=BORDER); y += 36

    label_value(c, RIGHT_X, y, "Dark pixel count:", "142 px (0.6%)",
                label_w=120); y += 20
    label_value(c, RIGHT_X, y, "Frame rejection rate:", "2 / 100 (2%)",
                label_w=140)


def page_capture(c):
    new_page(c, 9, 13, "\u2462 MEASUREMENT & ANALYSIS", "Capture")
    modality_badges(c, LEFT_X, BADGE_Y, tr=True, ir=True)
    ry = draw_more_options_divider(c)

    # ── PRIMARY ──
    y = CONTENT_Y
    button(c, LEFT_X, y, 200, 44, "Acquire",
           fill=GREEN, text_color=BLACK, border=GREEN, font_size=14)
    y += 58
    text_at(c, LEFT_X, y, "100 frames \u00d7 2 phases",
            size=10, color=TEXT); y += 22
    progress_bar(c, LEFT_X, y, LEFT_W - 20, 20, pct=0.5); y += 28
    text_at(c, LEFT_X, y, "Capturing cold phase... 50/100",
            size=9, color=ACCENT); y += 28

    y = label_above(c, LEFT_X, y, "Live Result Preview")
    placeholder_image(c, LEFT_X, y, 350, 220, "\u0394R/R thermal map")
    y_dd = y
    y += 230
    y = label_above(c, LEFT_X, y, "Color Map")
    dropdown(c, LEFT_X, y, 200, 24, "Thermal Delta")

    # ── MORE OPTIONS ──
    y = ry
    y = section_header(c, RIGHT_X, y, RIGHT_W, "Grid Mode"); y += 4
    checkbox(c, RIGHT_X, y, "Grid Scan", checked=False); y += 24
    text_at(c, RIGHT_X + 20, y, "(when checked)", size=7, color=TEXT_SUB)
    y += 14
    ix = RIGHT_X + 20
    spinbox(c, ix, y, 90, 22, "3", suffix=" cols")
    spinbox(c, ix + 100, y, 90, 22, "3", suffix=" rows"); y += 28
    spinbox(c, ix, y, 90, 22, "100", suffix=" \u03bcm X")
    spinbox(c, ix + 100, y, 90, 22, "100", suffix=" \u03bcm Y"); y += 28
    y = label_above(c, ix, y, "Overlap")
    spinbox(c, ix, y, 100, 22, "10", suffix=" %"); y += 36

    y = label_above(c, RIGHT_X, y, "Batch Naming")
    text_field(c, RIGHT_X, y, 300, 24,
               value="scan_{date}_{n}"); y += 34

    y = label_above(c, RIGHT_X, y, "Post-capture")
    radio_buttons(c, RIGHT_X, y,
                  ["Send to Analysis", "Save Only"],
                  selected_idx=0, gap=20)


def page_calibration(c):
    new_page(c, 10, 13, "\u2462 MEASUREMENT & ANALYSIS", "Calibration")
    modality_badges(c, LEFT_X, BADGE_Y, tr=True, ir=True)
    ry = draw_more_options_divider(c)

    # ── PRIMARY ──
    y = CONTENT_Y
    y = label_above(c, LEFT_X, y, "Preset Buttons")
    preset_row(c, LEFT_X, y,
               ["3-pt", "5-pt", "7-pt"],
               selected_idx=-1, btn_w=60, gap=4)
    # TR/IR specific presets
    bx = LEFT_X + 3 * 64 + 12
    button(c, bx, y, 70, 24, "TR Std", fill=SURFACE3,
           text_color=TEXT, border=GREEN, font_size=8)
    badge(c, bx + 74, y + 4, "TR", fill=GREEN, text_color=BLACK,
          font_size=6, h=14, radius=2)
    button(c, bx + 110, y, 70, 24, "IR Std", fill=SURFACE3,
           text_color=TEXT, border=BLUE, font_size=8)
    badge(c, bx + 184, y + 4, "IR", fill=BLUE, text_color=WHITE,
          font_size=6, h=14, radius=2)
    y += 38

    y = label_above(c, LEFT_X, y, "Temperature List")
    temps = [20, 40, 60, 80, 100, 120]
    for i, t in enumerate(temps):
        ty = y + i * 26
        filled_rect(c, LEFT_X, ty, 300, 22, fill=SURFACE2,
                    stroke=BORDER, radius=3)
        text_at(c, LEFT_X + 12, ty + 12, f"{t} \u00b0C",
                size=9, color=TEXT)
        button(c, LEFT_X + 264, ty, 30, 22, "\u00d7",
               fill=SURFACE3, text_color=ERROR, border=BORDER, font_size=9)
    y += len(temps) * 26 + 8

    y = label_above(c, LEFT_X, y, "Add Temperature")
    spinbox(c, LEFT_X, y, 140, 24, "25.00", suffix=" \u00b0C")
    button(c, LEFT_X + 150, y, 70, 24, "+ Add",
           fill=ACCENT, text_color=BLACK, border=ACCENT); y += 36

    button(c, LEFT_X, y, 180, 34, "Start Calibration",
           fill=GREEN, text_color=BLACK, border=GREEN, font_size=11)
    y += 42
    text_at(c, LEFT_X, y, "Estimated time: ~11 min 30 s",
            size=9, color=TEXT_DIM)
    text_at(c, LEFT_X, y + 14, "(6 steps \u00d7 [35s ramp + 60s settle])",
            size=8, color=TEXT_SUB)

    # ── MORE OPTIONS ──
    y = ry
    y = label_above(c, RIGHT_X, y, "Per-step Settle Time")
    spinbox(c, RIGHT_X, y, 160, 24, "60", suffix=" s"); y += 34
    y = label_above(c, RIGHT_X, y, "Ramp Rate Override")
    spinbox(c, RIGHT_X, y, 160, 24, "5.0", suffix=" \u00b0C/min"); y += 34
    checkbox(c, RIGHT_X, y,
             "Use different exposure per step", checked=False); y += 34
    button(c, RIGHT_X, y, 160, 26, "Save Calibration...",
           fill=SURFACE3, text_color=TEXT, border=BORDER)
    button(c, RIGHT_X + 170, y, 160, 26, "Load Calibration...",
           fill=SURFACE3, text_color=TEXT, border=BORDER)


def page_sessions(c):
    new_page(c, 11, 13, "\u2462 MEASUREMENT & ANALYSIS", "Sessions")
    modality_badges(c, LEFT_X, BADGE_Y, tr=True, ir=True)
    ry = draw_more_options_divider(c)

    # ── PRIMARY ──
    # Left: session cards, Right: detail
    y = CONTENT_Y
    card_w = 280
    cards = [
        ("GaN HEMT Sweep 25\u00b0C", "24.1 dB", "2026-03-25 14:32"),
        ("GaN HEMT Sweep 50\u00b0C", "22.8 dB", "2026-03-25 14:45"),
        ("Baseline Reference", "26.3 dB", "2026-03-24 09:10"),
    ]
    for i, (title, snr, date) in enumerate(cards):
        cy = y + i * 82
        sel = (i == 0)
        fill = SURFACE3 if sel else SURFACE2
        border = ACCENT if sel else BORDER
        filled_rect(c, LEFT_X, cy, card_w, 74, fill=fill,
                    stroke=border, radius=4)
        # thumbnail placeholder
        filled_rect(c, LEFT_X + 6, cy + 6, 56, 56, fill=SURFACE,
                    stroke=BORDER, radius=2)
        text_at(c, LEFT_X + 6 + 28, cy + 34, "\u25a3",
                size=16, color=TEXT_SUB, anchor="center")
        # text
        text_at(c, LEFT_X + 70, cy + 18, title,
                size=9, color=TEXT, font="Helvetica-Bold")
        badge(c, LEFT_X + 70, cy + 28, f"SNR {snr}",
              fill=GREEN, text_color=BLACK, font_size=7, h=14, radius=2)
        text_at(c, LEFT_X + 70, cy + 56, date,
                size=8, color=TEXT_DIM)

    # Right detail (within primary area)
    dx = LEFT_X + card_w + 16
    dw = LEFT_W - card_w - 16
    text_at(c, dx, y + 12, "GaN HEMT Sweep 25\u00b0C",
            size=11, color=TEXT, font="Helvetica-Bold")

    # Tabs
    ty = y + 24
    tabs = ["Cold", "Hot", "Diff", "\u0394R/R", "Metadata"]
    for i, t in enumerate(tabs):
        sel = (i == 3)  # ΔR/R active
        fill = ACCENT if sel else SURFACE3
        tc = BLACK if sel else TEXT
        button(c, dx + i * 60, ty, 56, 22, t,
               fill=fill, text_color=tc, border=BORDER, font_size=8)
    ty += 30

    placeholder_image(c, dx, ty, dw, 140, "\u0394R/R image")
    ty += 150

    # Tags
    ty = label_above(c, dx, ty, "Tags")
    for i, tag in enumerate(["25\u00b0C", "GaN", "HEMT"]):
        bw = badge(c, dx + i * 56, ty, tag, fill=SURFACE3,
                   text_color=TEXT, font_size=7, h=16, radius=8, pad_x=8)
    ty += 26

    # Note
    ty = label_above(c, dx, ty, "Notes (1)")
    filled_rect(c, dx, ty, dw, 30, fill=SURFACE, stroke=BORDER, radius=3)
    text_at(c, dx + 8, ty + 16, "Initial sweep at room temp",
            size=8, color=TEXT_DIM)

    # ── MORE OPTIONS ──
    y = ry
    y = label_above(c, RIGHT_X, y, "Sort")
    dropdown(c, RIGHT_X, y, 240, 24, "By date (newest)"); y += 34
    y = label_above(c, RIGHT_X, y, "Filter")
    text_field(c, RIGHT_X, y, 240, 24); y += 34

    button(c, RIGHT_X, y, 150, 26, "Compare Mode",
           fill=SURFACE3, text_color=TEXT, border=BORDER); y += 38

    y = label_above(c, RIGHT_X, y, "Export")
    for i, lbl in enumerate(["PNG", "CSV", "HDF5", "PDF Report"]):
        bw = 70 if lbl == "PDF Report" else 50
        button(c, RIGHT_X + i * 58, y, bw, 24, lbl,
               fill=SURFACE3, text_color=TEXT, border=BORDER, font_size=8)
    y += 36

    button(c, RIGHT_X, y, 140, 26, "Reprocess",
           fill=SURFACE3, text_color=TEXT, border=BORDER)
    text_at(c, RIGHT_X + 150, y + 14, "(when raw frames available)",
            size=7, color=TEXT_SUB); y += 38

    y = section_header(c, RIGHT_X, y, RIGHT_W, "Batch Operations"); y += 4
    checkbox(c, RIGHT_X, y, "Select multiple", checked=False); y += 26
    button(c, RIGHT_X, y, 130, 24, "Delete Selected",
           fill=SURFACE3, text_color=ERROR, border=BORDER, font_size=8)
    button(c, RIGHT_X + 140, y, 130, 24, "Export Selected",
           fill=SURFACE3, text_color=TEXT, border=BORDER, font_size=8)


def page_emissivity(c):
    new_page(c, 12, 13, "\u2462 MEASUREMENT & ANALYSIS", "Emissivity")
    # IR only
    modality_badges(c, LEFT_X, BADGE_Y, tr=False, ir=True)
    badge(c, LEFT_X + 40, BADGE_Y, "IR ONLY", fill=BLUE, text_color=WHITE,
          font_size=8, h=18, radius=4)
    ry = draw_more_options_divider(c)

    # ── PRIMARY ──
    y = CONTENT_Y
    y = label_above(c, LEFT_X, y, "Known Emissivity")
    spinbox(c, LEFT_X, y, 140, 26, "0.95"); y += 38
    y = label_above(c, LEFT_X, y, "Material Preset")
    dropdown(c, LEFT_X, y, 280, 26, "Select material..."); y += 38
    y = label_above(c, LEFT_X, y, "Reference Temperature")
    spinbox(c, LEFT_X, y, 160, 26, "25.0", suffix=" \u00b0C"); y += 42

    button(c, LEFT_X, y, 200, 36, "Calibrate Emissivity",
           fill=ACCENT, text_color=BLACK, border=ACCENT, font_size=11)
    y += 50

    y = label_above(c, LEFT_X, y, "Current Emissivity Map")
    placeholder_image(c, LEFT_X, y, 350, 240, "Emissivity map")

    # ── MORE OPTIONS ──
    y = ry
    checkbox(c, RIGHT_X, y, "Per-pixel emissivity map",
             checked=False); y += 30
    y = label_above(c, RIGHT_X, y, "Reference Source")
    dropdown(c, RIGHT_X, y, 200, 24, "Blackbody"); y += 34
    y = label_above(c, RIGHT_X, y, "Wavelength Band")
    dropdown(c, RIGHT_X, y, 260, 24, "8\u201314 \u03bcm (LWIR)"); y += 40

    button(c, RIGHT_X, y, 180, 26, "Save Emissivity Map...",
           fill=SURFACE3, text_color=TEXT, border=BORDER)
    button(c, RIGHT_X + 190, y, 180, 26, "Load Emissivity Map...",
           fill=SURFACE3, text_color=TEXT, border=BORDER)


def page_settings(c):
    new_page(c, 13, 13, "SYSTEM", "Settings")
    modality_badges(c, LEFT_X, BADGE_Y, tr=True, ir=True)
    ry = draw_more_options_divider(c)

    # ── PRIMARY ──
    y = CONTENT_Y
    y = label_above(c, LEFT_X, y, "Theme")
    segmented_buttons(c, LEFT_X, y, ["Auto", "Dark", "Light"],
                      selected_idx=1, btn_w=80, gap=0); y += 40

    checkbox(c, LEFT_X, y,
             "Run pre-capture validation before each acquisition",
             checked=True); y += 28
    checkbox(c, LEFT_X, y, "Auto-focus before capture",
             checked=False)

    # ── MORE OPTIONS ──
    y = ry
    y = section_header(c, RIGHT_X, y, RIGHT_W, "AI Assistant"); y += 6
    text_at(c, RIGHT_X, y, "Status:", size=9, color=TEXT_DIM)
    status_dot(c, RIGHT_X + 50, y - 1, GREEN, r=4)
    text_at(c, RIGHT_X + 60, y, "Ready", size=9, color=GREEN); y += 20
    y = label_above(c, RIGHT_X, y, "Backend")
    dropdown(c, RIGHT_X, y, 260, 24, "Local (llama.cpp)"); y += 32
    button(c, RIGHT_X, y, 150, 24, "Download Model...",
           fill=SURFACE3, text_color=TEXT, border=BORDER); y += 30
    text_at(c, RIGHT_X, y, "Cloud API:", size=8, color=TEXT_DIM)
    button(c, RIGHT_X + 70, y - 4, 80, 22, "Connect",
           fill=SURFACE3, text_color=TEXT, border=BORDER, font_size=8)
    text_field(c, RIGHT_X + 160, y - 4, 180, 22,
               value="\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022")
    y += 24
    text_at(c, RIGHT_X, y, "Ollama:", size=8, color=TEXT_DIM)
    button(c, RIGHT_X + 70, y - 4, 80, 22, "Connect",
           fill=SURFACE3, text_color=TEXT, border=BORDER, font_size=8)
    text_field(c, RIGHT_X + 160, y - 4, 180, 22,
               value="http://localhost:11434")
    y += 30

    y = section_header(c, RIGHT_X, y, RIGHT_W, "Software Updates"); y += 6
    y = label_above(c, RIGHT_X, y, "Channel")
    dropdown(c, RIGHT_X, y, 160, 24, "Stable"); y += 32
    y = label_above(c, RIGHT_X, y, "Frequency")
    dropdown(c, RIGHT_X, y, 160, 24, "Weekly"); y += 32
    button(c, RIGHT_X, y, 120, 24, "Check Now",
           fill=SURFACE3, text_color=TEXT, border=BORDER); y += 34

    y = section_header(c, RIGHT_X, y, RIGHT_W, "Data & Storage"); y += 6
    y = label_above(c, RIGHT_X, y, "Sessions Directory")
    text_field(c, RIGHT_X, y, 320, 22,
               value="/Users/data/sessions")
    button(c, RIGHT_X + 330, y, 80, 22, "Browse...",
           fill=SURFACE3, text_color=TEXT, border=BORDER, font_size=8)
    y += 30
    y = label_above(c, RIGHT_X, y, "Auto-save Interval")
    spinbox(c, RIGHT_X, y, 120, 22, "5", suffix=" min"); y += 34

    y = section_header(c, RIGHT_X, y, RIGHT_W, "Support"); y += 6
    text_at(c, RIGHT_X, y, "Version:", size=9, color=TEXT_DIM)
    text_at(c, RIGHT_X + 60, y, "1.5.0-beta.1", size=9,
            color=TEXT, font="Helvetica-Bold")
    button(c, RIGHT_X + 160, y - 4, 50, 20, "Copy",
           fill=SURFACE3, text_color=TEXT, border=BORDER, font_size=7)
    y += 28
    for i, lbl in enumerate(["Documentation", "Feedback",
                              "License", "About"]):
        button(c, RIGHT_X + i * 100, y, 94, 24, lbl,
               fill=SURFACE3, text_color=TEXT, border=BORDER, font_size=8)


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    c = Canvas(str(OUT), pagesize=(W, H))

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
        page_sessions,
        page_emissivity,
        page_settings,
    ]

    for i, draw_fn in enumerate(pages):
        draw_fn(c)
        if i < len(pages) - 1:
            c.showPage()

    c.save()
    print(f"Wrote {len(pages)} pages to {OUT}")


if __name__ == "__main__":
    main()
