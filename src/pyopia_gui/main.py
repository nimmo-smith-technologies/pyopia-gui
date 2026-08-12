# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Nimmo Smith Technologies Limited

from nicegui import ui


@ui.page("/")
def index() -> None:
    ui.label("pyopia-gui")


def run() -> None:
    ui.run(title="pyopia-gui", reload=False)


if __name__ in {"__main__", "__mp_main__"}:
    run()
