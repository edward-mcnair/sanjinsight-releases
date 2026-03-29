"""
tests/test_workflows.py

Unit tests for workflow profiles (Phase 5) and the acquisition subpackage
backward-compatibility shims (Phase 2).

Covers:
  1. WorkflowProfile frozen dataclass — field access, immutability
  2. Built-in profiles — FAILURE_ANALYSIS and METROLOGY presets
  3. Workflow registry — get_workflow(), WORKFLOWS dict
  4. Profile contract — FA vs Metrology differences
  5. Subpackage backward-compat shims — every shimmed import still works
  6. Acquisition __init__ re-exports

All tests are pure import / attribute checks — no hardware, no QApplication.

Run:
    cd sanjinsight
    pytest tests/test_workflows.py -v
"""

from __future__ import annotations

import os
import sys

import pytest

# Make sure the project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ================================================================== #
#  1. WorkflowProfile frozen dataclass                                 #
# ================================================================== #

class TestWorkflowProfile:
    """Verify WorkflowProfile structure and immutability."""

    def test_is_frozen(self):
        """WorkflowProfile instances must be immutable (frozen=True)."""
        from acquisition.workflows import WorkflowProfile
        profile = WorkflowProfile(
            name="test", display_name="Test", description="Testing")
        with pytest.raises(AttributeError):
            profile.name = "mutated"

    def test_required_fields(self):
        """name, display_name, description are required."""
        from acquisition.workflows import WorkflowProfile
        with pytest.raises(TypeError):
            WorkflowProfile()  # missing required fields

    def test_default_values(self):
        """Optional fields must have sensible defaults."""
        from acquisition.workflows import WorkflowProfile
        p = WorkflowProfile(name="t", display_name="T", description="D")
        assert p.default_n_frames == 100
        assert p.min_n_frames == 10
        assert p.preflight_level == "standard"
        assert p.require_calibration is False
        assert p.require_tec_stable is False
        assert p.auto_quality_score is True
        assert p.auto_analysis is True
        assert isinstance(p.export_formats, list)
        assert p.show_calibration_warning is False
        assert p.show_uncertainty is False


# ================================================================== #
#  2. Built-in profiles                                                #
# ================================================================== #

class TestBuiltInProfiles:
    """Verify FAILURE_ANALYSIS and METROLOGY presets."""

    def test_failure_analysis_exists(self):
        from acquisition.workflows import FAILURE_ANALYSIS
        assert FAILURE_ANALYSIS.name == "failure_analysis"
        assert FAILURE_ANALYSIS.display_name == "Failure Analysis"

    def test_metrology_exists(self):
        from acquisition.workflows import METROLOGY
        assert METROLOGY.name == "metrology"
        assert METROLOGY.display_name == "Metrology"

    def test_fa_frame_counts(self):
        from acquisition.workflows import FAILURE_ANALYSIS
        assert FAILURE_ANALYSIS.default_n_frames == 50
        assert FAILURE_ANALYSIS.min_n_frames == 10

    def test_metrology_frame_counts(self):
        from acquisition.workflows import METROLOGY
        assert METROLOGY.default_n_frames == 200
        assert METROLOGY.min_n_frames == 100

    def test_fa_relaxed_preflight(self):
        from acquisition.workflows import FAILURE_ANALYSIS
        assert FAILURE_ANALYSIS.preflight_level == "relaxed"
        assert FAILURE_ANALYSIS.require_calibration is False
        assert FAILURE_ANALYSIS.require_tec_stable is False

    def test_metrology_strict_preflight(self):
        from acquisition.workflows import METROLOGY
        assert METROLOGY.preflight_level == "strict"
        assert METROLOGY.require_calibration is True
        assert METROLOGY.require_tec_stable is True

    def test_fa_does_not_show_uncertainty(self):
        from acquisition.workflows import FAILURE_ANALYSIS
        assert FAILURE_ANALYSIS.show_uncertainty is False
        assert FAILURE_ANALYSIS.show_calibration_warning is False

    def test_metrology_shows_uncertainty(self):
        from acquisition.workflows import METROLOGY
        assert METROLOGY.show_uncertainty is True
        assert METROLOGY.show_calibration_warning is True

    def test_fa_export_formats(self):
        from acquisition.workflows import FAILURE_ANALYSIS
        assert "tiff" in FAILURE_ANALYSIS.export_formats
        assert "png" in FAILURE_ANALYSIS.export_formats

    def test_metrology_export_formats(self):
        from acquisition.workflows import METROLOGY
        assert "hdf5" in METROLOGY.export_formats
        assert "tiff" in METROLOGY.export_formats
        assert "csv" in METROLOGY.export_formats


