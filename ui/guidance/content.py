"""
ui/guidance/content.py  —  Centralized guidance content database

All instructional text in one place.  Section authors pull content from
here instead of hardcoding strings.  This separation allows:

  - UI code changes without touching help text
  - Help text updates without touching widget code
  - Bulk export for translation or documentation generation
  - AI system access to the same content (Tier 3)

Three content categories:

  HELP_CONTENT    — Parameter-level help (popovers via HelpButton)
  SECTION_CARDS   — Section-level guidance cards (GuidanceCard)
  MODALITY_INFO   — Camera type descriptions
  WORKFLOW_STEPS  — Re-exported from steps.py for convenience
"""
from __future__ import annotations

from ui.guidance.steps import WORKFLOW_STEPS, get_step  # noqa: F401


# ══════════════════════════════════════════════════════════════════════
#  MODALITY INFO
# ══════════════════════════════════════════════════════════════════════

MODALITY_INFO: dict[str, tuple[str, str]] = {
    "tr": ("Thermoreflectance",
           "Measures relative reflectance change (ΔR/R) induced by "
           "thermal modulation.  Best for high-spatial-resolution "
           "hotspot detection."),
    "ir": ("IR Lock-in Thermography",
           "Measures thermal emission under periodic stimulus.  "
           "Suited for failure isolation and backside imaging."),
}


def get_modality_info(cam_type: str) -> tuple[str, str]:
    """Return (name, description) for a camera type."""
    return MODALITY_INFO.get(cam_type, ("", ""))


# ══════════════════════════════════════════════════════════════════════
#  SECTION-LEVEL GUIDANCE CARDS
# ══════════════════════════════════════════════════════════════════════
#
# Each section key maps to a list of card dicts.  Cards with
# step_number are shown in Guided mode; the "overview" card (no
# step_number) is shown in Standard/Expert mode.
#
# Keys:
#   card_id      str   unique persistent ID for dismissal
#   title        str   card header text
#   body         str   help text (HTML subset supported by QLabel)
#   step_number  int?  numbered badge (Guided mode only)

