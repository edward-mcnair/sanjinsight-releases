"""
acquisition/preflight_remediation.py

Automatic remediation actions for failed preflight checks.

Each remediation is a small, targeted hardware adjustment that attempts to
bring a failing or warning check into the passing range.  Remediations are
always optional — the user can skip them from the preflight dialog.

Thread-safety
-------------
All methods are designed to run on the main (GUI) thread.  Hardware calls
(set_exposure, set_gain) are thread-safe in the camera driver.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Optional

log = logging.getLogger(__name__)


@dataclass
class Remediation:
    """A single proposed auto-fix for a preflight check."""
    rule_id:     str              # matches PreflightCheck.rule_id
    label:       str              # button text, e.g. "Auto-adjust exposure"
    description: str              # tooltip / detail text
    action:      Callable[[], bool]  # returns True on success


class PreflightRemediator:
    """
    Generates remediation actions for failing preflight checks.

    Parameters
    ----------
    app_state :
        The global app_state singleton (hardware.app_state.app_state).
    """

    # Target exposure: aim for the middle of the ideal band (50%)
    TARGET_MEAN_FRAC = 0.55

    def __init__(self, app_state):
        self._as = app_state

    def get_remediations(self, checks) -> list[Remediation]:
        """Return a list of available remediations for the given checks.

        Parameters
        ----------
        checks : list[PreflightCheck]
            Results from PreflightValidator.run().checks.

        Returns
        -------
        list[Remediation]
            One Remediation per fixable check.  Checks that already pass
            or have no automated fix are skipped.
        """
        remediations: list[Remediation] = []
        for check in checks:
            if check.status == "pass":
                continue
            fn = getattr(self, f"_fix_{check.rule_id.lower()}", None)
            if fn is not None:
                r = fn(check)
                if r is not None:
                    remediations.append(r)
        return remediations

    # ── Per-rule remediation factories ──────────────────────────────────

    def _fix_pf_exposure(self, check) -> Optional[Remediation]:
        """Adjust exposure time to bring mean intensity into the ideal band."""
        cam = self._as.cam
        if cam is None:
            return None

        vals = check.observed_values
        mean_f = vals.get("mean_frac")
        max_f = vals.get("max_frac")
        if mean_f is None or mean_f <= 0:
            return None

        current_exp = cam.get_exposure()
        exp_min, exp_max = cam.exposure_range()

        if max_f is not None and max_f > 0.90:
            # Clipping risk — scale down proportionally
            ratio = 0.80 / max_f
            new_exp = current_exp * ratio
            label = "Reduce exposure (clipping)"
            desc = (f"Reduce exposure from {current_exp:.0f} µs to "
                    f"{new_exp:.0f} µs to avoid saturation.")
        else:
            # Scale toward TARGET_MEAN_FRAC
            ratio = self.TARGET_MEAN_FRAC / mean_f
            new_exp = current_exp * ratio
            direction = "Increase" if ratio > 1 else "Reduce"
            label = f"{direction} exposure"
            desc = (f"{direction} exposure from {current_exp:.0f} µs to "
                    f"{new_exp:.0f} µs (target: {self.TARGET_MEAN_FRAC:.0%} "
                    f"mean intensity).")

        new_exp = max(exp_min, min(exp_max, new_exp))

        def _apply() -> bool:
            try:
                cam.set_exposure(new_exp)
                log.info("Remediation: exposure set to %.0f µs", new_exp)
                return True
            except Exception:
                log.exception("Remediation: failed to set exposure")
                return False

        return Remediation(
            rule_id="PF_EXPOSURE",
            label=label,
            description=desc,
            action=_apply,
        )

    def _fix_pf_stability(self, check) -> Optional[Remediation]:
        """Stability issues need settling time — offer a wait-and-recheck."""
        cv = check.observed_values.get("cv", 0)
        if cv <= 0:
            return None

        def _apply() -> bool:
            # There's no hardware action for stability — the remediation
            # is "wait".  The preflight dialog re-runs checks after the
            # user clicks this, giving the system time to settle.
            import time
            log.info("Remediation: waiting 3s for system to settle (CV=%.4f)", cv)
            time.sleep(3)
            return True

        return Remediation(
            rule_id="PF_STABILITY",
            label="Wait for stability",
            description=f"Wait 3 seconds for the system to settle "
                        f"(current CV = {cv:.4f}).",
            action=_apply,
        )

    def _fix_pf_ffc(self, check) -> Optional[Remediation]:
        """Run Flat-Field Correction on the IR camera."""
        # Find the FFC-capable camera (same logic as preflight.py)
        cam = None
        for c in (getattr(self._as, "ir_cam", None),
                  getattr(self._as, "cam", None)):
            if c is not None and getattr(c, "supports_ffc", lambda: False)():
                cam = c
                break
        if cam is None:
            return None

        age = check.observed_values.get("last_ffc_age_sec")
        if age is None:
            desc = "Run FFC to calibrate pixel offsets before acquisition."
        else:
            desc = (f"FFC is {age / 60:.0f} min old — re-run to recalibrate "
                    f"pixel offsets for accurate measurements.")

        def _apply() -> bool:
            try:
                ok = cam.do_ffc()
                if ok:
                    log.info("Remediation: FFC executed successfully")
                else:
                    log.warning("Remediation: FFC returned False")
                return ok
            except Exception:
                log.exception("Remediation: FFC failed")
                return False

        return Remediation(
            rule_id="PF_FFC",
            label="Run FFC",
            description=desc,
            action=_apply,
        )

    def _fix_pf_focus(self, check) -> Optional[Remediation]:
        """Trigger autofocus if a stage is available."""
        cam = self._as.cam
        stage = self._as.stage
        if cam is None or stage is None:
            return None

        score = check.observed_values.get("focus_score", 0)

        def _apply() -> bool:
            try:
                from hardware.autofocus import create_autofocus
                from config import config
                af_cfg = config.get("autofocus", {})
                af = create_autofocus(af_cfg, cam, stage)
                result = af.run()
                success = result.state.name == "COMPLETE"
                if success:
                    log.info("Remediation: autofocus complete at Z=%.2f µm "
                             "(score %.1f → %.1f)",
                             result.best_z, score, result.best_score)
                else:
                    log.warning("Remediation: autofocus %s: %s",
                                result.state.name, result.message)
                return success
            except Exception:
                log.exception("Remediation: autofocus failed")
                return False

        return Remediation(
            rule_id="PF_FOCUS",
            label="Run autofocus",
            description=f"Run autofocus to improve focus quality "
                        f"(current score: {score:.0f}).",
            action=_apply,
        )
