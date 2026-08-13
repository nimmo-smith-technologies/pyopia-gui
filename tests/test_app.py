# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Nimmo Smith Technologies Limited

from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User

from pyopia_gui import docker_client


async def test_index_page_loads(user: User) -> None:
    await user.open("/")
    await user.should_see("pyopia-gui")


async def test_shows_docker_warning_when_docker_not_installed(user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.NOT_INSTALLED)

    await user.open("/")

    await user.should_see("Docker isn't ready yet")
    await user.should_see("Recheck")


async def test_shows_docker_warning_when_docker_not_running(user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.NOT_RUNNING)

    await user.open("/")

    await user.should_see("Docker isn't ready yet")


async def test_shows_create_project_button_when_docker_available(user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)

    await user.open("/")

    await user.should_see("1. Create example project")


async def test_shows_ready_status_when_docker_available(user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)

    await user.open("/")

    await user.should_see("Ready")


async def test_shows_editable_project_folder_input(user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)

    await user.open("/")

    await user.should_see("Project folder")
    folder_input = user.find(ui.input).elements.pop()
    assert Path(folder_input.value) == Path.home() / "pyopia-gui-projects" / "demo"


async def test_shows_browse_button(user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)

    await user.open("/")

    await user.should_see("Browse")


async def test_create_warns_if_folder_already_exists(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)

    user.find(kind=ui.button, content="1. Create example project").click()

    await user.should_see("already exists")