SECTION_CARDS: dict[str, list[dict]] = {

    # ── Modality ────────────────────────────────────────────────────
    "modality": [
        {
            "card_id": "modality.overview",
            "title": "Getting Started with Modality",
            "body": (
                "Your <b>camera type</b> determines the measurement technique. "
                "<b>TR</b> detects surface hotspots via reflectance change. "
                "<b>IR</b> images thermal emission for backside analysis. "
                "A <b>profile</b> pre-loads optimized settings for your "
                "sample type."
            ),
        },
        {
            "card_id": "modality.technique",
            "title": "Choose Your Measurement Technique",
            "body": (
                "Your <b>camera type</b> determines the measurement technique. "
                "<b>Thermoreflectance (TR)</b> measures tiny changes in surface "
                "reflectivity caused by temperature — ideal for frontside hotspot "
                "detection at sub-micron resolution. "
                "<b>IR Lock-in</b> captures thermal emission through the substrate "
                "— ideal for backside failure analysis of flip-chip devices."
            ),
            "step_number": 1,
        },
        {
            "card_id": "modality.profile",
            "title": "Select a Measurement Profile",
            "body": (
                "Profiles load optimized capture settings for common sample "
                "types — exposure time, LED current, averaging count, and more. "
                "Choose a profile to get started quickly, or skip this step to "
                "configure everything manually."
            ),
            "step_number": 2,
        },
        {
            "card_id": "modality.finetune",
            "title": "Fine-Tune (Optional)",
            "body": (
                "Advanced users can adjust pixel pitch, sensor format, and "
                "wavelength filter. These are auto-populated from your profile "
                "— only change them if you know you need different values."
            ),
            "step_number": 3,
        },
    ],

    # ── Stimulus ────────────────────────────────────────────────────
    "stimulus": [
        {
            "card_id": "stimulus.overview",
            "title": "Getting Started with Stimulus",
            "body": (
                "The stimulus system drives periodic heating of your device. "
                "The <b>FPGA</b> generates the modulation signal, and the "
                "<b>bias source</b> delivers current to the DUT. Settings "
                "are auto-loaded from your profile."
            ),
        },
        {
            "card_id": "stimulus.modulation",
            "title": "Configure the Modulation Signal",
            "body": (
                "The FPGA generates a square wave that alternates the device "
                "between heated (hot) and unheated (cold) states. The "
                "<b>modulation frequency</b> must match your camera frame rate "
                "for lock-in detection to work. Your profile sets this "
                "automatically."
            ),
            "step_number": 1,
        },
        {
            "card_id": "stimulus.bias",
            "title": "Set the Bias Current",
            "body": (
                "The bias source delivers electrical current to heat the "
                "device under test. Set the current to the device's operating "
                "condition — too low and the thermal signal is weak, too high "
                "risks device damage."
            ),
            "step_number": 2,
        },
    ],

    # ── Temperature ─────────────────────────────────────────────────
    "temperature": [
        {
            "card_id": "temperature.overview",
            "title": "Getting Started with Temperature",
            "body": (
                "The TEC controller stabilizes your sample at a known "
                "temperature. Set a target, enable the output, and wait "
                "for the 'Stable' indicator before measuring."
            ),
        },
        {
            "card_id": "temperature.setup",
            "title": "Set a Stable Baseline",
            "body": (
                "Thermoreflectance measures <i>changes</i> in temperature, "
                "so a stable baseline is critical. Set your TEC to the "
                "desired temperature (typically 25–30 °C) and wait for "
                "the temperature readout to stabilize within ±0.1 °C."
            ),
            "step_number": 1,
        },
    ],

    # ── Live View ───────────────────────────────────────────────────
    "live_view": [
        {
            "card_id": "live_view.overview",
            "title": "Getting Started with Live View",
            "body": (
                "Live View shows a real-time ΔR/R thermal map. Use it to "
                "verify your sample is visible, in focus, and producing "
                "a measurable signal before capturing."
            ),
        },
        {
            "card_id": "live_view.verify",
            "title": "Verify Your Sample Is Visible",
            "body": (
                "The live feed should start automatically once your camera "
                "is connected. You should see the sample surface in the "
                "preview. If the image is dark or blank, check that the "
                "LED illumination is on and the camera shutter is open. "
                "Look for surface features — edges, pads, or traces — "
                "that confirm the sample is in view."
            ),
            "step_number": 1,
        },
    ],

    # ── Focus & Stage ───────────────────────────────────────────────
    "focus_stage": [
        {
            "card_id": "focus_stage.overview",
            "title": "Getting Started with Focus & Stage",
            "body": (
                "Precise focus is essential for spatial resolution. Use "
                "<b>autofocus</b> or the manual Z controls to find the "
                "sharpest image. The stage X/Y controls position the "
                "sample under the objective."
            ),
        },
        {
            "card_id": "focus_stage.home",
            "title": "Home the Stage",
            "body": (
                "Before positioning, the stage must be <b>homed</b> to "
                "establish its coordinate reference. Check the "
                "<b>Stage</b> tab — if it has a red dot, it needs your "
                "attention. Click <b>Home</b> to initialise all axes. "
                "This takes about 30 seconds."
            ),
            "step_number": 1,
        },
        {
            "card_id": "focus_stage.focus",
            "title": "Focus on Your Sample",
            "body": (
                "Switch to the <b>Focus</b> tab and click "
                "<b>Auto-Focus</b> to find the sharpest image "
                "automatically. If autofocus does not converge (e.g. on "
                "a featureless surface), use the manual Z controls to "
                "adjust. The live view updates in real time so you can "
                "see the focus improving."
            ),
            "step_number": 2,
        },
    ],

    # ── Signal Check ────────────────────────────────────────────────
    "signal_check": [
        {
            "card_id": "signal_check.overview",
            "title": "Getting Started with Signal Check",
            "body": (
                "Signal Check verifies that your measurement setup is "
                "producing a usable thermal signal. It checks exposure, "
                "noise level, and SNR. If the check fails, adjust focus "
                "or exposure and retry."
            ),
        },
        {
            "card_id": "signal_check.run",
            "title": "Run the Signal Quality Check",
            "body": (
                "Click <b>Run Check</b> to measure the thermal signal "
                "from your current setup. The check evaluates exposure "
                "level, background noise, and signal-to-noise ratio (SNR). "
                "A <b>green pass</b> means you're ready to capture. "
                "If you see a <b>red fail</b>, go back to Focus & Stage "
                "to improve focus or adjust exposure in the Camera settings."
            ),
            "step_number": 1,
        },
    ],

    # ── Capture ─────────────────────────────────────────────────────
    "capture": [
        {
            "card_id": "capture.overview",
            "title": "Getting Started with Capture",
            "body": (
                "Capture mode acquires a full measurement: multiple "
                "hot/cold frame pairs averaged together for high SNR. "
                "Use <b>Single</b> for a single-point measurement or "
                "<b>Grid</b> to scan across a large area."
            ),
        },
        {
            "card_id": "capture.settings",
            "title": "Review Capture Settings",
            "body": (
                "Your profile has pre-loaded the frame count and "
                "averaging depth. Higher frame counts give better SNR "
                "but take longer. Check the <b>time estimate</b> at "
                "the bottom to see how long the acquisition will take."
            ),
            "step_number": 1,
        },
        {
            "card_id": "capture.acquire",
            "title": "Start the Acquisition",
            "body": (
                "When you're ready, click <b>Acquire</b>. The system "
                "will collect hot and cold frames, compute ΔR/R, and "
                "save the result as a session. You'll see a success "
                "notification when it's done, and the result will appear "
                "in <b>Sessions</b>."
            ),
            "step_number": 2,
        },
    ],

    # ── Calibration ─────────────────────────────────────────────────
    "calibration": [
        {
            "card_id": "calibration.overview",
            "title": "Getting Started with Calibration",
            "body": (
                "Calibration converts ΔR/R to absolute temperature (°C). "
                "Run a <b>calibration sweep</b> to measure the "
                "thermoreflectance coefficient (C<sub>T</sub>) for your "
                "specific material and wavelength, or load a saved .cal file."
            ),
        },
        {
            "card_id": "calibration.sweep",
            "title": "Run a Calibration Sweep",
            "body": (
                "Set a temperature sequence (start, end, step) and click "
                "<b>Run Calibration</b>. The TEC will step through each "
                "temperature while the camera records reflectance. "
                "The system fits ΔR/R vs. ΔT to extract C<sub>T</sub>. "
                "If you already have a saved <b>.cal file</b>, you can "
                "load it instead and skip this step."
            ),
            "step_number": 1,
        },
    ],

    # ── Sessions ────────────────────────────────────────────────────
    "sessions": [
        {
            "card_id": "sessions.overview",
            "title": "Getting Started with Sessions",
            "body": (
                "Sessions organize your measurements. Each capture is "
                "saved with metadata, tags, and notes. Use the session "
                "browser to compare results, export data, or resume "
                "a previous measurement."
            ),
        },
        {
            "card_id": "sessions.review",
            "title": "Review Your Results",
            "body": (
                "Select a session from the list on the left to view its "
                "images and metadata. Use the <b>Cold</b>, <b>Hot</b>, "
                "<b>Difference</b>, and <b>ΔR/R</b> tabs to examine "
                "different views of your measurement. Add tags and notes "
                "to keep your data organized."
            ),
            "step_number": 1,
        },
    ],

    # ── Hardware Readiness ─────────────────────────────────────────
    "hardware_readiness": [
        {
            "card_id": "hardware_readiness.overview",
            "title": "Hardware Readiness Check",
            "body": (
                "The readiness orchestrator verifies that all connected "
                "hardware is communicating, calibrated, and within safe "
                "operating limits before you begin an acquisition."
            ),
        },
        {
            "card_id": "hardware_readiness.verify",
            "title": "Verify All Hardware Is Ready",
            "body": (
                "Click <b>Run Readiness Check</b> to test all connected "
                "devices in sequence. Each device shows a pass/fail "
                "status — green means ready, red means action is needed. "
                "If any device fails, follow the suggested fix before "
                "proceeding to capture."
            ),
            "step_number": 1,
        },
        {
            "card_id": "hardware_readiness.optimize",
            "title": "Apply Optimization Suggestions",
            "body": (
                "After the readiness check, the system may suggest "
                "optimizations such as <b>auto-gain</b> adjustment, "
                "<b>TEC preconditioning</b>, or <b>exposure tuning</b>. "
                "Review the tips and apply any that improve your "
                "measurement quality."
            ),
            "step_number": 2,
        },
    ],

    # ── Data Export ────────────────────────────────────────────────
    "data_export": [
        {
            "card_id": "data_export.overview",
            "title": "Exporting Your Data",
            "body": (
                "Export sessions in formats compatible with your analysis "
                "tools: <b>TIFF</b> for ImageJ, <b>HDF5</b> for Python "
                "and MATLAB, <b>CSV</b> for spreadsheets. Each export "
                "includes full metadata and spatial calibration."
            ),
        },
        {
            "card_id": "data_export.formats",
            "title": "Choose Export Formats",
            "body": (
                "Select one or more formats in the export dialog. "
                "<b>32-bit TIFF</b> preserves full precision for image "
                "analysis. <b>HDF5</b> bundles all arrays and metadata "
                "in a single file. <b>CSV</b> is best for importing ΔT "
                "values into a spreadsheet."
            ),
            "step_number": 1,
        },
        {
            "card_id": "data_export.presets",
            "title": "Save an Export Preset",
            "body": (
                "If you export regularly with the same settings, save "
                "a <b>preset</b> to recall your format selection and "
                "spatial calibration instantly. Presets appear in the "
                "dropdown at the top of the export dialog."
            ),
            "step_number": 2,
        },
    ],

    # ── Reporting ──────────────────────────────────────────────────
    "reporting": [
        {
            "card_id": "reporting.overview",
            "title": "Generating Reports",
            "body": (
                "Reports summarize your measurement with thermal maps, "
                "hotspot tables, quality scores, and analysis verdicts. "
                "Choose <b>PDF</b> for printable documents or <b>HTML</b> "
                "for interactive viewing in a browser."
            ),
        },
        {
            "card_id": "reporting.configure",
            "title": "Configure Report Content",
            "body": (
                "Use the checkboxes in the report dialog to choose which "
                "sections to include. The <b>live preview</b> on the "
                "right updates as you toggle sections, so you can see "
                "exactly what will appear in the final document."
            ),
            "step_number": 1,
        },
        {
            "card_id": "reporting.templates",
            "title": "Save a Report Template",
            "body": (
                "Save your content selections as a <b>template preset</b> "
                "for quick reuse. Templates remember which sections are "
                "enabled, the output format, and your operator/customer "
                "metadata — ideal for recurring test reports."
            ),
            "step_number": 2,
        },
        {
            "card_id": "reporting.batch",
            "title": "Batch Report Generation",
            "body": (
                "Generate reports for multiple sessions at once using "
                "<b>Batch Report</b>. Select the sessions, choose a "
                "template, and the system will produce one report per "
                "session in the background."
            ),
            "step_number": 3,
        },
    ],

    # ── Analysis Review ────────────────────────────────────────────
    "analysis_review": [
        {
            "card_id": "analysis_review.overview",
            "title": "Reviewing Analysis Results",
            "body": (
                "After calibration and analysis, review the verdict "
                "and hotspot locations before finalizing your session. "
                "Mark the session status to track its review state."
            ),
        },
        {
            "card_id": "analysis_review.verdict",
            "title": "Inspect the Verdict",
            "body": (
                "The analysis assigns a <b>PASS</b>, <b>WARN</b>, or "
                "<b>FAIL</b> verdict based on your threshold rules. "
                "Review the hotspot table and thermal map to confirm "
                "the verdict matches your engineering judgement."
            ),
            "step_number": 1,
        },
        {
            "card_id": "analysis_review.status",
            "title": "Set Session Status",
            "body": (
                "Mark the session as <b>Reviewed</b> once you've "
                "confirmed the results, or <b>Flagged</b> if further "
                "investigation is needed. Use the status filter in the "
                "session list to quickly find unreviewed measurements."
            ),
            "step_number": 2,
        },
    ],
}


