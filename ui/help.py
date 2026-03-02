"""
ui/help.py

Contextual help system for the Microsanj Thermal Analysis System.

Usage
-----
    from ui.help import HelpButton

    # In any QWidget layout:
    lay.addWidget(HelpButton("threshold_k"))

    # Or inline next to a label:
    row = help_row("Detection Threshold", "threshold_k")
    # Returns a QHBoxLayout with label + ? button

The help popover appears near the button that was clicked,
stays open until the user clicks elsewhere, and never blocks
the rest of the UI.
"""

from __future__ import annotations
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QApplication, QSizePolicy, QGraphicsDropShadowEffect)
from PyQt5.QtCore  import Qt, QPoint, QTimer, QRect, pyqtSignal
from PyQt5.QtGui   import QColor, QFont, QCursor


# ------------------------------------------------------------------ #
#  Help content database                                               #
# ------------------------------------------------------------------ #
#
# Each entry is a dict with:
#   title      : short display name
#   what       : plain-English explanation (1-3 sentences, no jargon)
#   do         : concrete action recommendation
#   range      : expected values / normal operating range (optional)
#   warning    : common mistake or gotcha (optional)
#   docs       : section name in user manual (optional)
#
HELP_CONTENT: dict[str, dict] = {

    # ---- Analysis / Pass-Fail ----------------------------------------

    "threshold_k": {
        "title":   "Detection Threshold (°C)",
        "what":    "The minimum temperature rise that counts as a hotspot. "
                   "Pixels with ΔT below this value are ignored.",
        "do":      "Set this just above the background noise floor of your "
                   "measurement. Use a preset for your material type as a "
                   "starting point.",
        "range":   "1–5 °C for semiconductors, 3–10 °C for PCB/EV",
        "warning": "Too low → noise is flagged as hotspots. "
                   "Too high → real hotspots are missed.",
        "docs":    "Pass/Fail Analysis › Threshold",
    },

    "fail_hotspot_count": {
        "title":   "FAIL Rule — Hotspot Count",
        "what":    "The measurement is marked FAIL if this many or more "
                   "distinct hotspots are detected above the threshold.",
        "do":      "Set to 1 for components where any hotspot indicates a "
                   "defect. Set higher (or 0 to disable) for components "
                   "where multiple local heating events are expected.",
        "range":   "1 for most semiconductor and PCB testing",
        "docs":    "Pass/Fail Analysis › Verdict Rules",
    },

    "fail_peak_k": {
        "title":   "FAIL Rule — Peak Temperature Rise (°C)",
        "what":    "The measurement fails if any single pixel reaches this "
                   "temperature above the cold baseline, regardless of "
                   "hotspot count.",
        "do":      "Set this based on the device's safe operating limit. "
                   "Consult the component datasheet for junction temperature "
                   "ratings.",
        "range":   "5–15 °C typical for ICs, 20–40 °C for power modules",
        "warning": "This is a rise above baseline, not an absolute "
                   "temperature. Ensure your baseline measurement is at "
                   "a known temperature.",
        "docs":    "Pass/Fail Analysis › Verdict Rules",
    },

    "fail_area_fraction": {
        "title":   "FAIL Rule — Hotspot Area (%)",
        "what":    "The measurement fails if the total area of all hotspots "
                   "exceeds this percentage of the measurement region.",
        "do":      "Use this to catch distributed heating (e.g. resistive "
                   "heating across a wide trace) that wouldn't trigger the "
                   "peak rule.",
        "range":   "2–5 % typical",
        "docs":    "Pass/Fail Analysis › Verdict Rules",
    },

    "warn_peak_k": {
        "title":   "WARNING Rule — Peak Temperature Rise (°C)",
        "what":    "The measurement is marked WARNING — not FAIL — if the "
                   "peak ΔT exceeds this value but stays below the FAIL "
                   "limit. Useful for catching devices that are running "
                   "hot but still within spec.",
        "do":      "Set this to about 50–60% of your FAIL threshold as a "
                   "caution zone.",
        "docs":    "Pass/Fail Analysis › Verdict Rules",
    },

    # ---- Camera ------------------------------------------------------

    "exposure_us": {
        "title":   "Camera Exposure (µs)",
        "what":    "How long the camera sensor is exposed to light for each "
                   "frame. Longer exposure = more signal, but also more "
                   "risk of saturation and motion blur.",
        "do":      "Start with the value from your material profile. "
                   "If the image is too dark, increase it. If pixels appear "
                   "white/clipped, reduce it.",
        "range":   "2,000–15,000 µs for most materials at 532 nm",
        "warning": "Saturated pixels (showing as white) will produce "
                   "incorrect ΔR/R values. Always check the histogram.",
        "docs":    "Camera › Exposure",
    },

    "gain_db": {
        "title":   "Camera Gain (dB)",
        "what":    "Amplifies the camera signal after exposure. Higher gain "
                   "brightens a dim image but also amplifies noise.",
        "do":      "Use gain only after maximising exposure. Keep gain as "
                   "low as possible — 0 dB is ideal for high-SNR "
                   "measurements.",
        "range":   "0–6 dB typical; above 6 dB noise dominates",
        "warning": "High gain reduces sensitivity. Noise added by gain "
                   "cannot be removed by averaging more frames.",
        "docs":    "Camera › Gain",
    },

    # ---- Acquisition -------------------------------------------------

    "n_frames": {
        "title":   "Frames per Half-Cycle",
        "what":    "How many camera frames are averaged in the hot state "
                   "and in the cold state separately. More frames = lower "
                   "noise, but longer acquisition time.",
        "do":      "Use the value from your material profile. Increase it "
                   "if the ΔR/R map looks noisy (grainy). Halve it if "
                   "speed is more important than sensitivity.",
        "range":   "32–64 for standard measurements; 128+ for weak signals",
        "docs":    "Acquisition › Frame Count",
    },

    "accumulation": {
        "title":   "EMA Accumulation Depth (Live Mode)",
        "what":    "In Live mode, frames are averaged using an Exponential "
                   "Moving Average (EMA). This value controls how many "
                   "past cycles influence the current display — higher "
                   "values smooth the image but respond slower to changes.",
        "do":      "Leave at the profile default. Increase for stable "
                   "samples; decrease when scanning a moving sample or "
                   "monitoring transient events.",
        "range":   "8–32 typical",
        "docs":    "Live Mode › Accumulation",
    },

    # ---- Calibration -------------------------------------------------

    "ct_value": {
        "title":   "Thermoreflectance Coefficient (C_T)",
        "what":    "The constant that converts the measured reflectance "
                   "change (ΔR/R) into a temperature change (ΔT). It is "
                   "specific to each material and measurement wavelength.",
        "do":      "Use the value from your material profile for standard "
                   "measurements. Run a full calibration if you need "
                   "absolute accuracy on an unfamiliar material.",
        "range":   "10⁻⁵ to 10⁻³ K⁻¹ depending on material",
        "warning": "Using the wrong C_T shifts all ΔT values by a "
                   "constant factor. Profile values are measured at "
                   "532 nm — different wavelengths require different C_T.",
        "docs":    "Calibration › C_T Coefficient",
    },

    "calibration_t_range": {
        "title":   "Calibration Temperature Range",
        "what":    "The temperature range over which C_T is measured. "
                   "The TEC heats the sample from T_min to T_max while "
                   "the camera records reflectance at each step.",
        "do":      "Use a range that brackets your expected operating "
                   "temperature. A 20–30 °C span is typical.",
        "range":   "T_min: 20–30 °C  |  T_max: 50–80 °C",
        "warning": "C_T can be nonlinear at extreme temperatures. "
                   "Calibrate close to your actual operating conditions.",
        "docs":    "Calibration › Temperature Range",
    },

    # ---- ROI ---------------------------------------------------------

    "roi": {
        "title":   "Region of Interest (ROI)",
        "what":    "The rectangular area of the camera image that is used "
                   "for measurement. Pixels outside the ROI are ignored.",
        "do":      "Draw the ROI tightly around the device or feature you "
                   "are measuring. Smaller ROIs process faster and reduce "
                   "background noise contributions.",
        "warning": "Make sure your ROI covers the entire device, or "
                   "hotspots near the edge may be partially clipped.",
        "docs":    "ROI › Drawing an ROI",
    },

    # ---- Autofocus ---------------------------------------------------

    "autofocus": {
        "title":   "Autofocus",
        "what":    "Automatically moves the objective to the plane of "
                   "sharpest focus by maximising image contrast while "
                   "sweeping the Z axis.",
        "do":      "Click Auto-Focus with the sample in view. For best "
                   "results, start close to focus manually so the sweep "
                   "range is small.",
        "warning": "Autofocus works best on samples with sharp edges or "
                   "surface features. Uniform, featureless surfaces may "
                   "not converge correctly — focus manually in that case.",
        "docs":    "Autofocus › Operation",
    },

    "af_sweep_range": {
        "title":   "Autofocus Sweep Range (µm)",
        "what":    "The total Z-axis distance the autofocus algorithm "
                   "searches. A wider range finds focus from further away "
                   "but takes longer.",
        "do":      "Use 100–200 µm for rough positioning; reduce to "
                   "20–50 µm once you are close to focus for finer "
                   "convergence.",
        "range":   "20–500 µm",
        "docs":    "Autofocus › Sweep Range",
    },

    # ---- Profiles ----------------------------------------------------

    "profile_ct": {
        "title":   "Profile C_T Confidence Range",
        "what":    "The min and max C_T values show the range of published "
                   "measurements for this material. The nominal value is "
                   "the midpoint used for conversion.",
        "do":      "If your calibration gives a C_T outside this range, "
                   "check the laser wavelength and surface condition. "
                   "Duplicate the profile and enter your measured value.",
        "docs":    "Profiles › C_T Range",
    },

    "profile_source": {
        "title":   "Profile Source",
        "what":    "Built-in and official (🔒) profiles are provided by "
                   "Microsanj and cannot be edited. User (✎) profiles "
                   "are created locally and can be changed freely.",
        "do":      "To customise a built-in profile, click Duplicate — "
                   "this copies it into your user library where you can "
                   "edit it.",
        "docs":    "Profiles › Protection Model",
    },

    # ---- Live mode ---------------------------------------------------

    "live_snr": {
        "title":   "Signal-to-Noise Ratio (SNR)",
        "what":    "The ratio of the thermoreflectance signal to the "
                   "background noise. Higher SNR means more reliable ΔT "
                   "measurements.",
        "do":      "Aim for SNR above 10 before recording. If SNR is low, "
                   "increase frame count, reduce gain, or increase "
                   "exposure.",
        "range":   "SNR > 10: acceptable  |  SNR > 30: good  |  SNR > 100: excellent",
        "docs":    "Live Mode › SNR",
    },

    # ---- Stage -------------------------------------------------------

    "stage_step": {
        "title":   "Stage Step Size (µm)",
        "what":    "The distance the stage moves per key press or scan "
                   "step. Smaller values give finer positioning but take "
                   "longer to traverse.",
        "do":      "Use large steps (50–100 µm) to navigate to the "
                   "device, then switch to small steps (1–5 µm) for "
                   "fine positioning over the feature of interest.",
        "range":   "0.1–500 µm",
        "docs":    "Stage › Step Size",
    },

    # ---- FPGA --------------------------------------------------------

    "fpga_frequency": {
        "title":   "Modulation Frequency (Hz)",
        "what":    "The rate at which the FPGA switches the device between "
                   "the heated (hot) and unheated (cold) state. This sets "
                   "the lock-in reference frequency.",
        "do":      "Match this to the camera frame rate divided by 2 for "
                   "optimal synchronisation. The profile default is "
                   "calibrated for your hardware.",
        "range":   "1–1000 Hz depending on thermal time constant of sample",
        "warning": "Very high frequencies may not allow the sample to "
                   "reach thermal equilibrium between cycles, reducing "
                   "signal amplitude.",
        "docs":    "FPGA › Modulation",
    },

    # ---- Material & Calibration reference ----------------------------

    "ctr_lookup": {
        "title":   "C_T Coefficient Reference",
        "what":    "Thermoreflectance coefficient linking ΔR/R to ΔT. "
                   "It is specific to each material and illumination wavelength.",
        "do":      ("Select a profile matching your material and LED wavelength. "
                    "Si/532 nm: 1.5×10⁻⁴  |  GaAs/532 nm: 2.0×10⁻⁴  |  "
                    "Au/530 nm: 2.5×10⁻⁴  |  Al: use 780 nm LED only "
                    "(Cth too small at 532/470 nm)."),
        "range":   "Typical: 1×10⁻⁵ to 3×10⁻⁴ K⁻¹",
        "warning": ("Aluminium and dielectric-coated surfaces require 780 nm. "
                    "Changing LED wavelength requires a new calibration."),
        "docs":    "EZ-Therm User Manual §C_T Coefficients; NanoTherm Rev.A §Calibration",
    },

    "startup_sequence": {
        "title":   "System Power-Up Sequence",
        "what":    "Required hardware startup order to avoid communication errors "
                   "and hardware damage.",
        "do":      ("1. Release EMO button (turn counterclockwise).  "
                    "2. Flip Master switch ON.  "
                    "3. Flip Chiller switch ON; press external chiller power button.  "
                    "4. Press EZ-Therm / Nano-THERM power button.  "
                    "5. Press 4D Nano Align power button.  "
                    "6. Launch SanjINSIGHT only after all hardware LEDs are stable."),
        "warning": ("Never launch software before all hardware is fully powered. "
                    "Never run the cooling pump without coolant in the reservoir — "
                    "dry-running voids the warranty."),
        "docs":    "EZ-Therm User Manual §System Startup",
    },

    # ---- Scan --------------------------------------------------------

    "scan_step": {
        "title":   "Scan Step Size (µm)",
        "what":    "The distance between adjacent scan tiles. Should be "
                   "set close to the camera field of view width to avoid "
                   "gaps or excessive overlap.",
        "do":      "Set step size ≤ camera FOV width for full coverage. "
                   "A 10–20% overlap between tiles helps with stitching.",
        "docs":    "Scan Mode › Step Size",
    },

    "scan_snake": {
        "title":   "Boustrophedon (Snake) Path",
        "what":    "When enabled, the scan alternates direction on each "
                   "row (left→right, then right→left) rather than always "
                   "returning to the start. This reduces total stage "
                   "travel distance.",
        "do":      "Leave enabled for most scans. Disable only if your "
                   "stage shows backlash errors on direction reversal.",
        "docs":    "Scan Mode › Path",
    },

}


