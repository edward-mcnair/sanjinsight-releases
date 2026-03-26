"""
Shared drawing helpers for SanjINSIGHT wireframe PDFs.

All coordinates use reportlab's bottom-left origin.  Helper functions
accept top-left-style (x, y_from_top) and convert internally so the
calling code reads like a normal UI layout (top-to-bottom).
"""
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.colors import Color

# ── Page geometry ─────────────────────────────────────────────────────
W, H = 1200, 800  # landscape points

# ── Dark-theme palette ────────────────────────────────────────────────
BG        = Color(0.11, 0.11, 0.12)       # #1c1c1e  — app background
SURFACE   = Color(0.18, 0.18, 0.19)       # #2d2d30  — panels
SURFACE2  = Color(0.22, 0.22, 0.24)       # #38383c  — elevated
SURFACE3  = Color(0.26, 0.26, 0.28)       # #424246  — cards / hover
BORDER    = Color(0.28, 0.28, 0.30)       # #484848
TEXT      = Color(0.92, 0.92, 0.92)       # #ebebeb
TEXT_DIM  = Color(0.60, 0.60, 0.60)       # #999999
TEXT_SUB  = Color(0.42, 0.42, 0.42)       # #6a6a6a
ACCENT    = Color(0.00, 0.83, 0.67)       # #00d4aa  — teal
ACCENT_DIM= Color(0.00, 0.50, 0.40)       # dimmed teal
WARNING   = Color(1.00, 0.70, 0.00)       # #ffb300  — amber
ERROR     = Color(1.00, 0.27, 0.27)       # #ff4444
GREEN     = Color(0.00, 0.83, 0.47)       # #00d479
WHITE     = Color(1, 1, 1)
BLACK     = Color(0, 0, 0)
ESTOP_BG  = Color(0.35, 0.00, 0.00)
ESTOP_FG  = Color(1.00, 0.27, 0.27)


# ── Coordinate helper ─────────────────────────────────────────────────

def Y(top_y: float) -> float:
    """Convert a top-down y coordinate to reportlab bottom-up."""
    return H - top_y


# ── Drawing primitives ────────────────────────────────────────────────

def filled_rect(c: Canvas, x, top_y, w, h,
                fill=SURFACE, stroke=None, radius=0):
    """Draw a filled (optionally rounded) rectangle."""
    y = Y(top_y) - h
    c.setFillColor(fill)
    if stroke:
        c.setStrokeColor(stroke)
        c.setLineWidth(1)
    else:
        c.setStrokeColor(fill)
        c.setLineWidth(0)
    if radius:
        c.roundRect(x, y, w, h, radius, stroke=1 if stroke else 0, fill=1)
    else:
        c.rect(x, y, w, h, stroke=1 if stroke else 0, fill=1)


def text_at(c: Canvas, x, top_y, label, size=10, color=TEXT,
            font="Helvetica", anchor="left"):
    """Draw a single line of text.  anchor: left | center | right."""
    c.setFont(font, size)
    c.setFillColor(color)
    y = Y(top_y) - size * 0.3          # fudge baseline
    if anchor == "center":
        c.drawCentredString(x, y, label)
    elif anchor == "right":
        c.drawRightString(x, y, label)
    else:
        c.drawString(x, y, label)


def hline(c: Canvas, x1, x2, top_y, color=BORDER, width=1):
    c.setStrokeColor(color)
    c.setLineWidth(width)
    y = Y(top_y)
    c.line(x1, y, x2, y)


def vline(c: Canvas, x, top_y1, top_y2, color=BORDER, width=1):
    c.setStrokeColor(color)
    c.setLineWidth(width)
    c.line(x, Y(top_y1), x, Y(top_y2))


def button(c: Canvas, x, top_y, w, h, label,
           fill=SURFACE3, text_color=TEXT, border=BORDER,
           font_size=9, radius=4):
    """Draw a button-shaped rounded rect with centred label."""
    filled_rect(c, x, top_y, w, h, fill=fill, stroke=border, radius=radius)
    text_at(c, x + w / 2, top_y + h / 2 + 1, label,
            size=font_size, color=text_color, anchor="center")


def status_dot(c: Canvas, x, top_y, color=GREEN, r=4):
    """Small filled circle."""
    c.setFillColor(color)
    c.setStrokeColor(color)
    c.circle(x, Y(top_y), r, stroke=0, fill=1)


