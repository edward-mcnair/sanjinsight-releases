"""
ui/services/recipe_service.py

Extracts recipe-application logic from MainWindow into a reusable service.
"""

import logging

log = logging.getLogger(__name__)


class RecipeApplicationService:
    """Apply a Recipe to live hardware and optionally start acquisition.

    Dependencies are injected via ``set_targets()`` after MainWindow has
    constructed all tabs.  This avoids circular imports and keeps the
    service testable in isolation.
    """

    def __init__(self):
        self._hw = None
        self._app_state = None
        self._profile_mgr = None
        self._profile_tab = None
        self._analysis_tab = None
        self._acquire_tab = None
        self._nav = None
        self._capture_tab = None
        self._safe_call = None

    def set_targets(self, *, hw_service, app_state, profile_mgr,
                    profile_tab, analysis_tab, acquire_tab, nav,
                    capture_tab, safe_call):
        self._hw = hw_service
        self._app_state = app_state
        self._profile_mgr = profile_mgr
        self._profile_tab = profile_tab
        self._analysis_tab = analysis_tab
        self._acquire_tab = acquire_tab
        self._nav = nav
        self._capture_tab = capture_tab
        self._safe_call = safe_call

    def apply(self, recipe) -> None:
        """Apply *recipe* to hardware and start acquisition."""
        log.info("Applying recipe: %s", recipe.label)

        # Reflect active recipe name in the Acquire tab
        self._safe_call(self._acquire_tab.set_active_recipe_name,
                        recipe.label,
                        label="acquire_tab.set_active_recipe_name",
                        level=logging.DEBUG)

        # ── Camera settings ───────────────────────────────────────
        try:
            self._hw.cam_set_exposure(recipe.camera.exposure_us)
            self._hw.cam_set_gain(recipe.camera.gain_db)
        except Exception as e:
            log.warning("Recipe: failed to set camera params: %s", e)

        # ── Modality ──────────────────────────────────────────────
        self._app_state.active_modality = recipe.acquisition.modality

        # ── Material profile ──────────────────────────────────────
        if recipe.profile_name:
            try:
                profile = self._profile_mgr.find_by_name(recipe.profile_name)
                if profile:
                    self._app_state.active_profile = profile
                    self._profile_tab.select_profile(profile)
            except Exception as e:
                log.warning("Recipe: could not activate profile '%s': %s",
                            recipe.profile_name, e)

        # ── TEC setpoint ──────────────────────────────────────────
        if recipe.tec.enabled:
            for idx in range(len(self._app_state.tecs)):
                try:
                    self._hw.tec_set_target(idx, recipe.tec.setpoint_c)
                except Exception as e:
                    log.warning("Recipe: TEC setpoint failed: %s", e)

        # ── Analysis config ───────────────────────────────────────
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
            log.warning("Recipe: analysis config not applied: %s", e)

        # ── Switch to Capture tab and start ───────────────────────
        self._nav.navigate_to(self._capture_tab)
        try:
            self._acquire_tab.start_acquisition(
                n_frames=recipe.camera.n_frames,
                inter_phase_delay_s=recipe.acquisition.inter_phase_delay_s,
            )
        except Exception as e:
            log.warning("Recipe: could not auto-start acquisition: %s", e)
