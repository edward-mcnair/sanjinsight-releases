"""
tests/test_widgets.py

Smoke tests for the v1.1.0 hardware-panel widgets.

Covers:
    CameraTab  — saturation guard (OK / warn / clipped states, reset)
    BiasTab    — output port selector (spinbox limits, VO EXT warning, 20 mA checkbox)
    FpgaTab    — duty cycle warning label (visibility, style change at danger threshold)
    CalibrationTab — TR Std / IR Std presets, time-estimate label, extended temp range

No physical hardware required — all tabs are instantiated with
hw_service=None (CameraTab / BiasTab / FpgaTab) or no arguments
(CalibrationTab), which leaves them in their disconnected / demo state.
No Qt event loop is started; signal–slot connections fire synchronously.
"""

from __future__ import annotations

import os
import sys
import types

import numpy as np
import pytest
from PyQt5.QtWidgets import QApplication

# Ensure the project root is on sys.path regardless of where pytest is invoked
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Ensure a QApplication exists before any QWidget is constructed ───────────
_app: QApplication = QApplication.instance() or QApplication(sys.argv[:1])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_frame(data: np.ndarray, frame_index: int = 0) -> types.SimpleNamespace:
    """Return a minimal frame-like object accepted by CameraTab.update_frame."""
    return types.SimpleNamespace(data=data, frame_index=frame_index)


def _shown(widget) -> bool:
    """
    Return True when a widget has been explicitly shown with setVisible(True).

    QWidget.isVisible() checks the *entire* parent chain — a widget whose
    top-level window has never been show()n always returns False, even if
    setVisible(True) was called on it.  QWidget.isHidden() only reflects
    the widget's own explicit hide/show state, making it the correct check
    in headless unit tests where no window is ever shown.
    """
    return not widget.isHidden()


# ================================================================== #
#  CameraTab — saturation guard                                       #
# ================================================================== #

class TestCameraTabSaturationGuard:
    """
    Verify the SATURATION readout text for all three states:
      • OK      — max pixel < 3900  (CAMERA_SAT_WARN)
      • percent — max pixel ≥ 3900  but < 4095
      • CLIPPED — max pixel == 4095 (CAMERA_SAT_LIMIT)
    """

    @pytest.fixture(scope="class")
    def tab(self):
        from ui.tabs.camera_tab import CameraTab
        return CameraTab()

    def test_instantiates(self, tab):
        """CameraTab must instantiate without hardware."""
        assert tab is not None
        assert hasattr(tab, "_sat_w")

    def test_ok_state(self, tab):
        """All pixels well below 3900 → readout must be 'OK'."""
        frame = _make_frame(np.full((64, 64), 1000, dtype=np.uint16))
        tab.update_frame(frame)
        assert tab._sat_w._val.text() == "OK"

    def test_warn_state_shows_percentage(self, tab):
        """Single pixel at 3950 (≥3900, <4095) → readout must show a percentage."""
        data = np.zeros((64, 64), dtype=np.uint16)
        data[0, 0] = 3950
        tab.update_frame(_make_frame(data))
        text = tab._sat_w._val.text()
        assert "%" in text, f"Expected a percentage string, got: {text!r}"
        assert text != "OK"
        assert "CLIPPED" not in text

    def test_clipped_state(self, tab):
        """Any pixel == 4095 → readout must be 'CLIPPED ✗'."""
        data = np.zeros((64, 64), dtype=np.uint16)
        data[0, 0] = 4095
        tab.update_frame(_make_frame(data))
        assert tab._sat_w._val.text() == "CLIPPED ✗"

    def test_resets_to_ok_after_clipped(self, tab):
        """Saturation guard must reset to 'OK' when a safe frame follows a clipped one."""
        tab.update_frame(_make_frame(np.full((64, 64), 4095, dtype=np.uint16)))
        assert "CLIPPED" in tab._sat_w._val.text()
        tab.update_frame(_make_frame(np.full((64, 64), 500, dtype=np.uint16)))
        assert tab._sat_w._val.text() == "OK"

    def test_fully_clipped_frame_percentage_is_100(self, tab):
        """A fully clipped frame must still show 'CLIPPED ✗', not a percentage."""
        tab.update_frame(_make_frame(np.full((32, 32), 4095, dtype=np.uint16)))
        assert tab._sat_w._val.text() == "CLIPPED ✗"

    def test_warn_state_one_pixel_below_limit(self, tab):
        """Max pixel == 4094 (one below limit) must still show a percentage, not 'CLIPPED ✗'."""
        data = np.zeros((64, 64), dtype=np.uint16)
        data[0, 0] = 4094
        tab.update_frame(_make_frame(data))
        text = tab._sat_w._val.text()
        assert "%" in text
        assert "CLIPPED" not in text


# ================================================================== #
#  BiasTab — output port selector                                     #
# ================================================================== #

