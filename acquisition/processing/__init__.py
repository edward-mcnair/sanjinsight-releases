"""
acquisition.processing — image processing, analysis, and quality scoring.

Re-exports public names so that ``from acquisition.processing import ...``
continues to work after the flat-to-subpackage migration.
"""

from .processing import (                          # noqa: F401
    to_display, apply_colormap, export_result,
    get_mpl_cmap_name, get_cmap_preview_color,
    setup_cmap_combo, extract_channel, to_luminance,
    COLORMAP_OPTIONS, COLORMAP_TOOLTIPS,
)
from .analysis import (                            # noqa: F401
    AnalysisConfig, Hotspot, AnalysisResult,
    ThermalAnalysisEngine, VERDICT_WARNING,
)
from .quality_scorecard import (                   # noqa: F401
    MetricGrade, QualityScorecard, QualityScoringEngine,
)
from .image_filters import (                       # noqa: F401
    replace_nans, shadow_correct, median_filter_2d,
    lowpass_gaussian, subpixel_register,
    align_to_reference, bilinear_stitch,
    compute_shading_reference,
)
from .image_metrics import (                       # noqa: F401
    compute_focus, compute_intensity_stats, compute_frame_stability,
)
from .drift_correction import estimate_shift, apply_shift   # noqa: F401
from .fps_optimizer import FpsOptimizer            # noqa: F401
from .rgb_analysis import (                        # noqa: F401
    CHANNEL_NAMES, split_channels,
    per_channel_stats, per_channel_analysis,
)
