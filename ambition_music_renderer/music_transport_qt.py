"""Reusable Qt transport for music authoring/review frontends."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStyle,
    QVBoxLayout,
    QWidget,
)


class SeekSlider(QSlider):
    """Playback slider with click-to-seek and continuous scrubbing."""

    jumpRequested = Signal(int)
    scrubStarted = Signal()
    scrubFinished = Signal()

    def __init__(self, orientation, parent=None) -> None:
        super().__init__(orientation, parent)
        self._mouse_scrubbing = False

    def _jump_from_x(self, x: float) -> None:
        if self.width() <= 0:
            return
        ratio = max(0.0, min(1.0, x / self.width()))
        value = self.minimum() + round(ratio * (self.maximum() - self.minimum()))
        self.setValue(value)
        self.jumpRequested.emit(value)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            self._mouse_scrubbing = True
            self.scrubStarted.emit()
            self._jump_from_x(event.position().x())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._mouse_scrubbing and event.buttons() & Qt.LeftButton:
            self._jump_from_x(event.position().x())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if self._mouse_scrubbing and event.button() == Qt.LeftButton:
            self._jump_from_x(event.position().x())
            self._mouse_scrubbing = False
            self.scrubFinished.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


def format_time(ms: int) -> str:
    seconds = max(0, int(ms)) // 1000
    return f"{seconds // 60}:{seconds % 60:02d}"


class MusicTransport(QWidget):
    """Canonical media transport with a source chooser and shared playhead.

    Playback intent is tracked separately from QMediaPlayer's transient state.
    Replacing a local file briefly puts QMediaPlayer into StoppedState while it
    loads the new source; that transition should not turn a user-requested
    source switch into a pause or make the play button lie about intent.
    """

    sourceSelectionChanged = Signal()
    playRequested = Signal()
    positionChanged = Signal(int)
    playbackError = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pending_seek_ms: int | None = None
        self._pending_resume = False
        self._desired_playing = False
        self._seeking = False
        # Some clients (notably Instrument Inspector) can prepare media in
        # response to Play.  Keep that capability explicit so ordinary media
        # transports such as Stem Lab still require an already loaded source.
        self._play_request_available = False

        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.8)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio)
        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.playbackStateChanged.connect(self._playback_state_changed)
        self.player.mediaStatusChanged.connect(self._media_status_changed)
        self.player.errorOccurred.connect(self._player_error)

        self._build_ui()
        self._update_play_button()
        self._update_enabled_state()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(6)

        seek_row = QHBoxLayout()
        self.current_time = QLabel("0:00")
        self.current_time.setMinimumWidth(42)
        seek_row.addWidget(self.current_time)
        self.seek = SeekSlider(Qt.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.scrubStarted.connect(self._scrub_started)
        self.seek.scrubFinished.connect(self._scrub_finished)
        self.seek.jumpRequested.connect(self.seek_to)
        seek_row.addWidget(self.seek, 1)
        self.total_time = QLabel("0:00")
        self.total_time.setMinimumWidth(42)
        self.total_time.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        seek_row.addWidget(self.total_time)
        outer.addLayout(seek_row)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Listen"))
        self.source_combo = QComboBox()
        self.source_combo.currentIndexChanged.connect(
            lambda _index: self.sourceSelectionChanged.emit()
        )
        controls.addWidget(self.source_combo, 1)

        controls.addStretch(1)
        self.to_start_button = QPushButton()
        self.to_start_button.setIcon(self.style().standardIcon(QStyle.SP_MediaSkipBackward))
        self.to_start_button.setToolTip("Go to start")
        self.to_start_button.setAccessibleName("Go to start")
        self.to_start_button.clicked.connect(lambda _checked=False: self.seek_to(0))
        controls.addWidget(self.to_start_button)

        self.play_button = QPushButton()
        self.play_button.setToolTip("Play / pause (Space)")
        self.play_button.setAccessibleName("Play or pause")
        self.play_button.setMinimumSize(42, 34)
        self.play_button.clicked.connect(lambda _checked=False: self.playRequested.emit())
        controls.addWidget(self.play_button)

        self.stop_button = QPushButton()
        self.stop_button.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        self.stop_button.setToolTip("Stop")
        self.stop_button.setAccessibleName("Stop")
        self.stop_button.setMinimumSize(42, 34)
        self.stop_button.clicked.connect(lambda _checked=False: self.stop())
        controls.addWidget(self.stop_button)
        controls.addStretch(1)

        controls.addWidget(QLabel("Volume"))
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(80)
        self.volume.setMaximumWidth(150)
        self.volume.valueChanged.connect(lambda value: self.audio.setVolume(value / 100.0))
        controls.addWidget(self.volume)
        outer.addLayout(controls)

        self._space_shortcut = QShortcut(QKeySequence(Qt.Key_Space), self)
        self._space_shortcut.activated.connect(lambda: self.playRequested.emit())

    @property
    def position(self) -> int:
        return int(self.player.position())

    @property
    def duration(self) -> int:
        return int(self.player.duration())

    @property
    def is_playing(self) -> bool:
        return self.player.playbackState() == QMediaPlayer.PlayingState

    @property
    def wants_playback(self) -> bool:
        """Whether the user expects audio to be playing, including source loads."""
        return self._desired_playing

    @property
    def has_media(self) -> bool:
        return self.player.source().isValid()

    def current_source_data(self):
        return self.source_combo.currentData()

    def set_play_request_available(self, enabled: bool) -> None:
        """Allow Play to request client-side media preparation.

        This does not fabricate media or change playback state.  It only keeps
        the Play control actionable when the owning UI knows how to render or
        otherwise prepare the current selection on demand.
        """
        self._play_request_available = bool(enabled)
        self._update_enabled_state()

    def set_source_choices(self, choices: Iterable[tuple[str, object]], *, selected=None) -> None:
        old = self.source_combo.currentData() if selected is None else selected
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        for label, data in choices:
            self.source_combo.addItem(label, data)
        index = next(
            (i for i in range(self.source_combo.count()) if self.source_combo.itemData(i) == old),
            0,
        )
        if self.source_combo.count():
            self.source_combo.setCurrentIndex(index)
        self.source_combo.blockSignals(False)
        if not self.source_combo.count():
            self.clear_media()
        else:
            self._update_enabled_state()

    def clear_media(self) -> None:
        """Forget rendered audio so stale media cannot be played accidentally."""
        self._desired_playing = False
        self._pending_resume = False
        self._pending_seek_ms = None
        self.player.stop()
        self.player.setSource(QUrl())
        self.seek.setRange(0, 0)
        self.seek.setValue(0)
        self.current_time.setText("0:00")
        self.total_time.setText("0:00")
        self._update_play_button()
        self._update_enabled_state()

    def clear_sources(self) -> None:
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        self.source_combo.blockSignals(False)
        self.clear_media()

    def set_media(self, path: Path, *, preserve: bool = True, resume: bool | None = None) -> None:
        path = Path(path)
        if not path.is_file():
            return
        old_position = self.player.position() if preserve else 0
        should_resume = self.wants_playback if resume is None else bool(resume)
        self._desired_playing = should_resume

        if self.player.source().toLocalFile() == str(path):
            if preserve:
                self.player.setPosition(old_position)
            if should_resume:
                self.player.play()
            elif self.is_playing:
                self.player.pause()
            self._update_play_button()
            return

        self._pending_seek_ms = int(old_position)
        self._pending_resume = should_resume
        self._update_play_button()
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self._update_enabled_state()

    def toggle(self, path: Path | None) -> bool:
        if self.wants_playback:
            self._desired_playing = False
            self._pending_resume = False
            self.player.pause()
            self._update_play_button()
            return True
        if path is None or not Path(path).is_file():
            return False
        self._desired_playing = True
        self._update_play_button()
        if self.player.source().toLocalFile() != str(path):
            self.set_media(Path(path), preserve=True, resume=True)
        else:
            self.player.play()
        return True

    def stop(self) -> None:
        self._desired_playing = False
        self._pending_resume = False
        self._pending_seek_ms = None
        self.player.stop()
        self.player.setPosition(0)
        self._update_play_button()

    def seek_to(self, value: int) -> None:
        value = max(0, int(value))
        self._pending_seek_ms = None
        self.player.setPosition(value)
        self.current_time.setText(format_time(value))

    def close_transport(self) -> None:
        self.stop()

    def _scrub_started(self) -> None:
        self._seeking = True

    def _scrub_finished(self) -> None:
        self._seeking = False
        self.seek_to(self.seek.value())

    def _position_changed(self, position: int) -> None:
        if not self._seeking:
            self.seek.setValue(position)
        self.current_time.setText(format_time(position))
        self.positionChanged.emit(int(position))

    def _duration_changed(self, duration: int) -> None:
        self.seek.setRange(0, max(0, int(duration)))
        self.total_time.setText(format_time(duration))
        if duration > 0:
            self._apply_pending_media_state()

    def _playback_state_changed(self, state) -> None:
        if state == QMediaPlayer.PlayingState:
            self._desired_playing = True
        self._update_play_button()

    def _update_play_button(self) -> None:
        icon = QStyle.SP_MediaPause if self._desired_playing else QStyle.SP_MediaPlay
        self.play_button.setIcon(self.style().standardIcon(icon))
        self._update_enabled_state()

    def _update_enabled_state(self) -> None:
        has_choice = self.source_combo.count() > 0 and self.source_combo.currentData() is not None
        has_media = self.has_media
        self.source_combo.setEnabled(self.source_combo.count() > 0)
        self.play_button.setEnabled(self._play_request_available or (has_choice and has_media))
        self.to_start_button.setEnabled(has_media)
        self.stop_button.setEnabled(has_media)
        self.seek.setEnabled(has_media)

    def _media_status_changed(self, status) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._desired_playing = False
            self._pending_resume = False
            self._update_play_button()
            return
        if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
            self._apply_pending_media_state()

    def _apply_pending_media_state(self) -> None:
        ready = self.player.mediaStatus() in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        )
        if not ready:
            return
        duration = int(self.player.duration())
        if self._pending_seek_ms is not None:
            if duration <= 0:
                return
            self.player.setPosition(min(self._pending_seek_ms, duration))
            self._pending_seek_ms = None
        if self._pending_resume:
            self._pending_resume = False
            self.player.play()
        self._update_play_button()

    def _player_error(self, _error, error_string: str) -> None:
        self._desired_playing = False
        self._pending_resume = False
        self._update_play_button()
        if error_string:
            self.playbackError.emit(error_string)
