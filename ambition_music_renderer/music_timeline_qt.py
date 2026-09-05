"""Qt read-only piano-roll visualization for music note timelines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QBrush, QFontMetricsF, QPainter, QPen, QTransform
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .music_timeline import TimelineGridLine, TimelineNote, TimelineSection
from .music_track_palette import group_hsl, group_palette_hsl


_X_PIXELS_PER_SECOND = 90.0
_PITCH_HEIGHT = 12.0
_SECTION_RULER_HEIGHT = 22
_BAR_RULER_HEIGHT = 20
_RULER_HEIGHT = _SECTION_RULER_HEIGHT + _BAR_RULER_HEIGHT
_NOTE_HEIGHT = 9.0


@dataclass(frozen=True)
class PianoRollViewportState:
    x_zoom: float
    center_seconds: float
    center_pitch: float


@dataclass(frozen=True)
class DisplayNote:
    note: TimelineNote
    version_label: str
    exact_for_render: bool
    role: str = "normal"
    annotation: str = ""


def color_for_group(group: str) -> QColor:
    """Return the shared semantic color for one stem/track group."""
    return QColor.fromHsl(*group_hsl(group))


def _pitch_label(pitch: int) -> str:
    names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    return f"{names[pitch % 12]}{pitch // 12 - 1}"


def _styled_note_colors(base: QColor, role: str) -> tuple[QColor, QPen]:
    """Return fill/outline styling while preserving the stem's semantic hue."""
    fill = QColor(base)
    outline = QColor(base.darker(135))
    pen = QPen(outline)
    pen.setCosmetic(True)

    if role == "unchanged":
        fill.setAlpha(70)
        pen.setColor(QColor(base.darker(115)))
    elif role == "removed":
        fill.setAlpha(25)
        pen.setWidth(2)
        pen.setStyle(Qt.DashLine)
        pen.setColor(QColor(205, 85, 75))
    elif role == "added":
        fill.setAlpha(235)
        pen.setWidth(2)
        pen.setColor(QColor(70, 175, 105))
    elif role == "changed":
        fill.setAlpha(220)
        pen.setWidth(2)
        pen.setStyle(Qt.DashDotLine)
        pen.setColor(QColor(215, 155, 55))
    return fill, pen


class _NoteItem(QGraphicsRectItem):
    def __init__(self, display: DisplayNote, rect, color: QColor) -> None:
        super().__init__(rect)
        self.display = display
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        fill, pen = _styled_note_colors(color, display.role)
        self.setBrush(QBrush(fill))
        self.setPen(pen)
        exact = "exact render" if display.exact_for_render else "live-score fallback"
        note = display.note
        role = "" if display.role == "normal" else f"\ndiff: {display.role}"
        annotation = f"\n{display.annotation}" if display.annotation else ""
        self.setToolTip(
            f"{note.group} | {display.version_label}\n"
            f"{note.instrument} | {note.note} | velocity {note.velocity}\n"
            f"{note.start_seconds:.3f}s -> {note.end_seconds:.3f}s\n"
            f"section {note.section or '-'} | layer {note.layer or '-'}\n"
            f"{exact}{role}{annotation}"
        )