def crosshair(c: Canvas, cx, top_cy, size=30, color=ACCENT):
    """Draw a thin crosshair."""
    cy = Y(top_cy)
    c.setStrokeColor(color)
    c.setLineWidth(0.75)
    c.line(cx - size, cy, cx + size, cy)
    c.line(cx, cy - size, cx, cy + size)
    # small centre circle
    c.circle(cx, cy, 4, stroke=1, fill=0)


# ── Reusable header bar ───────────────────────────────────────────────

def draw_header(c: Canvas, header_h=44):
    """Standard app header: logo · devices · e-stop."""
    filled_rect(c, 0, 0, W, header_h, fill=SURFACE2, stroke=BORDER)

    # Logo placeholder
    filled_rect(c, 16, 9, 120, 26, fill=SURFACE3, stroke=BORDER, radius=4)
    text_at(c, 36, 22, "microsanj", size=11, color=TEXT,
            font="Helvetica-Bold")

    # Connected Devices
    status_dot(c, W - 310, 22, GREEN)
    text_at(c, W - 300, 22, "Connected Devices (4/4)", size=9, color=TEXT)

    # Peripheral dots
    for i, (label, clr) in enumerate([
        ("TEC", GREEN), ("FPGA", GREEN), ("Bias", GREEN), ("Stage", GREEN)
    ]):
        bx = W - 180 + i * 40
        status_dot(c, bx, 22, clr, r=3)
        text_at(c, bx + 6, 22, label, size=7, color=TEXT_DIM)

    # E-Stop
    filled_rect(c, W - 16 - 80, 7, 80, 30, fill=ESTOP_BG,
                stroke=Color(0.67, 0, 0), radius=5)
    text_at(c, W - 16 - 40, 22, "STOP", size=12,
            color=ESTOP_FG, font="Helvetica-Bold", anchor="center")

    return header_h


def draw_status_bar(c: Canvas, bar_h=28):
    """Bottom status bar with BT / DT readout."""
    y_top = H - bar_h
    filled_rect(c, 0, y_top, W, bar_h, fill=SURFACE2, stroke=BORDER)
    text_at(c, 16, y_top + 15, "BT 39.4 C", size=9,
            color=WARNING, font="Helvetica-Bold")
    text_at(c, 110, y_top + 15, "DT -0.03 C", size=9, color=TEXT_DIM)
    vline(c, 100, y_top + 6, y_top + bar_h - 6)
    text_at(c, W - 16, y_top + 15, "TEC: 25.0 C  |  Stable",
            size=8, color=TEXT_DIM, anchor="right")
    return bar_h


# ── Small "inset" wireframe helpers ───────────────────────────────────

def draw_inset_configure(c: Canvas, x, top_y, w, h):
    """Tiny representation of the Configure phase layout."""
    filled_rect(c, x, top_y, w, h, fill=SURFACE, stroke=BORDER, radius=4)
    text_at(c, x + 6, top_y + 14, "Configure Phase", size=7,
            color=TEXT_DIM, font="Helvetica-Bold")
    # Section blocks
    sections = ["Modality", "Stimulus", "Timing", "Temperature", "Acquisition"]
    for i, s in enumerate(sections):
        sy = top_y + 24 + i * 18
        filled_rect(c, x + 6, sy, w - 12, 14, fill=SURFACE2,
                    stroke=BORDER, radius=2)
        text_at(c, x + 12, sy + 9, s, size=6, color=TEXT_DIM)


def badge(c: Canvas, x, top_y, label, fill=ACCENT, text_color=BLACK,
          font_size=7, pad_x=8, h=16, radius=3):
    """Small rounded badge (e.g., TR / IR / TR+IR)."""
    c.setFont("Helvetica-Bold", font_size)
    tw = c.stringWidth(label, "Helvetica-Bold", font_size)
    bw = tw + pad_x * 2
    filled_rect(c, x, top_y, bw, h, fill=fill, radius=radius)
    text_at(c, x + bw / 2, top_y + h / 2 + 1, label,
            size=font_size, color=text_color, font="Helvetica-Bold",
            anchor="center")
    return bw