# ================================================================== #
#  3. Workflow registry                                                #
# ================================================================== #

class TestWorkflowRegistry:
    """Verify the WORKFLOWS dict and get_workflow() helper."""

    def test_workflows_dict_has_both_presets(self):
        from acquisition.workflows import WORKFLOWS
        assert "failure_analysis" in WORKFLOWS
        assert "metrology" in WORKFLOWS

    def test_get_workflow_returns_correct_profile(self):
        from acquisition.workflows import get_workflow, FAILURE_ANALYSIS, METROLOGY
        assert get_workflow("failure_analysis") is FAILURE_ANALYSIS
        assert get_workflow("metrology") is METROLOGY

    def test_get_workflow_returns_none_for_unknown(self):
        from acquisition.workflows import get_workflow
        assert get_workflow("nonexistent_workflow") is None

    def test_get_workflow_returns_none_for_empty_string(self):
        from acquisition.workflows import get_workflow
        assert get_workflow("") is None

    def test_registry_values_match_keys(self):
        from acquisition.workflows import WORKFLOWS
        for key, profile in WORKFLOWS.items():
            assert profile.name == key, (
                f"Registry key {key!r} does not match profile.name {profile.name!r}"
            )


# ================================================================== #
#  4. Profile contract: FA vs Metrology differences                    #
# ================================================================== #

class TestProfileContracts:
    """Verify the meaningful differences between FA and Metrology."""

    def test_metrology_has_higher_min_frames(self):
        from acquisition.workflows import FAILURE_ANALYSIS, METROLOGY
        assert METROLOGY.min_n_frames > FAILURE_ANALYSIS.min_n_frames

    def test_metrology_is_stricter(self):
        from acquisition.workflows import FAILURE_ANALYSIS, METROLOGY
        strictness = {"relaxed": 0, "standard": 1, "strict": 2}
        assert strictness[METROLOGY.preflight_level] > strictness[FAILURE_ANALYSIS.preflight_level]

    def test_fa_does_not_require_calibration(self):
        from acquisition.workflows import FAILURE_ANALYSIS
        assert FAILURE_ANALYSIS.require_calibration is False

    def test_metrology_requires_calibration(self):
        from acquisition.workflows import METROLOGY
        assert METROLOGY.require_calibration is True


# ================================================================== #
#  5. Subpackage backward-compat shims                                 #
# ================================================================== #

