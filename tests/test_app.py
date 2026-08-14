# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Nimmo Smith Technologies Limited

import asyncio
from collections.abc import Callable
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User
from nicegui.testing.user_interaction import UserInteraction

from pyopia_gui import __version__, docker_client, version_check


async def _click_through_pinned_version_dialog_if_shown(user: User) -> None:
    """Confirm the "This will run PyOPIA vX.Y.Z" dialog if it appeared.

    Closed dialogs stay in the DOM (just hidden), so a previous run's own confirm
    button can still match a marker/content lookup done after a second run starts a
    new one - scope explicitly to the currently *open* dialog to avoid clicking a
    stale button from an earlier run instead of the current one.
    """
    await asyncio.sleep(0.2)
    open_dialogs = [dialog for dialog in user.find(ui.dialog).elements if dialog.value]
    if not open_dialogs:
        return
    buttons = {
        button
        for button in user.find(kind=ui.button, marker="confirm-pinned-version").elements
        if any(button in dialog.descendants() for dialog in open_dialogs)
    }
    if buttons:
        UserInteraction(user, buttons, target=None).click()
        await asyncio.sleep(0.2)


async def test_index_page_loads(user: User) -> None:
    await user.open("/")
    await user.should_see("pyopia-gui")


async def test_header_shows_pyopia_gui_version(user: User) -> None:
    await user.open("/")
    await user.should_see(f"v{__version__}")


async def test_header_shows_update_link_when_newer_release_exists(user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(version_check, "check_for_newer_release", lambda *a, **k: "v99.0.0")

    await user.open("/")

    await user.should_see("v99.0.0 available")


async def test_header_has_no_update_link_when_already_current(user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(version_check, "check_for_newer_release", lambda *a, **k: None)

    await user.open("/")
    await asyncio.sleep(0.1)  # let the background version-check task finish before asserting its absence

    await user.should_not_see("available ↗")


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


async def test_main_screen_shows_expected_elements_when_docker_available(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)

    await user.open("/")

    await user.should_see("1. Create example project")
    await user.should_see("4. Run processing")
    await user.should_see("Ready")
    await user.should_see("Browse")


async def test_future_tabs_are_disabled(user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)

    await user.open("/")

    for label in ("2. Raw data explorer", "3. Configuration"):
        tab = user.find(kind=ui.tab, content=label).elements.pop()
        assert not tab.enabled


async def test_process_and_results_tabs_start_disabled_for_invalid_default_project(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The real default project folder may or may not exist on the machine running the
    # tests - use an explicitly-invalid one so this test doesn't depend on that.
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = "/nonexistent/path/for/testing"
    await asyncio.sleep(0.2)

    process_tab = user.find(kind=ui.tab, content="4. Process").elements.pop()
    results_tab = user.find(kind=ui.tab, content="5. Results").elements.pop()
    assert not process_tab.enabled
    assert not results_tab.enabled


async def test_process_tab_enables_for_a_valid_project(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    _write_config_with_pixel_size(tmp_path)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await asyncio.sleep(0.2)

    process_tab = user.find(kind=ui.tab, content="4. Process").elements.pop()
    results_tab = user.find(kind=ui.tab, content="5. Results").elements.pop()
    assert process_tab.enabled
    assert not results_tab.enabled  # no stats file yet


async def test_opening_an_already_processed_project_auto_jumps_to_results(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "read_pinned_version", lambda *a, **k: "2.16.23")
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: [])
    _write_config_with_pixel_size(tmp_path)
    (tmp_path / "processed").mkdir()
    (tmp_path / "processed" / "demo-STATS.nc").write_bytes(b"")

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await asyncio.sleep(0.2)

    results_tab = user.find(kind=ui.tab, content="5. Results").elements.pop()
    assert results_tab.enabled
    assert results_tab.tabs.value == "results"
    await user.should_see("processed with PyOPIA v2.16.23")


async def test_clicking_a_disabled_tab_does_not_switch_to_it(user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)

    await user.open("/")
    explorer_tab = user.find(kind=ui.tab, content="2. Raw data explorer").elements.pop()

    user.find(kind=ui.tab, content="2. Raw data explorer").click()

    assert explorer_tab.tabs.value == "project"


async def test_shows_editable_project_folder_input(user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)

    await user.open("/")

    await user.should_see("Project folder")
    folder_input = user.find(ui.input).elements.pop()
    assert Path(folder_input.value) == Path.home() / "pyopia-gui-projects" / "demo"


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
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: [])
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
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: [])
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
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: [])
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


async def test_create_lets_user_choose_pyopia_version(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: ["2.16.23", "2.16.20"])
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

    version_select = user.find(ui.select).elements.pop()
    version_select.set_value("2.16.20")
    user.find(kind=ui.button, content="Create here").click()
    await asyncio.sleep(0.2)  # let on_create()'s coroutine run the (mocked) docker command

    assert any("ghcr.io/nimmo-smith-technologies/pyopia:2.16.20" in command for command in calls)

    await user.should_see("Example project created")


