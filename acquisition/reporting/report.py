"""
acquisition/report.py

Generates a professional PDF report for a thermoreflectance session.

Layout (2 pages):
    Page 1 — Header (logo + title), session metadata table,
              ΔR/R image with colour scale, SNR indicator
    Page 2 — Cold baseline, Hot stimulus, Difference images side-by-side,
              ΔT calibrated map (if available), notes section

Usage:
    from acquisition.report import generate_report
    path = generate_report(session, output_dir=".", calibration=cal_result)
    # Returns path to the saved PDF
"""

from __future__ import annotations
import os, time, tempfile
import numpy as np
from dataclasses import dataclass, field
from typing import Optional

from reportlab.lib.pagesizes   import A4
from reportlab.lib.units       import mm
from reportlab.lib             import colors
from reportlab.lib.styles      import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums       import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus        import (SimpleDocTemplate, Paragraph, Spacer,
                                       Table, TableStyle, Image as RLImage,
                                       HRFlowable, PageBreak, KeepTogether)
from reportlab.pdfgen          import canvas as rl_canvas

from acquisition.storage.session        import Session
from acquisition.calibration.calibration import CalibrationResult
from acquisition.processing.processing   import to_display
from acquisition.processing.image_rendering import render_to_tmpfile


# ------------------------------------------------------------------ #
#  Colour palette (matches app dark theme, but on white paper)        #
# ------------------------------------------------------------------ #

TEAL   = colors.HexColor("#00a88a")   # Microsanj teal
DARK   = colors.HexColor("#1a1a2e")   # Near-black for headings
MID    = colors.HexColor("#4a4a6a")   # Mid-grey for sub-headings
LIGHT  = colors.HexColor("#e8e8f0")   # Light fill for table rows
WHITE  = colors.white
BLACK  = colors.black

PW, PH = A4                            # 595 × 842 pt
MARGIN = 18 * mm


# ------------------------------------------------------------------ #
#  Report configuration                                              #
# ------------------------------------------------------------------ #

@dataclass
class ReportConfig:
    """User-configurable report content and metadata."""
    # Content toggles
    thermal_map: bool = True
    hotspot_table: bool = True
    measurement_params: bool = True
    device_info: bool = True
    raw_data_summary: bool = False
    verdict_and_recommendations: bool = True
    calibration_details: bool = False
    quality_scorecard: bool = True

    # Cube-modality sections (transient / movie)
    transient_section: bool = True
    movie_section: bool = True

    # Format
    format: str = "pdf"  # "pdf" | "html"

    # Metadata overrides (empty = use session values)
    operator: str = ""
    customer: str = ""
    notes: str = ""


# ------------------------------------------------------------------ #
#  Helpers                                                            #
# ------------------------------------------------------------------ #

def _array_to_tmpimg(data: np.ndarray, mode: str = "percentile",
                     cmap: str = "Thermal Delta", size: tuple = (300, 220)) -> str:
    """Convert a numpy array to a temp PNG file and return its path.

    Delegates to :func:`render_to_tmpfile` from the shared image-rendering
    module.
    """
    tw, th = size
    return render_to_tmpfile(
        data, mode=mode, colormap=cmap, width=tw, height=th,
    )


def _logo_png(logo_svg: str, width_px: int = 240) -> Optional[str]:
    """
    Rasterise the SVG logo to a temp PNG using PyQt5.QtSvg.
    Returns the PNG path, or None if rendering fails.
    """
    if not logo_svg or not os.path.exists(logo_svg):
        return None
    try:
        from PyQt5.QtSvg     import QSvgRenderer
        from PyQt5.QtGui     import QImage, QPainter, QColor
        from PyQt5.QtCore    import Qt, QSize
        from PyQt5.QtWidgets import QApplication
        import sys

        # Ensure a QApplication exists
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)

        renderer = QSvgRenderer(logo_svg)
        vb       = renderer.viewBoxF()
        ratio    = vb.height() / vb.width() if vb.width() else 0.22
        height_px = max(1, int(width_px * ratio))

        img = QImage(width_px, height_px, QImage.Format_ARGB32)
        img.fill(QColor(0, 0, 0, 0))   # transparent background

        p = QPainter(img)
        renderer.render(p)
        p.end()

        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        img.save(tmp.name)
        tmp.close()
        return tmp.name
    except Exception:
        return None