def get_section_cards(section: str) -> list[dict]:
    """Return all guidance card definitions for a section."""
    return SECTION_CARDS.get(section, [])


# ══════════════════════════════════════════════════════════════════════
#  PARAMETER-LEVEL HELP CONTENT
# ══════════════════════════════════════════════════════════════════════
#
# Each entry is a dict with:
#   title      : short display name
#   what       : plain-English explanation (1-3 sentences, no jargon)
#   do         : concrete action recommendation
#   range      : expected values / normal operating range (optional)
#   warning    : common mistake or gotcha (optional)
#   docs       : section name in user manual (optional)

HELP_CONTENT: dict[str, dict] = {

    # ── Analysis / Pass-Fail ────────────────────────────────────────

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

    # ── Camera ──────────────────────────────────────────────────────

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

    # ── Acquisition ─────────────────────────────────────────────────

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

    # ── Calibration ─────────────────────────────────────────────────

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

    # ── ROI ─────────────────────────────────────────────────────────

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

    # ── Autofocus ───────────────────────────────────────────────────

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

    # ── Profiles ────────────────────────────────────────────────────

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

    # ── Live mode ───────────────────────────────────────────────────

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

    # ── Stage ───────────────────────────────────────────────────────

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

    # ── FPGA ────────────────────────────────────────────────────────

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

    # ── Material & Calibration reference ────────────────────────────

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

    # ── Optics & Technique reference ────────────────────────────────

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

    # ── Scan ────────────────────────────────────────────────────────

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

    # ── Objective turret ────────────────────────────────────────────

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

    # ── Movie mode ──────────────────────────────────────────────────

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

    # ── Transient tab ───────────────────────────────────────────────

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

    # ── Probe station ───────────────────────────────────────────────

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

    # ── Thermal chuck ───────────────────────────────────────────────

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


def get_help(topic_id: str) -> dict:
    """Look up parameter help content by topic ID.

    Returns a dict with title/what/do/range/warning/docs, or a
    placeholder if the topic is not found.
    """
    return HELP_CONTENT.get(topic_id, {
        "title": topic_id,
        "what":  "No help available for this topic yet.",
        "do":    "",
    })
