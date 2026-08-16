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
    QButtonGroup,
    QCheckBox,
    QComboBox,
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
    QRadioButton,
    QSlider,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .music_reviews import ISSUE_TAGS, RUBRIC, RenderVersion, ReviewDocument, ReviewStore, cue_summary, discover_render_versions, discover_score_sources, reviews_by_cue


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
        self.filter_combo.addItems(["All", "Unrated latest", "Needs polish (1–3)", "Strong (4–5)", "Standout (5)"])
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
        self.cue_table = QTableWidget(0, 6)
        self.cue_table.setHorizontalHeaderLabels(["Latest", "Best", "Reviewed", "Cue", "Title", "Verdict"])
        self.cue_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.cue_table.setSelectionMode(QTableWidget.SingleSelection)
        self.cue_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.cue_table.verticalHeader().setVisible(False)
        self.cue_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.cue_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
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
        rating_layout.addWidget(QLabel("Overall quality — keys 1–5 set score"))
        score_row = QHBoxLayout()
        self.score_group = QButtonGroup(self)
        self.score_buttons: dict[int, QRadioButton] = {}
        for score, (label, description) in RUBRIC.items():
            button = QRadioButton(f"{score} · {label}")
            button.setToolTip(description)
            self.score_group.addButton(button, score)
            self.score_buttons[score] = button
            score_row.addWidget(button)
            button.toggled.connect(self._mark_dirty)
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
        self.save_button = QPushButton("Save exact-version review")
        self.save_button.clicked.connect(self.save_review)
        self.saved_label = QLabel("")
        save_row.addWidget(self.save_button)
        save_row.addWidget(self.saved_label)
        save_row.addStretch(1)
        rating_layout.addLayout(save_row)
        right_layout.addWidget(rating_frame, 1)

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

        self.statusBar().showMessage("Reviews are keyed by renderer hash + preview SHA-256.")

    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self.toggle_play)
        QShortcut(QKeySequence.Save, self, activated=self.save_review)
        QShortcut(QKeySequence("N"), self, activated=self.select_next_unrated)
        for score in RUBRIC:
            QShortcut(QKeySequence(str(score)), self, activated=lambda value=score: self._set_score(value))

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
        item = self.cue_table.item(rows[0].row(), 3)
        return item.data(Qt.UserRole) if item else None

    def _summary_rows(self) -> list[dict[str, Any]]:
        return cue_summary(self.versions, self.store.load_all(), self.active_sources)

    def _populate_cue_table(self, *_args: Any, select_cue: str | None = None) -> None:
        wanted = (self.search.text() if hasattr(self, "search") else "").strip().lower()
        filter_name = self.filter_combo.currentText() if hasattr(self, "filter_combo") else "All"
        rows = self._summary_rows()
        if filter_name == "Unrated latest":
            rows = [row for row in rows if row["latest_score"] is None]
        elif filter_name == "Needs polish (1–3)":
            rows = [row for row in rows if row["latest_score"] is not None and row["latest_score"] <= 3]
        elif filter_name == "Strong (4–5)":
            rows = [row for row in rows if row["latest_score"] is not None and row["latest_score"] >= 4]
        elif filter_name == "Standout (5)":
            rows = [row for row in rows if row["latest_score"] == 5]
        if wanted:
            rows = [row for row in rows if wanted in row["cue_id"].lower() or wanted in row["title"].lower()]
        # Weak/latest-unrated tracks float upward so this doubles as a polish queue.
        rows.sort(key=lambda row: (row["latest_score"] is not None, row["latest_score"] or 0, row["cue_id"]))
        self.cue_table.blockSignals(True)
        self.cue_table.setRowCount(len(rows))
        selected_row = None
        for row_idx, row in enumerate(rows):
            values = [
                "—" if row["latest_score"] is None else str(row["latest_score"]),
                "—" if row["best_score"] is None else str(row["best_score"]),
                str(row["reviewed_versions"]),
                row["cue_id"],
                row["title"],
                row["latest_label"],
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 3:
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
                item = self.cue_table.item(row, 3)
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
            score_text = f" · score {doc.current.score}" if doc and doc.current else ""
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
        self.player.setSource(QUrl.fromLocalFile(str(version.preview_path)))
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
        for button in self.score_buttons.values():
            button.setAutoExclusive(False)
            button.setChecked(False)
            button.setAutoExclusive(True)
        for box in self.issue_boxes.values():
            box.setChecked(False)
        self.notes.clear()
        if self.current_review and self.current_review.current:
            current = self.current_review.current
            self.score_buttons[current.score].setChecked(True)
            for issue in current.issues:
                if issue in self.issue_boxes:
                    self.issue_boxes[issue].setChecked(True)
            self.notes.setPlainText(current.notes)
            self.furthest_played_ms = int(current.furthest_played_seconds * 1000)
            self.saved_label.setText(f"Saved {current.reviewed_at}")
        else:
            self.saved_label.setText("Unrated exact version")
        self._loading_form = False
        self._dirty = False
        self._update_listen_progress()

    def _clear_version(self) -> None:
        self.current_version = None
        self.current_review = None
        self.player.stop()
        self.identity_label.clear()
        self.version_badge.clear()

    def _populate_history(self, cue_id: str) -> None:
        docs = self.documents_by_cue.get(cue_id, [])
        self.history_table.setRowCount(len(docs))
        for row, doc in enumerate(docs):
            current = doc.current
            version_available = any(version.version_id == doc.version_id for version in self.versions_by_cue.get(cue_id, []))
            values = [
                str(current.score) if current else "—",
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

    def toggle_play(self) -> None:
        if self.current_version is None:
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            if self.player.duration() > 0 and self.player.position() >= self.player.duration() - 20:
                self.player.setPosition(0)
            self.player.play()

    def _playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        self.play_button.setText("⏸ Pause" if state == QMediaPlayer.PlayingState else "▶ Play")

    def _player_error(self, _error: QMediaPlayer.Error, message: str) -> None:
        if message:
            self.statusBar().showMessage(f"Audio playback error: {message}", 8000)

    def _position_changed(self, position: int) -> None:
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.furthest_played_ms = max(self.furthest_played_ms, position)
        duration = self.player.duration()
        if not self._seeking and duration > 0:
            self.seek.setValue(round(position / duration * 1000))
        self.time_label.setText(f"{_format_time(position)} / {_format_time(duration)}")
        self._update_listen_progress()
        if self.loop_box.isChecked() and duration > 0 and position >= duration - 30:
            self.player.setPosition(0)
            self.player.play()

    def _duration_changed(self, _duration: int) -> None:
        self._update_listen_progress()

    def _seek_released(self) -> None:
        self._seeking = False
        duration = self.player.duration()
        if duration > 0:
            self.player.setPosition(round(self.seek.value() / 1000 * duration))

    def _update_listen_progress(self) -> None:
        duration = self.player.duration()
        fraction = min(1.0, self.furthest_played_ms / duration) if duration > 0 else 0.0
        self.listen_progress.setValue(round(fraction * 100))

    def _set_score(self, score: int) -> None:
        if score in self.score_buttons:
            self.score_buttons[score].setChecked(True)
            self._dirty = True

    def _mark_dirty(self, *_args: Any) -> None:
        if not self._loading_form:
            self._dirty = True
            self.saved_label.setText("Unsaved changes")

    def save_review(self) -> None:
        version = self.current_version
        if version is None:
            return
        score = self.score_group.checkedId()
        if score not in RUBRIC:
            QMessageBox.information(self, "Choose a score", "Choose an overall score from 1 to 5 before saving.")
            return
        issues = [name for name, box in self.issue_boxes.items() if box.isChecked()]
        duration = self.player.duration()
        fraction = self.furthest_played_ms / duration if duration > 0 else 0.0
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
        self.statusBar().showMessage(f"Saved exact-version review: {doc.path.relative_to(self.project_root)}", 6000)

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
