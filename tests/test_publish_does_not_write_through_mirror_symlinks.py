"""⛔⛔ A PUBLISH THROUGH A MIRRORED SYMLINK REWRITES THE MAIN CHECKOUT.

`scripts/regen/music.sh` points this publisher at the parent repository's audio
tree, and in a worktree that tree is mirrored FILE BY FILE: each asset is a
symlink at the main checkout's copy, so that regenerating one lands a real file
here and leaves the rest shared.

`shutil.copy2()` opens its destination for writing, and an open-for-write follows
a symlink — so publishing a cue from a worktree wrote the bytes into the MAIN
checkout, left the link in place, and looked entirely successful. The SFX packer
was fixed for this in the parent repo; these three music writes were the
remaining half of the same invariant.

⚠ Behavioural, not textual: each test builds a REAL symlink over a target whose
bytes are then asserted unchanged. A test that only grepped for `copy2` would
pass the moment someone wrote `open(dest, "wb")` instead.
"""

from __future__ import annotations

from pathlib import Path

from ambition_music_renderer.publish_safely import (
    break_mirrored_destination,
    publish_copy,
)

PROTECTED = b"the MAIN checkout's bytes"


def _mirrored(tmp_path: Path) -> tuple[Path, Path, Path]:
    """(src, dest_in_worktree, protected_target_in_main_checkout)."""
    main_checkout = tmp_path / "main"
    main_checkout.mkdir()
    protected = main_checkout / "full.ogg"
    protected.write_bytes(PROTECTED)

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    dest = worktree / "full.ogg"
    dest.symlink_to(protected)

    src = tmp_path / "rendered.ogg"
    src.write_bytes(b"freshly rendered")
    return src, dest, protected


def test_publishing_over_a_mirror_symlink_leaves_the_main_checkout_alone(tmp_path):
    src, dest, protected = _mirrored(tmp_path)

    publish_copy(src, dest)

    assert protected.read_bytes() == PROTECTED, (
        "publishing from a mirrored worktree must not reach through the symlink "
        "and rewrite the checkout every other session builds from"
    )
    assert not dest.is_symlink(), "the destination must become a real local file"
    assert dest.read_bytes() == b"freshly rendered"


def test_a_real_destination_is_overwritten_normally(tmp_path):
    """Non-vacuity: the guard must not turn publishing into a no-op."""
    src = tmp_path / "rendered.ogg"
    src.write_bytes(b"new")
    dest = tmp_path / "full.ogg"
    dest.write_bytes(b"old")

    publish_copy(src, dest)

    assert dest.read_bytes() == b"new"
    assert not dest.is_symlink()


def test_a_missing_destination_publishes_without_complaint(tmp_path):
    src = tmp_path / "rendered.ogg"
    src.write_bytes(b"new")
    dest = tmp_path / "nested" / "full.ogg"
    dest.parent.mkdir()

    publish_copy(src, dest)

    assert dest.read_bytes() == b"new"


def test_a_symlinked_DIRECTORY_raises_rather_than_being_rewritten(tmp_path):
    """A symlinked directory in a mirrored tree is a bug in the mirror. Silently
    unlinking it would take the whole shared folder out of the picture."""
    shared = tmp_path / "shared_dir"
    shared.mkdir()
    link = tmp_path / "cue_dir"
    link.symlink_to(shared, target_is_directory=True)

    try:
        break_mirrored_destination(link)
    except IsADirectoryError:
        pass
    else:
        raise AssertionError("a symlinked directory must not be silently unlinked")
    assert shared.is_dir() and link.is_symlink()
