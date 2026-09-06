from __future__ import annotations

from ambition_music_renderer.music_review_gui import build_parser


def test_gui_launcher_parser_does_not_require_qt():
    args = build_parser().parse_args(["--check", "--cue", "foo"])
    assert args.check is True
    assert args.cue == "foo"
