"""
ui/widgets/experiment_log_widget.py  —  Experiment Log table widget

Displays the structured experiment run log as a sortable table.
Reads from :class:`ExperimentLog`, emits navigation signals.

v1 scope:
  - QTableWidget with fixed default columns
  - Sortable by clicking column headers
  - Source filter combo (All / Recipe / Manual)
  - Verdict filter combo (All / Pass / Warning / Fail)
  - CSV export button
  - Row double-click → open_session_requested(session_uid)
  - Refresh button

v2 deferred:
  - Custom column configuration / show-hide
  - Date-range filtering
  - Inline search / text filter
  - Excel (.xlsx) export
  - Report generation from selected rows
  - Charts or image panes
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QComboBox, QPushButton,
    QSizePolicy, QFrame, QFileDialog,
)
from PyQt5.QtCore import Qt, pyqtSignal

from ui.theme import PALETTE, FONT, MONO_FONT
from ui.icons import IC, set_btn_icon
from ui.display_terms import TERMS

log = logging.getLogger(__name__)


# ── Column definitions ───────────────────────────────────────────────

# (key, header_label, default_width, alignment)
# key must match RunEntry field name or be a computed column
_COLUMNS = [
    ("timestamp",       "Time",       140, Qt.AlignLeft),
    ("source",          "Source",      80,  Qt.AlignCenter),
    ("recipe_label",    TERMS["recipe"], 120, Qt.AlignLeft),
    ("session_label",   "Session",    140, Qt.AlignLeft),
    ("modality",        "Type",        80, Qt.AlignCenter),
    ("device_id",       "Device ID",  100, Qt.AlignLeft),
    ("project",         "Project",    100, Qt.AlignLeft),
    ("verdict",         "Verdict",     70, Qt.AlignCenter),
    ("hotspot_count",   "Hotspots",    60, Qt.AlignCenter),
    ("roi_peak_k",      "Peak ΔT",    70, Qt.AlignRight),
    ("duration_s",      "Duration",    70, Qt.AlignRight),
    ("operator",        "Operator",    90, Qt.AlignLeft),
]

_COL_KEYS = [c[0] for c in _COLUMNS]

# Guided mode shows a simplified column set — these columns are hidden
_GUIDED_HIDDEN = {"source", "modality", "device_id", "project", "operator"}

# Modality short names for display
_MODALITY_SHORT = {
    "thermoreflectance": "TR",
    "ir_lockin": "IR",
    "hybrid_tr_ir": "Hybrid",
    "opp": "OPP",
    "movie": "Movie",
    "transient": "Transient",
}


# ── ExperimentLogWidget ─────────────────────────────────────────────

class ExperimentLogWidget(QWidget):
    """Table display of the experiment run log.

    Signals
    -------
    open_session_requested(str)
        Emitted on row double-click with the session UID.
        Parent handles navigation to the session in the library.
    """

    open_session_requested = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entries: list = []        # cached RunEntry list (newest first)
        self._log_dir = str(Path.home() / ".microsanj")
        self._build_ui()
        self._apply_styles()

    # ── UI construction ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Toolbar ──────────────────────────────────────────────────
        toolbar = QFrame()
        toolbar.setObjectName("logToolbar")
        tb_lay = QHBoxLayout(toolbar)
        tb_lay.setContentsMargins(12, 8, 12, 8)
        tb_lay.setSpacing(10)

        title = QLabel("Experiment Log")
        title.setStyleSheet(
            f"font-size: {FONT['subhead']}pt; "
            f"font-weight: 600; "
            f"color: {PALETTE['text']};")
        tb_lay.addWidget(title)

        tb_lay.addStretch()

        # Source filter
        src_lbl = QLabel("Source:")
        src_lbl.setStyleSheet(
            f"font-size: {FONT['caption']}pt; color: {PALETTE['textDim']};")
        tb_lay.addWidget(src_lbl)
        self._source_filter = QComboBox()
        self._source_filter.addItems(["All", TERMS["source_recipe"], TERMS["source_manual"]])
        self._source_filter.setFixedWidth(110)
        self._source_filter.currentIndexChanged.connect(self._on_filter_changed)
        tb_lay.addWidget(self._source_filter)

        # Verdict filter
        vrd_lbl = QLabel("Verdict:")
        vrd_lbl.setStyleSheet(
            f"font-size: {FONT['caption']}pt; color: {PALETTE['textDim']};")
        tb_lay.addWidget(vrd_lbl)
        self._verdict_filter = QComboBox()
        self._verdict_filter.addItems(["All", "Pass", "Warning", "Fail"])
        self._verdict_filter.setFixedWidth(90)
        self._verdict_filter.currentIndexChanged.connect(self._on_filter_changed)
        tb_lay.addWidget(self._verdict_filter)

        # Refresh
        self._refresh_btn = QPushButton()
        set_btn_icon(self._refresh_btn, "mdi.refresh", PALETTE['textDim'])
        self._refresh_btn.setFixedSize(28, 28)
        self._refresh_btn.setToolTip("Refresh log")
        self._refresh_btn.setFlat(True)
        self._refresh_btn.clicked.connect(self.refresh)
        tb_lay.addWidget(self._refresh_btn)

        # Export CSV
        self._export_btn = QPushButton("  Export CSV")
        set_btn_icon(self._export_btn, "mdi.file-export-outline",
                     PALETTE['textDim'])
        self._export_btn.setFixedHeight(28)
        self._export_btn.setToolTip("Export full log to CSV")
        self._export_btn.clicked.connect(self._on_export)
        tb_lay.addWidget(self._export_btn)

        root.addWidget(toolbar)

        # ── Count label ──────────────────────────────────────────────
        self._count_label = QLabel("")
        self._count_label.setStyleSheet(
            f"font-size: {FONT['small']}pt; "
            f"color: {PALETTE['textDim']}; "
            f"padding: 2px 12px;")
        root.addWidget(self._count_label)

        # ── Table ────────────────────────────────────────────────────
        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels([c[1] for c in _COLUMNS])
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setShowGrid(False)

        # Column sizing
        hh = self._table.horizontalHeader()
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for i, (_, _, width, _) in enumerate(_COLUMNS):
            hh.resizeSection(i, width)
        # Session column stretches
        session_idx = _COL_KEYS.index("session_label")
        hh.setSectionResizeMode(session_idx, QHeaderView.Stretch)

        # Row height
        self._table.verticalHeader().setDefaultSectionSize(28)

        # Double-click → open session
        self._table.cellDoubleClicked.connect(self._on_row_double_clicked)

        root.addWidget(self._table, 1)

        # ── Empty state ──────────────────────────────────────────────
        self._empty_label = QLabel(
            "No experiment log entries yet.\n\n"
            "The experiment log records every acquisition\n"
            "with its verdict, duration, and operator context.\n\n"
            "Run a scan profile or start a manual capture\n"
            "to see your first entry here.")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._empty_label.setStyleSheet(
            f"font-size: {FONT['body']}pt; "
            f"color: {PALETTE['textDim']}; "
            f"padding: 40px;")
        self._empty_label.setVisible(False)
        root.addWidget(self._empty_label)

    # ── Public API ───────────────────────────────────────────────────

    def refresh(self) -> None:
        """Reload entries from the experiment log and repopulate the table."""
        try:
            from acquisition.storage.experiment_log import ExperimentLog
            elog = ExperimentLog(self._log_dir)
            self._entries = elog.all_entries()
        except Exception:
            log.debug("Failed to load experiment log", exc_info=True)
            self._entries = []

        self._apply_filters_and_populate()

    def set_log_dir(self, path: str) -> None:
        """Override the log directory (for testing or multi-user)."""
        self._log_dir = path

    def append_entry(self, entry) -> None:
        """Live-append a single entry without full reload.

        Called by the parent after a run completes, so the table
        updates immediately without disk I/O.
        """
        self._entries.insert(0, entry)  # newest first
        self._apply_filters_and_populate()

    def showEvent(self, event) -> None:
        """Auto-refresh entries whenever the widget becomes visible."""
        super().showEvent(event)
        self.refresh()

    # ── Filtering + population ───────────────────────────────────────

    def _on_filter_changed(self) -> None:
        """Re-filter and repopulate when a filter combo changes."""
        self._apply_filters_and_populate()

    def _apply_filters_and_populate(self) -> None:
        """Apply current filters and populate the table."""
        # Map display label → stored data key
        _SOURCE_MAP = {"scan profile": "recipe"}
        raw = self._source_filter.currentText().lower()
        source_filter = _SOURCE_MAP.get(raw, raw)
        verdict_filter = self._verdict_filter.currentText().lower()

        filtered = []
        for entry in self._entries:
            # Source filter
            if source_filter != "all":
                if getattr(entry, "source", "") != source_filter:
                    continue
            # Verdict filter
            if verdict_filter != "all":
                v = getattr(entry, "verdict", "")
                if v != verdict_filter:
                    continue
            filtered.append(entry)

        self._populate_table(filtered)

        # Update count
        total = len(self._entries)
        shown = len(filtered)
        if total == shown:
            self._count_label.setText(f"{total} entries")
        else:
            self._count_label.setText(f"{shown} of {total} entries")

        # Empty state
        self._empty_label.setVisible(total == 0)
        self._table.setVisible(total > 0)

    def _populate_table(self, entries: list) -> None:
        """Fill the table from a filtered list of RunEntry objects."""
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(entries))

        for row, entry in enumerate(entries):
            for col, (key, _, _, alignment) in enumerate(_COLUMNS):
                val = getattr(entry, key, "")
                item = self._make_item(key, val, alignment)
                # Store session_uid as row data for navigation
                if col == 0:
                    item.setData(Qt.UserRole,
                                 getattr(entry, "session_uid", ""))
                self._table.setItem(row, col, item)

            # Verdict cell coloring
            verdict_col = _COL_KEYS.index("verdict")
            verdict_item = self._table.item(row, verdict_col)
            if verdict_item:
                v = getattr(entry, "verdict", "")
                if v == "pass":
                    verdict_item.setForeground(
                        _qt_color(PALETTE['success']))
                elif v == "warning":
                    verdict_item.setForeground(
                        _qt_color(PALETTE['warning']))
                elif v == "fail":
                    verdict_item.setForeground(
                        _qt_color(PALETTE['danger']))

        self._table.setSortingEnabled(True)

    def _make_item(self, key: str, val, alignment: int) -> QTableWidgetItem:
        """Create a styled table item for a given column."""
        if val is None:
            display = ""
        elif key == "timestamp":
            # Show date + time, truncate fractional seconds
            display = str(val)[:19].replace("T", "  ")
        elif key == "modality":
            display = _MODALITY_SHORT.get(str(val), str(val)[:10])
        elif key == "source":
            _SRC_DISPLAY = {"recipe": TERMS["source_recipe"], "manual": TERMS["source_manual"]}
            display = _SRC_DISPLAY.get(str(val), str(val).title())
        elif key == "verdict":
            display = str(val).title() if val else "—"
        elif key == "roi_peak_k":
            try:
                display = f"{float(val):.2f} K"
            except (ValueError, TypeError):
                display = ""
        elif key == "duration_s":
            try:
                display = f"{float(val):.1f}s"
            except (ValueError, TypeError):
                display = ""
        elif key == "hotspot_count":
            display = str(val) if val else "0"
        else:
            display = str(val) if val else ""

        item = QTableWidgetItem(display)
        item.setTextAlignment(alignment | Qt.AlignVCenter)

        # Numeric columns: set sort data
        if key in ("roi_peak_k", "duration_s", "hotspot_count"):
            try:
                item.setData(Qt.UserRole + 1, float(val or 0))
            except (ValueError, TypeError):
                pass

        return item

    # ── Row activation ───────────────────────────────────────────────

    def _on_row_double_clicked(self, row: int, col: int) -> None:
        """Handle row double-click → open session."""
        item = self._table.item(row, 0)
        if item is None:
            return
        session_uid = item.data(Qt.UserRole)
        if session_uid:
            self.open_session_requested.emit(session_uid)
        else:
            log.debug("Double-clicked row %d has no session_uid", row)

    # ── Export ───────────────────────────────────────────────────────

    def _on_export(self) -> None:
        """Export the full log to a user-chosen CSV file."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Experiment Log",
            os.path.expanduser("~/experiment_log.csv"),
            "CSV Files (*.csv)")
        if not path:
            return
        try:
            from acquisition.storage.experiment_log import ExperimentLog
            elog = ExperimentLog(self._log_dir)
            count = elog.export_csv(path)
            log.info("Exported %d entries to %s", count, path)
        except Exception:
            log.warning("Failed to export experiment log", exc_info=True)

    # ── Styling ──────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        """Apply palette-aware styles to all sub-widgets."""
        self._table.setStyleSheet(
            f"QTableWidget {{"
            f"  background: {PALETTE['bg']}; "
            f"  alternate-background-color: {PALETTE['surface']}; "
            f"  gridline-color: {PALETTE['border2']}; "
            f"  border: none; "
            f"  font-family: {MONO_FONT}; "
            f"  font-size: {FONT['label']}pt; "
            f"  color: {PALETTE['text']}; "
            f"  selection-background-color: {PALETTE['accent']}20; "
            f"  selection-color: {PALETTE['text']};"
            f"}}"
            f"QTableWidget::item {{"
            f"  padding: 2px 6px;"
            f"}}"
            f"QHeaderView::section {{"
            f"  background: {PALETTE['surface']}; "
            f"  color: {PALETTE['textSub']}; "
            f"  padding: 4px 6px; "
            f"  border: none; "
            f"  border-bottom: 1px solid {PALETTE['border']}; "
            f"  font-size: {FONT['caption']}pt; "
            f"  font-weight: 600;"
            f"}}"
        )

        toolbar_qss = (
            f"#logToolbar {{"
            f"  background: {PALETTE['surface']}; "
            f"  border-bottom: 1px solid {PALETTE['border']};"
            f"}}"
        )
        self.findChild(QFrame, "logToolbar").setStyleSheet(toolbar_qss)

        combo_qss = (
            f"QComboBox {{"
            f"  background: {PALETTE['bg']}; "
            f"  color: {PALETTE['text']}; "
            f"  border: 1px solid {PALETTE['border']}; "
            f"  border-radius: 3px; "
            f"  padding: 2px 6px; "
            f"  font-size: {FONT['caption']}pt;"
            f"}}"
            f"QComboBox:hover {{ border-color: {PALETTE['accent']}; }}"
            f"QComboBox::drop-down {{ border: none; width: 18px; }}"
        )
        self._source_filter.setStyleSheet(combo_qss)
        self._verdict_filter.setStyleSheet(combo_qss)

        self._export_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {PALETTE['surface']}; "
            f"  color: {PALETTE['textDim']}; "
            f"  border: 1px solid {PALETTE['border']}; "
            f"  border-radius: 4px; "
            f"  padding: 2px 10px; "
            f"  font-size: {FONT['caption']}pt;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {PALETTE['surfaceHover']}; "
            f"  color: {PALETTE['text']};"
            f"}}")


# ── Helper ───────────────────────────────────────────────────────────

def _qt_color(hex_color: str):
    """Convert a hex color string to a QColor for item foreground."""
    from PyQt5.QtGui import QColor
    return QColor(hex_color)
