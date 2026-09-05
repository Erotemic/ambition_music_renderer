from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
from typing import Iterable

from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .music_audition import (
    StemVersion,
    compose_stem_mix,
    discover_versions,
    discover_versions_from_path,
    mix_identity,
)
from .music_stem_inspector import (
    StemDiffReport,
    compare_stem_timelines,
    format_note,
    instrument_definition_lines,
    score_source_for_version,
)
from .music_instrument_audition import instrument_choices, safe_variant_slug, write_instrument_variant
from .music_instrument_audition_qt import InstrumentAuditionPanel
from .music_stem_inspector_qt import StemInspectorPanel
from .music_stem_lab_model import StemLabSession
from .music_timeline import TimelineDocument, load_version_timeline, version_timeline_status
from .music_timeline_qt import DisplayNote, NoteTimelinePanel
from .music_transport_qt import MusicTransport
from .music_qt_runtime import install_sigint_quit


def _source_label(version: StemVersion) -> str:
    mapping = {
        "scratch_render": "scratch",
        "folder": "folder",
        "generated_latest": "generated · latest",
        "generated": "generated",
    }
    return mapping.get(version.source_kind, version.source_kind.replace("_", " "))


def _grid_signature(document: TimelineDocument) -> tuple[tuple[float, int, int, bool], ...]:
    return tuple(
        (round(row.time_seconds, 4), row.bar, row.beat, row.major)
        for row in document.timeline.grid
    )


def _section_signature(document: TimelineDocument) -> tuple[tuple[str, float, float], ...]:
    return tuple(
        (row.id, round(row.start_seconds, 4), round(row.end_seconds, 4))
        for row in document.timeline.sections
    )


def _group_icon(color, size: int = 12) -> QIcon:
    """Small routing-table swatch matching the piano-roll note color."""
    pixmap = QPixmap(size, size)
    pixmap.fill(color)
    return QIcon(pixmap)


