"""
acquisition.reporting — PDF/HTML report generation and batch operations.

Re-exports public names so that ``from acquisition.reporting import ...``
continues to work after the flat-to-subpackage migration.
"""

from .report import (                              # noqa: F401
    ReportConfig, generate_report, generate_report_any_format,
)
from .report_html import generate_html_report      # noqa: F401
from .report_presets import (                      # noqa: F401
    ReportPreset, save_report_preset, load_report_preset,
    list_report_presets, delete_report_preset,
)
from .batch_report import (                        # noqa: F401
    BatchReportUpdate, BatchReportResult,
    BatchReportGenerator, BatchReportWorker,
)
from .batch_reprocessor import (                   # noqa: F401
    BatchUpdate, BatchResult, BatchReprocessor,
    BatchAnalysisUpdate, BatchAnalysisResult, BatchAnalyzer,
)
