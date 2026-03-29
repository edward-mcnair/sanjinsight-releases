"""
acquisition/quality_scorecard.py

Deterministic post-acquisition quality scoring engine.

Computes letter grades (A–F) for SNR, exposure, thermal contrast,
and stability from raw acquisition metrics.  No AI/LLM — pure
threshold comparison.

Usage
-----
    from acquisition.quality_scorecard import QualityScoringEngine

    scorecard = QualityScoringEngine.compute(
        snr_db=32.4,
        mean_frac=0.58,
        max_frac=0.82,
        peak_drr=1.2e-3,
        frame_cv=0.0018,
        n_frames=256,
        duration_s=12.3,
    )
    print(scorecard.overall_grade)      # "A"
    print(scorecard.recommendations)    # ["Excellent quality — ready for analysis"]
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


# ── Result dataclasses ─────────────────────────────────────────────────────


@dataclass
class MetricGrade:
    """Score for a single quality dimension."""
    metric:     str     # "snr", "exposure", "thermal_contrast", "stability"
    grade:      str     # "A" | "B" | "C" | "D" | "F" | "N/A"
    value:      float   # raw numeric value (NaN when N/A)
    display:    str     # human-readable, e.g. "32.4 dB"
    threshold:  str     # range description, e.g. "A: >= 30 dB"


@dataclass
class QualityScorecard:
    """Aggregate quality assessment for one acquisition."""
    snr:               MetricGrade
    exposure:          MetricGrade
    thermal_contrast:  MetricGrade
    stability:         MetricGrade
    overall_grade:     str                   # worst individual grade
    overall_color:     str                   # PALETTE key for the grade
    timestamp:         float = 0.0
    recommendations:   list[str] = field(default_factory=list)

    # ── Serialisation ──────────────────────────────────────────────

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> QualityScorecard:
        def _mg(raw: dict) -> MetricGrade:
            return MetricGrade(**raw)
        return QualityScorecard(
            snr=_mg(d["snr"]),
            exposure=_mg(d["exposure"]),
            thermal_contrast=_mg(d["thermal_contrast"]),
            stability=_mg(d["stability"]),
            overall_grade=d["overall_grade"],
            overall_color=d["overall_color"],
            timestamp=d.get("timestamp", 0.0),
            recommendations=d.get("recommendations", []),
        )

    @property
    def grades_list(self) -> list[MetricGrade]:
        return [self.snr, self.exposure, self.thermal_contrast, self.stability]


# ── Grading thresholds ─────────────────────────────────────────────────────

_GRADE_ORDER = ["A", "B", "C", "D", "F"]

# Maps grade → PALETTE key for colour coding
GRADE_COLORS: dict[str, str] = {
    "A":   "success",    # green
    "B":   "accent",     # teal
    "C":   "warning",    # amber
    "D":   "danger",     # red
    "F":   "danger",     # red
    "N/A": "textDim",    # grey
}


def _worst_grade(*grades: str) -> str:
    """Return the worst (lowest) of the given letter grades."""
    valid = [g for g in grades if g in _GRADE_ORDER]
    if not valid:
        return "N/A"
    return max(valid, key=lambda g: _GRADE_ORDER.index(g))


# ── Scoring engine ─────────────────────────────────────────────────────────


class QualityScoringEngine:
    """Deterministic quality scorer for post-acquisition results."""

    # ── SNR thresholds (dB) ────────────────────────────────────────
    @staticmethod
    def _grade_snr(snr_db: Optional[float]) -> MetricGrade:
        if snr_db is None or snr_db != snr_db:  # NaN check
            return MetricGrade("snr", "N/A", float("nan"),
                               "N/A", "Requires ΔR/R data")
        if snr_db >= 30:
            g = "A"
        elif snr_db >= 20:
            g = "B"
        elif snr_db >= 10:
            g = "C"
        elif snr_db >= 5:
            g = "D"
        else:
            g = "F"
        return MetricGrade(
            "snr", g, snr_db,
            f"{snr_db:.1f} dB",
            "A: ≥30  B: ≥20  C: ≥10  D: ≥5  F: <5 dB")

    # ── Exposure thresholds (mean fraction 0-1) ────────────────────
    @staticmethod
    def _grade_exposure(mean_frac: float, max_frac: float) -> MetricGrade:
        # Grade by how well the exposure fills the dynamic range
        display = f"Mean {mean_frac * 100:.0f}%, Peak {max_frac * 100:.0f}%"
        if 0.40 <= mean_frac <= 0.70 and max_frac < 0.85:
            g = "A"
        elif 0.30 <= mean_frac <= 0.80 and max_frac < 0.90:
            g = "B"
        elif 0.20 <= mean_frac <= 0.85 and max_frac < 0.95:
            g = "C"
        elif 0.15 <= mean_frac <= 0.90:
            g = "D"
        else:
            g = "F"
        return MetricGrade(
            "exposure", g, mean_frac,
            display,
            "A: 40–70% mean  B: 30–80%  C: 20–85%  D: 15–90%")

    # ── Thermal contrast thresholds (peak |ΔR/R|) ─────────────────
    @staticmethod
    def _grade_thermal_contrast(peak_drr: Optional[float]) -> MetricGrade:
        if peak_drr is None or peak_drr != peak_drr:
            return MetricGrade("thermal_contrast", "N/A", float("nan"),
                               "N/A", "Requires ΔR/R data")
        if peak_drr >= 1e-3:
            g = "A"
        elif peak_drr >= 5e-4:
            g = "B"
        elif peak_drr >= 1e-4:
            g = "C"
        elif peak_drr >= 5e-5:
            g = "D"
        else:
            g = "F"
        return MetricGrade(
            "thermal_contrast", g, peak_drr,
            f"{peak_drr:.2e} ΔR/R",
            "A: ≥1e-3  B: ≥5e-4  C: ≥1e-4  D: ≥5e-5")

    # ── Stability thresholds (coefficient of variation) ────────────
    @staticmethod
    def _grade_stability(cv: Optional[float]) -> MetricGrade:
        if cv is None or cv != cv:
            return MetricGrade("stability", "N/A", float("nan"),
                               "N/A", "Requires multi-frame data")
        if cv < 0.002:
            g = "A"
        elif cv < 0.005:
            g = "B"
        elif cv < 0.01:
            g = "C"
        elif cv < 0.02:
            g = "D"
        else:
            g = "F"
        return MetricGrade(
            "stability", g, cv,
            f"CV {cv:.4f}",
            "A: <0.002  B: <0.005  C: <0.01  D: <0.02")

    # ── Recommendation generator ───────────────────────────────────
    @staticmethod
    def _recommendations(sc: QualityScorecard) -> list[str]:
        recs: list[str] = []

        if sc.snr.grade in ("D", "F"):
            recs.append(
                "Signal-to-noise ratio is low — try increasing exposure "
                "time, averaging more frames, or reducing ambient light.")
        elif sc.snr.grade == "C":
            recs.append(
                "SNR is marginal — consider increasing frame count "
                "or optimising exposure for better results.")

        if sc.exposure.grade in ("D", "F"):
            if sc.exposure.value < 0.20:
                recs.append(
                    "Image is severely underexposed — run Auto-Exposure "
                    "or increase exposure time in Camera settings.")
            else:
                recs.append(
                    "Image is near saturation — reduce exposure time "
                    "or gain to avoid clipping.")
        elif sc.exposure.grade == "C":
            recs.append(
                "Exposure could be optimised — run Auto-Exposure "
                "for best dynamic range usage.")

        if sc.thermal_contrast.grade in ("D", "F"):
            recs.append(
                "Thermal contrast is very weak — verify the stimulus "
                "is active and the sample is thermally responsive.")
        elif sc.thermal_contrast.grade == "C":
            recs.append(
                "Thermal contrast is moderate — ensure the stimulus "
                "frequency and amplitude are appropriate for this material.")

        if sc.stability.grade in ("D", "F"):
            recs.append(
                "Frame-to-frame stability is poor — check for vibration, "
                "sample drift, or unstable illumination.")

        if not recs:
            recs.append("Excellent quality — ready for analysis.")

        return recs

    # ── Main entry point ───────────────────────────────────────────

    @classmethod
    def compute(
        cls,
        snr_db: Optional[float] = None,
        mean_frac: float = 0.5,
        max_frac: float = 0.7,
        peak_drr: Optional[float] = None,
        frame_cv: Optional[float] = None,
        n_frames: int = 0,
        duration_s: float = 0.0,
    ) -> QualityScorecard:
        """Compute a full quality scorecard from raw acquisition metrics.

        Parameters
        ----------
        snr_db : Signal-to-noise ratio in decibels (from AcquisitionResult.snr_db).
        mean_frac : Mean pixel intensity as fraction of full scale (0–1).
        max_frac : Maximum pixel intensity as fraction of full scale (0–1).
        peak_drr : Peak absolute ΔR/R value.
        frame_cv : Coefficient of variation across captured frames.
        n_frames : Number of frames captured per phase.
        duration_s : Total acquisition duration in seconds.
        """
        import time as _time

        snr_g  = cls._grade_snr(snr_db)
        exp_g  = cls._grade_exposure(mean_frac, max_frac)
        tc_g   = cls._grade_thermal_contrast(peak_drr)
        stab_g = cls._grade_stability(frame_cv)

        overall = _worst_grade(snr_g.grade, exp_g.grade,
                               tc_g.grade, stab_g.grade)
        color = GRADE_COLORS.get(overall, "textDim")

        sc = QualityScorecard(
            snr=snr_g,
            exposure=exp_g,
            thermal_contrast=tc_g,
            stability=stab_g,
            overall_grade=overall,
            overall_color=color,
            timestamp=_time.time(),
        )
        sc.recommendations = cls._recommendations(sc)
        return sc
