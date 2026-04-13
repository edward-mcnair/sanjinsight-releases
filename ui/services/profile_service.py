"""
ui/services/profile_service.py

Extracts material-profile application logic from MainWindow.

The ``ProfileApplicationService`` encapsulates the 20-step fan-out that
happens when a user selects or loads a material profile.  All widget
references are injected via ``set_targets()`` after MainWindow construction.
"""

import logging
import time
import threading

from PyQt5.QtCore import Qt

log = logging.getLogger(__name__)


class ProfileApplicationService:
    """Coordinate profile save / load / apply across all subsystems."""

    def __init__(self):
        # Injected later via set_targets()
        self._hw = None
        self._app_state = None
        self._header = None
        self._toasts = None
        self._log_tab = None
        self._status = None
        self._phase_tracker = None
        self._recipe_store = None
        self._profile_mgr = None
        # Tabs (set via set_targets)
        self._camera_tab = None
        self._acquire_tab = None
        self._live_tab = None
        self._scan_tab = None
        self._fpga_tab = None
        self._bias_tab = None
        self._cal_tab = None
        self._af_tab = None
        self._analysis_tab = None
        self._signal_check_section = None
        self._modality_section = None
        self._nav = None
        self._library_tab = None
        # Callbacks
        self._maybe_launch_advisor = None
        self._on_auto_expose_done = None
        # Guard
        self._advisor_launched_for = None

    def set_targets(self, **kw):
        """Inject all widget / service references.  Call once after __init__."""
        for k, v in kw.items():
            setattr(self, f"_{k}", v)

    # ── Save / Load dialogs ──────────────────────────────────────────

    def navigate_to_profiles(self):
        """Navigate to the Library tab → Recipes sub-tab."""
        self._nav.navigate_to(self._library_tab)
        self._library_tab._tabs.setCurrentIndex(1)

    def save_dialog(self, parent):
        """Show dialog to save current state as a named profile."""
        from PyQt5.QtWidgets import QInputDialog
        from acquisition.recipe_tab import Recipe

        label, ok = QInputDialog.getText(
            parent, "Save Profile",
            "Profile name:",
            text=f"Profile {time.strftime('%Y-%m-%d %H:%M')}")
        if not ok or not label.strip():
            return

        label = label.strip()
        recipe = Recipe.from_current_state(self._app_state, label=label)

        # Capture TEC and bias state
        if self._app_state.tecs:
            try:
                tec = self._app_state.tecs[0]
                st = tec.get_status()
                recipe.tec.enabled = True
                recipe.tec.setpoint_c = st.target_temp
            except Exception:
                pass
        if self._app_state.bias is not None:
            try:
                st = self._app_state.bias.get_status()
                recipe.bias.enabled = True
                recipe.bias.voltage_v = st.actual_voltage
                recipe.bias.current_a = st.actual_current
            except Exception:
                pass

        # Capture FPGA settings
        if self._app_state.fpga is not None:
            try:
                self._app_state.fpga.get_status()
                recipe.acquisition.modality = getattr(
                    self._app_state, "active_modality", "thermoreflectance")
            except Exception:
                pass

        self._recipe_store.save(recipe)
        self._header._profile_btn.set_active_recipe(label)
        self._toasts.show_success(f"Profile saved: {label}")
        log.info("Profile saved: %s", label)

    def open_dialog(self, parent):
        """Show dialog listing saved profiles for user to open."""
        from PyQt5.QtWidgets import QInputDialog

        recipes = self._recipe_store.list()
        if not recipes:
            self._toasts.show_warning("No saved profiles found.")
            return

        labels = [r.label for r in recipes]
        chosen, ok = QInputDialog.getItem(
            parent, "Open Profile", "Select a profile:", labels, 0, False)
        if not ok:
            return

        recipe = self._recipe_store.load(chosen)
        if recipe:
            self.load_profile(recipe)

    def load_profile(self, recipe):
        """Apply a saved profile without starting acquisition."""
        log.info("Loading profile: %s", recipe.label)

        # Camera
        try:
            self._hw.cam_set_exposure(recipe.camera.exposure_us)
            self._hw.cam_set_gain(recipe.camera.gain_db)
            self._camera_tab.set_exposure(recipe.camera.exposure_us)
            self._camera_tab.set_gain(recipe.camera.gain_db)
        except Exception as e:
            log.debug("Profile load — camera: %s", e)

        # Modality
        self._app_state.active_modality = recipe.acquisition.modality

        # Material profile
        if recipe.profile_name:
            try:
                _find = getattr(self._profile_mgr, 'find_by_name',
                                self._profile_mgr.find)
                profile = _find(recipe.profile_name)
                if profile:
                    self.apply(profile)
            except Exception as e:
                log.debug("Profile load — material profile: %s", e)

        # TEC
        if recipe.tec.enabled:
            for idx in range(len(self._app_state.tecs)):
                try:
                    self._hw.tec_set_target(idx, recipe.tec.setpoint_c)
                except Exception:
                    pass

        # Analysis
        try:
            from acquisition.analysis import AnalysisConfig
            cfg = AnalysisConfig(
                threshold_k=recipe.analysis.threshold_k,
                fail_hotspot_count=recipe.analysis.fail_hotspot_count,
                fail_peak_k=recipe.analysis.fail_peak_k,
                fail_area_fraction=recipe.analysis.fail_area_fraction,
                warn_hotspot_count=recipe.analysis.warn_hotspot_count,
                warn_peak_k=recipe.analysis.warn_peak_k,
                warn_area_fraction=recipe.analysis.warn_area_fraction,
            )
            self._analysis_tab.set_config(cfg)
        except Exception as e:
            log.debug("Profile load — analysis: %s", e)

        self._header._profile_btn.set_active_recipe(recipe.label)
        self._toasts.show_success(f"Profile loaded: {recipe.label}")

    # ── Core profile application (20-step fan-out) ───────────────────

    def apply(self, profile):
        """Propagate a material profile's settings to all subsystems."""
        self._app_state.active_profile = profile
        self._advisor_launched_for = None

        # 1. Header indicator
        self._header.set_profile(profile)

        # 1b. Modality section profile picker
        try:
            self._modality_section._profile_picker.set_profile(profile)
        except Exception as _e:
            log.debug("Profile apply — modality picker sync: %s", _e)

        # 2. Camera settings
        try:
            self._hw.cam_set_exposure(profile.exposure_us)
            self._hw.cam_set_gain(profile.gain_db)
            self._camera_tab.set_exposure(profile.exposure_us)
            self._camera_tab.set_gain(profile.gain_db)
        except Exception as _e:
            log.warning("Profile apply — camera settings: %s", _e)

        # 3. Acquisition frame count
        try:
            self._acquire_tab.set_n_frames(profile.n_frames)
        except Exception as _e:
            log.debug("Profile apply — acquire n_frames: %s", _e)

        # 4. Live tab accumulation + frames per half
        try:
            self._live_tab._frames_per_half.setValue(
                max(2, profile.n_frames // 4))
            self._live_tab._accum.setValue(profile.accumulation)
        except Exception as _e:
            log.debug("Profile apply — live tab settings: %s", _e)

        # 5. Scan frames per tile
        try:
            self._scan_tab._n_frames.setValue(profile.n_frames)
        except Exception as _e:
            log.debug("Profile apply — scan n_frames: %s", _e)

        # 6. Stimulus settings
        try:
            freq = getattr(profile, "stimulus_freq_hz", 0)
            duty = getattr(profile, "stimulus_duty", 0)
            if freq > 0:
                self._hw.fpga_set_frequency(freq)
                self._fpga_tab._freq_spin.setValue(freq)
            if duty > 0:
                self._hw.fpga_set_duty_cycle(duty)
                self._fpga_tab._duty_spin.setValue(duty * 100)
        except Exception as _e:
            log.debug("Profile apply — stimulus settings: %s", _e)

        # 7. TEC setpoint
        try:
            if getattr(profile, "tec_enabled", False):
                sp = getattr(profile, "tec_setpoint_c", 25.0)
                self._hw.tec_set_target(0, sp)
        except Exception as _e:
            log.debug("Profile apply — TEC settings: %s", _e)

        # 8. Bias source settings
        try:
            if getattr(profile, "bias_enabled", False):
                self._bias_tab._level_spin.setValue(
                    getattr(profile, "bias_voltage_v", 0))
                comp_ma = getattr(profile, "bias_compliance_ma", 100)
                self._bias_tab._comp_spin.setValue(comp_ma / 1000.0)
        except Exception as _e:
            log.debug("Profile apply — bias settings: %s", _e)

        # 9. Calibration settings
        try:
            cal_temps = getattr(profile, "cal_temps", "")
            settle = getattr(profile, "cal_settle_s", 60.0)
            if cal_temps:
                self._cal_tab.set_temp_sequence(cal_temps)
            if settle > 0:
                self._cal_tab._settle.setValue(settle)
            cal_n_avg = getattr(profile, "cal_n_avg", 0)
            if cal_n_avg > 0:
                self._cal_tab._n_avg.setValue(cal_n_avg)
            cal_tol = getattr(profile, "cal_stability_tol_c", 0)
            if cal_tol > 0:
                self._cal_tab._stable_tol.setValue(cal_tol)
            cal_dur = getattr(profile, "cal_stability_dur_s", 0)
            if cal_dur > 0:
                self._cal_tab._stable_dur.setValue(cal_dur)
            cal_r2 = getattr(profile, "cal_min_r2", 0)
            if cal_r2 > 0:
                self._cal_tab._min_r2.setValue(cal_r2)
        except Exception as _e:
            log.debug("Profile apply — calibration settings: %s", _e)

        # 10. Signal check SNR threshold + ROI strategy
        try:
            snr_thr = getattr(profile, "snr_threshold_db", 20.0)
            self._signal_check_section.set_snr_threshold(snr_thr)
            roi = getattr(profile, "roi_strategy", "")
            if roi:
                self._signal_check_section.set_roi_strategy(roi)
        except Exception as _e:
            log.debug("Profile apply — signal check settings: %s", _e)

        # 11. Grid scan defaults
        try:
            step = getattr(profile, "grid_step_um", 0)
            if step > 0:
                self._scan_tab.set_grid_from_profile(
                    step, getattr(profile, "grid_overlap_pct", 10.0))
        except Exception as _e:
            log.debug("Profile apply — grid scan settings: %s", _e)

        # 12. Autofocus defaults
        try:
            af_strat = getattr(profile, "af_strategy", "")
            if af_strat:
                idx = self._af_tab._strategy.findText(
                    af_strat, Qt.MatchFixedString)
                if idx >= 0:
                    self._af_tab._strategy.setCurrentIndex(idx)
            af_metric = getattr(profile, "af_metric", "")
            if af_metric:
                idx = self._af_tab._metric.findText(
                    af_metric, Qt.MatchFixedString)
                if idx >= 0:
                    self._af_tab._metric.setCurrentIndex(idx)
            af_z = getattr(profile, "af_z_range_um", 0)
            if af_z > 0:
                self._af_tab._z_start.setValue(-af_z / 2)
                self._af_tab._z_end.setValue(af_z / 2)
            af_c = getattr(profile, "af_coarse_um", 0)
            if af_c > 0:
                self._af_tab._coarse.setValue(af_c)
            af_f = getattr(profile, "af_fine_um", 0)
            if af_f > 0:
                self._af_tab._fine.setValue(af_f)
            af_n = getattr(profile, "af_n_avg", 0)
            if af_n > 0:
                self._af_tab._n_avg.setValue(af_n)
        except Exception as _e:
            log.debug("Profile apply — autofocus settings: %s", _e)

        # 13. FPGA trigger mode
        try:
            trig = getattr(profile, "trigger_mode", "continuous")
            if trig == "single_shot":
                self._fpga_tab._trig_single_rb.setChecked(True)
            else:
                self._fpga_tab._trig_cont_rb.setChecked(True)
        except Exception as _e:
            log.debug("Profile apply — trigger mode: %s", _e)

        # 14. BILT pulse settings
        try:
            if getattr(profile, "bias_enabled", False) and \
               hasattr(self._bias_tab, "_g_bias_sp"):
                self._bias_tab._g_bias_sp.setValue(
                    getattr(profile, "bilt_gate_bias_v", -5.0))
                self._bias_tab._g_pulse_sp.setValue(
                    getattr(profile, "bilt_gate_pulse_v", -2.2))
                self._bias_tab._g_width_sp.setValue(
                    getattr(profile, "bilt_gate_width_us", 110.0))
                self._bias_tab._g_delay_sp.setValue(
                    getattr(profile, "bilt_gate_delay_us", 5.0))
                self._bias_tab._d_bias_sp.setValue(
                    getattr(profile, "bilt_drain_bias_v", 0.0))
                self._bias_tab._d_pulse_sp.setValue(
                    getattr(profile, "bilt_drain_pulse_v", 1.0))
                self._bias_tab._d_width_sp.setValue(
                    getattr(profile, "bilt_drain_width_us", 100.0))
                self._bias_tab._d_delay_sp.setValue(
                    getattr(profile, "bilt_drain_delay_us", 10.0))
        except Exception as _e:
            log.debug("Profile apply — BILT pulse settings: %s", _e)

        # 15. Analysis thresholds
        try:
            at = getattr(profile, "analysis_threshold_k", 0)
            if at > 0:
                self._analysis_tab.set_thresholds_from_profile(
                    threshold_k=at,
                    fail_hotspot_n=getattr(
                        profile, "analysis_fail_hotspot_n", 0),
                    fail_peak_k=getattr(profile, "analysis_fail_peak_k", 0),
                    warn_hotspot_n=getattr(
                        profile, "analysis_warn_hotspot_n", 0),
                    warn_peak_k=getattr(profile, "analysis_warn_peak_k", 0))
        except Exception as _e:
            log.debug("Profile apply — analysis thresholds: %s", _e)

        # 16. Log
        self._log_tab.append(
            f"Profile applied: {profile.name}  ·  "
            f"C_T = {profile.ct_value:.3e} K⁻¹  ·  "
            f"exposure = {profile.exposure_us:.0f} µs  ·  "
            f"gain = {profile.gain_db:.1f} dB  ·  "
            f"frames = {profile.n_frames}  ·  "
            f"EMA = {profile.accumulation}")

        # 18. Status bar
        self._status.showMessage(
            f"Profile active: {profile.name}   "
            f"C_T = {profile.ct_value:.3e} K⁻¹",
            8000)

        # 19. Proactive AI Advisor
        if self._maybe_launch_advisor:
            self._maybe_launch_advisor(profile)

        # 20. Auto-exposure
        if (getattr(profile, "auto_exposure", False)
                and self._app_state.cam is not None):
            target = getattr(profile, "exposure_target_pct", 70.0)
            roi = getattr(profile, "roi_strategy", "center50")

            def _run_ae():
                from hardware.cameras.auto_exposure import auto_expose
                result = auto_expose(
                    self._hw, target_pct=target, roi=roi, max_iters=6)
                from PyQt5.QtCore import QTimer
                if self._on_auto_expose_done:
                    QTimer.singleShot(
                        0, lambda: self._on_auto_expose_done(result))

            threading.Thread(target=_run_ae, daemon=True,
                             name="auto-exposure").start()
            self._toasts.show_info("Auto-exposure running…")
