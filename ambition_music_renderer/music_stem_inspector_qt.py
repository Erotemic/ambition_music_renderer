"""Qt controls for read-only cross-version stem inspection."""

from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class StemInspectorPanel(QWidget):
    """Compare the selected stem's routed source against one alternate version."""

    selectionChanged = Signal()
    groupChanged = Signal(str)
    diffViewChanged = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._main_key: str | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        top = QHBoxLayout()
        top.addWidget(QLabel("Stem inspector"))
        self.group_combo = QComboBox()
        self.group_combo.currentIndexChanged.connect(self._group_changed)
        top.addWidget(self.group_combo, 1)
        outer.addLayout(top)

        compare = QHBoxLayout()
        compare.addWidget(QLabel("Main"))
        self.main_label = QLabel("—")
        self.main_label.setToolTip("The source version currently routed for this stem.")
        compare.addWidget(self.main_label, 1)
        compare.addWidget(QLabel("Compare with"))
        self.compare_combo = QComboBox()
        self.compare_combo.currentIndexChanged.connect(lambda _index: self.selectionChanged.emit())
        compare.addWidget(self.compare_combo, 1)
        outer.addLayout(compare)

        action_row = QHBoxLayout()
        self.diff_button = QPushButton("Note diff: OFF")
        self.diff_button.setCheckable(True)
        self.diff_button.setToolTip("Show the selected stem's semantic note diff in the piano roll.")
        self.diff_button.toggled.connect(self._diff_toggled)
        action_row.addWidget(self.diff_button)
        action_row.addStretch(1)
        outer.addLayout(action_row)

        self.summary = QLabel("Select a stem with a routed source and another loaded version to compare.")
        self.summary.setWordWrap(True)
        outer.addWidget(self.summary)

        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumBlockCount(500)
        self.details.setPlaceholderText("Instrument definitions and note changes appear here.")
        outer.addWidget(self.details, 1)

    def current_group(self) -> str | None:
        data = self.group_combo.currentData()
        return str(data) if data else None

    def current_versions(self) -> tuple[str | None, str | None]:
        compare = self.compare_combo.currentData()
        return self._main_key, (str(compare) if compare else None)

    @property
    def diff_enabled(self) -> bool:
        return self.diff_button.isChecked()

    def set_groups(
        self,
        groups: Iterable[tuple[str, QIcon]],
        *,
        selected: str | None = None,
    ) -> None:
        old = selected or self.current_group()
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        for group, icon in groups:
            self.group_combo.addItem(icon, group, group)
        index = next(
            (i for i in range(self.group_combo.count()) if self.group_combo.itemData(i) == old),
            0,
        )
        if self.group_combo.count():
            self.group_combo.setCurrentIndex(index)
        self.group_combo.blockSignals(False)

    def set_versions(
        self,
        versions: Iterable[tuple[str, str]],
        *,
        main: str | None,
        compare: str | None,
    ) -> None:
        rows = list(versions)
        labels = {key: label for label, key in rows}
        self._main_key = main if main in labels else None
        self.main_label.setText(labels.get(self._main_key, "—"))

        self.compare_combo.blockSignals(True)
        self.compare_combo.clear()
        for label, key in rows:
            if key != self._main_key:
                self.compare_combo.addItem(label, key)
        index = next(
            (
                i
                for i in range(self.compare_combo.count())
                if self.compare_combo.itemData(i) == compare
            ),
            0,
        )
        if self.compare_combo.count():
            self.compare_combo.setCurrentIndex(index)
        self.compare_combo.blockSignals(False)

    def set_report(self, summary: str, details: str, *, can_diff: bool) -> None:
        self.summary.setText(summary)
        self.details.setPlainText(details)
        self.diff_button.setEnabled(can_diff)
        if not can_diff and self.diff_button.isChecked():
            self.diff_button.blockSignals(True)
            self.diff_button.setChecked(False)
            self._sync_diff_button_text(False)
            self.diff_button.blockSignals(False)

    def _group_changed(self) -> None:
        group = self.current_group()
        if group:
            self.groupChanged.emit(group)
        self.selectionChanged.emit()

    def _diff_toggled(self, enabled: bool) -> None:
        self._sync_diff_button_text(enabled)
        self.diffViewChanged.emit(enabled)

    def _sync_diff_button_text(self, enabled: bool) -> None:
        self.diff_button.setText("Note diff: ON" if enabled else "Note diff: OFF")