def checkbox(c: Canvas, x, top_y, label, checked=False, size=10,
             color=TEXT, dim=False):
    """Wireframe checkbox."""
    bs = 11
    y = Y(top_y + bs / 2) - bs / 2
    if checked:
        filled_rect(c, x, top_y + (size - bs) / 2 + 2, bs, bs,
                    fill=ACCENT, radius=2)
        # checkmark
        c.setStrokeColor(WHITE)
        c.setLineWidth(1.5)
        cx_r, cy_r = x + bs / 2, y + bs / 2
        c.line(cx_r - 3, cy_r - 1, cx_r - 0.5, cy_r - 3.5)
        c.line(cx_r - 0.5, cy_r - 3.5, cx_r + 3.5, cy_r + 2.5)
    else:
        filled_rect(c, x, top_y + (size - bs) / 2 + 2, bs, bs,
                    fill=SURFACE, stroke=BORDER, radius=2)
    text_at(c, x + bs + 6, top_y + size / 2 + 2, label,
            size=size, color=TEXT_DIM if dim else color)


def spinbox(c: Canvas, x, top_y, w, h, value, suffix="",
            fill=SURFACE, border_color=BORDER):
    """Wireframe spinbox / number input."""
    filled_rect(c, x, top_y, w, h, fill=fill, stroke=border_color, radius=3)
    text_at(c, x + 6, top_y + h / 2 + 1, f"{value}{suffix}",
            size=8, color=TEXT)
    # up/down arrows area
    aw = 16
    vline(c, x + w - aw, top_y + 2, top_y + h - 2, color=border_color)
    text_at(c, x + w - aw / 2, top_y + h * 0.3, "\u25b2",
            size=5, color=TEXT_DIM, anchor="center")
    text_at(c, x + w - aw / 2, top_y + h * 0.75, "\u25bc",
            size=5, color=TEXT_DIM, anchor="center")


def dropdown(c: Canvas, x, top_y, w, h, value,
             fill=SURFACE, border_color=BORDER):
    """Wireframe dropdown / combobox."""
    filled_rect(c, x, top_y, w, h, fill=fill, stroke=border_color, radius=3)
    text_at(c, x + 8, top_y + h / 2 + 1, value, size=8, color=TEXT)
    text_at(c, x + w - 12, top_y + h / 2 + 1, "\u25bc",
            size=7, color=TEXT_DIM, anchor="center")


def slider_bar(c: Canvas, x, top_y, w, pos=0.5, h=6, color=ACCENT):
    """Wireframe slider track with thumb."""
    track_y = top_y
    filled_rect(c, x, track_y, w, h, fill=SURFACE3, radius=3)
    filled_rect(c, x, track_y, w * pos, h, fill=color, radius=3)
    # thumb
    thumb_x = x + w * pos
    c.setFillColor(WHITE)
    c.circle(thumb_x, Y(track_y + h / 2), 5, stroke=0, fill=1)


def section_header(c: Canvas, x, top_y, w, title, collapsed=False):
    """Section divider with title and collapse chevron."""
    hline(c, x, x + w, top_y, color=BORDER)
    text_at(c, x + 4, top_y + 14, title, size=9,
            color=TEXT, font="Helvetica-Bold")
    chevron = "\u25b6" if collapsed else "\u25bc"
    text_at(c, x + w - 8, top_y + 14, chevron,
            size=7, color=TEXT_DIM, anchor="right")
    return top_y + 20


def advanced_toggle(c: Canvas, x, top_y, w, expanded=False):
    """The 'Advanced' expand/collapse toggle button."""
    h = 24
    filled_rect(c, x, top_y, w, h, fill=SURFACE2, stroke=BORDER, radius=4)
    chevron = "\u25bc" if expanded else "\u25b6"
    text_at(c, x + w / 2 - 30, top_y + h / 2 + 1,
            f"{chevron}  Advanced", size=9, color=ACCENT,
            font="Helvetica-Bold")
    return top_y + h + 6


def draw_inset_measure(c: Canvas, x, top_y, w, h):
    """Tiny representation of the Measure & Analyze phase layout."""
    filled_rect(c, x, top_y, w, h, fill=SURFACE, stroke=BORDER, radius=4)
    text_at(c, x + 6, top_y + 14, "Measure Phase", size=7,
            color=TEXT_DIM, font="Helvetica-Bold")
    mid = x + w // 2
    # Left: sweep builder
    filled_rect(c, x + 6, top_y + 22, mid - x - 10, h - 28,
                fill=SURFACE2, stroke=BORDER, radius=2)
    text_at(c, x + 12, top_y + 36, "Sweep Builder", size=6, color=TEXT_DIM)
    # Right: results
    filled_rect(c, mid + 4, top_y + 22, x + w - mid - 10, h - 28,
                fill=SURFACE2, stroke=BORDER, radius=2)
    text_at(c, mid + 10, top_y + 36, "Results / Charts", size=6,
            color=TEXT_DIM)