async def test_running_right_after_create_does_not_ask_for_version_again(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The version was already chosen moments ago via the create dialog - nothing's been
    # processed yet for on_run() to read a pin back from, so it must reuse that choice
    # silently rather than opening the "Choose a PyOPIA version" picker a second time.
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "read_pinned_version", lambda *a, **k: None)
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: ["2.16.23", "2.16.20"])
    target = tmp_path / "new-project"
    calls: list[list[str]] = []

    async def fake_run_streamed(command: list[str], on_line: Callable[[str], None]) -> int:
        calls.append(command)
        if "init-project" in command:
            # A real init-project would write a real config.toml - on_run()'s own
            # validate_project() check needs one to find to proceed past it at all.
            target.mkdir(parents=True, exist_ok=True)
            _write_config_with_pixel_size(target)
        return 0

    monkeypatch.setattr(docker_client, "run_streamed", fake_run_streamed)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(target)

    user.find(kind=ui.button, content="1. Create example project").click()
    await user.should_see("Create a new PyOPIA project here?")
    version_select = user.find(ui.select).elements.pop()
    version_select.set_value("2.16.20")
    user.find(kind=ui.button, content="Create here").click()
    await user.should_see("Example project created")

    user.find(kind=ui.button, content="4. Run processing").click()
    await asyncio.sleep(0.2)

    await user.should_not_see("Choose a PyOPIA version")
    assert any("ghcr.io/nimmo-smith-technologies/pyopia:2.16.20" in command for command in calls[1:])


async def test_run_shows_friendly_message_in_log_on_image_pull_failure(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: [])
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

    user.find(kind=ui.button, content="4. Run processing").click()

    await user.should_see("Couldn't pull the PyOPIA image")


def _write_config_with_pixel_size(tmp_path: Path, output_datafile: str = "processed/demo") -> None:
    tmp_path.joinpath("config.toml").write_text(
        f'[general]\npixel_size = 24\n\n[steps.output]\noutput_datafile = "{output_datafile}"\n'
    )


async def test_run_shows_pyopia_version_after_successful_processing(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: [])
    monkeypatch.setattr(docker_client, "read_pinned_version", lambda *a, **k: "2.16.23")
    _write_config_with_pixel_size(tmp_path)

    async def fake_run_streamed(command: list[str], on_line: Callable[[str], None]) -> int:
        if "process" in command:
            on_line("PYOPIA VERSION 2.16.23")
            on_line("LOAD CONFIG")
        if "merge-mfdata" in command:
            # A real run's merge-mfdata step is what actually produces the stats file the
            # Results tab looks for - a dummy file is enough here since this test only
            # cares about the version label, not the (separately tested) stats reading.
            (tmp_path / "processed").mkdir(exist_ok=True)
            (tmp_path / "processed" / "demo-STATS.nc").write_bytes(b"")
        return 0

    monkeypatch.setattr(docker_client, "run_streamed", fake_run_streamed)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)

    user.find(kind=ui.button, content="4. Run processing").click()

    await user.should_see("processed with PyOPIA v2.16.23")


async def test_rerun_clears_stale_results_from_previous_run(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: [])
    monkeypatch.setattr(docker_client, "read_pinned_version", lambda *a, **k: "2.16.23")
    _write_config_with_pixel_size(tmp_path)
    run_count = {"n": 0}

    async def fake_run_streamed(command: list[str], on_line: Callable[[str], None]) -> int:
        if "process" in command:
            run_count["n"] += 1
            if run_count["n"] == 1:
                on_line("PYOPIA VERSION 2.16.23")
                return 0
            return 1  # the second run's process step fails outright
        if "merge-mfdata" in command:
            (tmp_path / "processed").mkdir(exist_ok=True)
            (tmp_path / "processed" / "demo-STATS.nc").write_bytes(b"")
        return 0

    monkeypatch.setattr(docker_client, "run_streamed", fake_run_streamed)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)

    user.find(kind=ui.button, content="4. Run processing").click()
    await _click_through_pinned_version_dialog_if_shown(user)
    await user.should_see("processed with PyOPIA v2.16.23")
    await user.should_see("Done")

    user.find(kind=ui.button, content="4. Run processing").click()
    await _click_through_pinned_version_dialog_if_shown(user)
    await asyncio.sleep(0.2)  # let on_run() clear the Results tab before the second run fails

    await user.should_not_see("processed with PyOPIA v2.16.23")