# ------------------------------------------------------------------ #
#  Popover widget                                                      #
# ------------------------------------------------------------------ #

class HelpPopover(QWidget):
    """
    Floating, non-modal help panel.
    Appears near the trigger widget; dismissed by clicking elsewhere.
    """

    _ACCENT = "#00d4aa"
    _BG     = "#181818"
    _BORDER = "#2a2a2a"

    def __init__(self, topic_id: str, anchor: QWidget):
        super().__init__(
            anchor.window(),
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setMinimumWidth(320)
        self.setMaximumWidth(380)

        content = HELP_CONTENT.get(topic_id)
        if content is None:
            content = {
                "title": topic_id,
                "what":  "No help available for this topic yet.",
                "do":    "",
            }

        self._build(content)
        self._position_near(anchor)

        # Close when anything outside is clicked
        QApplication.instance().installEventFilter(self)

    def _build(self, content: dict):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 8)   # shadow room

        card = QFrame()
        card.setObjectName("helpCard")
        card.setStyleSheet(f"""
            QFrame#helpCard {{
                background:{self._BG};
                border:1px solid {self._BORDER};
                border-radius:6px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 140))
        card.setGraphicsEffect(shadow)

        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(10)

        # Header row
        hdr = QHBoxLayout()
        icon = QLabel("?")
        icon.setFixedSize(22, 22)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(
            f"background:{self._ACCENT}22; color:{self._ACCENT}; "
            f"border:1px solid {self._ACCENT}44; border-radius:11px; "
            f"font-size:14pt; font-weight:bold;")
        title = QLabel(content["title"])
        title.setStyleSheet(
            f"font-size:15pt; font-weight:bold; color:#ddd;")
        title.setWordWrap(True)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(20, 20)
        close_btn.setStyleSheet(
            "QPushButton{background:transparent; color:#444; border:none; "
            "font-size:14pt;} QPushButton:hover{color:#888;}")
        close_btn.clicked.connect(self.close)

        hdr.addWidget(icon)
        hdr.addWidget(title, 1)
        hdr.addWidget(close_btn)
        cl.addLayout(hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{self._BORDER};")
        cl.addWidget(sep)

        def section(heading: str, body: str, accent=False):
            sl = QVBoxLayout()
            sl.setSpacing(3)
            h = QLabel(heading.upper())
            h.setStyleSheet(
                f"font-size:11pt; letter-spacing:1.5px; "
                f"color:{self._ACCENT if accent else '#777'};")
            b = QLabel(body)
            b.setWordWrap(True)
            b.setStyleSheet(
                f"font-size:12pt; "
                f"color:{'#ddd' if accent else '#999'};")
            sl.addWidget(h)
            sl.addWidget(b)
            return sl

        cl.addLayout(section("What it is", content["what"]))

        if content.get("do"):
            cl.addLayout(section("What to do", content["do"], accent=True))

        if content.get("range"):
            cl.addLayout(section("Typical range", content["range"]))

        if content.get("warning"):
            warn_row = QHBoxLayout()
            warn_row.setSpacing(8)
            warn_icon = QLabel("⚠")
            warn_icon.setStyleSheet("color:#ffb300; font-size:14pt;")
            warn_icon.setFixedWidth(16)
            warn_text = QLabel(content["warning"])
            warn_text.setWordWrap(True)
            warn_text.setStyleSheet(
                "font-size:12pt; color:#cc9900; font-style:italic;")
            warn_row.addWidget(warn_icon, 0, Qt.AlignTop)
            warn_row.addWidget(warn_text, 1)
            cl.addLayout(warn_row)

        if content.get("docs"):
            docs_lbl = QLabel(f"📖  User Guide: {content['docs']}")
            docs_lbl.setStyleSheet(
                "font-size:12pt; color:#666; font-style:italic;")
            cl.addWidget(docs_lbl)

        outer.addWidget(card)
        self.adjustSize()

    def _position_near(self, anchor: QWidget):
        """Position the popover to the right of the anchor, staying on screen."""
        global_pos = anchor.mapToGlobal(QPoint(anchor.width() + 4, 0))
        screen     = QApplication.primaryScreen().availableGeometry()
        w, h       = self.sizeHint().width(), self.sizeHint().height()

        x = global_pos.x()
        y = global_pos.y() - h // 2 + anchor.height() // 2

        # Flip to left if off right edge
        if x + w > screen.right():
            x = anchor.mapToGlobal(QPoint(-w - 4, 0)).x()

        # Clamp vertically
        y = max(screen.top() + 8, min(y, screen.bottom() - h - 8))

        self.move(x, y)

    def eventFilter(self, obj, event):
        from PyQt5.QtCore import QEvent
        if event.type() == QEvent.MouseButtonPress:
            # Close if click is outside this widget
            if not self.geometry().contains(
                    self.mapFromGlobal(QCursor.pos())):
                self.close()
        return False

    def showEvent(self, e):
        super().showEvent(e)
        self.activateWindow()

    def closeEvent(self, e):
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(e)


# ------------------------------------------------------------------ #
#  Help button                                                         #
# ------------------------------------------------------------------ #

_active_popover: Optional[HelpPopover] = None


class HelpButton(QPushButton):
    """
    Compact '?' button. Drop it into any layout next to the
    control it describes.

        lay.addWidget(HelpButton("exposure_us"))
    """

    def __init__(self, topic_id: str, parent=None):
        super().__init__("?", parent)
        self._topic = topic_id
        self.setFixedSize(22, 22)
        self.setStyleSheet("""
            QPushButton {
                background:#1a1a1a;
                color:#00d4aa99;
                border:1px solid #2a2a2a;
                border-radius:11px;
                font-size:12pt;
                font-weight:bold;
            }
            QPushButton:hover {
                color:#00d4aa;
                border-color:#00d4aa66;
                background:#0d2a1a;
            }
        """)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"Help: {HELP_CONTENT.get(topic_id, {}).get('title', topic_id)}")
        self.clicked.connect(self._show_help)

    def _show_help(self):
        global _active_popover
        if _active_popover is not None:
            try:
                _active_popover.close()
            except Exception:
                pass
        _active_popover = HelpPopover(self._topic, self)
        _active_popover.show()


# ------------------------------------------------------------------ #
#  Convenience helpers                                                 #
# ------------------------------------------------------------------ #

def help_row(label_text: str,
             topic_id:   str,
             label_style: str = "") -> QHBoxLayout:
    """
    Returns a QHBoxLayout containing [QLabel | HelpButton].
    Drop the whole row into a form or grid layout.

    Example:
        lay.addRow(help_row("Detection Threshold", "threshold_k"),
                   self._thresh_spin)
    """
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(4)
    lbl = QLabel(label_text)
    if label_style:
        lbl.setStyleSheet(label_style)
    row.addWidget(lbl)
    row.addWidget(HelpButton(topic_id))
    row.addStretch()
    return row


def help_label(label_text: str,
               topic_id:   str,
               style:      str = "") -> QWidget:
    """
    Returns a compact QWidget containing [label text + ? button] on one line.
    Useful inside QGridLayout cells or QFormLayout labels.
    """
    w   = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    lbl = QLabel(label_text)
    if style:
        lbl.setStyleSheet(style)
    lay.addWidget(lbl)
    lay.addWidget(HelpButton(topic_id))
    lay.addStretch()
    return w
