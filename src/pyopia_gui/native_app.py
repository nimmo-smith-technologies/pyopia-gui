# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Nimmo Smith Technologies Limited

from nicegui import native, ui

from pyopia_gui.main import index  # noqa: F401  registers the "/" page


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