async def test_successful_rerun_removes_stale_montage(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A montage built from a previous run's stats no longer necessarily matches fresh
    # ones from a rerun - it should be removed (not left displayed) until regenerated.
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: [])
    monkeypatch.setattr(docker_client, "read_pinned_version", lambda *a, **k: "2.16.23")
    _write_config_with_pixel_size(tmp_path)
    (tmp_path / "montage.png").write_bytes(b"stale montage from an earlier run")

    async def fake_run_streamed(command: list[str], on_line: Callable[[str], None]) -> int:
        if "merge-mfdata" in command:
            (tmp_path / "processed").mkdir(exist_ok=True)
            (tmp_path / "processed" / "demo-STATS.nc").write_bytes(b"")
        return 0

    monkeypatch.setattr(docker_client, "run_streamed", fake_run_streamed)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)

    user.find(kind=ui.button, content="4. Run processing").click()
    await _click_through_pinned_version_dialog_if_shown(user)
    await user.should_see("Done")

    assert not (tmp_path / "montage.png").exists()
    await user.should_see("Generate montage")
    await user.should_not_see("Regenerate montage")


async def test_results_tab_offers_regenerate_when_a_montage_already_exists(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "read_pinned_version", lambda *a, **k: "2.16.23")
    _write_config_with_pixel_size(tmp_path)
    (tmp_path / "processed").mkdir()
    (tmp_path / "processed" / "demo-STATS.nc").write_bytes(b"")
    (tmp_path / "montage.png").write_bytes(b"an existing montage")

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)

    await user.should_see("Regenerate montage")
    # Not should_not_see("Generate montage") - "Regenerate montage" contains it as a
    # substring, so that check alone can't tell the two buttons apart. Assert on the
    # actual button count/labels instead.
    button_labels = {button.text for button in user.find(kind=ui.button).elements}
    assert "Generate montage" not in button_labels


async def test_run_reuses_pinned_version_from_existing_output(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "read_pinned_version", lambda *a, **k: "2.16.15")
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: ["2.16.23", "2.16.15"])
    (tmp_path / "config.toml").write_text('[steps.output]\noutput_datafile = "processed/demo"\n')
    calls: list[list[str]] = []

    async def fake_run_streamed(command: list[str], on_line: Callable[[str], None]) -> int:
        calls.append(command)
        return 0

    monkeypatch.setattr(docker_client, "run_streamed", fake_run_streamed)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)

    user.find(kind=ui.button, content="4. Run processing").click()

    await user.should_see("This will run PyOPIA v2.16.15")
    await user.should_see("A newer version (v2.16.23) is available")

    user.find(kind=ui.button, content="Run processing").click()
    await asyncio.sleep(0.2)

    assert any("ghcr.io/nimmo-smith-technologies/pyopia:2.16.15" in command for command in calls)


async def test_run_cancelled_pinned_version_confirmation_does_not_run_docker(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "read_pinned_version", lambda *a, **k: "2.16.15")
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: ["2.16.15"])
    (tmp_path / "config.toml").write_text('[steps.output]\noutput_datafile = "processed/demo"\n')
    calls: list[list[str]] = []

    async def fake_run_streamed(command: list[str], on_line: Callable[[str], None]) -> int:
        calls.append(command)
        return 0

    monkeypatch.setattr(docker_client, "run_streamed", fake_run_streamed)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)

    user.find(kind=ui.button, content="4. Run processing").click()
    await user.should_see("This will run PyOPIA v2.16.15")

    user.find(kind=ui.button, content="Cancel").click()
    await asyncio.sleep(0.2)

    assert calls == []


async def test_run_prompts_for_version_when_project_has_no_pin_yet(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "read_pinned_version", lambda *a, **k: None)
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: ["2.16.23", "2.16.15"])
    (tmp_path / "config.toml").write_text('[steps.output]\noutput_datafile = "processed/demo"\n')
    calls: list[list[str]] = []

    async def fake_run_streamed(command: list[str], on_line: Callable[[str], None]) -> int:
        calls.append(command)
        return 0

    monkeypatch.setattr(docker_client, "run_streamed", fake_run_streamed)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)

    user.find(kind=ui.button, content="4. Run processing").click()
    await user.should_see("Choose a PyOPIA version")

    version_select = user.find(ui.select).elements.pop()
    version_select.set_value("2.16.15")
    user.find(kind=ui.button, content="Use this version").click()
    await asyncio.sleep(0.2)

    assert any("ghcr.io/nimmo-smith-technologies/pyopia:2.16.15" in command for command in calls)


async def test_run_cancelled_version_choice_does_not_run_docker(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "read_pinned_version", lambda *a, **k: None)
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: ["2.16.23"])
    (tmp_path / "config.toml").write_text('[steps.output]\noutput_datafile = "processed/demo"\n')
    calls: list[list[str]] = []

    async def fake_run_streamed(command: list[str], on_line: Callable[[str], None]) -> int:
        calls.append(command)
        return 0

    monkeypatch.setattr(docker_client, "run_streamed", fake_run_streamed)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)

    user.find(kind=ui.button, content="4. Run processing").click()
    await user.should_see("Choose a PyOPIA version")

    user.find(kind=ui.button, content="Cancel").click()
    await asyncio.sleep(0.2)

    assert calls == []