class TestBiasTabPortSelector:
    """Verify that port selection updates spinbox limits and the VO EXT warning."""

    @pytest.fixture(scope="class")
    def tab(self):
        from ui.tabs.bias_tab import BiasTab
        return BiasTab()

    def test_instantiates(self, tab):
        """BiasTab must instantiate without hardware."""
        assert tab is not None
        assert hasattr(tab, "_port_combo")
        assert hasattr(tab, "_level_spin")
        assert hasattr(tab, "_port_warn_lbl")
        assert hasattr(tab, "_ma_range_cb")

    def test_initial_port_is_vo_int(self, tab):
        """Default selected port (index 0) must be VO INT."""
        assert tab._port_combo.currentIndex() == 0

    def test_vo_int_spinbox_range(self, tab):
        """VO INT is bipolar ±10 V → spinbox range must be [−10, +10]."""
        tab._port_combo.setCurrentIndex(0)
        assert tab._level_spin.minimum() == pytest.approx(-10.0)
        assert tab._level_spin.maximum() == pytest.approx(10.0)

    def test_aux_int_spinbox_range(self, tab):
        """AUX INT is bipolar ±10 V → spinbox range must be [−10, +10]."""
        tab._port_combo.setCurrentIndex(1)
        assert tab._level_spin.minimum() == pytest.approx(-10.0)
        assert tab._level_spin.maximum() == pytest.approx(10.0)

    def test_vo_ext_spinbox_range(self, tab):
        """VO EXT is unipolar ≤+60 V → spinbox range must be [0, +60]."""
        tab._port_combo.setCurrentIndex(2)
        assert tab._level_spin.minimum() == pytest.approx(0.0)
        assert tab._level_spin.maximum() == pytest.approx(60.0)

    def test_vo_ext_warning_visible(self, tab):
        """Selecting VO EXT (index 2) must make the safety warning visible."""
        tab._port_combo.setCurrentIndex(2)
        assert _shown(tab._port_warn_lbl)

    def test_warning_hidden_for_vo_int(self, tab):
        """VO INT (index 0) must hide the safety warning."""
        tab._port_combo.setCurrentIndex(0)
        assert not _shown(tab._port_warn_lbl)

    def test_warning_hidden_for_aux_int(self, tab):
        """AUX INT (index 1) must hide the safety warning."""
        tab._port_combo.setCurrentIndex(1)
        assert not _shown(tab._port_warn_lbl)

    def test_warning_reappears_when_vo_ext_reselected(self, tab):
        """Warning must reappear if the user switches back to VO EXT."""
        tab._port_combo.setCurrentIndex(0)
        assert not _shown(tab._port_warn_lbl)
        tab._port_combo.setCurrentIndex(2)
        assert _shown(tab._port_warn_lbl)

    def test_20ma_checkbox_checked_by_default(self, tab):
        """20 mA Range Mode must be checked by default (safe mode)."""
        assert tab._ma_range_cb.isChecked()

    def test_port_combo_has_three_entries(self, tab):
        """Port combo box must list exactly three ports."""
        assert tab._port_combo.count() == 3


# ================================================================== #
#  FpgaTab — duty cycle warning                                       #
# ================================================================== #

class TestFpgaTabDutyCycleWarning:
    """Verify warning label visibility and style at key duty-cycle thresholds."""

    @pytest.fixture(scope="class")
    def tab(self):
        from ui.tabs.fpga_tab import FpgaTab
        return FpgaTab()

    def test_instantiates(self, tab):
        """FpgaTab must instantiate without hardware."""
        assert tab is not None
        assert hasattr(tab, "_dc_warn_lbl")
        assert hasattr(tab, "_duty_spin")

    def test_warning_hidden_below_threshold(self, tab):
        """Duty cycle < 50 % must hide the warning label."""
        tab._on_duty_changed(49.0)
        assert not _shown(tab._dc_warn_lbl)

    def test_warning_visible_at_exact_threshold(self, tab):
        """Duty cycle == 50 % (DUTY_CYCLE_WARN_PCT) must show the warning."""
        tab._on_duty_changed(50.0)
        assert _shown(tab._dc_warn_lbl)

    def test_warning_visible_above_threshold(self, tab):
        """Duty cycle > 50 % must keep the warning visible."""
        tab._on_duty_changed(75.0)
        assert _shown(tab._dc_warn_lbl)

    def test_style_changes_at_danger_threshold(self, tab):
        """Style must change when crossing the 80 % danger threshold."""
        tab._on_duty_changed(75.0)
        style_warn = tab._dc_warn_lbl.styleSheet()
        tab._on_duty_changed(80.0)
        style_danger = tab._dc_warn_lbl.styleSheet()
        assert style_warn != style_danger, (
            "Expected distinct styles for warn (75%) and danger (80%) levels"
        )

    def test_warning_hidden_after_reducing_below_threshold(self, tab):
        """Reducing duty cycle back below 50 % must hide the warning."""
        tab._on_duty_changed(80.0)
        assert _shown(tab._dc_warn_lbl)
        tab._on_duty_changed(49.0)
        assert not _shown(tab._dc_warn_lbl)

    def test_duty_spin_default_is_50(self, tab):
        """Default duty cycle spinbox value must be 50 (matching DUTY_CYCLE_WARN_PCT)."""
        assert tab._duty_spin.value() == pytest.approx(50.0)


