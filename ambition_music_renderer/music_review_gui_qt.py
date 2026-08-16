"""PySide6 UI for exact-version music audition and review."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .music_reviews import (
    ISSUE_TAGS,
    MAX_SCORE,
    MIN_SCORE,
    POLISH_THRESHOLD,
    RenderVersion,
    ReviewDocument,
    ReviewStore,
    cue_summary,
    discover_render_versions,
    discover_score_sources,
    format_score,
    pairwise_rankings,
    reviews_by_cue,
    score_description,
    score_label,
    subject_key,
    version_key,
)


def _format_time(ms: int) -> str:
    seconds = max(0, int(ms // 1000))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _format_date(timestamp: float) -> str:
    try:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


class ReviewWindow(QMainWindow):
    def __init__(self, project_root: Path, review_root: Path, initial_cue: str | None = None):
        super().__init__()
        self.project_root = project_root
        self.store = ReviewStore(project_root, review_root)
        self.versions: list[RenderVersion] = []
        self.versions_by_cue: dict[str, list[RenderVersion]] = {}
        self.documents_by_cue: dict[str, list[ReviewDocument]] = {}
        self.active_sources = {}
        self._loaded_cue_id: str | None = None
        self.current_version: RenderVersion | None = None
        self.current_review: ReviewDocument | None = None
        self.playback_version: RenderVersion | None = None
        self.current_duration_ms = 0
        self.furthest_played_ms = 0
        self._loading_form = False
        self._dirty = False
        self._seeking = False

        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.8)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio)
        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.playbackStateChanged.connect(self._playback_state_changed)
        self.player.errorOccurred.connect(self._player_error)

        self.setWindowTitle("Ambition Music Review Bank")
        self.resize(1420, 860)
        self._build_ui()
        self._install_shortcuts()
        self.refresh(initial_cue=initial_cue, confirm=False)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)

        toolbar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter cues…")
        self.search.textChanged.connect(self._populate_cue_table)
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All", "Unrated latest", "Needs polish (1–6)", "Strong (7–10)", "Standout (9–10)"])
        self.filter_combo.currentTextChanged.connect(self._populate_cue_table)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(lambda: self.refresh())
        next_unrated = QPushButton("Next unrated")
        next_unrated.clicked.connect(self.select_next_unrated)
        toolbar.addWidget(QLabel("Search"))
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(self.filter_combo)
        toolbar.addWidget(next_unrated)
        toolbar.addWidget(refresh)
        root_layout.addLayout(toolbar)

        split = QSplitter(Qt.Horizontal)
        root_layout.addWidget(split, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        self.cue_table = QTableWidget(0, 7)
        self.cue_table.setHorizontalHeaderLabels(["Latest", "Best", "Pair", "Reviewed", "Cue", "Title", "Verdict"])
        self.cue_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.cue_table.setSelectionMode(QTableWidget.SingleSelection)
        self.cue_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.cue_table.verticalHeader().setVisible(False)
        self.cue_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.cue_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.cue_table.itemSelectionChanged.connect(self._cue_selected)
        left_layout.addWidget(self.cue_table)
        split.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.title_label = QLabel("Select a cue")
        title_font = self.title_label.font()
        title_font.setPointSize(title_font.pointSize() + 5)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        right_layout.addWidget(self.title_label)

        version_row = QHBoxLayout()
        version_row.addWidget(QLabel("Rendered version"))
        self.version_combo = QComboBox()
        self.version_combo.currentIndexChanged.connect(self._version_selected)
        version_row.addWidget(self.version_combo, 1)
        self.version_badge = QLabel("")
        version_row.addWidget(self.version_badge)
        right_layout.addLayout(version_row)

        self.identity_label = QLabel("")
        self.identity_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.identity_label.setWordWrap(True)
        right_layout.addWidget(self.identity_label)

        player_frame = QFrame()
        player_frame.setFrameShape(QFrame.StyledPanel)
        player_layout = QVBoxLayout(player_frame)
        controls = QHBoxLayout()
        self.play_button = QPushButton("▶ Play")
        self.play_button.clicked.connect(self.toggle_play)
        self.restart_button = QPushButton("↺ Restart")
        self.restart_button.clicked.connect(lambda: self.player.setPosition(0))
        self.loop_box = QCheckBox("Loop")
        controls.addWidget(self.play_button)
        controls.addWidget(self.restart_button)
        controls.addWidget(self.loop_box)
        self.playback_label = QLabel("Playback: current")
        controls.addWidget(self.playback_label)
        controls.addStretch(1)
        controls.addWidget(QLabel("Volume"))
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.setMaximumWidth(160)
        self.volume_slider.valueChanged.connect(lambda value: self.audio.setVolume(value / 100.0))
        controls.addWidget(self.volume_slider)
        player_layout.addLayout(controls)
        seek_row = QHBoxLayout()
        self.time_label = QLabel("0:00 / 0:00")
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setRange(0, 1000)
        self.seek.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.seek.sliderReleased.connect(self._seek_released)
        seek_row.addWidget(self.time_label)
        seek_row.addWidget(self.seek, 1)
        player_layout.addLayout(seek_row)
        self.listen_progress = QProgressBar()
        self.listen_progress.setRange(0, 100)
        self.listen_progress.setFormat("Furthest played position: %p%")
        player_layout.addWidget(self.listen_progress)
        right_layout.addWidget(player_frame)

        rating_frame = QFrame()
        rating_frame.setFrameShape(QFrame.StyledPanel)
        rating_layout = QVBoxLayout(rating_frame)
        rating_layout.addWidget(QLabel("Overall quality — 1.0 to 10.0; decimals allowed"))
        score_row = QHBoxLayout()
        self.score_value = QDoubleSpinBox()
        self.score_value.setRange(0.0, MAX_SCORE)
        self.score_value.setDecimals(2)
        self.score_value.setSingleStep(0.1)
        self.score_value.setSpecialValueText("Unrated")
        self.score_value.setSuffix(" / 10")
        self.score_value.setMaximumWidth(150)
        self.score_value.valueChanged.connect(self._score_changed)
        self.rating_band_label = QLabel("Unrated")
        score_row.addWidget(self.score_value)
        score_row.addWidget(self.rating_band_label)
        score_row.addStretch(1)
        rating_layout.addLayout(score_row)

        issue_row = QHBoxLayout()
        issue_row.addWidget(QLabel("Needs work in:"))
        self.issue_boxes: dict[str, QCheckBox] = {}
        for issue in ISSUE_TAGS:
            box = QCheckBox(issue)
            box.toggled.connect(self._mark_dirty)
            self.issue_boxes[issue] = box
            issue_row.addWidget(box)
        issue_row.addStretch(1)
        rating_layout.addLayout(issue_row)

        self.notes = QTextEdit()
        self.notes.setPlaceholderText("What works? What should a future pass preserve or change?")
        self.notes.textChanged.connect(self._mark_dirty)
        rating_layout.addWidget(self.notes, 1)

        save_row = QHBoxLayout()
        self.save_button = QPushButton("Save / update exact-version rating")
        self.save_button.clicked.connect(self.save_review)
        self.saved_label = QLabel("")
        save_row.addWidget(self.save_button)
        save_row.addWidget(self.saved_label)
        save_row.addStretch(1)
        rating_layout.addLayout(save_row)
        right_layout.addWidget(rating_frame, 1)

        pair_frame = QFrame()
        pair_frame.setFrameShape(QFrame.StyledPanel)
        pair_layout = QVBoxLayout(pair_frame)
        pair_layout.addWidget(QLabel("Pairwise comparison — exact rendered versions"))
        pair_select = QHBoxLayout()
        pair_select.addWidget(QLabel("Compare against"))
        self.compare_combo = QComboBox()
        self.compare_combo.currentIndexChanged.connect(self._comparison_selected)
        pair_select.addWidget(self.compare_combo, 1)
        self.compare_play_button = QPushButton("▶ Play comparison")
        self.compare_play_button.clicked.connect(self.play_comparison)
        pair_select.addWidget(self.compare_play_button)
        pair_layout.addLayout(pair_select)
        pair_buttons = QHBoxLayout()
        self.current_better_button = QPushButton("Current is better")
        self.current_better_button.clicked.connect(lambda: self._save_pairwise("first"))
        self.pair_tie_button = QPushButton("About equal")
        self.pair_tie_button.clicked.connect(lambda: self._save_pairwise("tie"))
        self.other_better_button = QPushButton("Comparison is better")
        self.other_better_button.clicked.connect(lambda: self._save_pairwise("second"))
        pair_buttons.addWidget(self.current_better_button)
        pair_buttons.addWidget(self.pair_tie_button)
        pair_buttons.addWidget(self.other_better_button)
        pair_buttons.addStretch(1)
        pair_layout.addLayout(pair_buttons)
        self.pair_status_label = QLabel("No comparison selected")
        self.pair_status_label.setWordWrap(True)
        pair_layout.addWidget(self.pair_status_label)
        right_layout.addWidget(pair_frame)

        right_layout.addWidget(QLabel("Version history for this cue"))
        self.history_table = QTableWidget(0, 6)
        self.history_table.setHorizontalHeaderLabels(["Score", "Version", "Reviewed", "Issues", "Available", "Notes"])
        self.history_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.history_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.history_table.cellDoubleClicked.connect(self._history_double_clicked)
        right_layout.addWidget(self.history_table, 1)
        split.addWidget(right)
        split.setSizes([520, 900])

        self.statusBar().showMessage("Ratings and pairwise judgments are keyed by renderer hash + preview SHA-256.")

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self.toggle_play)
        QShortcut(QKeySequence.Save, self, activated=self.save_review)
        QShortcut(QKeySequence("N"), self, activated=self.select_next_unrated)

    def refresh(self, initial_cue: str | None = None, *, confirm: bool = True) -> None:
        if confirm and self._dirty and not self._confirm_discard():
            return
        current_cue = initial_cue or self.selected_cue_id()
        self.versions = discover_render_versions(self.project_root)
        grouped: dict[str, list[RenderVersion]] = defaultdict(list)
        for version in self.versions:
            grouped[version.cue_id].append(version)
        for cue_versions in grouped.values():
            cue_versions.sort(key=lambda version: (not version.is_latest, -version.generated_at))
        self.versions_by_cue = dict(grouped)
        self.documents_by_cue = reviews_by_cue(self.store.load_all())
        self.active_sources = {cue: source for cue, source in discover_score_sources(self.project_root).items() if source.scope == "active"}
        self._populate_cue_table(select_cue=current_cue)

    def selected_cue_id(self) -> str | None:
        rows = self.cue_table.selectionModel().selectedRows() if self.cue_table.selectionModel() else []
        if not rows:
            return None
        item = self.cue_table.item(rows[0].row(), 4)
        return item.data(Qt.UserRole) if item else None

    def _summary_rows(self) -> list[dict[str, Any]]:
        return cue_summary(self.versions, self.store.load_all(), self.active_sources, self.store.load_comparisons())

    def _populate_cue_table(self, *_args: Any, select_cue: str | None = None) -> None:
        wanted = (self.search.text() if hasattr(self, "search") else "").strip().lower()
        filter_name = self.filter_combo.currentText() if hasattr(self, "filter_combo") else "All"
        rows = self._summary_rows()
        if filter_name == "Unrated latest":
            rows = [row for row in rows if row["latest_score"] is None]
        elif filter_name == "Needs polish (1–6)":
            rows = [row for row in rows if row["latest_score"] is not None and row["latest_score"] <= POLISH_THRESHOLD]
        elif filter_name == "Strong (7–10)":
            rows = [row for row in rows if row["latest_score"] is not None and row["latest_score"] >= 7]
        elif filter_name == "Standout (9–10)":
            rows = [row for row in rows if row["latest_score"] is not None and row["latest_score"] >= 9]
        if wanted:
            rows = [row for row in rows if wanted in row["cue_id"].lower() or wanted in row["title"].lower()]
        # Weak/latest-unrated tracks float upward so this doubles as a polish queue.
        rows.sort(key=lambda row: (row["latest_score"] is not None, row["latest_score"] or 0, row["cue_id"]))
        self.cue_table.blockSignals(True)
        self.cue_table.setRowCount(len(rows))
        selected_row = None
        for row_idx, row in enumerate(rows):
            pair_text = "—"
            if row["latest_pairwise_rank"] is not None:
                pair_text = f"#{row['latest_pairwise_rank']} · {row['latest_pairwise_wins']}-{row['latest_pairwise_losses']}-{row['latest_pairwise_ties']}"
            values = [
                format_score(row["latest_score"]),
                format_score(row["best_score"]),
                pair_text,
                str(row["reviewed_versions"]),
                row["cue_id"],
                row["title"],
                row["latest_label"],
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 4:
                    item.setData(Qt.UserRole, row["cue_id"])
                self.cue_table.setItem(row_idx, col, item)
            if select_cue and row["cue_id"] == select_cue:
                selected_row = row_idx
        self.cue_table.blockSignals(False)
        if selected_row is not None:
            self.cue_table.selectRow(selected_row)
        elif rows and not self.cue_table.selectionModel().hasSelection():
            self.cue_table.selectRow(0)

    def _confirm_discard(self) -> bool:
        if not self._dirty:
            return True
        result = QMessageBox.question(self, "Unsaved review", "Discard unsaved review changes?", QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel)
        return result == QMessageBox.Discard

    def _restore_cue_selection(self, cue_id: str) -> None:
        self.cue_table.blockSignals(True)
        try:
            for row in range(self.cue_table.rowCount()):
                item = self.cue_table.item(row, 4)
                if item and item.data(Qt.UserRole) == cue_id:
                    self.cue_table.selectRow(row)
                    break
        finally:
            self.cue_table.blockSignals(False)

    def _cue_selected(self) -> None:
        cue_id = self.selected_cue_id()
        if not cue_id:
            return
        if self._dirty and self._loaded_cue_id and cue_id != self._loaded_cue_id:
            if not self._confirm_discard():
                self._restore_cue_selection(self._loaded_cue_id)
                return
        self._loaded_cue_id = cue_id
        versions = self.versions_by_cue.get(cue_id, [])
        self.version_combo.blockSignals(True)
        self.version_combo.clear()
        for version in versions:
            doc = self.store.load_for_version(version)
            score_text = f" · score {format_score(doc.current.score)}" if doc and doc.current else ""
            latest = "latest · " if version.is_latest else ""
            self.version_combo.addItem(f"{latest}{version.display_hash} · {_format_date(version.generated_at)}{score_text}", version)
        self.version_combo.blockSignals(False)
        title = versions[0].title if versions else (self.active_sources[cue_id].title if cue_id in self.active_sources else cue_id)
        self.title_label.setText(f"{title}\n{cue_id}")
        self._populate_history(cue_id)
        if versions:
            self.version_combo.setCurrentIndex(0)
            self._load_version(versions[0])
        else:
            self._clear_version()
            self.identity_label.setText("No playable generated preview is available locally for this active score.")

    def _version_selected(self, index: int) -> None:
        if index < 0:
            return
        version = self.version_combo.itemData(index)
        if isinstance(version, RenderVersion):
            if not self._confirm_discard():
                if self.current_version is not None:
                    self.version_combo.blockSignals(True)
                    for old_index in range(self.version_combo.count()):
                        old_version = self.version_combo.itemData(old_index)
                        if isinstance(old_version, RenderVersion) and old_version.version_id == self.current_version.version_id:
                            self.version_combo.setCurrentIndex(old_index)
                            break
                    self.version_combo.blockSignals(False)
                return
            self._load_version(version)

    def _load_version(self, version: RenderVersion) -> None:
        self.player.stop()
        self.current_version = version
        self.furthest_played_ms = 0
        self.current_duration_ms = 0
        self._ensure_player_source(version, stop=True)
        self.current_review = self.store.load_for_version(version)
        self.version_badge.setText("LATEST" if version.is_latest else "historical render")
        identity = [f"render {version.render_hash}", f"audio sha256 {version.preview_sha256[:20]}…"]
        if version.backend:
            identity.append(f"backend {version.backend}")
        if version.renderer_version:
            identity.append(version.renderer_version)
        if version.source_score:
            try:
                newer = version.source_score.path.stat().st_mtime > version.preview_path.stat().st_mtime
            except OSError:
                newer = False
            identity.append(f"score {version.source_score.scope}/{version.source_score.path.name}" + (" (source newer than render)" if newer else ""))
        self.identity_label.setText("  ·  ".join(identity))
        self._loading_form = True
        self.score_value.setValue(0.0)
        self.rating_band_label.setText("Unrated")
        for box in self.issue_boxes.values():
            box.setChecked(False)
        self.notes.clear()
        if self.current_review and self.current_review.current:
            current = self.current_review.current
            self.score_value.setValue(current.score)
            self.rating_band_label.setText(f"{current.label} — {score_description(current.score)}")
            for issue in current.issues:
                if issue in self.issue_boxes:
                    self.issue_boxes[issue].setChecked(True)
            self.notes.setPlainText(current.notes)
            self.furthest_played_ms = int(current.furthest_played_seconds * 1000)
            self.saved_label.setText(f"Saved {current.reviewed_at}")
        else:
            # An unrated selection must start genuinely blank rather than
            # inheriting score/notes/tags from the previously selected track.
            self.furthest_played_ms = 0
            self.saved_label.setText("Unrated exact version")
        self._loading_form = False
        self._dirty = False
        self._populate_comparison_choices()
        self._update_listen_progress()

    def _clear_version(self) -> None:
        self.current_version = None
        self.current_review = None
        self.player.stop()
        self.identity_label.clear()
        self.version_badge.clear()
        self._loading_form = True
        self.score_value.setValue(0.0)
        self.rating_band_label.setText("Unrated")
        self.notes.clear()
        for box in self.issue_boxes.values():
            box.setChecked(False)
        self._loading_form = False
        self.compare_combo.clear()
        self.pair_status_label.setText("No comparison selected")

    def _populate_history(self, cue_id: str) -> None:
        docs = self.documents_by_cue.get(cue_id, [])
        self.history_table.setRowCount(len(docs))
        for row, doc in enumerate(docs):
            current = doc.current
            version_available = any(version.version_id == doc.version_id for version in self.versions_by_cue.get(cue_id, []))
            values = [
                format_score(current.score) if current else "—",
                doc.version_id,
                current.reviewed_at if current else "",
                ", ".join(current.issues) if current else "",
                "yes" if version_available else "no",
                (current.notes.replace("\n", " ")[:180] if current else ""),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, doc.version_id)
                self.history_table.setItem(row, col, item)

    def _history_double_clicked(self, row: int, _column: int) -> None:
        item = self.history_table.item(row, 1)
        if not item:
            return
        version_id = item.text()
        for idx in range(self.version_combo.count()):
            version = self.version_combo.itemData(idx)
            if isinstance(version, RenderVersion) and version.version_id == version_id:
                self.version_combo.setCurrentIndex(idx)
                return
        self.statusBar().showMessage("That reviewed version's audio is no longer available locally.", 5000)

    def _ensure_player_source(self, version: RenderVersion, *, stop: bool = False) -> None:
        if stop:
            self.player.stop()
        if self.playback_version is None or self.playback_version.version_id != version.version_id:
            self.player.stop()
            self.player.setSource(QUrl.fromLocalFile(str(version.preview_path)))
            self.playback_version = version
            role = "current" if self.current_version and version.version_id == self.current_version.version_id else "comparison"
            self.playback_label.setText(f"Playback: {role} · {version.cue_id}")

    def _comparison_version(self) -> RenderVersion | None:
        version = self.compare_combo.currentData() if self.compare_combo.count() else None
        return version if isinstance(version, RenderVersion) else None

    def _populate_comparison_choices(self) -> None:
        current = self.current_version
        self.compare_combo.blockSignals(True)
        self.compare_combo.clear()
        if current is not None:
            candidates = [version for version in self.versions if version_key(version) != version_key(current)]
            candidates.sort(
                key=lambda version: (
                    version.cue_id != current.cue_id,
                    not version.is_latest,
                    version.title.lower(),
                    -version.generated_at,
                )
            )
            for version in candidates:
                doc = self.store.load_for_version(version)
                rating = f" · {format_score(doc.current.score)}/10" if doc and doc.current else " · unrated"
                marker = "latest" if version.is_latest else "historical"
                self.compare_combo.addItem(
                    f"{version.title} · {marker} · {version.display_hash}{rating}",
                    version,
                )
        self.compare_combo.blockSignals(False)
        self._comparison_selected(self.compare_combo.currentIndex())

    def _comparison_selected(self, _index: int) -> None:
        current = self.current_version
        other = self._comparison_version()
        enabled = current is not None and other is not None
        for button in (self.current_better_button, self.pair_tie_button, self.other_better_button, self.compare_play_button):
            button.setEnabled(enabled)
        if not enabled:
            self.pair_status_label.setText("No comparison selected")
            return
        self.current_better_button.setText(f"{current.cue_id} is better")
        self.other_better_button.setText(f"{other.cue_id} is better")
        doc = self.store.load_comparison(current, other)
        if doc is None:
            self.pair_status_label.setText("Uncompared exact-version pair")
        else:
            current_key = version_key(current)
            if doc.outcome == "tie":
                verdict = "about equal"
            else:
                winner_key = subject_key(doc.first if doc.outcome == "first" else doc.second)
                verdict = "current better" if winner_key == current_key else "comparison better"
            self.pair_status_label.setText(f"Saved: {verdict} · {doc.updated_at}")
        self._refresh_pairwise_rank_status()

    def _refresh_pairwise_rank_status(self) -> None:
        if self.current_version is None:
            return
        row = next(
            (item for item in pairwise_rankings(self.store.load_comparisons()) if item["subject_key"] == version_key(self.current_version)),
            None,
        )
        if row is not None:
            base = self.pair_status_label.text()
            self.pair_status_label.setText(
                f"{base}  ·  current pairwise rank #{row['rank']} · "
                f"{row['wins']}-{row['losses']}-{row['ties']} · {row['pairwise_score'] * 100:.1f}% points"
            )

    def _save_pairwise(self, outcome: str) -> None:
        current = self.current_version
        other = self._comparison_version()
        if current is None or other is None:
            return
        doc = self.store.save_comparison(current, other, outcome=outcome)
        self._comparison_selected(self.compare_combo.currentIndex())
        self._populate_cue_table(select_cue=current.cue_id)
        self.statusBar().showMessage(
            f"Saved pairwise judgment in place: {doc.path.relative_to(self.project_root)}",
            5000,
        )

    def play_comparison(self) -> None:
        other = self._comparison_version()
        if other is None:
            return
        if self.playback_version is None or self.playback_version.version_id != other.version_id:
            self._ensure_player_source(other, stop=True)
            self.player.play()
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            if self.player.duration() > 0 and self.player.position() >= self.player.duration() - 20:
                self.player.setPosition(0)
            self.player.play()

    def toggle_play(self) -> None:
        if self.current_version is None:
            return
        if self.playback_version is None or self.playback_version.version_id != self.current_version.version_id:
            self._ensure_player_source(self.current_version, stop=True)
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            if self.player.duration() > 0 and self.player.position() >= self.player.duration() - 20:
                self.player.setPosition(0)
            self.player.play()

    def _playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        current_playing = (
            state == QMediaPlayer.PlayingState
            and self.playback_version is not None
            and self.current_version is not None
            and self.playback_version.version_id == self.current_version.version_id
        )
        other = self._comparison_version()
        comparison_playing = (
            state == QMediaPlayer.PlayingState
            and self.playback_version is not None
            and other is not None
            and self.playback_version.version_id == other.version_id
        )
        self.play_button.setText("⏸ Pause current" if current_playing else "▶ Play current")
        self.compare_play_button.setText("⏸ Pause comparison" if comparison_playing else "▶ Play comparison")

    def _player_error(self, _error: QMediaPlayer.Error, message: str) -> None:
        if message:
            self.statusBar().showMessage(f"Audio playback error: {message}", 8000)

    def _position_changed(self, position: int) -> None:
        if (
            self.player.playbackState() == QMediaPlayer.PlayingState
            and self.current_version is not None
            and self.playback_version is not None
            and self.playback_version.version_id == self.current_version.version_id
        ):
            self.furthest_played_ms = max(self.furthest_played_ms, position)
        duration = self.player.duration()
        if not self._seeking and duration > 0:
            self.seek.setValue(round(position / duration * 1000))
        self.time_label.setText(f"{_format_time(position)} / {_format_time(duration)}")
        self._update_listen_progress()
        if self.loop_box.isChecked() and duration > 0 and position >= duration - 30:
            self.player.setPosition(0)
            self.player.play()

    def _duration_changed(self, duration: int) -> None:
        if (
            self.current_version is not None
            and self.playback_version is not None
            and self.playback_version.version_id == self.current_version.version_id
        ):
            self.current_duration_ms = max(0, int(duration))
        self._update_listen_progress()

    def _seek_released(self) -> None:
        self._seeking = False
        duration = self.player.duration()
        if duration > 0:
            self.player.setPosition(round(self.seek.value() / 1000 * duration))

    def _update_listen_progress(self) -> None:
        duration = self.current_duration_ms
        fraction = min(1.0, self.furthest_played_ms / duration) if duration > 0 else 0.0
        self.listen_progress.setValue(round(fraction * 100))

    def _score_changed(self, value: float) -> None:
        if value < MIN_SCORE:
            self.rating_band_label.setText("Unrated")
        else:
            self.rating_band_label.setText(f"{score_label(value)} — {score_description(value)}")
        self._mark_dirty()

    def _mark_dirty(self, *_args: Any) -> None:
        if not self._loading_form:
            self._dirty = True
            self.saved_label.setText("Unsaved changes")

    def save_review(self) -> None:
        version = self.current_version
        if version is None:
            return
        score = float(self.score_value.value())
        if score < MIN_SCORE or score > MAX_SCORE:
            QMessageBox.information(self, "Choose a score", "Choose an overall score from 1.0 to 10.0 before saving.")
            return
        issues = [name for name, box in self.issue_boxes.items() if box.isChecked()]
        duration = self.current_duration_ms
        if duration > 0:
            fraction = self.furthest_played_ms / duration
        elif self.current_review and self.current_review.current:
            fraction = self.current_review.current.furthest_played_fraction
        else:
            fraction = 0.0
        doc = self.store.save(
            version,
            score=score,
            notes=self.notes.toPlainText(),
            issues=issues,
            furthest_played_seconds=self.furthest_played_ms / 1000.0,
            furthest_played_fraction=fraction,
        )
        self.current_review = doc
        self._dirty = False
        self.saved_label.setText(f"Saved {doc.current.reviewed_at if doc.current else ''}")
        cue_id = version.cue_id
        self.documents_by_cue = reviews_by_cue(self.store.load_all())
        self._populate_history(cue_id)
        self._populate_cue_table(select_cue=cue_id)
        self.statusBar().showMessage(f"Saved exact-version rating in place: {doc.path.relative_to(self.project_root)}", 6000)

    def select_next_unrated(self) -> None:
        rows = self._summary_rows()
        unrated = [row for row in rows if row["latest_score"] is None and row["cue_id"] in self.versions_by_cue]
        if not unrated:
            self.statusBar().showMessage("No unrated latest renders remain.", 4000)
            return
        current = self.selected_cue_id()
        ids = [row["cue_id"] for row in sorted(unrated, key=lambda row: row["cue_id"])]
        target = ids[0]
        if current in ids and len(ids) > 1:
            target = ids[(ids.index(current) + 1) % len(ids)]
        self.search.clear()
        self.filter_combo.setCurrentText("All")
        self._populate_cue_table(select_cue=target)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()


def run_gui(*, project_root: Path, review_root: Path, initial_cue: str | None = None) -> int:
    app = QApplication.instance() or QApplication([])
    window = ReviewWindow(project_root, review_root, initial_cue=initial_cue)
    window.show()
    return int(app.exec())


__all__ = ["ReviewWindow", "run_gui"]
