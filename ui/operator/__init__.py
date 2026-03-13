"""
ui/operator/

Operator Shell — simplified single-screen UI for Technician users.

Technicians run approved, locked recipes from a guided interface that
produces unambiguous PASS/FAIL verdicts, full part traceability, and
automatic PDF reports.  This package is entirely self-contained and
never imports from MainWindow.

Components
----------
VerdictOverlay          Full-screen modal shown after each scan.
ShiftLogPanel           Scrollable today's results + CSV export.
RecipeSelectorPanel     Shows only approved/locked recipes.
ScanWorkArea            Live view + part ID entry + START SCAN.
OperatorShell           QMainWindow that assembles all panels.
"""

from ui.operator.verdict_overlay       import VerdictOverlay
from ui.operator.shift_log_panel       import ShiftLogPanel
from ui.operator.recipe_selector_panel import RecipeSelectorPanel
from ui.operator.scan_work_area        import ScanWorkArea
from ui.operator.operator_shell        import OperatorShell

__all__ = [
    "VerdictOverlay",
    "ShiftLogPanel",
    "RecipeSelectorPanel",
    "ScanWorkArea",
    "OperatorShell",
]