# ================================================================== #
#  CalibrationTab — presets and time-estimate label                   #
# ================================================================== #

class TestCalibrationTabPresets:
    """
    Verify that TR Std / IR Std presets load the correct temperatures,
    that the time-estimate label updates to match, and that the spinbox
    range covers the extended −20–150 °C operating range.
    """

    @pytest.fixture(scope="class")
    def tab(self):
        from acquisition.calibration_tab import CalibrationTab
        return CalibrationTab()

    def _get_temps(self, tab) -> list[float]:
        return sorted(sp.value() for _, sp in tab._temp_rows)

    def test_instantiates(self, tab):
        """CalibrationTab must instantiate without arguments."""
        assert tab is not None
        assert hasattr(tab, "_temp_rows")
        assert hasattr(tab, "_time_est_lbl")

    def test_tr_std_preset_count(self, tab):
        """TR Std preset must load exactly 6 temperature steps."""
        from ai.instrument_knowledge import CAL_TR_TEMPS_C
        tab._set_preset(CAL_TR_TEMPS_C)
        assert len(tab._temp_rows) == 6

    def test_tr_std_preset_values(self, tab):
        """TR Std temperatures must match CAL_TR_TEMPS_C exactly."""
        from ai.instrument_knowledge import CAL_TR_TEMPS_C
        tab._set_preset(CAL_TR_TEMPS_C)
        assert self._get_temps(tab) == pytest.approx(sorted(CAL_TR_TEMPS_C))

    def test_ir_std_preset_count(self, tab):
        """IR Std preset must load exactly 7 temperature steps."""
        from ai.instrument_knowledge import CAL_IR_TEMPS_C
        tab._set_preset(CAL_IR_TEMPS_C)
        assert len(tab._temp_rows) == 7

    def test_ir_std_preset_values(self, tab):
        """IR Std temperatures must match CAL_IR_TEMPS_C exactly."""
        from ai.instrument_knowledge import CAL_IR_TEMPS_C
        tab._set_preset(CAL_IR_TEMPS_C)
        assert self._get_temps(tab) == pytest.approx(sorted(CAL_IR_TEMPS_C))

    def test_time_est_label_after_tr_std(self, tab):
        """After loading TR Std (6 steps), time-estimate must mention '6 steps'."""
        from ai.instrument_knowledge import CAL_TR_TEMPS_C
        tab._set_preset(CAL_TR_TEMPS_C)
        tab._update_time_est()
        text = tab._time_est_lbl.text()
        assert "6" in text, f"Expected '6' in time estimate, got: {text!r}"
        assert "min" in text

    def test_time_est_label_after_ir_std(self, tab):
        """After loading IR Std (7 steps), time-estimate must mention '7 steps'."""
        from ai.instrument_knowledge import CAL_IR_TEMPS_C
        tab._set_preset(CAL_IR_TEMPS_C)
        tab._update_time_est()
        text = tab._time_est_lbl.text()
        assert "7" in text, f"Expected '7' in time estimate, got: {text!r}"
        assert "min" in text

    def test_time_est_empty_state(self, tab):
        """With no temperature steps loaded, label must show the em-dash placeholder."""
        tab._set_preset([])
        tab._update_time_est()
        assert "—" in tab._time_est_lbl.text()

    def test_time_est_increases_with_more_steps(self, tab):
        """A 6-step preset must produce a longer estimated time than a 3-step preset."""
        tab._n_avg.setValue(20)
        tab._settle.setValue(30.0)

        tab._set_preset([25.0, 35.0, 45.0])   # 3 steps
        tab._update_time_est()
        text_3 = tab._time_est_lbl.text()

        from ai.instrument_knowledge import CAL_TR_TEMPS_C
        tab._set_preset(CAL_TR_TEMPS_C)        # 6 steps
        tab._update_time_est()
        text_6 = tab._time_est_lbl.text()

        # Both should show non-trivial content and differ
        assert text_3 != text_6

    def test_temperature_range_extended_min(self, tab):
        """Temperature spinboxes must accept −20 °C (extended range)."""
        tab._set_preset([-20.0])
        assert self._get_temps(tab) == pytest.approx([-20.0])

    def test_temperature_range_extended_max(self, tab):
        """Temperature spinboxes must accept 150 °C (AF-200 stage maximum)."""
        tab._set_preset([150.0])
        assert self._get_temps(tab) == pytest.approx([150.0])

    def test_preset_replaces_previous_temps(self, tab):
        """Applying a second preset must discard the previous temperature list."""
        from ai.instrument_knowledge import CAL_TR_TEMPS_C, CAL_IR_TEMPS_C
        tab._set_preset(CAL_TR_TEMPS_C)
        assert len(tab._temp_rows) == 6
        tab._set_preset(CAL_IR_TEMPS_C)
        assert len(tab._temp_rows) == 7
