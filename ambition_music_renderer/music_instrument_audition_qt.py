"""Qt panel for safe, scratch-only instrument auditions in Stem Lab."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .music_instrument_audition import (
    InstrumentCandidate,
    InstrumentChoice,
    gm_program_names,
    safe_variant_slug,
    sfz_library_refs,
)


class InstrumentAuditionPanel(QWidget):
    """Choose authored A/B candidates or make an explicit scratch override."""

    renderRequested = Signal(object)
    renderBankRequested = Signal(object)
    candidateSelected = Signal(object)

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
        self._candidates: tuple[InstrumentCandidate, ...] = ()
        self._candidate_versions: dict[str, str] = {}
        self._candidate_versions_by_instrument: dict[str, dict[str, str]] = {}
        self._selected_candidate_by_instrument: dict[str, str] = {}
        self._rendering = False
        self._updating_context = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        title = QLabel("Instrument A/B")
        title.setStyleSheet("font-weight: 700; font-size: 14px")
        outer.addWidget(title)
        self.context = QLabel("Select a routed stem with an inspectable score.")
        self.context.setWordWrap(True)
        outer.addWidget(self.context)

        primary_form = QFormLayout()
        self.instrument_combo = QComboBox()
        self.instrument_combo.currentIndexChanged.connect(self._instrument_changed)
        primary_form.addRow("Part", self.instrument_combo)

        self.candidate_combo = QComboBox()
        self.candidate_combo.currentIndexChanged.connect(self._candidate_changed)
        primary_form.addRow("Candidate", self.candidate_combo)
        outer.addLayout(primary_form)

        self.candidate_detail = QLabel(
            "Authored candidates are deliberate alternatives. The primary candidate is the score baseline."
        )
        self.candidate_detail.setWordWrap(True)
        outer.addWidget(self.candidate_detail)

        candidate_buttons = QHBoxLayout()
        self.render_selected_button = QPushButton("Render selected")
        self.render_selected_button.setToolTip(
            "Render the selected candidate now. If it is already ready, selecting it routes the pre-rendered stem immediately."
        )
        self.render_selected_button.clicked.connect(self._request_selected_candidate)
        candidate_buttons.addWidget(self.render_selected_button)
        self.render_bank_button = QPushButton("Render missing candidates")
        self.render_bank_button.setToolTip(
            "Pre-render only the authored alternatives that are not ready yet. All renders share the stem cache."
        )
        self.render_bank_button.clicked.connect(self._request_bank)
        candidate_buttons.addWidget(self.render_bank_button)
        candidate_buttons.addStretch(1)
        outer.addLayout(candidate_buttons)

        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.hide()
        outer.addWidget(self.progress)

        self.manual_toggle = QPushButton("Manual one-off override ▸")
        self.manual_toggle.setCheckable(True)
        self.manual_toggle.toggled.connect(self._manual_toggled)
        outer.addWidget(self.manual_toggle)

        self.manual_widget = QWidget()
        manual = QVBoxLayout(self.manual_widget)
        manual.setContentsMargins(12, 0, 0, 0)
        manual_form = QFormLayout()

        self.backend_combo = QComboBox()
        for label, value in self._BACKENDS:
            self.backend_combo.addItem(label, value)
        self.backend_combo.currentIndexChanged.connect(self._backend_changed)
        manual_form.addRow("Backend", self.backend_combo)

        self.program_combo = QComboBox()
        self.program_combo.setEditable(True)
        self.program_combo.addItems(gm_program_names())
        manual_form.addRow("GM fallback", self.program_combo)

        self.library_combo = QComboBox()
        self.library_combo.setEditable(True)
        self.library_combo.addItems(sfz_library_refs())
        manual_form.addRow("SFZ library", self.library_combo)

        self.sfz_path = QLineEdit()
        self.sfz_path.setPlaceholderText("e.g. **/Sonatina .../Harpsichord Full.sfz")
        manual_form.addRow("SFZ path", self.sfz_path)

        self.variant_name = QLineEdit()
        self.variant_name.setPlaceholderText("scratch variant name")
        manual_form.addRow("Variant", self.variant_name)
        manual.addLayout(manual_form)

        manual_buttons = QHBoxLayout()
        self.render_button = QPushButton("Clone + render override")
        self.render_button.clicked.connect(self._request_render)
        manual_buttons.addWidget(self.render_button)
        manual_buttons.addStretch(1)
        manual.addLayout(manual_buttons)
        self.manual_widget.hide()
        outer.addWidget(self.manual_widget)

        self.status = QLabel("No source selected.")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        outer.addStretch(1)
        self._set_enabled(False)

    def _manual_toggled(self, expanded: bool) -> None:
        self.manual_widget.setVisible(expanded)
        self.manual_toggle.setText("Manual one-off override ▾" if expanded else "Manual one-off override ▸")

    def _set_enabled(self, enabled: bool) -> None:
        available = enabled and not self._rendering
        for widget in (
            self.instrument_combo,
            self.manual_toggle,
            self.backend_combo,
            self.program_combo,
            self.variant_name,
            self.render_button,
        ):
            widget.setEnabled(available)
        candidate_available = available and bool(self._candidates)
        self.candidate_combo.setEnabled(candidate_available)
        self.render_selected_button.setEnabled(candidate_available)
        self.render_bank_button.setEnabled(candidate_available)
        if available:
            self._backend_changed()
        else:
            self.library_combo.setEnabled(False)
            self.sfz_path.setEnabled(False)

    def set_context(
        self,
        *,
        base_label: str,
        group: str,
        source_score: Path | None,
        exact_source: bool,
        choices: tuple[InstrumentChoice, ...],
        candidate_versions_by_instrument: Mapping[str, Mapping[str, str]] | None = None,
        selected_candidate_by_instrument: Mapping[str, str] | None = None,
    ) -> None:
        old_instrument = self.instrument_combo.currentData()
        self._source_score = Path(source_score).resolve() if source_score is not None else None
        self._group = group
        self._base_label = base_label
        self._choices = choices
        self._candidate_versions_by_instrument = {
            str(name): dict(rows) for name, rows in (candidate_versions_by_instrument or {}).items()
        }
        self._selected_candidate_by_instrument = dict(selected_candidate_by_instrument or {})
        provenance = "render snapshot" if exact_source else "live-source fallback"
        self._updating_context = True
        try:
            if not group or self._source_score is None or not choices:
                self.context.setText("Select a routed stem whose source version has authored instrument metadata.")
                self.instrument_combo.clear()
                self.candidate_combo.clear()
                self._candidates = ()
                self._set_enabled(False)
                self.status.setText("Instrument audition unavailable for this selection.")
                return

            self.context.setText(f"Base: {base_label} · stem: {group} · source: {provenance}")
            self.instrument_combo.blockSignals(True)
            self.instrument_combo.clear()
            for row in choices:
                marker = " · candidates" if row.candidates else ""
                self.instrument_combo.addItem(f"{row.name}{marker}", row.name)
            index = next(
                (i for i in range(self.instrument_combo.count()) if self.instrument_combo.itemData(i) == old_instrument),
                0,
            )
            self.instrument_combo.setCurrentIndex(index)
            self.instrument_combo.blockSignals(False)
            self._set_enabled(True)
            self._instrument_changed()
            self.status.setText("Select a ready candidate to switch instantly. Play renders the selected candidate when needed.")
        finally:
            self._updating_context = False

    def _choice(self) -> InstrumentChoice | None:
        name = self.instrument_combo.currentData()
        return next((row for row in self._choices if row.name == name), None)

    def _candidate(self) -> InstrumentCandidate | None:
        key = self.candidate_combo.currentData()
        return next((row for row in self._candidates if row.key == key), None)

    def _set_combo_text(self, combo: QComboBox, value: str) -> None:
        index = combo.findText(value)
        if index >= 0:
            combo.setCurrentIndex(index)
        else:
            combo.setEditText(value)

    def _instrument_changed(self, *_args) -> None:
        row = self._choice()
        if row is None:
            self._candidates = ()
            self.candidate_combo.clear()
            return
        self._candidate_versions = dict(self._candidate_versions_by_instrument.get(row.name, {}))
        self._set_combo_text(self.program_combo, str(row.program))
        backend = row.backend_mode if row.backend_mode in {value for _, value in self._BACKENDS} else "keep"
        index = next((i for i in range(self.backend_combo.count()) if self.backend_combo.itemData(i) == backend), 0)
        self.backend_combo.setCurrentIndex(index)
        self._set_combo_text(self.library_combo, row.library_ref)
        self.sfz_path.setText(row.sfz_glob)
        self.variant_name.setText(safe_variant_slug(f"{self._base_label}_{self._group}_{row.name}_audition"))
        self._backend_changed()
        self._refresh_candidates(
            row, selected_candidate_key=self._selected_candidate_by_instrument.get(row.name)
        )

    def _refresh_candidates(self, row: InstrumentChoice, *, selected_candidate_key: str | None = None) -> None:
        # The fast A/B surface is intentionally limited to score-authored
        # candidates. Broad catalog exploration stays behind the manual override
        # instead of turning one button into a render-everything operation.
        self._candidates = row.candidates
        old = selected_candidate_key or self.candidate_combo.currentData()
        self.candidate_combo.blockSignals(True)
        self.candidate_combo.clear()
        for candidate in self._candidates:
            ready = candidate.key in self._candidate_versions
            prefix = "★ " if candidate.primary else ""
            state = "ready" if ready else "render on Play"
            self.candidate_combo.addItem(f"{prefix}{candidate.label} — {state}", candidate.key)
        fallback = next((candidate.key for candidate in self._candidates if candidate.primary), None)
        target = old if any(candidate.key == old for candidate in self._candidates) else fallback
        index = next(
            (i for i in range(self.candidate_combo.count()) if self.candidate_combo.itemData(i) == target),
            0,
        )
        if self.candidate_combo.count():
            self.candidate_combo.setCurrentIndex(index)
        self.candidate_combo.blockSignals(False)
        self._set_enabled(self._source_score is not None and bool(self._choices))
        self._candidate_changed(emit=False)

    def _candidate_changed(self, *_args, emit: bool = True) -> None:
        candidate = self._candidate()
        row = self._choice()
        if candidate is None or row is None:
            self.candidate_detail.setText(
                "No authored candidate bank for this part. Expand Manual one-off override to explore the broader catalog."
            )
            return
        ready_key = self._candidate_versions.get(candidate.key)
        primary = "Primary baseline. " if candidate.primary else "Alternative. "
        state = "Pre-rendered; switching is immediate." if ready_key else "Not rendered; Play will generate it first."
        summary = f" {candidate.summary}" if candidate.summary else ""
        self.candidate_detail.setText(primary + state + summary)
        if emit and not self._updating_context:
            self.candidateSelected.emit(
                {
                    "group": self._group,
                    "instrument_name": row.name,
                    "candidate_id": candidate.key,
                    "candidate_label": candidate.label,
                    "version_key": ready_key or "",
                    "render_request": self._candidate_request(row, candidate),
                }
            )

    def _backend_changed(self, *_args) -> None:
        if self._rendering:
            self.library_combo.setEnabled(False)
            self.sfz_path.setEnabled(False)
            return
        mode = self.backend_combo.currentData()
        self.library_combo.setEnabled(mode == "sfz_library" and self._source_score is not None)
        self.sfz_path.setEnabled(mode == "sfz_path" and self._source_score is not None)

    def _base_request(self, row: InstrumentChoice) -> dict[str, object]:
        assert self._source_score is not None
        return {
            "source_score": self._source_score,
            "group": self._group,
            "instrument_name": row.name,
            "program": self.program_combo.currentText().strip(),
        }

    def _candidate_request(self, row: InstrumentChoice, candidate: InstrumentCandidate) -> dict[str, object]:
        request = self._base_request(row)
        request.update(
            {
                "program": candidate.program if candidate.program is not None else row.program,
                "backend_mode": candidate.backend_mode,
                "library_ref": candidate.library_ref,
                "sfz_glob": candidate.sfz_glob,
                "candidate_id": candidate.key,
                "candidate_label": candidate.label,
                "variant_name": safe_variant_slug(
                    f"{self._base_label}_{self._group}_{row.name}_{candidate.key}"
                ),
            }
        )
        return request

    def select_candidate(self, instrument_name: str, candidate_key: str) -> bool:
        """Select one candidate from another Stem Lab surface."""
        instrument_index = next(
            (
                index
                for index in range(self.instrument_combo.count())
                if self.instrument_combo.itemData(index) == instrument_name
            ),
            -1,
        )
        if instrument_index < 0:
            return False
        if self.instrument_combo.currentIndex() != instrument_index:
            self.instrument_combo.setCurrentIndex(instrument_index)
        candidate_index = next(
            (
                index
                for index in range(self.candidate_combo.count())
                if self.candidate_combo.itemData(index) == candidate_key
            ),
            -1,
        )
        if candidate_index < 0:
            return False
        if self.candidate_combo.currentIndex() == candidate_index:
            self._candidate_changed()
        else:
            self.candidate_combo.setCurrentIndex(candidate_index)
        return True

    def selected_candidate_request(self) -> dict[str, object] | None:
        """Return a render request only when the selected candidate is missing."""
        row = self._choice()
        candidate = self._candidate()
        if row is None or candidate is None or self._source_score is None:
            return None
        if not candidate.authored:
            return None
        if candidate.key in self._candidate_versions:
            return None
        return self._candidate_request(row, candidate)

    def _request_selected_candidate(self) -> None:
        request = self.selected_candidate_request()
        if request is None:
            if self._candidate() is None:
                self.status.setText("This part has no authored candidate bank; use Manual one-off override for exploration.")
            else:
                self.status.setText("Selected candidate is already rendered; choosing it routes the stem immediately.")
            return
        request["route_after"] = True
        self.renderRequested.emit(request)

    def _request_bank(self) -> None:
        row = self._choice()
        if row is None or self._source_score is None:
            return
        requests: list[dict[str, object]] = []
        for candidate in self._candidates:
            if not candidate.authored or candidate.key in self._candidate_versions:
                continue
            request = self._candidate_request(row, candidate)
            request["route_after"] = False
            requests.append(request)
        if requests:
            self.renderBankRequested.emit(requests)
        else:
            self.status.setText("All authored alternatives are already rendered.")

    def _request_render(self) -> None:
        row = self._choice()
        if row is None or self._source_score is None:
            return
        name = safe_variant_slug(self.variant_name.text())
        if not name:
            return
        request = self._base_request(row)
        request.update(
            {
                "backend_mode": str(self.backend_combo.currentData()),
                "library_ref": self.library_combo.currentText().strip(),
                "sfz_glob": self.sfz_path.text().strip(),
                "variant_name": name,
                "route_after": True,
            }
        )
        self.renderRequested.emit(request)

    def set_rendering(
        self,
        active: bool,
        text: str,
        *,
        completed: int = 0,
        total: int = 0,
    ) -> None:
        self._rendering = bool(active)
        self._set_enabled(self._source_score is not None and bool(self._choices))
        self.status.setText(text)
        if not active:
            self.progress.hide()
            return
        self.progress.show()
        if total > 1:
            self.progress.setRange(0, total)
            self.progress.setValue(max(0, min(completed, total)))
            self.progress.setFormat(f"{completed} / {total}")
        else:
            self.progress.setRange(0, 0)
            self.progress.setFormat("Rendering…")
