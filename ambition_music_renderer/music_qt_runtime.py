"""Small shared runtime helpers for the music Qt applications."""

from __future__ import annotations

import signal
from typing import Any

from PySide6.QtCore import QTimer


def install_sigint_quit(app: Any, *, interval_ms: int = 100) -> QTimer:
    """Make terminal Ctrl+C close Qt windows and run their close handlers.

    Qt's native event loop can otherwise keep Python from dispatching SIGINT
    until some unrelated callback returns to the interpreter.  A lightweight
    timer gives Python a regular scheduling point, while the signal handler
    closes top-level windows so their normal cleanup (media/QProcess teardown)
    still runs.
    """

    timer = QTimer(app)
    timer.setInterval(max(25, int(interval_ms)))
    timer.timeout.connect(lambda: None)
    timer.start()

    previous = signal.getsignal(signal.SIGINT)

    def _sigint(_signum, _frame) -> None:
        for widget in list(app.topLevelWidgets()):
            widget.close()
        app.quit()

    signal.signal(signal.SIGINT, _sigint)

    # Keep both the timer and previous handler alive for the lifetime of app.
    # The previous handler is restored when the application exits, which is
    # useful for embedded/test processes that create another QApplication.
    setattr(app, "_ambition_sigint_timer", timer)
    setattr(app, "_ambition_previous_sigint_handler", previous)
    app.aboutToQuit.connect(lambda: signal.signal(signal.SIGINT, previous))
    return timer
