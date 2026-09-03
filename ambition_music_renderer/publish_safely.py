"""Publish a rendered file into a tree that may be MIRRORED BY SYMLINK.

`scripts/mirror_assets_for_worktree.py` in the parent repository gives a worktree
its generated assets by symlinking them, file by file, at the main checkout's
copies. Its whole design rests on one sentence:

    mirror the files individually and a regenerated asset lands as a REAL file in
    the worktree, replacing that one symlink, while every other asset still
    points at the shared copy.

⛔⛔ **THAT IS ONLY TRUE IF THE WRITER UNLINKS FIRST.** `shutil.copy2()`,
`open(dst, "wb")`, `Path.write_bytes()` — every one of them OPENS THE
DESTINATION FOR WRITING, and an open-for-write FOLLOWS a symlink. The bytes land
in the MAIN CHECKOUT that every other session builds and gates from, the link
stays in place, and nothing looks wrong afterwards.

⚠ This module is a deliberate DUPLICATE of the parent repository's
`scripts/lib/publish_safely.py`. This is a submodule: it cannot import from the
parent, and it must not grow a dependency on being checked out inside one. The
invariant is small enough to carry twice and too silent to leave uncarried —
`scripts/regen/music.sh` points this publisher at the mirrored audio tree, so
these are exactly the writes that reach through.

⚠ **Not `os.O_NOFOLLOW`, and not a race guard.** The writer and the link are
both ours; this stops an ACCIDENT, not an attacker. "Unlink the link, then write
normally" is the honest shape.

⚠ **Directories are never unlinked**, only file symlinks: a symlinked directory
in a mirrored tree is a bug in the mirror, not something a publisher should
silently rewrite.
"""

from __future__ import annotations

import shutil
from pathlib import Path

__all__ = ["break_mirrored_destination", "publish_copy"]


def break_mirrored_destination(dest: Path) -> bool:
    """Unlink `dest` when it is a symlink, so a following write lands locally.

    Returns True when a link was broken, so callers can say so. A missing
    destination, or a real file, is left exactly as it is — this is not a
    "remove the destination" helper.
    """
    if not dest.is_symlink():
        return False
    if dest.is_dir():
        raise IsADirectoryError(
            f"{dest} is a SYMLINKED DIRECTORY in a mirrored tree. Publishing "
            "through it would rewrite the shared checkout wholesale; that is a "
            "bug in the mirror, not something to unlink here."
        )
    dest.unlink()
    return True


def publish_copy(src: Path, dest: Path) -> bool:
    """`shutil.copy2` that cannot write through a mirrored symlink.

    The one road every publish in this package takes, so the invariant is stated
    once rather than at each call site — forgetting it is silent.
    """
    broke = break_mirrored_destination(dest)
    shutil.copy2(src, dest)
    return broke
