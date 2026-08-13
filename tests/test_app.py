# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Nimmo Smith Technologies Limited

import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User

from pyopia_gui import __version__, docker_client


async def test_index_page_loads(user: User) -> None:
    await user.open("/")
    await user.should_see("pyopia-gui")


async def test_header_shows_pyopia_gui_version(user: User) -> None:
    await user.open("/")
    await user.should_see(f"v{__version__}")


async def test_shows_docker_warning_when_docker_not_installed(user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.NOT_INSTALLED)

    await user.open("/")

    await user.should_see("Docker isn't ready yet")
    await user.should_see("Recheck")


async def test_shows_docker_warning_when_docker_not_running(user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.NOT_RUNNING)

    await user.open("/")

    await user.should_see("Docker isn't ready yet")


async def test_shows_download_button_when_docker_not_installed_on_windows(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.NOT_INSTALLED)
    monkeypatch.setattr(docker_client.platform, "system", lambda: "Windows")

    await user.open("/")

    await user.should_see("Open Docker download page")


async def test_no_download_button_when_docker_not_installed_on_linux(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.NOT_INSTALLED)
    monkeypatch.setattr(docker_client.platform, "system", lambda: "Linux")

    await user.open("/")

    await user.should_not_see("Open Docker download page")


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


async def test_create_shows_confirmation_dialog_with_resolved_path(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    target = tmp_path / "new-project"

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(target)

    user.find(kind=ui.button, content="1. Create example project").click()

    await user.should_see("Create a new PyOPIA project here?")
    await user.should_see(str(target.resolve()))


async def test_create_cancelled_does_not_run_docker(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    target = tmp_path / "new-project"
    calls: list[list[str]] = []

    async def fake_run_streamed(command: list[str], on_line: Callable[[str], None]) -> int:
        calls.append(command)
        return 0

    monkeypatch.setattr(docker_client, "run_streamed", fake_run_streamed)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(target)

    user.find(kind=ui.button, content="1. Create example project").click()
    await user.should_see("Create a new PyOPIA project here?")

    user.find(kind=ui.button, content="Cancel").click()
    await asyncio.sleep(0.2)  # let on_create()'s coroutine resume past `await dialog` and return

    assert calls == []
    assert not target.exists()


async def test_create_confirmed_runs_docker(user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    target = tmp_path / "new-project"

    async def fake_run_streamed(command: list[str], on_line: Callable[[str], None]) -> int:
        return 0

    monkeypatch.setattr(docker_client, "run_streamed", fake_run_streamed)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(target)

    user.find(kind=ui.button, content="1. Create example project").click()
    await user.should_see("Create a new PyOPIA project here?")

    user.find(kind=ui.button, content="Create here").click()

    await user.should_see("Example project created")


async def test_run_shows_friendly_message_in_log_on_image_pull_failure(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    (tmp_path / "config.toml").write_text('[steps.output]\noutput_datafile = "processed/demo"\n')

    async def fake_run_streamed(command: list[str], on_line: Callable[[str], None]) -> int:
        on_line("Unable to find image 'ghcr.io/sintef/pyopia:latest' locally")
        on_line("docker: Error response from daemon: error from registry: denied")
        on_line("denied")
        return 125

    monkeypatch.setattr(docker_client, "run_streamed", fake_run_streamed)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)

    user.find(kind=ui.button, content="2. Run processing").click()

    await user.should_see("Couldn't pull the PyOPIA image")


async def test_run_shows_pyopia_version_after_successful_processing(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    (tmp_path / "config.toml").write_text('[steps.output]\noutput_datafile = "processed/demo"\n')

    async def fake_run_streamed(command: list[str], on_line: Callable[[str], None]) -> int:
        if "process" in command:
            on_line("PYOPIA VERSION 2.16.23")
            on_line("LOAD CONFIG")
        return 0

    monkeypatch.setattr(docker_client, "run_streamed", fake_run_streamed)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)

    user.find(kind=ui.button, content="2. Run processing").click()

    await user.should_see("Processed with PyOPIA v2.16.23")