class PianoRollView(QGraphicsView):
    seekRequested = Signal(int)
    noteSelected = Signal(str)
    viewportMappingChanged = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setMinimumHeight(260)
        self.setMouseTracking(True)
        self._playhead: QGraphicsLineItem | None = None
        self._duration = 0.0
        self._min_pitch = 36
        self._max_pitch = 84
        self._x_zoom = 1.0
        self._group_colors: dict[str, QColor] = {}
        self._scene.selectionChanged.connect(self._selection_changed)
        self.horizontalScrollBar().valueChanged.connect(
            lambda _value: self.viewportMappingChanged.emit()
        )
        self.horizontalScrollBar().rangeChanged.connect(
            lambda _minimum, _maximum: self.viewportMappingChanged.emit()
        )

    def set_group_palette(self, groups: Iterable[str]) -> None:
        self._group_colors = {
            group: QColor.fromHsl(*hsl)
            for group, hsl in group_palette_hsl(groups).items()
        }

    def group_color(self, group: str) -> QColor:
        return self._group_colors.get(group, color_for_group(group))

    def clear_timeline(self, message: str = "No note timeline available.") -> None:
        self._scene.clear()
        self._playhead = None
        self._duration = 0.0
        text = self._scene.addSimpleText(message)
        text.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        text.setPos(12, 12)
        self._scene.setSceneRect(0, 0, 900, 260)
        self.resetTransform()
        self._x_zoom = 1.0
        self.viewportMappingChanged.emit()

    def capture_view_state(self) -> PianoRollViewportState | None:
        if self._duration <= 0.0 or self._scene.sceneRect().isEmpty():
            return None
        center = self.mapToScene(self.viewport().rect().center())
        center_pitch = self._max_pitch - (float(center.y()) / _PITCH_HEIGHT)
        return PianoRollViewportState(
            x_zoom=float(self._x_zoom),
            center_seconds=max(0.0, float(center.x()) / _X_PIXELS_PER_SECOND),
            center_pitch=center_pitch,
        )

    def restore_view_state(self, state: PianoRollViewportState) -> None:
        self._x_zoom = max(0.03, min(8.0, float(state.x_zoom)))
        self._apply_zoom()
        center_x = max(0.0, min(self._duration, state.center_seconds)) * _X_PIXELS_PER_SECOND
        center_pitch = max(float(self._min_pitch), min(float(self._max_pitch), state.center_pitch))
        center_y = (self._max_pitch - center_pitch) * _PITCH_HEIGHT
        center_y = max(self._scene.sceneRect().top(), min(self._scene.sceneRect().bottom(), center_y))
        self.centerOn(center_x, center_y)
        self.viewportMappingChanged.emit()

    def set_timeline(
        self,
        notes: Iterable[DisplayNote],
        *,
        sections: Iterable[TimelineSection] = (),
        grid: Iterable[TimelineGridLine] = (),
        duration_seconds: float = 0.0,
        preserve_view: bool = True,
    ) -> None:
        prior_view = self.capture_view_state() if preserve_view else None
        rows = list(notes)
        sections = list(sections)
        grid = list(grid)
        self._scene.clear()
        self._playhead = None
        pitches = [row.note.pitch for row in rows]
        self._min_pitch = max(0, min(pitches) - 2) if pitches else 36
        self._max_pitch = min(127, max(pitches) + 2) if pitches else 84
        self._duration = max(
            [float(duration_seconds)]
            + [row.note.end_seconds for row in rows]
            + [section.end_seconds for section in sections]
            + [1.0]
        )
        pitch_span = max(1, self._max_pitch - self._min_pitch + 1)
        bottom = pitch_span * _PITCH_HEIGHT
        width = max(600.0, self._duration * _X_PIXELS_PER_SECOND)

        for index, section in enumerate(sections):
            x = section.start_seconds * _X_PIXELS_PER_SECOND
            w = max(1.0, (section.end_seconds - section.start_seconds) * _X_PIXELS_PER_SECOND)
            shade = self.palette().alternateBase().color()
            shade.setAlpha(45 if index % 2 else 25)
            rect = self._scene.addRect(x, 0, w, bottom, QPen(Qt.NoPen), QBrush(shade))
            rect.setZValue(-20)

        for pitch in range(self._min_pitch, self._max_pitch + 1):
            if pitch % 12 != 0:
                continue
            y = (self._max_pitch - pitch) * _PITCH_HEIGHT
            pen = QPen(self.palette().mid().color())
            pen.setCosmetic(True)
            line = self._scene.addLine(0, y, width, y, pen)
            line.setZValue(-10)

        for marker in grid:
            x = marker.time_seconds * _X_PIXELS_PER_SECOND
            color = self.palette().mid().color() if marker.major else self.palette().midlight().color()
            pen = QPen(color)
            pen.setCosmetic(True)
            pen.setWidth(2 if marker.major else 1)
            line = self._scene.addLine(x, 0, x, bottom, pen)
            line.setZValue(-9)

        for display in rows:
            note = display.note
            x = note.start_seconds * _X_PIXELS_PER_SECOND
            w = max(2.0, (note.end_seconds - note.start_seconds) * _X_PIXELS_PER_SECOND)
            y = (self._max_pitch - note.pitch) * _PITCH_HEIGHT + 1.5
            item = _NoteItem(display, QRectF(x, y, w, _NOTE_HEIGHT), self.group_color(note.group))
            item.setZValue(1)
            self._scene.addItem(item)

        play_pen = QPen(self.palette().highlight().color())
        play_pen.setWidth(2)
        play_pen.setCosmetic(True)
        self._playhead = self._scene.addLine(0, 0, 0, bottom, play_pen)
        self._playhead.setZValue(20)

        self._scene.setSceneRect(0, 0, width, bottom + 4)
        if prior_view is None:
            self.fit_horizontal()
        else:
            self.restore_view_state(prior_view)

    def fit_horizontal(self) -> None:
        rect = self._scene.sceneRect()
        available = max(1, self.viewport().width() - 4)
        self._x_zoom = available / max(rect.width(), 1.0)
        self._apply_zoom()
        self.horizontalScrollBar().setValue(0)
        self.viewportMappingChanged.emit()

    def zoom_in(self) -> None:
        self._x_zoom = min(8.0, self._x_zoom * 1.5)
        self._apply_zoom()

    def zoom_out(self) -> None:
        self._x_zoom = max(0.03, self._x_zoom / 1.5)
        self._apply_zoom()

    def _apply_zoom(self) -> None:
        self.setTransform(QTransform.fromScale(self._x_zoom, 1.0))
        self.viewportMappingChanged.emit()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.viewportMappingChanged.emit()

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:  # type: ignore[override]
        """Draw only the fixed-size pitch gutter inside the note viewport."""
        super().drawForeground(painter, rect)
        painter.save()
        painter.resetTransform()
        metrics = QFontMetricsF(painter.font())
        pitch_bg = self.palette().base().color()
        pitch_bg.setAlpha(215)
        painter.setPen(self.palette().text().color())
        for pitch in range(self._min_pitch, self._max_pitch + 1):
            if pitch % 12 != 0:
                continue
            scene_y = (self._max_pitch - pitch) * _PITCH_HEIGHT
            y = float(self.mapFromScene(0, scene_y).y())
            label = _pitch_label(pitch)
            label_width = metrics.horizontalAdvance(label)
            label_rect = QRectF(2.0, y + 1.0, label_width + 7.0, metrics.height() + 2.0)
            painter.fillRect(label_rect, pitch_bg)
            painter.drawText(label_rect.adjusted(3.0, 0.0, -2.0, 0.0), Qt.AlignVCenter, label)
        painter.restore()

    def set_playhead_ms(self, milliseconds: int) -> None:
        if self._playhead is None:
            return
        x = max(0.0, milliseconds / 1000.0) * _X_PIXELS_PER_SECOND
        line = self._playhead.line()
        self._playhead.setLine(x, line.y1(), x, line.y2())

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        item = self.itemAt(event.position().toPoint())
        if event.button() == Qt.LeftButton and not isinstance(item, _NoteItem):
            scene_pos = self.mapToScene(event.position().toPoint())
            seconds = max(0.0, min(self._duration, scene_pos.x() / _X_PIXELS_PER_SECOND))
            self.seekRequested.emit(int(round(seconds * 1000.0)))
            event.accept()
            return
        super().mousePressEvent(event)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if event.modifiers() & Qt.ControlModifier:
            self.zoom_in() if event.angleDelta().y() > 0 else self.zoom_out()
            event.accept()
            return
        super().wheelEvent(event)

    def _selection_changed(self) -> None:
        selected = [item for item in self._scene.selectedItems() if isinstance(item, _NoteItem)]
        if not selected:
            self.noteSelected.emit("")
            return
        display = selected[-1].display
        note = display.note
        exact = "exact render data" if display.exact_for_render else "live source fallback"
        role = "" if display.role == "normal" else f" | diff {display.role}"
        annotation = f" | {display.annotation}" if display.annotation else ""
        self.noteSelected.emit(
            f"{note.group} | {display.version_label} | {note.instrument} | {note.note} | "
            f"{note.start_seconds:.3f}-{note.end_seconds:.3f}s | "
            f"{note.section or 'no section'} / {note.layer or 'no layer'} | {exact}{role}{annotation}"
        )