def _colourbar_png(lo: float, hi: float,
                   width_px: int = 400, height_px: int = 20,
                   signed: bool = True) -> Optional[str]:
    """Generate a horizontal colour bar PNG."""
    try:
        bar = np.zeros((height_px, width_px, 3), dtype=np.uint8)
        for x in range(width_px):
            t = x / (width_px - 1)
            if signed:
                v  = t * 2 - 1          # -1 … +1
                r  = int(max(0,  v) * 255)
                b  = int(max(0, -v) * 255)
                g  = 0
            else:
                r = int(t * 255)
                g = int(t * 200)
                b = 0
            bar[:, x] = [b, g, r]   # BGR for cv2

        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        try:
            import cv2
            cv2.imwrite(tmp.name, bar)
        except ImportError:
            from PIL import Image as PILImage
            PILImage.fromarray(bar[:, :, ::-1]).save(tmp.name)
        tmp.close()
        return tmp.name
    except Exception:
        return None


# ------------------------------------------------------------------ #
#  Style helpers                                                       #
# ------------------------------------------------------------------ #

def _styles():
    base = getSampleStyleSheet()
    s = {}

    s["title"] = ParagraphStyle(
        "ReportTitle",
        fontSize=20, leading=24, textColor=DARK,
        fontName="Helvetica-Bold", spaceAfter=2*mm)

    s["subtitle"] = ParagraphStyle(
        "ReportSubtitle",
        fontSize=11, leading=14, textColor=MID,
        fontName="Helvetica", spaceAfter=4*mm)

    s["h1"] = ParagraphStyle(
        "H1", fontSize=13, leading=16, textColor=DARK,
        fontName="Helvetica-Bold",
        spaceBefore=4*mm, spaceAfter=2*mm)

    s["h2"] = ParagraphStyle(
        "H2", fontSize=10, leading=13, textColor=MID,
        fontName="Helvetica-Bold",
        spaceBefore=2*mm, spaceAfter=1*mm)

    s["body"] = ParagraphStyle(
        "Body", fontSize=9, leading=12, textColor=colors.HexColor("#333333"),
        fontName="Helvetica")

    s["mono"] = ParagraphStyle(
        "Mono", fontSize=8, leading=11, textColor=colors.HexColor("#333333"),
        fontName="Courier")

    s["caption"] = ParagraphStyle(
        "Caption", fontSize=7.5, leading=10, textColor=MID,
        fontName="Helvetica", alignment=TA_CENTER)

    s["footer"] = ParagraphStyle(
        "Footer", fontSize=7, leading=9, textColor=colors.HexColor("#aaaaaa"),
        fontName="Helvetica", alignment=TA_CENTER)

    return s


# ------------------------------------------------------------------ #
#  Page template (header bar + footer)                                #
# ------------------------------------------------------------------ #

class _ReportTemplate(SimpleDocTemplate):
    """Adds a teal top bar and footer to every page."""

    def __init__(self, path, logo_png, **kwargs):
        super().__init__(path, **kwargs)
        self._logo_png = logo_png
        self._page_no  = 0

    def handle_pageBegin(self):
        super().handle_pageBegin()
        self._page_no += 1

    def afterPage(self):
        c    = self.canv
        c.saveState()

        # Teal top bar
        c.setFillColor(DARK)
        c.rect(0, PH - 14*mm, PW, 14*mm, fill=1, stroke=0)

        # Logo in bar
        if self._logo_png and os.path.exists(self._logo_png):
            try:
                c.drawImage(self._logo_png,
                            MARGIN, PH - 11*mm,
                            width=38*mm, height=8*mm,
                            preserveAspectRatio=True, mask='auto')
            except Exception:
                pass

        # Title in bar
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(MARGIN + 42*mm, PH - 7.5*mm,
                     "Microsanj Thermal Analysis System")

        # Page number in bar (right)
        c.setFont("Helvetica", 8)
        c.setFillColor(colors.HexColor("#aaaacc"))
        c.drawRightString(PW - MARGIN, PH - 7.5*mm,
                          f"Page {self._page_no}")

        # Teal bottom rule
        c.setStrokeColor(TEAL)
        c.setLineWidth(1.5)
        c.line(MARGIN, 10*mm, PW - MARGIN, 10*mm)

        # Footer text
        c.setFont("Helvetica", 6.5)
        c.setFillColor(colors.HexColor("#aaaaaa"))
        ts = time.strftime("%Y-%m-%d %H:%M")
        c.drawCentredString(PW / 2, 7*mm,
                            f"Generated {ts}  ·  Microsanj Thermal Analysis System  "
                            f"·  CONFIDENTIAL")
        c.restoreState()