class StemLabWindow(QMainWindow):
    """Read-only cross-version stem audition and semantic score inspection."""

    def __init__(
        self,
        project_root: Path,
        versions: Iterable[StemVersion],
        *,
        initial_cue: str | None = None,
    ) -> None:
        super().__init__()
        self.project_root = Path(project_root).resolve()
        self.manual_library_roots: list[Path] = []
        self.session = StemLabSession.from_versions(versions)
        self.mix_path: Path | None = None
        self.mix_identity_value: str | None = None
        self._temp_dir = Path(tempfile.mkdtemp(prefix="ambition-stem-lab-"))
        self._route_widgets: dict[str, tuple[QTableWidgetItem, QComboBox]] = {}
        self._timeline_docs: dict[str, TimelineDocument | None] = {}
        self.render_process: QProcess | None = None
        self._instrument_render_group: str | None = None
        self._instrument_render_dir: Path | None = None
        self._instrument_render_log: list[str] = []

        self.mix_timer = QTimer(self)
        self.mix_timer.setSingleShot(True)
        self.mix_timer.setInterval(180)
        self.mix_timer.timeout.connect(self._rebuild_mix)

        self.setWindowTitle("Ambition Stem Lab")
        self.resize(1500, 980)
        self._build_ui()
        self._refresh_cues(initial_cue)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.transport.close_transport()
        if self.render_process is not None and self.render_process.state() != QProcess.ProcessState.NotRunning:
            self.render_process.kill()
            self.render_process.waitForFinished(1500)
        shutil.rmtree(self._temp_dir, ignore_errors=True)
        super().closeEvent(event)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        top = QHBoxLayout()
        top.addWidget(QLabel("Cue"))
        self.cue_combo = QComboBox()
        self.cue_combo.currentIndexChanged.connect(self._cue_changed)
        top.addWidget(self.cue_combo, 1)
        self.rescan_button = QPushButton("Rescan disk")
        self.rescan_button.clicked.connect(self._rescan)
        top.addWidget(self.rescan_button)
        self.add_folder_button = QPushButton("Add render folder…")
        self.add_folder_button.clicked.connect(self._add_folder)
        top.addWidget(self.add_folder_button)
        outer.addLayout(top)

        explanation = QLabel(
            "Stem audition view. Route rendered stems independently and inspect the notes that produced them. "
            "The piano roll remains read-only; instrument auditions always clone to a new scratch variant and never overwrite a source score."
        )
        explanation.setWordWrap(True)
        outer.addWidget(explanation)

        split = QSplitter(Qt.Horizontal)
        outer.addWidget(split, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Versions on disk"))
        self.library_table = QTableWidget(0, 7)
        self.library_table.setHorizontalHeaderLabels(
            ["Version", "Source", "Hash", "Stems", "Full mix", "Notes", "Loaded"]
        )
        self.library_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.library_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.library_table.verticalHeader().setVisible(False)
        self.library_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.library_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        left_layout.addWidget(self.library_table, 2)
        library_buttons = QHBoxLayout()
        self.load_button = QPushButton("Load selected")
        self.load_button.clicked.connect(self._load_selected)
        library_buttons.addWidget(self.load_button)
        library_buttons.addStretch(1)
        left_layout.addLayout(library_buttons)

        left_layout.addWidget(QLabel("Loaded working set"))
        self.loaded_table = QTableWidget(0, 6)
        self.loaded_table.setHorizontalHeaderLabels(["Reference", "Version", "Stems", "Full mix", "Notes", ""])
        self.loaded_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.loaded_table.verticalHeader().setVisible(False)
        self.loaded_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.loaded_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        left_layout.addWidget(self.loaded_table, 1)

        reference_row = QHBoxLayout()
        reference_row.addWidget(QLabel("Reference"))
        self.reference_combo = QComboBox()
        self.reference_combo.currentIndexChanged.connect(self._reference_changed)
        reference_row.addWidget(self.reference_combo, 1)
        left_layout.addLayout(reference_row)
        split.addWidget(left)

        right_split = QSplitter(Qt.Vertical)
        split.addWidget(right_split)

        top_right = QSplitter(Qt.Horizontal)
        right_split.addWidget(top_right)

        routing = QWidget()
        right_layout = QVBoxLayout(routing)
        route_top = QHBoxLayout()
        route_top.addWidget(QLabel("Stem routing"))
        self.enable_all_button = QPushButton("Select all")
        self.enable_all_button.setToolTip("Enable every routed stem")
        self.enable_all_button.clicked.connect(lambda: self._set_all_route_enabled(True))
        route_top.addWidget(self.enable_all_button)
        self.enable_none_button = QPushButton("Select none")
        self.enable_none_button.setToolTip("Disable every routed stem")
        self.enable_none_button.clicked.connect(lambda: self._set_all_route_enabled(False))
        route_top.addWidget(self.enable_none_button)
        route_top.addStretch(1)
        route_top.addWidget(QLabel("Set all to"))
        self.route_all_combo = QComboBox()
        route_top.addWidget(self.route_all_combo)
        self.route_all_button = QPushButton("Apply")
        self.route_all_button.clicked.connect(self._route_all)
        route_top.addWidget(self.route_all_button)
        self.reference_all_button = QPushButton("Use reference")
        self.reference_all_button.clicked.connect(self._route_all_reference)
        route_top.addWidget(self.reference_all_button)
        right_layout.addLayout(route_top)

        self.route_table = QTableWidget(0, 4)
        self.route_table.setHorizontalHeaderLabels(["On", "Stem", "Source version", "Asset"])
        self.route_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.route_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.route_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.route_table.verticalHeader().setVisible(False)
        self.route_table.itemChanged.connect(self._route_item_changed)
        self.route_table.itemSelectionChanged.connect(self._route_selection_changed)
        self.route_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.route_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        right_layout.addWidget(self.route_table, 1)

        self.mix_status = QLabel("Load a rendered version with stems to begin.")
        self.mix_status.setWordWrap(True)
        right_layout.addWidget(self.mix_status)
        top_right.addWidget(routing)

        diagnostics = QWidget()
        diagnostics_layout = QVBoxLayout(diagnostics)
        diagnostics_layout.setContentsMargins(0, 0, 0, 0)
        self.stem_inspector = StemInspectorPanel()
        self.stem_inspector.groupChanged.connect(self._inspector_group_changed)
        self.stem_inspector.selectionChanged.connect(self._refresh_inspector_report)
        self.stem_inspector.diffViewChanged.connect(lambda _enabled: self._refresh_timeline())
        diagnostics_layout.addWidget(self.stem_inspector, 2)
        self.instrument_audition = InstrumentAuditionPanel()
        self.instrument_audition.renderRequested.connect(self._render_instrument_audition)
        diagnostics_layout.addWidget(self.instrument_audition, 1)
        top_right.addWidget(diagnostics)
        top_right.setSizes([620, 460])

        self.timeline_panel = NoteTimelinePanel()
        self.timeline_panel.seekRequested.connect(self._seek_from_timeline)
        right_split.addWidget(self.timeline_panel)
        right_split.setSizes([360, 500])
        split.setSizes([560, 940])

        transport_frame = QFrame()
        transport_frame.setFrameShape(QFrame.StyledPanel)
        transport_layout = QVBoxLayout(transport_frame)
        transport_layout.setContentsMargins(0, 0, 0, 0)
        self.transport = MusicTransport()
        self.transport.sourceSelectionChanged.connect(self._listen_source_changed)
        self.transport.playRequested.connect(self._toggle_play)
        self.transport.positionChanged.connect(self.timeline_panel.set_playhead_ms)
        self.transport.playbackError.connect(self._player_error)
        transport_layout.addWidget(self.transport)
        outer.addWidget(transport_frame)

        self.statusBar().showMessage(
            "Piano-roll edits are read-only. Instrument auditions are exported as new scratch variants only."
        )

    @property
    def current_cue(self) -> str | None:
        return self.session.current_cue

    def _versions_for_cue(self, cue_id: str | None = None) -> list[StemVersion]:
        return self.session.versions_for_cue(cue_id)

    def _refresh_cues(self, requested: str | None = None) -> None:
        current = requested or self.current_cue
        cues = sorted({version.cue_id for version in self.session.versions.values()})
        self.cue_combo.blockSignals(True)
        self.cue_combo.clear()
        for cue in cues:
            title = next((v.title for v in self.session.versions.values() if v.cue_id == cue), cue)
            self.cue_combo.addItem(f"{title}  [{cue}]", cue)
        if cues:
            target = current if current in cues else cues[0]
            index = next((i for i in range(self.cue_combo.count()) if self.cue_combo.itemData(i) == target), 0)
            self.cue_combo.setCurrentIndex(index)
        self.cue_combo.blockSignals(False)
        self._cue_changed()

    def _cue_changed(self) -> None:
        cue = self.cue_combo.currentData()
        cue = str(cue) if cue else None
        if cue != self.current_cue:
            self.transport.stop()
            self.timeline_panel.reset_view_on_next_timeline()
            self.session.select_cue(cue)
        self._refresh_all_tables()
        self._mark_mix_dirty()
        self._refresh_timeline()

    def _refresh_all_tables(self) -> None:
        self._refresh_library_table()
        self._refresh_loaded_table()
        self._refresh_reference_combo()
        self._refresh_route_table()
        self._refresh_inspector()
        self._refresh_listen_sources()

    def _note_status(self, version: StemVersion) -> str:
        return version_timeline_status(version)

    def _refresh_library_table(self) -> None:
        versions = self._versions_for_cue()
        self.library_table.setRowCount(len(versions))
        for row, version in enumerate(versions):
            assets = self.session.assets_for(version.key)
            cells = [
                version.label,
                _source_label(version),
                version.display_hash,
                str(len(assets)),
                "yes" if version.full_mix_path else "—",
                self._note_status(version),
                "yes" if version.key in self.session.loaded_keys else "—",
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, version.key)
                self.library_table.setItem(row, col, item)

    def _refresh_loaded_table(self) -> None:
        self.loaded_table.setRowCount(len(self.session.loaded_keys))
        for row, key in enumerate(self.session.loaded_keys):
            version = self.session.versions[key]
            values = [
                "●" if key == self.session.reference_key else "",
                version.label,
                str(len(self.session.assets_for(key))),
                "yes" if version.full_mix_path else "—",
                self._note_status(version),
            ]
            for col, text in enumerate(values):
                self.loaded_table.setItem(row, col, QTableWidgetItem(text))
            button = QPushButton("Unload")
            button.clicked.connect(lambda _checked=False, k=key: self._unload_version(k))
            self.loaded_table.setCellWidget(row, 5, button)

    def _refresh_reference_combo(self) -> None:
        selected = self.session.reference_key
        self.reference_combo.blockSignals(True)
        self.reference_combo.clear()
        self.reference_combo.addItem("none", None)
        for key in self.session.loaded_keys:
            self.reference_combo.addItem(self.session.versions[key].label, key)
        index = next(
            (i for i in range(self.reference_combo.count()) if self.reference_combo.itemData(i) == selected),
            0,
        )
        self.reference_combo.setCurrentIndex(index)
        self.reference_combo.blockSignals(False)

    def _refresh_route_all_combo(self) -> None:
        current = self.route_all_combo.currentData()
        self.route_all_combo.blockSignals(True)
        self.route_all_combo.clear()
        for key in self.session.loaded_keys:
            self.route_all_combo.addItem(self.session.versions[key].label, key)
        index = next(
            (i for i in range(self.route_all_combo.count()) if self.route_all_combo.itemData(i) == current),
            0,
        )
        if self.route_all_combo.count():
            self.route_all_combo.setCurrentIndex(index)
        self.route_all_combo.blockSignals(False)

    def _refresh_route_table(self) -> None:
        self.route_table.blockSignals(True)
        self._route_widgets.clear()
        groups = self.session.groups
        self.timeline_panel.set_group_palette(groups)
        self.route_table.setRowCount(len(groups))
        for row, group in enumerate(groups):
            route = self.session.routes[group]
            enabled_item = QTableWidgetItem()
            enabled_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            enabled_item.setCheckState(Qt.Checked if route.enabled else Qt.Unchecked)
            enabled_item.setData(Qt.UserRole, group)
            self.route_table.setItem(row, 0, enabled_item)
            stem_item = QTableWidgetItem(_group_icon(self.timeline_panel.view.group_color(group)), group)
            stem_item.setToolTip(f"{group}: this swatch matches the note color in the piano roll")
            self.route_table.setItem(row, 1, stem_item)

            combo = QComboBox()
            candidates = self.session.candidates_for_group(group)
            for key in candidates:
                combo.addItem(self.session.versions[key].label, key)
            index = next((i for i in range(combo.count()) if combo.itemData(i) == route.version_key), 0)
            if combo.count():
                combo.setCurrentIndex(index)
            combo.currentIndexChanged.connect(
                lambda _index, g=group, widget=combo: self._route_source_changed(g, widget)
            )
            self.route_table.setCellWidget(row, 2, combo)

            asset = self.session.assets_for(str(route.version_key)).get(group) if route.version_key else None
            self.route_table.setItem(row, 3, QTableWidgetItem(asset.quality_label if asset else "unavailable"))
            self._route_widgets[group] = (enabled_item, combo)
        self.route_table.blockSignals(False)
        self._refresh_route_all_combo()

    def _refresh_inspector(self, selected_group: str | None = None) -> None:
        groups = self.session.groups
        icons = [
            (group, _group_icon(self.timeline_panel.view.group_color(group)))
            for group in groups
        ]
        self.stem_inspector.set_groups(icons, selected=selected_group)
        group = self.stem_inspector.current_group()
        if not group:
            self.stem_inspector.set_versions([], main=None, compare=None)
            self.stem_inspector.set_report(
                "Load a version with stems to inspect differences.", "", can_diff=False
            )
            self._refresh_instrument_audition(None, None)
            return

        candidates = self.session.candidates_for_group(group)
        main = self.session.routed_source_for_group(group)
        alternates = self.session.comparison_candidates_for_group(group)
        _previous_main, previous_compare = self.stem_inspector.current_versions()
        compare = previous_compare if previous_compare in alternates else None
        if compare is None and self.session.reference_key in alternates:
            compare = self.session.reference_key
        if compare is None:
            compare = alternates[0] if alternates else None

        versions = [(self.session.versions[key].label, key) for key in candidates]
        self.stem_inspector.set_versions(versions, main=main, compare=compare)
        self._select_route_group(group)
        self._refresh_instrument_audition(group, main)
        self._refresh_inspector_report()

    def _refresh_instrument_audition(self, group: str | None, main_key: str | None) -> None:
        if not group or not main_key or main_key not in self.session.versions:
            self.instrument_audition.set_context(
                base_label="", group=group or "", source_score=None, exact_source=False, choices=()
            )
            return
        version = self.session.versions[main_key]
        source_score, exact = score_source_for_version(version)
        choices = instrument_choices(source_score, group) if source_score is not None else ()
        self.instrument_audition.set_context(
            base_label=version.label,
            group=group,
            source_score=source_score,
            exact_source=exact,
            choices=choices,
        )

    def _render_instrument_audition(self, request: object) -> None:
        if not isinstance(request, dict):
            return
        if self.render_process is not None and self.render_process.state() != QProcess.ProcessState.NotRunning:
            self.statusBar().showMessage("An instrument audition render is already running.", 4000)
            return
        try:
            cue = safe_variant_slug(self.current_cue or "cue")
            requested_name = safe_variant_slug(str(request.get("variant_name") or "instrument_audition"))
            scratch_root = self.project_root / "agent" / "stem_lab_edits" / cue
            score_path = write_instrument_variant(
                source_score=Path(request["source_score"]),
                destination_score=scratch_root / "scores" / f"{requested_name}.music.yaml",
                group=str(request["group"]),
                instrument_name=str(request["instrument_name"]),
                program=request.get("program", "string_ensemble_1"),
                backend_mode=str(request.get("backend_mode") or "keep"),
                library_ref=str(request.get("library_ref") or ""),
                sfz_glob=str(request.get("sfz_glob") or ""),
            )
        except Exception as exc:
            self.instrument_audition.set_rendering(False, f"Could not create scratch variant: {exc}")
            return

        label = score_path.name.removesuffix(".music.yaml")
        render_dir = scratch_root / "renders" / label
        self._instrument_render_group = str(request["group"])
        self._instrument_render_dir = render_dir
        self._instrument_render_log = []

        process = QProcess(self)
        self.render_process = process
        process.setWorkingDirectory(str(self.project_root))
        process.setProgram(sys.executable)
        process.setArguments([
            "-m", "ambition_music_renderer.render.isolated",
            str(score_path),
            "--outdir", str(render_dir),
            "--backend", "auto",
            "--simple_mix",
            "--audition_stems",
            "--stem_cache",
            "--force",
            "-j", "1",
            "--json",
        ])
        process.readyReadStandardOutput.connect(self._instrument_render_output)
        process.readyReadStandardError.connect(self._instrument_render_output)
        process.errorOccurred.connect(self._instrument_render_error)
        process.finished.connect(self._instrument_render_finished)
        self.instrument_audition.set_rendering(True, f"Rendering scratch variant {label}…")
        self.statusBar().showMessage(f"Rendering instrument audition {label}…")
        process.start()

    def _instrument_render_output(self) -> None:
        process = self.render_process
        if process is None:
            return
        chunks = [
            bytes(process.readAllStandardOutput()).decode("utf8", "replace"),
            bytes(process.readAllStandardError()).decode("utf8", "replace"),
        ]
        for chunk in chunks:
            if chunk:
                self._instrument_render_log.extend(line for line in chunk.splitlines() if line.strip())
        if self._instrument_render_log:
            self.instrument_audition.set_rendering(True, self._instrument_render_log[-1][-240:])

    def _instrument_render_error(self, error) -> None:
        process = self.render_process
        if process is None:
            return
        message = process.errorString() or str(error)
        self._instrument_render_log.append(message)
        # FailedToStart does not reliably reach the normal finished path on all
        # Qt versions.  Restore the editor immediately; other process errors are
        # still finalized by ``finished`` with their exit code.
        if process.state() == QProcess.ProcessState.NotRunning:
            self.render_process = None
            self.instrument_audition.set_rendering(False, f"Render process failed: {message}")
            self.statusBar().showMessage(f"Instrument audition could not start: {message}", 7000)

    def _instrument_render_finished(self, exit_code: int, _status) -> None:
        process = self.render_process
        self._instrument_render_output()
        render_dir = self._instrument_render_dir
        group = self._instrument_render_group
        self.render_process = None
        if exit_code != 0 or render_dir is None:
            tail = " | ".join(self._instrument_render_log[-3:]) or f"renderer exited with code {exit_code}"
            self.instrument_audition.set_rendering(False, f"Render failed: {tail}")
            self.statusBar().showMessage("Instrument audition render failed.", 6000)
            return

        versions = discover_versions_from_path(render_dir)
        if not versions:
            self.instrument_audition.set_rendering(False, "Render finished but no Stem Lab manifest was found.")
            return
        self.session.add_versions(versions)
        version = max(versions, key=lambda item: item.generated_at)
        self.session.load(version.key)
        if group and group in self.session.assets_for(version.key):
            self.session.set_route_source(group, version.key)
        self._timeline_docs.pop(version.key, None)
        self._refresh_all_tables()
        self._mark_mix_dirty()
        self._refresh_timeline()
        self.instrument_audition.set_rendering(False, f"Loaded {version.label}; {group or 'edited'} is routed to the new render.")
        self.statusBar().showMessage(f"Instrument audition ready: {version.label}", 6000)

    def _select_route_group(self, group: str) -> None:
        for row in range(self.route_table.rowCount()):
            item = self.route_table.item(row, 1)
            if item and item.text() == group:
                self.route_table.blockSignals(True)
                self.route_table.selectRow(row)
                self.route_table.blockSignals(False)
                return

    def _route_selection_changed(self) -> None:
        rows = self.route_table.selectionModel().selectedRows()
        if not rows:
            return
        item = self.route_table.item(rows[0].row(), 1)
        if item is not None:
            self._refresh_inspector(selected_group=item.text())

    def _inspector_group_changed(self, group: str) -> None:
        self._select_route_group(group)
        self._refresh_inspector(selected_group=group)
        if self.stem_inspector.diff_enabled:
            self._refresh_timeline()

    def _current_stem_diff(self) -> tuple[StemDiffReport, str, str] | None:
        group = self.stem_inspector.current_group()
        main_key, compare_key = self.stem_inspector.current_versions()
        if not group or not main_key or not compare_key:
            return None
        if main_key not in self.session.versions or compare_key not in self.session.versions:
            return None
        main_doc = self._timeline_document(main_key)
        compare_doc = self._timeline_document(compare_key)
        if main_doc is None or compare_doc is None:
            return None
        return (
            compare_stem_timelines(main_doc.timeline, compare_doc.timeline, group),
            main_key,
            compare_key,
        )

    def _refresh_inspector_report(self) -> None:
        current = self._current_stem_diff()
        if current is None:
            was_diff_enabled = self.stem_inspector.diff_enabled
            self.stem_inspector.set_report(
                "The main routed version and comparison version both need note data for semantic comparison.",
                "Load another version or rerender older variants to attach immutable note timelines.",
                can_diff=False,
            )
            if was_diff_enabled:
                self._refresh_timeline()
            return

        report, main_key, compare_key = current
        main_version = self.session.versions[main_key]
        compare_version = self.session.versions[compare_key]
        main_doc = self._timeline_document(main_key)
        compare_doc = self._timeline_document(compare_key)
        main_defs = instrument_definition_lines(main_version, main_doc, report.group)
        compare_defs = instrument_definition_lines(compare_version, compare_doc, report.group)
        main_config = tuple(line for line in main_defs if not line.startswith("["))
        compare_config = tuple(line for line in compare_defs if not line.startswith("["))
        instrument_changed = (
            report.before_instruments != report.after_instruments
            or main_config != compare_config
        )
        summary = (
            f"{report.group}: {len(report.before_notes)} -> {len(report.after_notes)} notes | "
            f"{len(report.unchanged)} unchanged, {len(report.changed)} changed, "
            f"{len(report.removed)} removed, {len(report.added)} added | "
            f"instrument config {'changed' if instrument_changed else 'same'}"
        )
        lines = [
            f"MAIN | {main_version.label}",
            "Expanded instruments: " + (", ".join(report.before_instruments) or "none"),
            *main_defs,
            "",
            f"COMPARE | {compare_version.label}",
            "Expanded instruments: " + (", ".join(report.after_instruments) or "none"),
            *compare_defs,
            "",
            "NOTE CHANGES",
        ]
        changes: list[str] = []
        for row in report.changed[:12]:
            changes.append(f"~ {format_note(row.before)} -> {format_note(row.after)}")
        for note in report.removed[:8]:
            changes.append(f"- {format_note(note)}")
        for note in report.added[:8]:
            changes.append(f"+ {format_note(note)}")
        shown = min(12, len(report.changed)) + min(8, len(report.removed)) + min(8, len(report.added))
        total = len(report.changed) + len(report.removed) + len(report.added)
        if changes:
            lines.extend(changes)
            if total > shown:
                lines.append(f"... {total - shown} more changed events")
        else:
            lines.append("No semantic note changes.")
        lines.extend([
            "",
            "Piano-roll diff: dim = unchanged; dashed = removed; solid bright = added; dash-dot = changed.",
        ])
        self.stem_inspector.set_report(summary, "\n".join(lines), can_diff=True)
        if self.stem_inspector.diff_enabled:
            self._refresh_timeline()

    def _route_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        group = item.data(Qt.UserRole)
        if not group:
            return
        self.session.set_route_enabled(str(group), item.checkState() == Qt.Checked)
        self._mark_mix_dirty()
        self._refresh_timeline()

    def _route_source_changed(self, group: str, combo: QComboBox) -> None:
        key = combo.currentData()
        if not key:
            return
        self.session.set_route_source(group, str(key))
        asset = self.session.assets_for(str(key)).get(group)
        for row in range(self.route_table.rowCount()):
            stem_item = self.route_table.item(row, 1)
            if stem_item and stem_item.text() == group:
                self.route_table.setItem(row, 3, QTableWidgetItem(asset.quality_label if asset else "unavailable"))
                break
        self._mark_mix_dirty()
        self._refresh_inspector(selected_group=group)
        self._refresh_timeline()

    def _refresh_listen_sources(self) -> None:
        old = self.transport.current_source_data()
        choices: list[tuple[str, object]] = [("Routed stem mix", ("mix", None))]
        for key in self.session.loaded_keys:
            version = self.session.versions[key]
            if version.full_mix_path:
                prefix = "Reference" if key == self.session.reference_key else "Full"
                choices.append((f"{prefix} · {version.label}", ("full", key)))
        self.transport.set_source_choices(choices, selected=old)

    def _load_selected(self) -> None:
        rows = sorted({index.row() for index in self.library_table.selectionModel().selectedRows()})
        for row in rows:
            item = self.library_table.item(row, 0)
            key = item.data(Qt.UserRole) if item else None
            if key:
                self.session.load(str(key))
        self._refresh_all_tables()
        self._mark_mix_dirty()
        self._refresh_timeline()

    def _unload_version(self, key: str) -> None:
        if not self.session.unload(key):
            return
        self._refresh_all_tables()
        self._mark_mix_dirty()
        self._refresh_timeline()

    def _reference_changed(self) -> None:
        key = self.reference_combo.currentData()
        self.session.set_reference(str(key) if key else None)
        self._refresh_loaded_table()
        self._refresh_inspector()
        self._refresh_listen_sources()

    def _set_all_route_enabled(self, enabled: bool) -> None:
        self.session.set_all_routes_enabled(enabled)
        self.route_table.blockSignals(True)
        state = Qt.Checked if enabled else Qt.Unchecked
        for row in range(self.route_table.rowCount()):
            item = self.route_table.item(row, 0)
            if item is not None:
                item.setCheckState(state)
        self.route_table.blockSignals(False)
        self._mark_mix_dirty()
        self._refresh_timeline()

    def _route_all(self) -> None:
        key = self.route_all_combo.currentData()
        if not key:
            return
        self.session.route_all(str(key))
        self._refresh_route_table()
        self._refresh_inspector()
        self._mark_mix_dirty()
        self._refresh_timeline()

    def _route_all_reference(self) -> None:
        if not self.session.route_reference():
            self.statusBar().showMessage("No reference is selected for this cue.", 4000)
            return
        self._refresh_route_table()
        self._refresh_inspector()
        self._mark_mix_dirty()
        self._refresh_timeline()

    def _mark_mix_dirty(self, *_args) -> None:
        self.mix_identity_value = None
        if self.current_cue and self.session.loaded_keys:
            self.mix_status.setText("Routing changed; rebuilding playback mix…")
            self.mix_timer.start()

    def _rebuild_mix(self) -> None:
        selections = self.session.selections()
        if not selections:
            self.mix_path = None
            self.mix_status.setText("No enabled routable stems.")
            data = self.transport.current_source_data()
            if data and data[0] == "mix":
                self.transport.stop()
            return
        identity = mix_identity(selections)
        path = self._temp_dir / f"{self.current_cue or 'cue'}-{identity}.wav"
        if identity != self.mix_identity_value or not path.is_file():
            try:
                result = compose_stem_mix(selections, path)
            except Exception as exc:
                self.mix_path = None
                self.mix_status.setText(f"Could not build routed mix: {exc}")
                return
            self.mix_identity_value = identity
            self.mix_path = result.path
            fallback = " · normalized fallback present; do not judge balance" if result.used_normalized_fallback else ""
            guard = f" · peak guard {result.peak_before_guard:.2f}" if result.peak_before_guard > 0.98 else ""
            self.mix_status.setText(f"Routed mix ready · {len(selections)} stems{fallback}{guard}")
        else:
            self.mix_path = path

        data = self.transport.current_source_data()
        if data and data[0] == "mix" and self.transport.has_media:
            self.transport.set_media(self.mix_path, preserve=True)

    def _add_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Add rendered variant folder", str(self.project_root))
        if not selected:
            return
        root = Path(selected).resolve()
        if root not in self.manual_library_roots:
            self.manual_library_roots.append(root)
        versions = discover_versions_from_path(root)
        self.session.add_versions(versions)
        self._refresh_cues(self.current_cue)
        self.statusBar().showMessage(f"Added {len(versions)} render version(s) from {root}", 5000)

    def _rescan(self) -> None:
        discovered = discover_versions(self.project_root)
        for root in self.manual_library_roots:
            discovered.extend(discover_versions_from_path(root))
        unique = {version.key: version for version in discovered}
        self.session.replace_versions(unique.values())
        # A rescan may observe changed live-score fallback content under the same
        # variant key. Reload semantic data rather than showing a stale piano roll.
        self._timeline_docs.clear()
        self._refresh_cues(self.current_cue)
        self.statusBar().showMessage(f"Found {len(self.session.versions)} rendered version(s).", 4000)

    def _listen_source_changed(self) -> None:
        path = self._current_listen_path(build_mix=True)
        if path is not None:
            self.transport.set_media(path, preserve=True)
        self._refresh_timeline()

    def _current_listen_path(self, *, build_mix: bool) -> Path | None:
        data = self.transport.current_source_data()
        if not data:
            return None
        kind, key = data
        if kind == "mix":
            if build_mix and (self.mix_path is None or self.mix_identity_value is None):
                self.mix_timer.stop()
                self._rebuild_mix()
            return self.mix_path
        if kind == "full" and key in self.session.versions:
            return self.session.versions[key].full_mix_path
        return None

    def _toggle_play(self) -> None:
        path = self._current_listen_path(build_mix=True)
        if not self.transport.toggle(path):
            self.statusBar().showMessage("Selected source has no playable audio.", 4000)

    def _player_error(self, error_string: str) -> None:
        self.statusBar().showMessage(f"Playback error: {error_string}", 8000)

    def _seek_from_timeline(self, milliseconds: int) -> None:
        self.transport.seek_to(milliseconds)

    def _timeline_document(self, key: str) -> TimelineDocument | None:
        if key not in self._timeline_docs:
            try:
                self._timeline_docs[key] = load_version_timeline(self.session.versions[key])
            except Exception as exc:
                self._timeline_docs[key] = None
                self.statusBar().showMessage(
                    f"Could not build note timeline for {self.session.versions[key].label}: {exc}", 8000
                )
        return self._timeline_docs[key]

    def _refresh_timeline(self) -> None:
        if self.stem_inspector.diff_enabled:
            current = self._current_stem_diff()
            if current is not None:
                report, main_key, compare_key = current
                self._show_stem_diff_timeline(report, main_key, compare_key)
                self.timeline_panel.set_playhead_ms(self.transport.position)
                return
        data = self.transport.current_source_data()
        if not data:
            self.timeline_panel.clear("Select a playback source to inspect its notes.")
            return
        kind, key = data
        if kind == "full" and key in self.session.versions:
            self._show_full_timeline(str(key))
        elif kind == "mix":
            self._show_routed_timeline()
        else:
            self.timeline_panel.clear("The selected playback source has no note timeline.")
        self.timeline_panel.set_playhead_ms(self.transport.position)

    def _show_stem_diff_timeline(
        self, report: StemDiffReport, main_key: str, compare_key: str
    ) -> None:
        main_version = self.session.versions[main_key]
        compare_version = self.session.versions[compare_key]
        main_doc = self._timeline_document(main_key)
        compare_doc = self._timeline_document(compare_key)
        if main_doc is None or compare_doc is None:
            self.timeline_panel.clear("Both versions need note data to show a stem diff.")
            return

        display: list[DisplayNote] = []
        display.extend(
            DisplayNote(note, compare_version.label, compare_doc.exact_for_render, role="unchanged")
            for note in report.unchanged
        )
        display.extend(
            DisplayNote(
                row.after,
                compare_version.label,
                compare_doc.exact_for_render,
                role="changed",
                annotation=f"was {row.before.note} vel {row.before.velocity} in {main_version.label}",
            )
            for row in report.changed
        )
        display.extend(
            DisplayNote(note, main_version.label, main_doc.exact_for_render, role="removed")
            for note in report.removed
        )
        display.extend(
            DisplayNote(note, compare_version.label, compare_doc.exact_for_render, role="added")
            for note in report.added
        )

        same_grid = _grid_signature(main_doc) == _grid_signature(compare_doc)
        same_sections = _section_signature(main_doc) == _section_signature(compare_doc)
        detail = (
            f"{report.group} | main {main_version.label} vs {compare_version.label} | "
            f"{len(report.unchanged)} unchanged, {len(report.changed)} changed, "
            f"{len(report.removed)} removed, {len(report.added)} added. "
            "Diff view is read-only."
        )
        if not same_grid:
            detail += " Beat grids differ; using absolute time."
        if not same_sections:
            detail += " Section boundaries differ."
        self.timeline_panel.set_timeline(
            display,
            sections=compare_doc.timeline.sections if same_sections else (),
            grid=compare_doc.timeline.grid if same_grid else (),
            duration_seconds=max(
                main_doc.timeline.duration_seconds, compare_doc.timeline.duration_seconds
            ),
            title=f"Diff | {report.group} | main {main_version.label} vs {compare_version.label}",
            detail=detail,
        )

    def _show_full_timeline(self, key: str) -> None:
        version = self.session.versions[key]
        document = self._timeline_document(key)
        if document is None:
            self.timeline_panel.clear(
                f"No note data is available for {version.label}. Rerender the variant to attach an exact note timeline."
            )
            return
        display = [DisplayNote(note, version.label, document.exact_for_render) for note in document.timeline.notes]
        accuracy = "exact for this render" if document.exact_for_render else "live score fallback; source may differ from audio"
        self.timeline_panel.set_timeline(
            display,
            sections=document.timeline.sections,
            grid=document.timeline.grid,
            duration_seconds=document.timeline.duration_seconds,
            title=f"Notes · {version.label}",
            detail=(
                f"{len(display)} notes · {document.provenance_label} · {accuracy}. "
                "Read-only; selecting a note only inspects it."
            ),
        )

    def _show_routed_timeline(self) -> None:
        selections = self.session.selections()
        if not selections:
            self.timeline_panel.clear("Enable at least one routed stem to inspect notes.")
            return
        documents: dict[str, TimelineDocument] = {}
        display: list[DisplayNote] = []
        missing: list[str] = []
        for group, (version, _asset) in selections.items():
            document = self._timeline_document(version.key)
            if document is None:
                missing.append(f"{group} ({version.label})")
                continue
            documents[version.key] = document
            display.extend(
                DisplayNote(note, version.label, document.exact_for_render)
                for note in document.timeline.notes
                if note.group == group
            )
        if not documents:
            self.timeline_panel.clear(
                "None of the routed versions has note data. Rerender a variant to attach an exact note timeline."
            )
            return

        docs = list(documents.values())
        same_grid = len({_grid_signature(document) for document in docs}) == 1
        same_sections = len({_section_signature(document) for document in docs}) == 1
        base = docs[0].timeline
        duration = max(document.timeline.duration_seconds for document in docs)
        exact_count = sum(document.exact_for_render for document in docs)
        detail_parts = [
            f"{len(display)} routed notes from {len(documents)} version(s)",
            f"{exact_count}/{len(documents)} source timeline(s) exact for their render",
        ]
        if missing:
            detail_parts.append("no note data for " + ", ".join(missing))
        if not same_grid:
            detail_parts.append("source beat grids differ; showing absolute time without a beat grid")
        if not same_sections:
            detail_parts.append("source section boundaries differ")
        self.timeline_panel.set_timeline(
            display,
            sections=base.sections if same_sections else (),
            grid=base.grid if same_grid else (),
            duration_seconds=duration,
            title="Notes · routed stem mix",
            detail=" · ".join(detail_parts) + ". Read-only.",
        )


def run_gui(
    *,
    project_root: Path,
    versions: Iterable[StemVersion],
    initial_cue: str | None = None,
) -> int:
    app = QApplication.instance() or QApplication([])
    window = StemLabWindow(project_root, versions, initial_cue=initial_cue)
    window.show()
    install_sigint_quit(app)
    return app.exec()