class TimelineRuler(QWidget):
    """A real sibling ruler synchronized to a PianoRollView's horizontal mapping."""

    def __init__(self, view: PianoRollView, parent=None) -> None:
        super().__init__(parent)
        self.view = view
        self._sections: tuple[TimelineSection, ...] = ()
        self._grid: tuple[TimelineGridLine, ...] = ()
        self.setFixedHeight(_RULER_HEIGHT)
        self.view.viewportMappingChanged.connect(self.update)

    def clear(self) -> None:
        self._sections = ()
        self._grid = ()
        self.update()

    def set_timeline(
        self,
        *,
        sections: Iterable[TimelineSection],
        grid: Iterable[TimelineGridLine],
    ) -> None:
        self._sections = tuple(sections)
        self._grid = tuple(grid)
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        width = self.width()
        header = self.palette().base().color()
        painter.fillRect(self.rect(), header)
        divider = QPen(self.palette().mid().color())
        painter.setPen(divider)
        painter.drawLine(0, _SECTION_RULER_HEIGHT, width, _SECTION_RULER_HEIGHT)
        painter.drawLine(0, _RULER_HEIGHT - 1, width, _RULER_HEIGHT - 1)

        metrics = QFontMetricsF(painter.font())
        painter.setPen(self.palette().text().color())
        for section in self._sections:
            x1 = self.view.mapFromScene(section.start_seconds * _X_PIXELS_PER_SECOND, 0).x()
            x2 = self.view.mapFromScene(section.end_seconds * _X_PIXELS_PER_SECOND, 0).x()
            left = max(0.0, float(x1) + 5.0)
            right = min(float(width), float(x2) - 5.0)
            available = right - left
            if available < 18.0:
                continue
            label = metrics.elidedText(section.label, Qt.ElideRight, int(available))
            if label:
                painter.drawText(
                    QRectF(left, 2.0, available, _SECTION_RULER_HEIGHT - 4.0),
                    Qt.AlignVCenter,
                    label,
                )

        last_right = -1.0e9
        for marker in self._grid:
            if not marker.major:
                continue
            x = float(self.view.mapFromScene(marker.time_seconds * _X_PIXELS_PER_SECOND, 0).x())
            if x < -40.0 or x > width + 40.0:
                continue
            label = str(marker.bar)
            label_width = metrics.horizontalAdvance(label)
            left = x + 3.0
            if left < last_right + 8.0:
                continue
            painter.drawText(
                QRectF(left, _SECTION_RULER_HEIGHT + 1.0, label_width + 4.0, _BAR_RULER_HEIGHT - 2.0),
                Qt.AlignVCenter,
                label,
            )
            last_right = left + label_width


