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

NOTE: Help content is now centralized in ``ui.guidance.content``.
This module re-exports ``HELP_CONTENT`` for backwards compatibility.
All new content should be added to ``ui/guidance/content.py``.
"""

from __future__ import annotations
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QApplication, QSizePolicy, QGraphicsDropShadowEffect)
from PyQt5.QtCore  import Qt, QPoint, QTimer, QRect, pyqtSignal
from PyQt5.QtGui   import QColor, QFont, QCursor
from ui.theme import FONT, PALETTE, scaled_qss

# ------------------------------------------------------------------ #
#  Help content — imported from centralized guidance module            #
# ------------------------------------------------------------------ #
#
# HELP_CONTENT is now the single source of truth in ui.guidance.content.
# This re-export preserves all existing ``from ui.help import HELP_CONTENT``
# call sites without changes.
from ui.guidance.content import HELP_CONTENT  # noqa: E402

# Legacy stub kept only for git diff readability — the actual content
# lives in ui/guidance/content.py.  This dict is never used.
_HELP_CONTENT_LEGACY: dict[str, dict] = {

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
                    "Si/470 nm: 1.5×10⁻⁴  |  GaAs/470 nm: 2.0×10⁻⁴  |  "
                    "Au/530 nm: 2.5×10⁻⁴  |  Al: use 780 nm LED only "
                    "(Cth too small at shorter wavelengths).  "
                    "See the LED Wavelength Selection help topic for per-material guidance."),
        "range":   "Valid range: 1×10⁻⁵ to 1×10⁻² K⁻¹",
        "warning": ("Aluminium and dielectric-coated surfaces require 780 nm. "
                    "Changing LED wavelength requires a new calibration."),
        "docs":    "AN-003 §C_T Coefficients; EZ-Therm Manual §Calibration",
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

    # ---- Optics & Technique reference --------------------------------

    "led_wavelength_selection": {
        "title":   "LED Wavelength Selection",
        "what":    "The thermoreflectance coefficient (Cth) is strongly "
                   "wavelength-dependent. Choosing the wrong LED for your "
                   "surface material will severely reduce signal strength.",
        "do":      ("Match your LED to the surface material of the hot-spot "
                    "region:  Si / GaAs / InP → 470 nm Blue (optimal)  |  "
                    "GaN → 365 nm UV, 470 nm Blue, or 530 nm Green  |  "
                    "Au → 470 nm Blue or 530 nm Green  |  "
                    "Al → 780 nm N-IR ONLY  |  "
                    "Ni / Ti → 585 nm Yellow or 660 nm Red  |  "
                    "Flip-chip / backside → 1050–1500 nm NIR."),
        "range":   "Visible top-side: 365–700 nm  |  Thru-substrate NIR: 1050–1500 nm",
        "warning": ("Aluminium surfaces require 780 nm — Cth is negligibly small at "
                    "532/470 nm.  For devices with mixed surface materials, select the "
                    "wavelength that optimises Cth for the material at the defect site.  "
                    "Changing LED wavelength requires a new calibration."),
        "docs":    "AN-003 §Optimal LED Wavelength; AN-005 §Wavelength Selection",
    },

    "objective_fov": {
        "title":   "Objective Magnification & Field of View",
        "what":    "Higher magnification gives better spatial resolution "
                   "but reduces the field of view (FOV). The FOV also "
                   "determines the maximum useful scan tile step size.",
        "do":      ("Start with a low-magnification objective (5× or 20×) to "
                    "locate the device, then switch to higher magnification for "
                    "sub-micron hot-spot analysis.  "
                    "Approximate FOVs: 5× ≈ 2.5 mm  |  20× ≈ 0.6 mm  |  "
                    "50× ≈ 250 µm  |  100× ≈ 120 µm."),
        "range":   "Set scan step ≤ FOV for full coverage; 10–20 % overlap for stitching",
        "warning": ("At NA > 0.5, the thermoreflectance coefficient Cth becomes "
                    "NA-dependent.  High-NA objectives may require a dedicated "
                    "calibration for accurate absolute temperature measurements."),
        "docs":    "AN-002 §Objective Selection; AN-003 §Numerical Aperture Effects",
    },

    "technique_comparison": {
        "title":   "TTI vs IR vs EMMI vs OBIRCH",
        "what":    "Four imaging techniques are used for semiconductor failure "
                   "analysis. Each has different strengths, limitations, and "
                   "spatial resolution capabilities.",
        "do":      ("Use Thermoreflectance (TTI) when: sub-micron resolution is "
                    "needed, the defect is in a metal interconnect (invisible to "
                    "EMMI), time resolution below 1 ms is required, or budget is "
                    "limited.  "
                    "Use IR when: the highest temperature resolution (< 1 mK) is "
                    "needed and black-paint coating of the device is acceptable.  "
                    "Use EMMI when: detecting junction-level photon emission from "
                    "ESD, hot carriers, or bandgap recombination events.  "
                    "Use OBIRCH when: resistance changes in metal lines are too "
                    "small for thermal mapping."),
        "range":   ("TTI: 250 nm spatial, 0.25–0.5 °C (2 min), < 1 ns time  |  "
                    "IR: 2–5 µm spatial, 25 mK, tens of ms  |  "
                    "EMMI: 2–3 µm, light-emitting defects only  |  "
                    "OBIRCH: 1–1.5 µm, resistance change only"),
        "warning": ("IR requires heating the device to 50–70 °C for adequate "
                    "sensitivity, and metals have low emissivity.  "
                    "EMMI cannot detect heating in metal interconnects — metals "
                    "do not emit detectable photons.  "
                    "OBIRCH can miss small resistance changes entirely."),
        "docs":    "AN-004 §Technique Comparison",
    },

    "transient_imaging": {
        "title":   "Transient (Time-Resolved) Thermal Imaging",
        "what":    "Time-resolved mode sweeps the LED illumination delay "
                   "relative to the device bias pulse, building a movie of "
                   "temperature vs. time with nanosecond resolution.",
        "do":      ("Set DUT bias pulse duty cycle to 25–35 % — high enough to "
                    "reach peak temperature, low enough to allow full cool-down "
                    "between pulses.  "
                    "Use a LED pulse width of ~100 µs as a starting point.  "
                    "If the thermal response is delayed relative to the bias onset, "
                    "the heat source is sub-surface — do not assume it is at the "
                    "top surface.  "
                    "For < 10 ns measurements, use impedance-matched 100 MHz+ cabling."),
        "range":   ("Time resolution: < 1 ns to ~100 ns typical; 800 ps best achieved.  "
                    "Duty cycle: 25–35 % recommended."),
        "warning": ("At 100 MHz pulsing rates, impedance mismatches on signal cables "
                    "cause reflections that corrupt lock-in timing and alter bias "
                    "conditions — use matched transmission lines.  "
                    "A time-delayed thermal response is diagnostic of a sub-surface "
                    "heat source, not a surface defect."),
        "docs":    "AN-006 §Transient Thermal Imaging",
    },

    "thru_substrate": {
        "title":   "Thru-the-Substrate (Backside) Imaging",
        "what":    "Flip-chip and face-down assemblies have the active junctions "
                   "blocked by bump bonds and metal layers. Back-side NIR imaging "
                   "passes through the silicon substrate to reach the active layer.",
        "do":      ("Use NIR illumination (1050, 1200, 1300, or 1500 nm) with an "
                    "InGaAs camera — silicon is virtually transparent above 1100 nm.  "
                    "Image from the back side of the die.  "
                    "The silicon back surface is smooth and uniform, which simplifies "
                    "Cth calibration compared to the metallised top surface.  "
                    "Optical alignment and signal processing are otherwise identical "
                    "to standard visible-light thermoreflectance."),
        "range":   ("Spatial resolution: ~800 nm–2 µm (NIR) vs. 250–600 nm (visible).  "
                    "Available NIR wavelengths: 1050, 1200, 1300, 1500 nm."),
        "warning": ("NIR wavelengths reduce spatial resolution compared to visible "
                    "illumination — accept this trade-off for flip-chip access.  "
                    "Devices with complex top-side surfaces (multiple dissimilar "
                    "materials) also benefit from back-side imaging because the "
                    "back surface has a single uniform Cth for calibration."),
        "docs":    "AN-007 §Through-the-Substrate Imaging",
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

    # ---- Objective turret --------------------------------------------

    "objective_turret": {
        "title":   "Motorized Objective Turret",
        "what":    "A motorized nose-piece that rotates to select one of "
                   "the installed objective lenses (e.g. 4×, 10×, 20×, "
                   "50×, 100×). Changing the objective updates the camera "
                   "field of view (FOV) and pixel size automatically.",
        "do":      ("Select the objective in the Camera panel. "
                    "Use a low-magnification objective (4× or 10×) to locate "
                    "the device, then switch to higher magnification for "
                    "sub-micron hot-spot analysis.  "
                    "After changing objectives, click 'Use Objective Z-Range' "
                    "in the Autofocus panel to preset the Z-sweep range for "
                    "the new working distance."),
        "range":   ("4×: FOV ≈ 2.8 mm,  px ≈ 1.5 µm  |  "
                    "10×: FOV ≈ 1.1 mm,  px ≈ 0.59 µm  |  "
                    "20×: FOV ≈ 0.6 mm,  px ≈ 0.29 µm  |  "
                    "50×: FOV ≈ 225 µm,  px ≈ 0.12 µm  |  "
                    "100×: FOV ≈ 112 µm, px ≈ 0.06 µm"),
        "warning": ("At NA > 0.5 (50× and above), the thermoreflectance "
                    "coefficient Cth becomes NA-dependent — high-NA objectives "
                    "may require a dedicated calibration for accurate absolute "
                    "temperature values.  "
                    "Always lift the objective clear of the sample before "
                    "rotating the turret."),
        "docs":    "AN-002 §Objective Selection; LINX Olympus Turret.lvproj",
    },

    # ---- Movie mode --------------------------------------------------

    "movie_mode": {
        "title":   "Movie Mode (Burst Acquisition)",
        "what":    "Captures N frames as fast as the camera allows after "
                   "bias power turns ON, building a time-lapse 'movie' of "
                   "the thermal transient response.  Unlike lock-in live "
                   "mode, no FPGA synchronisation is required.",
        "do":      ("Set N frames to cover the full thermal event "
                    "(200–500 for most devices at 150 fps).  "
                    "Enable 'Capture cold reference' to compute ΔR/R from "
                    "each frame.  "
                    "Increase 'Settle' time if the device needs time to "
                    "reach operating conditions after power-on.  "
                    "Save the result cube (.npz) for post-processing in "
                    "SanjANALYZER or Python / MATLAB."),
        "range":   ("10–2000 frames;  "
                    "Frame rate: acA1920 ≈ 155 fps (full frame), "
                    "acA640 ≈ 750 fps"),
        "warning": ("Movie mode does NOT use FPGA lock-in — SNR is lower "
                    "than accumulated live mode.  "
                    "Long bursts (>500 frames) may require large RAM. "
                    "Verify system RAM before capturing high-frame-count "
                    "sequences at full resolution."),
        "docs":    "AN-006 §Thermal Movie Mode; EZ500_SV7.lvproj",
    },

    # ---- Transient tab -----------------------------------------------

    "transient_mode": {
        "title":   "Transient Acquisition (FPGA-Triggered)",
        "what":    "Time-resolved mode fires a precise power pulse and "
                   "captures one camera frame per delay step, building a "
                   "3D ΔR/R cube (N_delays × H × W).  "
                   "Multiple trigger cycles are averaged per delay step to "
                   "improve SNR.  Requires FPGA single-shot trigger support.",
        "do":      ("Set Delay end to cover the full cool-down period — "
                    "start with 5 ms and increase if the signal has not "
                    "returned to baseline.  "
                    "Use at least 50 averages per delay step for acceptable "
                    "SNR.  Pulse width should match the electrical test "
                    "condition.  "
                    "If 'HW Trigger' shows SW fallback, timing jitter will "
                    "be ~1 ms instead of ~50 ns — reduce number of delays "
                    "or increase averages to compensate."),
        "range":   ("N delays: 10–200;  N averages: 10–500;  "
                    "Delay range: 0–5,000 ms;  Pulse width: 1–100,000 µs"),
        "warning": ("SW fallback mode has ~1 ms timing jitter — not "
                    "suitable for sub-millisecond transient analysis.  "
                    "Keep pulse duty cycle ≤ 35 % to allow complete "
                    "cool-down between trigger cycles."),
        "docs":    "AN-006 §Time-Resolved Thermoreflectance; EZ500_SV7.lvproj",
    },

    # ---- Probe station -----------------------------------------------

    "prober": {
        "title":   "MPI Probe Station",
        "what":    "A motorised chuck that positions the wafer under the "
                   "optical microscope.  In probe-station mode the chuck "
                   "moves the die array to the measurement position while "
                   "probe needles make electrical contact for biasing.",
        "do":      ("1. Lift probe needles before any chuck movement.  "
                    "2. Step to the target die using the die map grid or "
                    "col/row spinboxes.  "
                    "3. Lower needles (Contact) and verify electrical "
                    "connection before enabling bias output.  "
                    "4. Lift needles again before stepping to the next die."),
        "warning": ("Always lift needles before moving the chuck — "
                    "contacting the wafer while moving will bend or break "
                    "the probe tips.  "
                    "Home the chuck on first use after power-up to "
                    "initialise position reference."),
        "docs":    "EZ500_SV7.lvproj §MPI Stage Driver",
    },

    # ---- Thermal chuck -----------------------------------------------

    "thermal_chuck": {
        "title":   "Thermal Chuck (Temperature-Controlled Stage)",
        "what":    "A wafer-holding platform with built-in heating and "
                   "cooling.  The chuck is controlled as a TEC channel "
                   "and appears in the Temperature tab alongside "
                   "Meerstetter TEC controllers.",
        "do":      ("Set the target temperature in the Temperature panel "
                    "and enable the chuck output.  "
                    "Allow 2–5 minutes for large temperature changes — the "
                    "chuck ramps slowly compared to a Meerstetter TEC.  "
                    "The stability tolerance is ±2 °C (wider than the TEC "
                    "± 1 °C) — wait for the 'Stable' indicator before "
                    "capturing calibration frames."),
        "range":   ("Temperature: −65 °C to +250 °C  |  "
                    "Stability tolerance: ±2 °C  |  "
                    "Max ramp rate: ~300 °C/min"),
        "warning": ("Condensation forms when chilling below the dew point "
                    "— purge the chuck with dry N₂ when operating below "
                    "ambient.  "
                    "The thermal chuck stability window (±2 °C) is wider "
                    "than the Meerstetter TEC — factor this into calibration "
                    "uncertainty estimates."),
        "docs":    "EZ-Therm Manual §Thermal Chuck; Temptronic ATS Manual",
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

    @property
    def _ACCENT(self): return PALETTE.get('accent',  '#00d4aa')
    @property
    def _BG(self):     return PALETTE.get('surface', '#2d2d2d')
    @property
    def _BORDER(self): return PALETTE.get('border',  '#484848')

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
            f"font-size:{FONT['heading']}pt; font-weight:bold;")
        title = QLabel(content["title"])
        title.setStyleSheet(
            scaled_qss(f"font-size:15pt; font-weight:bold; color:{PALETTE.get('text','#ebebeb')}; background:transparent;"))
        title.setWordWrap(True)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(20, 20)
        close_btn.setStyleSheet(
            f"QPushButton{{background:transparent; color:{PALETTE.get('textDim','#999999')}; border:none; "
            f"font-size:{FONT['heading']}pt;}} QPushButton:hover{{color:{PALETTE.get('text','#ebebeb')};}}")
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
                f"font-size:{FONT['sublabel']}pt; letter-spacing:1.5px; "
                f"color:{self._ACCENT if accent else PALETTE.get('textSub','#6a6a6a')}; background:transparent;")
            b = QLabel(body)
            b.setWordWrap(True)
            b.setStyleSheet(
                f"font-size:{FONT['label']}pt; background:transparent; "
                f"color:{PALETTE.get('text','#ebebeb') if accent else PALETTE.get('textDim','#999999')};")
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
            warn_icon.setStyleSheet(f"color:#ffb300; font-size:{FONT['heading']}pt;")
            warn_icon.setFixedWidth(16)
            warn_text = QLabel(content["warning"])
            warn_text.setWordWrap(True)
            warn_text.setStyleSheet(
                f"font-size:{FONT['label']}pt; color:#cc9900; font-style:italic;")
            warn_row.addWidget(warn_icon, 0, Qt.AlignTop)
            warn_row.addWidget(warn_text, 1)
            cl.addLayout(warn_row)

        if content.get("docs"):
            docs_lbl = QLabel(f"User Guide: {content['docs']}")
            docs_lbl.setStyleSheet(
                f"font-size:{FONT['label']}pt; color:{PALETTE.get('textDim','#999999')}; font-style:italic; background:transparent;")
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
        self._apply_styles()
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"Help: {HELP_CONTENT.get(topic_id, {}).get('title', topic_id)}")
        self.clicked.connect(self._show_help)

    def _apply_styles(self):
        acc  = PALETTE.get('accent',   '#00d4aa')
        surf = PALETTE.get('surface2', '#3d3d3d')
        bdr  = PALETTE.get('border',   '#484848')
        self.setStyleSheet(f"""
            QPushButton {{
                background:{surf};
                color:{acc}99;
                border:1px solid {bdr};
                border-radius:11px;
                font-size:{FONT['label']}pt;
                font-weight:bold;
            }}
            QPushButton:hover {{
                color:{acc};
                border-color:{acc}66;
                background:{surf};
            }}
        """)

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
    lay.addStretch()
    lay.addWidget(HelpButton(topic_id))
    return w
