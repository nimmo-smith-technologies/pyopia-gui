# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Nimmo Smith Technologies Limited

import pytest
from nicegui.testing import User

from pyopia_gui import docker_client


async def test_index_page_loads(user: User) -> None:
    await user.open("/")
    await user.should_see("pyopia-gui")


async def test_shows_docker_warning_when_docker_unavailable(user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_client, "is_docker_available", lambda: False)

    await user.open("/")

    await user.should_see("Docker was not found")


async def test_shows_create_project_button_when_docker_available(user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_client, "is_docker_available", lambda: True)

    await user.open("/")

    await user.should_see("1. Create example project")
