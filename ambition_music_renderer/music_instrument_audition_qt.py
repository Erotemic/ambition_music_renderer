"""Qt panel for safe, scratch-only instrument auditions in Stem Lab."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .music_instrument_audition import (
    InstrumentChoice,
    gm_program_names,
    safe_variant_slug,
    sfz_library_refs,
)


class InstrumentAuditionPanel(QWidget):
    """Edit one authored instrument definition and request a scratch rerender."""

    renderRequested = Signal(object)

    _BACKENDS = (
        ("Keep existing backend", "keep"),
        ("GM / SoundFont only", "gm"),
        ("SFZ library alias", "sfz_library"),
        ("SFZ path / glob", "sfz_path"),
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._source_score: Path | None = None
        self._group = ""
        self._base_label = ""
        self._choices: tuple[InstrumentChoice, ...] = ()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Instrument audition")
        title.setStyleSheet("font-weight: 600")
        outer.addWidget(title)
        self.context = QLabel("Select a routed stem with an inspectable score.")
        self.context.setWordWrap(True)
        outer.addWidget(self.context)

        form = QFormLayout()
        self.instrument_combo = QComboBox()
        self.instrument_combo.currentIndexChanged.connect(self._instrument_changed)
        form.addRow("Instrument", self.instrument_combo)

        self.backend_combo = QComboBox()
        for label, value in self._BACKENDS:
            self.backend_combo.addItem(label, value)
        self.backend_combo.currentIndexChanged.connect(self._backend_changed)
        form.addRow("Backend", self.backend_combo)

        self.program_combo = QComboBox()
        self.program_combo.setEditable(True)
        self.program_combo.addItems(gm_program_names())
        form.addRow("GM fallback", self.program_combo)

        self.library_combo = QComboBox()
        self.library_combo.setEditable(True)
        self.library_combo.addItems(sfz_library_refs())
        form.addRow("SFZ library", self.library_combo)

        self.sfz_path = QLineEdit()
        self.sfz_path.setPlaceholderText("e.g. **/Sonatina .../All Brass Marcato.sfz")
        form.addRow("SFZ path", self.sfz_path)

        self.variant_name = QLineEdit()
        self.variant_name.setPlaceholderText("scratch variant name")
        form.addRow("Variant", self.variant_name)
        outer.addLayout(form)

        buttons = QHBoxLayout()
        self.render_button = QPushButton("Clone + rerender")
        self.render_button.setToolTip(
            "Create a new scratch score from the selected render's score snapshot, change this instrument, and render it. The source score is never overwritten."
        )
        self.render_button.clicked.connect(self._request_render)
        buttons.addWidget(self.render_button)
        buttons.addStretch(1)
        outer.addLayout(buttons)

        self.status = QLabel("No source selected.")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        self._set_enabled(False)

    def _set_enabled(self, enabled: bool) -> None:
        for widget in (
            self.instrument_combo,
            self.backend_combo,
            self.program_combo,
            self.library_combo,
            self.sfz_path,
            self.variant_name,
            self.render_button,
        ):
            widget.setEnabled(enabled)

    def set_context(
        self,
        *,
        base_label: str,
        group: str,
        source_score: Path | None,
        exact_source: bool,
        choices: tuple[InstrumentChoice, ...],
    ) -> None:
        old_instrument = self.instrument_combo.currentData()
        self._source_score = Path(source_score).resolve() if source_score is not None else None
        self._group = group
        self._base_label = base_label
        self._choices = choices
        provenance = "render snapshot" if exact_source else "live-source fallback"
        if not group or self._source_score is None or not choices:
            self.context.setText("Select a routed stem whose source version has authored instrument metadata.")
            self.instrument_combo.clear()
            self._set_enabled(False)
            self.status.setText("Instrument audition unavailable for this selection.")
            return

        self.context.setText(f"Base: {base_label} · stem: {group} · source: {provenance}")
        self.instrument_combo.blockSignals(True)
        self.instrument_combo.clear()
        for row in choices:
            self.instrument_combo.addItem(row.name, row.name)
        index = next(
            (i for i in range(self.instrument_combo.count()) if self.instrument_combo.itemData(i) == old_instrument),
            0,
        )
        self.instrument_combo.setCurrentIndex(index)
        self.instrument_combo.blockSignals(False)
        self._set_enabled(True)
        self._instrument_changed()
        self.status.setText("Edits are written only to a new scratch variant.")

    def _choice(self) -> InstrumentChoice | None:
        name = self.instrument_combo.currentData()
        return next((row for row in self._choices if row.name == name), None)

    def _set_combo_text(self, combo: QComboBox, value: str) -> None:
        index = combo.findText(value)
        if index >= 0:
            combo.setCurrentIndex(index)
        else:
            combo.setEditText(value)

    def _instrument_changed(self, *_args) -> None:
        row = self._choice()
        if row is None:
            return
        self._set_combo_text(self.program_combo, str(row.program))
        backend = row.backend_mode if row.backend_mode in {value for _, value in self._BACKENDS} else "keep"
        index = next((i for i in range(self.backend_combo.count()) if self.backend_combo.itemData(i) == backend), 0)
        self.backend_combo.setCurrentIndex(index)
        self._set_combo_text(self.library_combo, row.library_ref)
        self.sfz_path.setText(row.sfz_glob)
        self.variant_name.setText(safe_variant_slug(f"{self._base_label}_{self._group}_{row.name}_audition"))
        self._backend_changed()

    def _backend_changed(self, *_args) -> None:
        mode = self.backend_combo.currentData()
        self.library_combo.setEnabled(mode == "sfz_library")
        self.sfz_path.setEnabled(mode == "sfz_path")

    def _request_render(self) -> None:
        row = self._choice()
        if row is None or self._source_score is None:
            return
        name = safe_variant_slug(self.variant_name.text())
        if not name:
            return
        self.renderRequested.emit(
            {
                "source_score": self._source_score,
                "group": self._group,
                "instrument_name": row.name,
                "program": self.program_combo.currentText().strip(),
                "backend_mode": str(self.backend_combo.currentData()),
                "library_ref": self.library_combo.currentText().strip(),
                "sfz_glob": self.sfz_path.text().strip(),
                "variant_name": name,
            }
        )

    def set_rendering(self, active: bool, text: str) -> None:
        self.render_button.setEnabled(not active and self._source_score is not None and bool(self._choices))
        self.status.setText(text)