# ------------------------------------------------------------------ #
#  Main report generator                                              #
# ------------------------------------------------------------------ #

def generate_report(session: Session,
                    output_dir: str = ".",
                    calibration: Optional[CalibrationResult] = None,
                    logo_svg: Optional[str] = None,
                    analysis=None,
                    report_config: Optional[ReportConfig] = None,
                    quality_scorecard=None) -> str:
    """
    Generate a PDF report for the given session.

    session:       Session object (arrays loaded on demand)
    output_dir:    Directory to write the PDF into
    calibration:   Optional CalibrationResult for ΔT map
    logo_svg:      Path to microsanj-logo.svg (white, for header bar — auto-detected)
    analysis:      Optional AnalysisResult — adds a Pass/Fail page to the report
    report_config: Optional ReportConfig — controls which sections to include
    quality_scorecard: Optional QualityScorecard — adds a quality scorecard page

    Returns the path to the generated PDF.
    """
    cfg = report_config or ReportConfig()
    os.makedirs(output_dir, exist_ok=True)

    here = os.path.dirname(os.path.abspath(__file__))
    assets = os.path.join(here, "..", "assets")

    # White logo → dark header band on every page
    if logo_svg is None:
        logo_svg = os.path.join(assets, "microsanj-logo.svg")

    # Print logo → white title area on page 1
    print_svg = os.path.join(assets, "microsanj-logo-print.svg")

    logo_png       = _logo_png(logo_svg,   width_px=300)   # white, for dark bar
    print_logo_png = _logo_png(print_svg,  width_px=480)   # dark,  for white page

    meta      = session.meta
    styles    = _styles()
    tmp_files = []
    if logo_png:
        tmp_files.append(logo_png)
    if print_logo_png:
        tmp_files.append(print_logo_png)

    # Output filename
    safe_label = meta.label.replace(" ", "_").replace("/", "-")[:40]
    pdf_name   = f"{meta.uid}_{safe_label}.pdf"
    pdf_path   = os.path.join(output_dir, pdf_name)

    doc = _ReportTemplate(
        pdf_path,
        logo_png    = logo_png,
        pagesize    = A4,
        leftMargin  = MARGIN,
        rightMargin = MARGIN,
        topMargin   = 20 * mm,
        bottomMargin= 16 * mm,
    )

    story = []
    usable_w = PW - 2 * MARGIN

    # ================================================================ #
    #  PAGE 1                                                          #
    # ================================================================ #

    # ---- Report title block with print logo ----
    if print_logo_png and os.path.exists(print_logo_png):
        logo_w = 60 * mm
        logo_h = logo_w * (223 / 1040)   # preserve SVG aspect ratio
        title_row = Table(
            [[RLImage(print_logo_png, width=logo_w, height=logo_h),
              [Paragraph("Thermoreflectance Measurement Report", styles["title"]),
               Paragraph(meta.label, styles["subtitle"])]]],
            colWidths=[logo_w + 6*mm, usable_w - logo_w - 6*mm])
        title_row.setStyle(TableStyle([
            ("VALIGN",  (0, 0), (-1, -1), "MIDDLE"),
            ("PADDING", (0, 0), (-1, -1), 0),
            ("LEFTPADDING", (1, 0), (1, 0), 8),
        ]))
        story.append(title_row)
    else:
        story.append(Paragraph("Thermoreflectance Measurement Report", styles["title"]))
        story.append(Paragraph(meta.label, styles["subtitle"]))

    story.append(HRFlowable(width="100%", thickness=1.5,
                            color=TEAL, spaceAfter=4*mm))

    # ---- Metadata table ----
    snr_str  = f"{meta.snr_db:.1f} dB" if meta.snr_db else "—"
    roi_str  = (f"x={meta.roi['x']}  y={meta.roi['y']}  "
                f"w={meta.roi['w']}  h={meta.roi['h']}"
                if meta.roi else "Full frame")
    cal_str  = (f"{calibration.t_min:.1f}–{calibration.t_max:.1f}°C  "
                f"({calibration.n_points} pts)"
                if (calibration and calibration.valid) else "Not applied")

    # Instrument / DUT condition strings
    tec_str  = (f"{meta.tec_temperature:.1f}°C  "
                f"(setpoint {meta.tec_setpoint:.1f}°C)"
                if meta.tec_temperature else "—")
    bias_str = (f"{meta.bias_voltage:.3f} V  /  {meta.bias_current*1e3:.2f} mA"
                if (meta.bias_voltage or meta.bias_current) else "—")
    fpga_str = (f"{meta.fpga_frequency_hz/1e3:.1f} kHz  "
                f"({meta.fpga_duty_cycle*100:.0f}% duty)"
                if meta.fpga_frequency_hz else "—")
    wl_str   = f"{meta.wavelength_nm} nm" if meta.wavelength_nm else "—"
    mode_str = meta.imaging_mode.replace("_", " ").title() if meta.imaging_mode else "—"
    prof_str = meta.profile_name or "—"
    ct_str   = f"{meta.ct_value:.4e} K⁻¹" if meta.ct_value else "— (uncalibrated)"

    col_w = [28*mm, 52*mm, 28*mm, 52*mm]

    def _make_table(rows, alternate_from=0):
        tbl = Table(
            [[Paragraph(str(c), styles["body"]) for c in row]
             for row in rows],
            colWidths=col_w)
        style_cmds = [
            ("TEXTCOLOR",   (0, 0), (0, -1), MID),
            ("TEXTCOLOR",   (2, 0), (2, -1), MID),
            ("FONTNAME",    (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME",    (2, 0), (2, -1), "Helvetica-Bold"),
            ("FONTNAME",    (1, 0), (1, -1), "Courier"),
            ("FONTNAME",    (3, 0), (3, -1), "Courier"),
            ("FONTSIZE",    (0, 0), (-1, -1), 8.5),
            ("PADDING",     (0, 0), (-1, -1), 4),
            ("GRID",        (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
            ("ROWBACKGROUND", (0, 0), (-1, -1),
             [WHITE, colors.HexColor("#f8f8fc")]),
        ]
        for i in range(0, len(rows), 2):
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), LIGHT))
        tbl.setStyle(TableStyle(style_cmds))
        return tbl

    # Apply metadata overrides from report config
    if cfg.operator:
        meta.operator = cfg.operator
    report_customer = cfg.customer
    report_notes = cfg.notes or meta.notes

    if cfg.measurement_params:
        story.append(Paragraph("Acquisition Parameters", styles["h1"]))
        meta_rows = [
            ["Date / Time",    meta.timestamp_str,
             "Frame size",     f"{meta.frame_w} × {meta.frame_h} px"],
            ["Frames (N)",     str(meta.n_frames),
             "Exposure",       f"{meta.exposure_us:.0f} μs"],
            ["Duration",       f"{meta.duration_s:.1f} s",
             "Gain",           f"{meta.gain_db:.1f} dB"],
            ["SNR",            snr_str,
             "ROI",            roi_str],
            ["Calibration",    cal_str,
             "Session ID",     meta.uid[:28]],
        ]
        story.append(_make_table(meta_rows))
        story.append(Spacer(1, 3*mm))

    if cfg.device_info:
        story.append(Paragraph("Instrument & DUT Conditions", styles["h1"]))
        instrument_rows = [
            ["Imaging mode",   mode_str,
             "Wavelength",     wl_str],
            ["TEC temp",       tec_str,
             "Bias",           bias_str],
            ["FPGA modulation",fpga_str,
             "Material profile", prof_str],
            ["C_T coefficient",ct_str,
             "",               ""],
        ]
        if meta.operator or report_customer:
            instrument_rows.append(
                ["Operator", meta.operator or "—",
                 "Customer", report_customer or "—"])
        story.append(_make_table(instrument_rows))
        story.append(Spacer(1, 5*mm))

    # ---- ΔR/R main image ----
    drr = session.delta_r_over_r
    if cfg.thermal_map and drr is not None:
        story.append(Paragraph("Thermoreflectance Map  (ΔR/R)", styles["h1"]))
        img_path = _array_to_tmpimg(drr, mode="percentile", cmap="Thermal Delta",
                                    size=(600, 440))
        if img_path:
            tmp_files.append(img_path)
            img_w = usable_w * 0.72
            img_h = img_w * (440 / 600)
            story.append(RLImage(img_path, width=img_w, height=img_h))

            # Colour bar
            vmin = float(np.percentile(drr, 0.5))
            vmax = float(np.percentile(drr, 99.5))
            cb_path = _colourbar_png(vmin, vmax, signed=True)
            if cb_path:
                tmp_files.append(cb_path)
                cb_table = Table(
                    [[Paragraph(f"{vmin:.3e}", styles["caption"]),
                      RLImage(cb_path, width=img_w * 0.6, height=4*mm),
                      Paragraph(f"{vmax:.3e}", styles["caption"])]],
                    colWidths=[20*mm, img_w * 0.6, 20*mm])
                story.append(cb_table)

            story.append(Paragraph(
                "ΔR/R thermoreflectance map. Blue = negative (cooling), "
                "Red = positive (heating). Colour scale clipped to 0.5–99.5 percentile.",
                styles["caption"]))
    elif cfg.thermal_map:
        story.append(Paragraph("No ΔR/R data available.", styles["body"]))

    # ================================================================ #
    #  PAGE 2 — Supporting images & stats                              #
    # ================================================================ #

    # Compute ΔT early — needed by both raw_data_summary and calibration_details
    dt_arr = getattr(session, "_delta_t", None)
    if dt_arr is None and calibration and calibration.valid and drr is not None:
        try:
            dt_arr = calibration.apply(drr)
        except Exception:
            dt_arr = None

    if cfg.raw_data_summary:
        story.append(PageBreak())

        if print_logo_png and os.path.exists(print_logo_png):
            logo_w2 = 40 * mm
            logo_h2 = logo_w2 * (223 / 1040)
            story.append(RLImage(print_logo_png, width=logo_w2, height=logo_h2))
            story.append(Spacer(1, 2*mm))

        story.append(Paragraph("Supporting Images", styles["h1"]))

        panel_w = (usable_w - 6*mm) / 3
        panel_h = panel_w * (220 / 300)

        panels = []
        for arr, label, mode, cmap in [
            (session.cold_avg,   "Cold  (baseline)",   "auto",       "gray"),
            (session.hot_avg,    "Hot  (stimulus)",    "auto",       "gray"),
            (session.difference, "Difference  (H−C)",  "percentile", "signed"),
        ]:
            if arr is not None:
                p = _array_to_tmpimg(arr, mode=mode, cmap=cmap,
                                      size=(300, 220))
                if p:
                    tmp_files.append(p)
                    cell = [RLImage(p, width=panel_w, height=panel_h),
                            Paragraph(label, styles["caption"])]
                else:
                    cell = [Paragraph(f"{label}\n(render failed)",
                                      styles["caption"])]
            else:
                cell = [Paragraph(f"{label}\n(no data)", styles["caption"])]
            panels.append(cell)

        if panels:
            panel_tbl = Table([
                [panels[0][0], panels[1][0], panels[2][0]],
                [panels[0][1], panels[1][1], panels[2][1]],
            ], colWidths=[panel_w] * 3)
            panel_tbl.setStyle(TableStyle([
                ("ALIGN",   (0, 0), (-1, -1), "CENTER"),
                ("VALIGN",  (0, 0), (-1, -1), "MIDDLE"),
                ("PADDING", (0, 0), (-1, -1), 2),
            ]))
            story.append(panel_tbl)
            story.append(Spacer(1, 4*mm))

    if cfg.calibration_details and dt_arr is not None:
        story.append(Paragraph(
            "Calibrated Temperature Map  (ΔT, °C)", styles["h1"]))
        dt_path = _array_to_tmpimg(dt_arr, mode="percentile", cmap="Thermal Delta",
                                    size=(600, 440))
        if dt_path:
            tmp_files.append(dt_path)
            story.append(KeepTogether([
                RLImage(dt_path, width=usable_w * 0.72,
                        height=usable_w * 0.72 * (440/600)),
                Spacer(1, 1*mm),
                Paragraph(
                    f"Calibrated ΔT map derived from ΔR/R using C<sub>T</sub> "
                    f"coefficient map  "
                    f"(calibration range {calibration.t_min:.1f}–"
                    f"{calibration.t_max:.1f}°C, "
                    f"{calibration.n_points} temperature points).",
                    styles["caption"]),
            ]))
        story.append(Spacer(1, 4*mm))

    # ---- Stats table ----
    if cfg.raw_data_summary:
        story.append(Paragraph("Signal Statistics", styles["h1"]))
        stats_rows = [["Metric", "ΔR/R",
                        "ΔT (°C)" if dt_arr is not None else ""]]

        def _fmt(arr):
            if arr is None:
                return ["—"] * 4
            flat = arr.ravel()
            flat = flat[np.isfinite(flat)]
            if len(flat) == 0:
                return ["—"] * 4
            return [f"{float(np.min(flat)):.4e}",
                    f"{float(np.max(flat)):.4e}",
                    f"{float(np.mean(flat)):.4e}",
                    f"{float(np.std(flat)):.4e}"]

        drr_s = _fmt(drr)
        dt_s  = _fmt(dt_arr)

        for i, lbl in enumerate(["Min", "Max", "Mean", "Std Dev"]):
            row = [lbl, drr_s[i] if i < len(drr_s) else "—"]
            if dt_arr is not None:
                row.append(dt_s[i] if i < len(dt_s) else "—")
            stats_rows.append(row)

        stats_cw = ([30*mm, 50*mm, 50*mm] if dt_arr is not None
                     else [30*mm, 50*mm])
        stats_tbl = Table(
            [[Paragraph(str(c), styles["body"]) for c in row]
             for row in stats_rows],
            colWidths=stats_cw)
        stats_tbl.setStyle(TableStyle([
            ("BACKGROUND",  (0, 0), (-1, 0), DARK),
            ("TEXTCOLOR",   (0, 0), (-1, 0), WHITE),
            ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME",    (1, 1), (-1, -1), "Courier"),
            ("FONTSIZE",    (0, 0), (-1, -1), 8.5),
            ("PADDING",     (0, 0), (-1, -1), 4),
            ("ROWBACKGROUND", (0, 1), (-1, -1),
             [WHITE, colors.HexColor("#f4f4f8")]),
            ("GRID",        (0, 0), (-1, -1), 0.25,
             colors.HexColor("#dddddd")),
        ]))
        story.append(stats_tbl)
        story.append(Spacer(1, 5*mm))

    # ---- Notes ----
    if report_notes:
        story.append(Paragraph("Notes", styles["h1"]))
        story.append(Paragraph(report_notes, styles["body"]))

    # ================================================================ #
    #  Pass / Fail Analysis page (optional)                            #
    # ================================================================ #

    if cfg.verdict_and_recommendations and analysis is not None and analysis.valid:
        story.append(PageBreak())
        story.append(Paragraph("Pass / Fail Thermal Analysis", styles["h1"]))
        story.append(Spacer(1, 3*mm))

        # Verdict block
        VERDICT_COLORS_PDF = {
            "PASS":    colors.HexColor("#00c070"),
            "WARNING": colors.HexColor("#ffb300"),
            "FAIL":    colors.HexColor("#e03030"),
        }
        verdict_color = VERDICT_COLORS_PDF.get(
            analysis.verdict, colors.HexColor("#888888"))

        verdict_tbl = Table(
            [[Paragraph(f"<b>{analysis.verdict}</b>",
                        ParagraphStyle("vrd",
                            fontName="Helvetica-Bold", fontSize=18,
                            textColor=colors.white))]],
            colWidths=[usable_w * 0.25])
        verdict_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), verdict_color),
            ("ALIGN",      (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 12),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ("ROUNDEDCORNERS", [4, 4, 4, 4]),
        ]))

        # Summary stats table
        cfg = analysis.config
        summary_rows = [
            ["Hotspots detected",  str(analysis.n_hotspots)],
            ["Peak ΔT",            f"{analysis.max_peak_k:.2f} °C"],
            ["Hotspot area",       f"{analysis.area_fraction*100:.2f} %"],
            ["Map mean ΔT",        f"{analysis.map_mean_k:.3f} °C"],
            ["Map std dev",        f"{analysis.map_std_k:.3f} °C"],
            ["Detection threshold",f"{analysis.threshold_k:.1f} °C"],
            ["Timestamp",          analysis.timestamp_str],
        ]
        if cfg:
            summary_rows += [
                ["FAIL rule — count ≥",   str(cfg.fail_hotspot_count)],
                ["FAIL rule — peak ≥",    f"{cfg.fail_peak_k:.1f} °C"],
                ["FAIL rule — area ≥",    f"{cfg.fail_area_fraction*100:.1f} %"],
            ]

        sum_tbl = Table(
            [[Paragraph(r[0], styles["body"]),
              Paragraph(r[1], ParagraphStyle("mono",
                  fontName="Courier", fontSize=8.5))]
             for r in summary_rows],
            colWidths=[70*mm, 50*mm])
        sum_tbl.setStyle(TableStyle([
            ("ROWBACKGROUND", (0, 0), (-1, -1),
             [WHITE, colors.HexColor("#f4f4f8")]),
            ("GRID",   (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
            ("PADDING",(0, 0), (-1, -1), 4),
        ]))

        # Side-by-side: verdict block + summary
        combined = Table(
            [[verdict_tbl, sum_tbl]],
            colWidths=[usable_w * 0.27, usable_w * 0.73])
        combined.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING",  (1, 0), (1, 0), 8),
        ]))
        story.append(combined)
        story.append(Spacer(1, 5*mm))

        # Annotated overlay image
        if analysis.overlay_rgb is not None:
            story.append(Paragraph("Annotated Thermal Map", styles["h1"]))
            story.append(Spacer(1, 2*mm))
            ov_path = _array_to_tmpimg(analysis.overlay_rgb)
            tmp_files.append(ov_path)
            ov_h = int(usable_w * 0.75 *
                       analysis.overlay_rgb.shape[0] /
                       max(analysis.overlay_rgb.shape[1], 1))
            story.append(RLImage(ov_path,
                                 width=usable_w * 0.75, height=ov_h))
            story.append(Paragraph(
                "Hotspots are numbered by peak temperature (highest = 1). "
                "Red regions exceed the FAIL threshold; amber regions exceed "
                "the WARNING threshold.",
                styles["caption"]))
            story.append(Spacer(1, 5*mm))

        # Per-hotspot table
        if cfg.hotspot_table and analysis.hotspots:
            story.append(Paragraph("Hotspot Detail", styles["h1"]))
            story.append(Spacer(1, 2*mm))
            hs_rows = [["#", "Peak ΔT (°C)", "Mean ΔT (°C)",
                        "Area (px)", "Centroid", "Severity"]]
            for h in analysis.hotspots:
                cx, cy = h.centroid
                hs_rows.append([
                    str(h.index),
                    f"{h.peak_k:.2f}", f"{h.mean_k:.2f}",
                    f"{h.area_px:,}", f"({cx}, {cy})",
                    h.severity.upper()])
            hs_cw = [12*mm, 30*mm, 30*mm, 22*mm, 28*mm, 25*mm]
            hs_tbl = Table(
                [[Paragraph(str(c), styles["body"]) for c in row]
                 for row in hs_rows],
                colWidths=hs_cw)
            hs_tbl.setStyle(TableStyle([
                ("BACKGROUND",  (0, 0), (-1, 0), DARK),
                ("TEXTCOLOR",   (0, 0), (-1, 0), WHITE),
                ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME",    (1, 1), (-1, -1), "Courier"),
                ("FONTSIZE",    (0, 0), (-1, -1), 8.5),
                ("PADDING",     (0, 0), (-1, -1), 4),
                ("ROWBACKGROUND", (0, 1), (-1, -1),
                 [WHITE, colors.HexColor("#f4f4f8")]),
                ("GRID",        (0, 0), (-1, -1), 0.25,
                 colors.HexColor("#dddddd")),
            ]))
            story.append(hs_tbl)

    # ================================================================ #
    #  Quality Scorecard page (optional)                               #
    # ================================================================ #

    if cfg.quality_scorecard and quality_scorecard is not None:
        story.append(PageBreak())
        story.append(Paragraph("Acquisition Quality Scorecard", styles["h1"]))
        story.append(Spacer(1, 3*mm))

        GRADE_COLORS_PDF = {
            "A": colors.HexColor("#00c070"),
            "B": colors.HexColor("#00a88a"),
            "C": colors.HexColor("#ffb300"),
            "D": colors.HexColor("#e03030"),
            "F": colors.HexColor("#e03030"),
        }

        # Overall grade badge
        overall = quality_scorecard.get("overall_grade", "—")
        overall_color = GRADE_COLORS_PDF.get(overall, colors.HexColor("#888888"))
        grade_tbl = Table(
            [[Paragraph(f"<b>{overall}</b>",
                        ParagraphStyle("grade", fontName="Helvetica-Bold",
                                       fontSize=24, textColor=colors.white,
                                       alignment=TA_CENTER))]],
            colWidths=[usable_w * 0.15])
        grade_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), overall_color),
            ("ALIGN",      (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 14),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
            ("ROUNDEDCORNERS", [6, 6, 6, 6]),
        ]))

        # Per-metric rows
        metrics = quality_scorecard.get("metrics", [])
        metric_rows = [["Metric", "Grade", "Value", "Threshold"]]
        for m in metrics:
            metric_rows.append([
                m.get("metric", ""),
                m.get("grade", "—"),
                m.get("display", "—"),
                m.get("threshold", "—"),
            ])

        if len(metric_rows) > 1:
            m_cw = [40*mm, 20*mm, 40*mm, 50*mm]
            m_tbl = Table(
                [[Paragraph(str(c), styles["body"]) for c in row]
                 for row in metric_rows],
                colWidths=m_cw)
            grade_style_cmds = [
                ("BACKGROUND",  (0, 0), (-1, 0), DARK),
                ("TEXTCOLOR",   (0, 0), (-1, 0), WHITE),
                ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME",    (2, 1), (2, -1), "Courier"),
                ("FONTSIZE",    (0, 0), (-1, -1), 9),
                ("PADDING",     (0, 0), (-1, -1), 5),
                ("ROWBACKGROUND", (0, 1), (-1, -1),
                 [WHITE, colors.HexColor("#f4f4f8")]),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
            ]
            # Colour the grade cells
            for row_idx, m in enumerate(metrics, start=1):
                gc = GRADE_COLORS_PDF.get(m.get("grade", ""), None)
                if gc:
                    grade_style_cmds.append(
                        ("TEXTCOLOR", (1, row_idx), (1, row_idx), gc))
            m_tbl.setStyle(TableStyle(grade_style_cmds))

            combined = Table(
                [[grade_tbl, m_tbl]],
                colWidths=[usable_w * 0.18, usable_w * 0.82])
            combined.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (1, 0), (1, 0), 8),
            ]))
            story.append(combined)
        else:
            story.append(grade_tbl)

        # Recommendations
        recs = quality_scorecard.get("recommendations", [])
        if recs:
            story.append(Spacer(1, 5*mm))
            story.append(Paragraph("Recommendations", styles["h1"]))
            for rec in recs:
                story.append(Paragraph(f"• {rec}", styles["body"]))

    # ================================================================ #
    #  Build                                                           #
    # ================================================================ #

    doc.build(story)

    # Clean up temp files
    for p in tmp_files:
        try:
            os.unlink(p)
        except Exception:
            pass

    # Unload session arrays
    session.unload()

    return pdf_path


# ------------------------------------------------------------------ #
#  Format dispatcher                                                  #
# ------------------------------------------------------------------ #

def generate_report_any_format(session: Session,
                               output_dir: str = ".",
                               calibration: Optional[CalibrationResult] = None,
                               analysis=None,
                               report_config: Optional[ReportConfig] = None,
                               quality_scorecard=None) -> str:
    """Route to PDF or HTML generator based on report_config.format."""
    rcfg = report_config or ReportConfig()
    if rcfg.format == "html":
        from .report_html import generate_html_report
        return generate_html_report(
            session, output_dir, calibration=calibration,
            analysis=analysis, config=rcfg,
            quality_scorecard=quality_scorecard)
    return generate_report(
        session, output_dir, calibration=calibration,
        analysis=analysis, report_config=rcfg,
        quality_scorecard=quality_scorecard)
