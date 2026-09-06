"""Standalone Qt instrument-library browser and YAML-backed auditioner."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import uuid

import yaml

from PySide6.QtCore import QProcess, QTimer, Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ._paths import agent_root
from .music_instrument_inspector_model import (
    EFFECT_TEMPLATES,
    LibraryEntry,
    alias_library_entries,
    append_effect_template,
    apply_library_entry,
    apply_probe_control_suggestions,
    build_probe_request,
    format_probe_diagnostics,
    default_instrument_document,
    default_processing_document,
    gm_library_entries,
    installed_sfz_entries,
    load_score_instrument,
    parse_yaml_mapping,
    probe_request_hash,
    probe_template_options,
    resolved_backend_path,
    score_instrument_names,
    sfz_probe_preflight_from_census,
    write_export_document,
    yaml_text,
)
from .instrument_resolution import backend_spec_from_instrument
from .instrument_usage_census import census_by_resolved_path, census_row_is_fresh, default_census_paths, load_usage_census
from .music_transport_qt import MusicTransport
from .music_qt_runtime import install_sigint_quit
from .render.score_core import DRUMS


class InstrumentInspectorWindow(QMainWindow):
    """Browse/audition instrument definitions without owning any score file."""

    def __init__(self, project_root: Path, parent=None) -> None:
        super().__init__(parent)
        self.project_root = Path(project_root).resolve()
        self._render_process: QProcess | None = None
        self._render_request_path: Path | None = None
        self._render_request_hash: str | None = None
        self._rendered_request_hash: str | None = None
        self._play_after_render = False
        self._last_preflight: dict = {}
        self._usage_census = load_usage_census()
        self._usage_census_by_path = census_by_resolved_path(self._usage_census)
        self._usage_census_alias_hits = dict((self._usage_census or {}).get("alias_hits") or {})
        self._resolved_backend_cache: dict[str, Path | None] = {}
        self.setWindowTitle("Ambition Instrument Inspector")
        self.resize(1420, 900)
        self._build_ui()
        self._populate_library_base()
        self._set_documents(default_instrument_document(), default_processing_document())
        self._validation_timer = QTimer(self)
        self._validation_timer.setSingleShot(True)
        self._validation_timer.setInterval(250)
        self._validation_timer.timeout.connect(self._refresh_document_state)
        self.instrument_yaml.textChanged.connect(self._schedule_validation)
        self.processing_yaml.textChanged.connect(self._schedule_validation)
        self.probe_template.currentIndexChanged.connect(self._probe_settings_changed)
        self.note_probe.textChanged.connect(self._probe_settings_changed)
        self.drum_probe.currentIndexChanged.connect(self._probe_settings_changed)
        self.velocity.valueChanged.connect(self._probe_settings_changed)
        self.duration.valueChanged.connect(self._probe_settings_changed)
        self.tempo.valueChanged.connect(self._probe_settings_changed)
        self.backend.currentIndexChanged.connect(self._probe_settings_changed)
        self._refresh_document_state()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(7)

        header = QHBoxLayout()
        title = QLabel("Instrument Inspector")
        title.setStyleSheet("font-size: 18px; font-weight: 650")
        header.addWidget(title)
        header.addStretch(1)
        self.new_button = QPushButton("New")
        self.new_button.clicked.connect(self._new_document)
        header.addWidget(self.new_button)
        self.load_button = QPushButton("Load from score…")
        self.load_button.clicked.connect(self._load_from_score)
        header.addWidget(self.load_button)
        self.export_button = QPushButton("Export YAML snippets…")
        self.export_button.clicked.connect(self._export)
        header.addWidget(self.export_button)
        outer.addLayout(header)

        note = QLabel(
            "This tool owns a disposable patch document, not a song. Library choices update the YAML below; "
            "the YAML remains authoritative. Probe renders are written under agent/instrument_inspector/."
        )
        note.setWordWrap(True)
        outer.addWidget(note)

        main_split = QSplitter(Qt.Horizontal)
        outer.addWidget(main_split, 1)
        main_split.addWidget(self._build_library_panel())
        main_split.addWidget(self._build_editor_panel())
        main_split.setStretchFactor(0, 0)
        main_split.setStretchFactor(1, 1)
        main_split.setSizes([360, 1040])

        self.transport = MusicTransport()
        self.transport.play_button.setToolTip("Play / pause; renders the current probe first when needed (Space)")
        self.transport.set_source_choices([])
        self.transport.sourceSelectionChanged.connect(self._transport_source_changed)
        self.transport.playRequested.connect(self._toggle_playback)
        outer.addWidget(self.transport)

        self.status = QLabel("Ready.")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)

    def _build_library_panel(self) -> QWidget:
        box = QGroupBox("Instrument library")
        layout = QVBoxLayout(box)
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter programs, aliases, or SFZ paths")
        self.search.textChanged.connect(self._filter_library)
        search_row.addWidget(self.search, 1)
        self.scan_button = QPushButton("Scan installed SFZs")
        self.scan_button.clicked.connect(self._scan_installed)
        search_row.addWidget(self.scan_button)
        layout.addLayout(search_row)

        census_path = default_census_paths()[0]
        if self._usage_census is not None:
            census_count = len(self._usage_census.get("instruments") or [])
            census_text = f"Usage census: {census_count} analyzed patches · {census_path}"
        else:
            census_text = f"Usage census: not found · run ./instrument_usage_census.sh to generate {census_path}"
        self.census_status = QLabel(census_text)
        self.census_status.setWordWrap(True)
        self.census_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.census_status)

        self.library = QTreeWidget()
        self.library.setHeaderLabels(["Instrument / patch"])
        self.library.currentItemChanged.connect(self._library_selection_changed)
        layout.addWidget(self.library, 1)

        self.library_detail = QLabel("Select an entry to inspect it.")
        self.library_detail.setWordWrap(True)
        self.library_detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.library_detail)

        buttons = QHBoxLayout()
        self.resolve_button = QPushButton("Resolve")
        self.resolve_button.clicked.connect(self._resolve_selected_library)
        buttons.addWidget(self.resolve_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return box

    def _build_editor_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        editor_split = QSplitter(Qt.Horizontal)
        layout.addWidget(editor_split, 1)

        instrument_box = QGroupBox("Instrument YAML")
        inst_layout = QVBoxLayout(instrument_box)
        self.instrument_yaml = QPlainTextEdit()
        self.instrument_yaml.setLineWrapMode(QPlainTextEdit.NoWrap)
        inst_layout.addWidget(self.instrument_yaml)
        editor_split.addWidget(instrument_box)

        processing_box = QGroupBox("Processing / effect-chain YAML")
        proc_layout = QVBoxLayout(processing_box)
        self.processing_yaml = QPlainTextEdit()
        self.processing_yaml.setLineWrapMode(QPlainTextEdit.NoWrap)
        proc_layout.addWidget(self.processing_yaml, 1)
        effect_row = QHBoxLayout()
        effect_row.addWidget(QLabel("Append effect template"))
        self.effect_template = QComboBox()
        self.effect_template.addItems(EFFECT_TEMPLATES)
        effect_row.addWidget(self.effect_template, 1)
        add_effect = QPushButton("Append")
        add_effect.clicked.connect(self._append_effect_template)
        effect_row.addWidget(add_effect)
        proc_layout.addLayout(effect_row)
        editor_split.addWidget(processing_box)
        editor_split.setSizes([520, 520])

        probe_box = QGroupBox("Probe")
        probe_layout = QVBoxLayout(probe_box)
        form = QFormLayout()
        self.probe_template = QComboBox()
        form.addRow("Audition phrase", self.probe_template)
        self.note_probe = QLineEdit("C4")
        self.note_probe.setPlaceholderText("C4 or MIDI 60")
        form.addRow("Root / single note", self.note_probe)
        self.drum_probe = QComboBox()
        for name, midi in sorted(DRUMS.items(), key=lambda kv: kv[1]):
            self.drum_probe.addItem(f"{name}  (MIDI {midi})", name)
        crash_index = self.drum_probe.findData("crash")
        if crash_index >= 0:
            self.drum_probe.setCurrentIndex(crash_index)
        form.addRow("Drum key", self.drum_probe)
        self.velocity = QSpinBox()
        self.velocity.setRange(1, 127)
        self.velocity.setValue(108)
        form.addRow("Velocity", self.velocity)
        self.duration = QDoubleSpinBox()
        self.duration.setRange(0.05, 12.0)
        self.duration.setDecimals(2)
        self.duration.setSingleStep(0.1)
        self.duration.setValue(1.4)
        form.addRow("Note gate / sustain (s)", self.duration)
        self.tempo = QDoubleSpinBox()
        self.tempo.setRange(30.0, 260.0)
        self.tempo.setDecimals(1)
        self.tempo.setValue(100.0)
        form.addRow("Phrase tempo (BPM)", self.tempo)
        self.backend = QComboBox()
        for name in ("auto", "pretty-midi", "sfizz", "fallback"):
            self.backend.addItem(name, name)
        form.addRow("Render backend", self.backend)
        probe_layout.addLayout(form)

        probe_buttons = QHBoxLayout()
        self.render_button = QPushButton("Render probe")
        self.render_button.clicked.connect(lambda _checked=False: self._render_probe(auto_play=False))
        probe_buttons.addWidget(self.render_button)
        probe_buttons.addStretch(1)
        self.resolution_label = QLabel("Backend: GM / SoundFont")
        self.resolution_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        probe_buttons.addWidget(self.resolution_label)
        probe_layout.addLayout(probe_buttons)
        layout.addWidget(probe_box)

        diagnostics_box = QGroupBox("SFZ diagnostics")
        diagnostics_layout = QVBoxLayout(diagnostics_box)
        self.diagnostics = QPlainTextEdit()
        self.diagnostics.setReadOnly(True)
        self.diagnostics.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.diagnostics.setMaximumHeight(170)
        self.diagnostics.setPlainText("Select an SFZ patch to inspect its region/key/controller contract.")
        diagnostics_layout.addWidget(self.diagnostics)
        diagnostics_actions = QHBoxLayout()
        self.apply_controls_button = QPushButton("Apply suggested controls")
        self.apply_controls_button.setEnabled(False)
        self.apply_controls_button.clicked.connect(self._apply_suggested_controls)
        diagnostics_actions.addWidget(self.apply_controls_button)
        diagnostics_actions.addStretch(1)
        diagnostics_layout.addLayout(diagnostics_actions)
        layout.addWidget(diagnostics_box)
        return panel

    def _set_documents(self, instrument: dict, processing: dict) -> None:
        self.instrument_yaml.blockSignals(True)
        self.processing_yaml.blockSignals(True)
        self.instrument_yaml.setPlainText(yaml_text(instrument))
        self.processing_yaml.setPlainText(yaml_text(processing))
        self.instrument_yaml.blockSignals(False)
        self.processing_yaml.blockSignals(False)
        self._invalidate_probe()
        if hasattr(self, "_validation_timer"):
            self._refresh_document_state()

    def _set_instrument_document(self, instrument: dict, *, refresh: bool = True) -> None:
        """Replace only the disposable instrument, preserving effects text."""
        self.instrument_yaml.blockSignals(True)
        self.instrument_yaml.setPlainText(yaml_text(instrument))
        self.instrument_yaml.blockSignals(False)
        self._invalidate_probe()
        if refresh and hasattr(self, "_validation_timer"):
            self._refresh_document_state()

    def _documents(self) -> tuple[dict, dict]:
        instrument = parse_yaml_mapping(self.instrument_yaml.toPlainText(), label="instrument")
        processing = parse_yaml_mapping(self.processing_yaml.toPlainText(), label="processing")
        return instrument, processing

    def _invalidate_probe(self) -> None:
        self._rendered_request_hash = None
        if hasattr(self, "transport"):
            self.transport.set_play_request_available(False)
            self.transport.clear_sources()

    def _schedule_validation(self) -> None:
        # Manual YAML edits make the editor authoritative and invalidate the
        # rendered probe for the previous definition.
        self._invalidate_probe()
        if hasattr(self, "_validation_timer"):
            self._validation_timer.start()

    def _probe_settings_changed(self, *_args) -> None:
        self._invalidate_probe()
        if hasattr(self, "_validation_timer"):
            self._validation_timer.start()

    def _update_probe_templates(self, *, is_drum: bool) -> None:
        desired = "rock_groove" if is_drum else "major_scale"
        current = self.probe_template.currentData()
        valid = {key for key, _label in probe_template_options(is_drum=is_drum)}
        if current in valid:
            desired = current
        self.probe_template.blockSignals(True)
        self.probe_template.clear()
        for key, label in probe_template_options(is_drum=is_drum):
            self.probe_template.addItem(label, key)
        index = self.probe_template.findData(desired)
        self.probe_template.setCurrentIndex(max(0, index))
        self.probe_template.blockSignals(False)

    def _current_request(self) -> dict:
        instrument, processing = self._documents()
        probe = self.drum_probe.currentData() if instrument.get("is_drum") else self.note_probe.text().strip()
        return build_probe_request(
            instrument=instrument,
            processing=processing,
            probe=probe,
            probe_template=str(self.probe_template.currentData()),
            velocity=self.velocity.value(),
            duration_seconds=self.duration.value(),
            tempo_bpm=self.tempo.value(),
            backend=str(self.backend.currentData()),
        )

    def _resolved_backend_path_fast(self, instrument: dict) -> Path | None:
        backend = backend_spec_from_instrument(instrument)
        if str(backend.get("kind", "")) not in {"sfz", "sfizz", "sample", "sampled"}:
            return None
        # Exact registered aliases from the generated machine-local census are
        # constant-time and already capture the resolver's selected entry point.
        library_ref = backend.get("library_ref")
        if library_ref:
            census_path = self._usage_census_alias_hits.get(str(library_ref))
            if census_path:
                path = Path(census_path)
                if path.is_file():
                    return path.resolve()
        # Cache arbitrary explicit/glob/custom-library resolutions for the life of
        # the GUI. Installed SFZ files are already process-static in the resolver.
        try:
            key = json.dumps(backend, sort_keys=True, default=str)
        except TypeError:
            key = repr(backend)
        if key not in self._resolved_backend_cache:
            self._resolved_backend_cache[key] = resolved_backend_path(instrument, base_dir=self.project_root)
        return self._resolved_backend_cache[key]

    def _instrument_availability(self, instrument: dict) -> tuple[bool, str]:
        backend = backend_spec_from_instrument(instrument)
        if not backend:
            return True, f"GM / SoundFont · {instrument.get('program', 'default')}"
        kind = str(backend.get("kind", "custom"))
        ref = backend.get("library_ref") or backend.get("sfz")
        if kind in {"sfz", "sfizz", "sample", "sampled"}:
            resolved = self._resolved_backend_path_fast(instrument)
            if resolved is None or not Path(resolved).is_file():
                return False, f"SFZ unavailable · {ref or 'unresolved selection'}"
            return True, f"SFZ · {ref or resolved.name} → {resolved.name}"
        return True, f"{kind} · {ref or 'configured'}"

    def _census_row_for_instrument(self, instrument: dict) -> tuple[Path | None, dict | None]:
        backend = backend_spec_from_instrument(instrument)
        if str(backend.get("kind", "")) not in {"sfz", "sfizz", "sample", "sampled"}:
            return None, None
        resolved = self._resolved_backend_path_fast(instrument)
        if resolved is None:
            return None, None
        path = Path(resolved).resolve()
        row = self._usage_census_by_path.get(str(path))
        if row is None or not census_row_is_fresh(row, path):
            return path, None
        return path, row

    def _cheap_preflight(self, request: dict) -> dict:
        """Use the static usage census on the UI thread; never deep-parse here."""
        instrument = request.get("instrument") or {}
        path, row = self._census_row_for_instrument(instrument)
        if row is not None:
            return sfz_probe_preflight_from_census(request, row, base_dir=self.project_root)
        backend = instrument.get("instrument_backend")
        if isinstance(backend, dict) and str(backend.get("kind", "")) == "sfz":
            if path is None:
                return {
                    "kind": "sfz",
                    "status": "unavailable",
                    "summary": "SFZ backend did not resolve on this machine.",
                }
            return {
                "kind": "sfz",
                "status": "deferred",
                "summary": (
                    f"SFZ resolved to {path.name}. Deep region/controller analysis is deferred until Render/Play "
                    "because no fresh usage-census row is available. Run ./instrument_usage_census.sh for instant diagnostics."
                ),
                "path": str(path),
            }
        return {"kind": "non_sfz", "status": "ok", "summary": "GM / non-SFZ backend; region preflight does not apply."}

    def _refresh_document_state(self) -> None:
        try:
            instrument, _processing = self._documents()
        except Exception as exc:
            self._last_preflight = {}
            self.diagnostics.setPlainText(f"YAML error: {exc}")
            self.apply_controls_button.setEnabled(False)
            self.status.setText(f"YAML error: {exc}")
            self.render_button.setEnabled(False)
            self.transport.set_play_request_available(False)
            return
        is_drum = bool(instrument.get("is_drum"))
        self._update_probe_templates(is_drum=is_drum)
        self.drum_probe.setEnabled(is_drum)
        self.note_probe.setEnabled(not is_drum)
        self.tempo.setEnabled(True)
        available, resolution = self._instrument_availability(instrument)
        self.resolution_label.setText(f"Backend: {resolution}")

        preflight: dict = {}
        preflight_blocks_render = False
        if available:
            try:
                preflight = self._cheap_preflight(self._current_request())
                self.diagnostics.setPlainText(format_probe_diagnostics(preflight))
                preflight_blocks_render = preflight.get("status") in {"blocked", "out_of_range", "no_regions", "no_match", "missing_samples"}
            except Exception as exc:
                preflight = {"status": "diagnostic_error", "summary": str(exc)}
                self.diagnostics.setPlainText(f"Could not inspect cached SFZ usage metadata: {exc}")
        else:
            self.diagnostics.setPlainText("Backend unavailable; no region diagnostics can be computed.")
        self._last_preflight = preflight
        self.apply_controls_button.setEnabled(bool(preflight.get("suggested_controls")) and self._render_process is None)

        can_render = available and not preflight_blocks_render and self._render_process is None
        self.render_button.setEnabled(can_render)
        self.transport.set_play_request_available(can_render)
        if not available:
            self.status.setText("The selected instrument backend is not available on this machine. Render and Play are disabled.")
        elif preflight_blocks_render:
            self.status.setText(
                "The current SFZ probe cannot trigger an active region. See SFZ diagnostics below; "
                "apply the suggested controller defaults when offered."
            )
        elif self._render_process is not None:
            self.status.setText("Rendering the current audition phrase…")
        elif self._rendered_request_hash is None:
            self.status.setText("Definition is valid but not rendered. Press Play to render it automatically, or Render probe to prepare it without playing.")

    def _apply_suggested_controls(self) -> None:
        if not self._last_preflight.get("suggested_controls"):
            return
        try:
            instrument, _processing = self._documents()
            instrument = apply_probe_control_suggestions(instrument, self._last_preflight)
        except Exception as exc:
            self.status.setText(f"Could not apply suggested controls: {exc}")
            return
        self._set_instrument_document(instrument)
        self.status.setText("Applied SFZ controller-gate suggestions to Instrument YAML. Press Play to audition the exact patch.")

    def _group_item(self, parent: QTreeWidgetItem, label: str) -> QTreeWidgetItem:
        for index in range(parent.childCount()):
            child = parent.child(index)
            if child.data(0, Qt.UserRole) is None and child.text(0) == label:
                return child
        child = QTreeWidgetItem([label])
        child.setFlags(child.flags() & ~Qt.ItemIsSelectable)
        parent.addChild(child)
        return child

    def _add_grouped_entry(self, root: QTreeWidgetItem, entry: LibraryEntry) -> None:
        parent = root
        for part in entry.group_path:
            parent = self._group_item(parent, part)
        item = QTreeWidgetItem([entry.label])
        item.setToolTip(0, entry.value)
        item.setData(0, Qt.UserRole, entry)
        parent.addChild(item)

    def _populate_library_base(self) -> None:
        self.library.clear()
        self.gm_root = QTreeWidgetItem(["GM / SoundFont programs"])
        self.alias_root = QTreeWidgetItem(["Registered SFZ aliases"])
        self.sfz_root = QTreeWidgetItem(["Installed SFZ files (not scanned)"])
        for root in (self.gm_root, self.alias_root, self.sfz_root):
            root.setFlags(root.flags() & ~Qt.ItemIsSelectable)
            self.library.addTopLevelItem(root)
        for entry in gm_library_entries():
            self._add_grouped_entry(self.gm_root, entry)
        for entry in alias_library_entries():
            self._add_grouped_entry(self.alias_root, entry)
        self.gm_root.setExpanded(False)
        self.alias_root.setExpanded(True)
        self.sfz_root.setExpanded(False)

    def _selected_entry(self) -> LibraryEntry | None:
        item = self.library.currentItem()
        if item is None:
            return None
        entry = item.data(0, Qt.UserRole)
        return entry if isinstance(entry, LibraryEntry) else None

    def _library_selection_changed(self, *_args) -> None:
        entry = self._selected_entry()
        if entry is None:
            self.library_detail.setText("Select a concrete library entry.")
            return
        # A concrete library click is an explicit audition choice.  Apply it to
        # the disposable editor immediately; there is no second "load" step.
        self._use_selected_library()

    def _filter_tree_item(self, item: QTreeWidgetItem, needle: str) -> bool:
        entry = item.data(0, Qt.UserRole)
        if isinstance(entry, LibraryEntry):
            hay = f"{item.text(0)} {entry.value} {' '.join(entry.group_path)}".lower()
            visible = not needle or needle in hay
            item.setHidden(not visible)
            return visible
        any_visible = False
        for index in range(item.childCount()):
            any_visible |= self._filter_tree_item(item.child(index), needle)
        own_match = bool(needle and needle in item.text(0).lower())
        visible = not needle or any_visible or own_match
        item.setHidden(not visible)
        if needle and visible:
            item.setExpanded(True)
        return visible

    def _filter_library(self, text: str) -> None:
        needle = text.strip().lower()
        for root in (self.gm_root, self.alias_root, self.sfz_root):
            self._filter_tree_item(root, needle)

    def _scan_installed(self) -> None:
        self.scan_button.setEnabled(False)
        self.status.setText("Scanning configured SFZ roots…")
        QApplication.processEvents()
        try:
            rows = installed_sfz_entries()
        except Exception as exc:
            self.status.setText(f"SFZ scan failed: {exc}")
            self.scan_button.setEnabled(True)
            return
        while self.sfz_root.childCount():
            self.sfz_root.takeChild(0)
        self.sfz_root.setText(0, f"Installed SFZ files ({len(rows)})")
        for entry in rows:
            self._add_grouped_entry(self.sfz_root, entry)
        self.sfz_root.setExpanded(True)
        self.scan_button.setEnabled(True)
        self.status.setText(
            f"Found {len(rows)} installed SFZ files, grouped by library/directory. Use search to filter across the hierarchy."
        )
        self._filter_library(self.search.text())

    def _use_selected_library(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        try:
            try:
                instrument = parse_yaml_mapping(self.instrument_yaml.toPlainText(), label="instrument")
            except Exception:
                # A concrete library choice should be able to recover from a
                # half-edited/invalid disposable instrument document.
                instrument = default_instrument_document()
            instrument = apply_library_entry(instrument, entry)
        except Exception as exc:
            self.status.setText(f"Cannot apply library choice: {exc}")
            return
        self._set_instrument_document(instrument, refresh=False)
        # One state refresh per click. Older code refreshed here, resolved the
        # library again, then refreshed a second time; large SFZ libraries made
        # that duplication visible as UI stalls.
        self._refresh_document_state()
        self._resolve_selected_library()

    def _resolve_selected_library(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        try:
            instrument = parse_yaml_mapping(self.instrument_yaml.toPlainText(), label="instrument")
            candidate = apply_library_entry(instrument, entry)
            resolved = self._resolved_backend_path_fast(candidate)
        except Exception as exc:
            self.library_detail.setText(f"Resolution failed: {exc}")
            return
        if entry.kind == "gm":
            self.library_detail.setText(f"GM / SoundFont program: {entry.value}")
            return
        if resolved is None:
            self.library_detail.setText(f"{entry.value}\nNot resolved on this machine.")
            return
        row = self._usage_census_by_path.get(str(Path(resolved).resolve()))
        span = row.get("key_span") if row and census_row_is_fresh(row, resolved) else None
        span_text = f" · MIDI range {span[0]}–{span[1]}" if isinstance(span, list) and len(span) == 2 else ""
        census_text = " · usage census" if row and census_row_is_fresh(row, resolved) else ""
        self.library_detail.setText(f"{entry.value}\n→ {resolved}{span_text}{census_text}")

    def _new_document(self) -> None:
        self._set_documents(default_instrument_document(), default_processing_document())
        self.status.setText("New disposable instrument document.")

    def _load_from_score(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Load instrument from MusicIR score",
            str(self.project_root / "scores"),
            "Music score (*.music.yaml *.yaml *.yml)",
        )
        if not filename:
            return
        path = Path(filename)
        try:
            names = score_instrument_names(path)
        except Exception as exc:
            QMessageBox.critical(self, "Load failed", str(exc))
            return
        if not names:
            QMessageBox.information(self, "No instruments", "That score contains no authored instruments.")
            return
        name, ok = QInputDialog.getItem(self, "Choose instrument", "Instrument", names, 0, False)
        if not ok:
            return
        try:
            instrument, processing = load_score_instrument(path, str(name))
        except Exception as exc:
            QMessageBox.critical(self, "Load failed", str(exc))
            return
        self._set_documents(instrument, processing)
        self.status.setText(f"Loaded {name} from {path.name}; edits remain local to this inspector document.")

    def _export(self) -> None:
        try:
            instrument, processing = self._documents()
        except Exception as exc:
            QMessageBox.critical(self, "Invalid YAML", str(exc))
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export instrument YAML snippets",
            str(agent_root() / "instrument_inspector" / "instrument_patch.yaml"),
            "YAML (*.yaml *.yml)",
        )
        if not filename:
            return
        try:
            out = write_export_document(Path(filename), instrument=instrument, processing=processing)
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self.status.setText(f"Exported YAML snippets to {out}. No score was modified.")

    def _append_effect_template(self) -> None:
        try:
            instrument, processing = self._documents()
            processing = append_effect_template(processing, self.effect_template.currentText())
        except Exception as exc:
            self.status.setText(f"Could not append effect template: {exc}")
            return
        self._set_documents(instrument, processing)

    def _render_probe(self, *, auto_play: bool = False) -> None:
        if self._render_process is not None:
            if auto_play:
                self._play_after_render = True
                self.status.setText("Probe render is already running; playback will start when it finishes.")
            else:
                self.status.setText("A probe render is already running.")
            return
        try:
            instrument, _processing = self._documents()
            available, _resolution = self._instrument_availability(instrument)
            if not available:
                raise ValueError("selected instrument backend is not available on this machine")
            request = self._current_request()
            preflight = self._cheap_preflight(request)
            if preflight.get("status") in {"blocked", "out_of_range", "no_regions", "no_match", "missing_samples"}:
                raise ValueError(format_probe_diagnostics(preflight))
        except Exception as exc:
            QMessageBox.critical(self, "Cannot render", str(exc))
            return
        self._invalidate_probe()
        request_hash = probe_request_hash(request)
        request_dir = agent_root() / "instrument_inspector" / "requests"
        request_dir.mkdir(parents=True, exist_ok=True)
        request_path = request_dir / f"probe-{uuid.uuid4().hex[:12]}.json"
        request_path.write_text(json.dumps(request, indent=2, sort_keys=True), encoding="utf8")
        self._render_request_path = request_path
        self._render_request_hash = request_hash
        self._play_after_render = bool(auto_play)

        process = QProcess(self)
        self._render_process = process
        process.setWorkingDirectory(str(self.project_root))
        process.finished.connect(self._probe_finished)
        process.errorOccurred.connect(lambda _error: self.status.setText("Probe process failed to start."))
        self.render_button.setEnabled(False)
        self.transport.set_play_request_available(False)
        action = "Rendering before playback" if auto_play else "Rendering"
        self.status.setText(f"{action}: canonical audition phrase through the normal backend and processing chain…")
        process.start(
            sys.executable,
            ["-m", "ambition_music_renderer.music_instrument_inspector", "--render-request", str(request_path)],
        )

    def _probe_finished(self, exit_code: int, _exit_status) -> None:
        process = self._render_process
        expected_hash = self._render_request_hash
        auto_play = self._play_after_render
        self._play_after_render = False
        self._render_process = None
        self._render_request_hash = None
        if process is None:
            return
        stdout = bytes(process.readAllStandardOutput()).decode("utf8", errors="replace")
        stderr = bytes(process.readAllStandardError()).decode("utf8", errors="replace")
        if exit_code != 0:
            failure = (stderr or stdout).strip()[-2000:]
            self._refresh_document_state()
            existing = self.diagnostics.toPlainText().strip()
            self.diagnostics.setPlainText((existing + "\n\nRenderer failure:\n" + failure).strip())
            self.status.setText("Probe render failed. See SFZ diagnostics for the region preflight and renderer output.")
            return
        try:
            line = next(line for line in reversed(stdout.splitlines()) if line.strip().startswith("{"))
            report = json.loads(line)
            processed = Path(report["processed_audio"])
            dry = Path(report["dry_audio"])
            current_hash = probe_request_hash(self._current_request())
        except Exception as exc:
            self.status.setText(f"Probe finished but its result could not be parsed: {exc}\n{stdout[-700:]}")
            self._refresh_document_state()
            return
        report_hash = str(report.get("request_hash") or "")
        if report_hash != expected_hash or current_hash != expected_hash:
            self.transport.clear_sources()
            self._rendered_request_hash = None
            self.status.setText("Probe finished, but the selected instrument or audition settings changed during rendering. Render again to Play.")
            self._refresh_document_state()
            return
        self._rendered_request_hash = report_hash
        self.transport.set_source_choices([("Processed", processed), ("Dry / no post-processing", dry)], selected=processed)
        self.transport.set_media(processed, preserve=False, resume=auto_play)
        resolved = report.get("resolved_backend_path") or "GM / SoundFont"
        dry_stats = report.get("dry") or {}
        proc_stats = report.get("processed") or {}
        dry_peak = float(dry_stats.get("peak", 0.0))
        proc_peak = float(proc_stats.get("peak", 0.0))
        dry_db = dry_stats.get("peak_dbfs")
        proc_db = proc_stats.get("peak_dbfs")
        preflight = report.get("preflight") or self._last_preflight
        diagnostic_text = format_probe_diagnostics(preflight)
        diagnostic_text += (
            f"\nRendered audio: dry peak {dry_peak:.6f}"
            + (f" ({float(dry_db):.1f} dBFS)" if dry_db is not None else " (silence)")
            + f"; processed peak {proc_peak:.6f}"
            + (f" ({float(proc_db):.1f} dBFS)" if proc_db is not None else " (silence)")
        )
        if stderr.strip():
            diagnostic_text += "\nBackend messages:\n" + stderr.strip()[-1200:]
        self.diagnostics.setPlainText(diagnostic_text)
        tail = f" Backend warnings are shown in diagnostics." if stderr.strip() else ""
        prefix = "Playing freshly rendered probe." if auto_play else "Probe ready and current."
        self.status.setText(
            f"{prefix} Resolved: {resolved}. Dry peak {dry_peak:.3f}; processed peak {proc_peak:.3f}.{tail}"
        )
        self._refresh_document_state()

    def _transport_source_changed(self) -> None:
        if self._rendered_request_hash is None:
            self.transport.clear_sources()
            return
        data = self.transport.current_source_data()
        if data:
            self.transport.set_media(Path(data), preserve=True)

    def _toggle_playback(self) -> None:
        try:
            current_hash = probe_request_hash(self._current_request())
        except Exception as exc:
            self._invalidate_probe()
            self._refresh_document_state()
            self.status.setText(f"Cannot audition current definition: {exc}")
            return

        if self._rendered_request_hash != current_hash:
            # Play means "audition what I am looking at".  If this exact
            # configuration is not rendered yet, prepare it first and start
            # playback only after the matching render succeeds.
            self._render_probe(auto_play=True)
            return

        data = self.transport.current_source_data()
        self.transport.toggle(Path(data) if data else None)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.transport.close_transport()
        if self._render_process is not None:
            self._render_process.kill()
            self._render_process.waitForFinished(1500)
        super().closeEvent(event)


def run_gui(project_root: Path) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = InstrumentInspectorWindow(project_root)
    window.show()
    install_sigint_quit(app)
    return int(app.exec())