class TestBackwardCompatShims:
    """
    Verify that the old flat import paths still work after the Phase 2
    subpackage reorganization.  Each test imports a key name from the
    shimmed path and checks it is the same object as from the new path.
    """

    def test_session_shim(self):
        """acquisition.session → acquisition.storage.session"""
        from acquisition.session import Session
        from acquisition.storage.session import Session as Real
        assert Session is Real

    def test_analysis_shim(self):
        """acquisition.analysis → acquisition.processing.analysis"""
        from acquisition.analysis import ThermalAnalysisEngine
        from acquisition.processing.analysis import ThermalAnalysisEngine as Real
        assert ThermalAnalysisEngine is Real

    def test_quality_scorecard_shim(self):
        """acquisition.quality_scorecard → acquisition.processing.quality_scorecard"""
        from acquisition.quality_scorecard import QualityScoringEngine
        from acquisition.processing.quality_scorecard import QualityScoringEngine as Real
        assert QualityScoringEngine is Real

    def test_image_filters_shim(self):
        """acquisition.image_filters → acquisition.processing.image_filters"""
        from acquisition.image_filters import replace_nans
        from acquisition.processing.image_filters import replace_nans as Real
        assert replace_nans is Real

    def test_image_metrics_shim(self):
        """acquisition.image_metrics → acquisition.processing.image_metrics"""
        from acquisition.image_metrics import compute_focus
        from acquisition.processing.image_metrics import compute_focus as Real
        assert compute_focus is Real

    def test_drift_correction_shim(self):
        """acquisition.drift_correction → acquisition.processing.drift_correction"""
        from acquisition.drift_correction import estimate_shift
        from acquisition.processing.drift_correction import estimate_shift as Real
        assert estimate_shift is Real

    def test_calibration_shim(self):
        """acquisition.calibration → acquisition.calibration package"""
        from acquisition.calibration import CalibrationLibrary
        from acquisition.calibration.calibration_library import CalibrationLibrary as Real
        assert CalibrationLibrary is Real

    def test_session_manager_shim(self):
        """acquisition.session_manager → acquisition.storage.session_manager"""
        from acquisition.session_manager import SessionManager
        from acquisition.storage.session_manager import SessionManager as Real
        assert SessionManager is Real

    def test_export_shim(self):
        """acquisition.export → acquisition.storage.export"""
        from acquisition.export import SessionExporter
        from acquisition.storage.export import SessionExporter as Real
        assert SessionExporter is Real

    def test_report_shim(self):
        """acquisition.report → acquisition.reporting.report"""
        from acquisition.report import ReportConfig
        from acquisition.reporting.report import ReportConfig as Real
        assert ReportConfig is Real

    def test_report_html_shim(self):
        """acquisition.report_html → acquisition.reporting.report_html"""
        from acquisition.report_html import generate_html_report
        from acquisition.reporting.report_html import generate_html_report as Real
        assert generate_html_report is Real

    def test_processing_init_reexports(self):
        """acquisition.processing.__init__ must re-export key names."""
        from acquisition.processing import (
            to_display, apply_colormap, export_result,
            COLORMAP_OPTIONS, COLORMAP_TOOLTIPS,
            ThermalAnalysisEngine, AnalysisResult,
            QualityScoringEngine, QualityScorecard,
            replace_nans, compute_focus,
            estimate_shift, FpsOptimizer,
        )
        assert callable(to_display)
        assert callable(apply_colormap)
        assert isinstance(COLORMAP_OPTIONS, (list, tuple, dict))


# ================================================================== #
#  6. Acquisition __init__ re-exports                                  #
# ================================================================== #

class TestAcquisitionReExports:
    """Verify that acquisition/__init__.py re-exports the architecture layer names."""

    def test_pipeline_exports(self):
        from acquisition import AcquisitionPipeline, AcquisitionResult
        assert AcquisitionPipeline is not None
        assert AcquisitionResult is not None

    def test_processing_exports(self):
        from acquisition import to_display, apply_colormap, export_result
        assert callable(to_display)
        assert callable(apply_colormap)
        assert callable(export_result)

    def test_orchestrator_exports(self):
        from acquisition import (
            MeasurementPhase, MeasurementContext, MeasurementResult,
            MeasurementOrchestrator, compute_grade,
        )
        assert MeasurementPhase is not None
        assert MeasurementContext is not None
        assert MeasurementResult is not None
        assert MeasurementOrchestrator is not None
        assert callable(compute_grade)

    def test_workflow_exports(self):
        from acquisition import (
            WorkflowProfile, FAILURE_ANALYSIS, METROLOGY,
            WORKFLOWS, get_workflow,
        )
        assert WorkflowProfile is not None
        assert FAILURE_ANALYSIS is not None
        assert METROLOGY is not None
        assert isinstance(WORKFLOWS, dict)
        assert callable(get_workflow)