class NoteTimelinePanel(QWidget):
    seekRequested = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        header = QHBoxLayout()
        self.title = QLabel("Notes")
        header.addWidget(self.title)
        header.addStretch(1)
        self.fit_button = QPushButton("Fit")
        self.fit_button.setToolTip("Fit the complete cue horizontally")
        header.addWidget(self.fit_button)
        self.zoom_out_button = QPushButton("-")
        self.zoom_out_button.setToolTip("Zoom out horizontally (Ctrl+wheel also works)")
        header.addWidget(self.zoom_out_button)
        self.zoom_in_button = QPushButton("+")
        self.zoom_in_button.setToolTip("Zoom in horizontally (Ctrl+wheel also works)")
        header.addWidget(self.zoom_in_button)
        outer.addLayout(header)

        self.view = PianoRollView()
        self.ruler = TimelineRuler(self.view)
        outer.addWidget(self.ruler)
        self.view.seekRequested.connect(self.seekRequested.emit)
        outer.addWidget(self.view, 1)

        self._preserve_next_view = True
        self.details = QLabel("Read-only piano roll. Click empty space to seek; click a note to inspect it.")
        self.details.setWordWrap(True)
        outer.addWidget(self.details)
        self.view.noteSelected.connect(self._note_selected)
        self.fit_button.clicked.connect(self.view.fit_horizontal)
        self.zoom_out_button.clicked.connect(self.view.zoom_out)
        self.zoom_in_button.clicked.connect(self.view.zoom_in)

    def set_group_palette(self, groups: Iterable[str]) -> None:
        self.view.set_group_palette(groups)

    def _note_selected(self, text: str) -> None:
        self.details.setText(text or "Read-only piano roll. Click empty space to seek; click a note to inspect it.")

    def reset_view_on_next_timeline(self) -> None:
        self._preserve_next_view = False

    def clear(self, message: str) -> None:
        self.title.setText("Notes | unavailable")
        self.ruler.clear()
        self.view.clear_timeline(message)
        self.details.setText(message)

    def set_timeline(
        self,
        notes: Iterable[DisplayNote],
        *,
        sections: Iterable[TimelineSection],
        grid: Iterable[TimelineGridLine],
        duration_seconds: float,
        title: str,
        detail: str,
    ) -> None:
        sections = tuple(sections)
        grid = tuple(grid)
        self.title.setText(title)
        preserve_view = self._preserve_next_view
        self._preserve_next_view = True
        self.view.set_timeline(
            notes,
            sections=sections,
            grid=grid,
            duration_seconds=duration_seconds,
            preserve_view=preserve_view,
        )
        self.ruler.set_timeline(sections=sections, grid=grid)
        self.details.setText(detail)

    def set_playhead_ms(self, milliseconds: int) -> None:
        self.view.set_playhead_ms(milliseconds)
