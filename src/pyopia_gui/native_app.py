# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Nimmo Smith Technologies Limited

import os
import sys

from nicegui import native, ui

from pyopia_gui.main import index  # noqa: F401  registers the "/" page

if sys.platform.startswith("linux"):
    # Confirmed on real hardware: the bundled Qt6 webview backend's GPU compositing
    # can fail against some Linux graphics drivers ("compositor returned null texture",
    # "failed to get native pixmap due to dma_buf acquisition failure"), leaving a blank
    # white window. Forcing software rendering avoids it; must be set before Qt starts.
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")


def run() -> None:
    ui.run(
        title="pyopia-gui",
        native=True,
        window_size=(1100, 800),
        reload=False,
        port=native.find_open_port(),
    )


if __name__ in {"__main__", "__mp_main__"}:
    run()
