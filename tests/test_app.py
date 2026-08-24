# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Nimmo Smith Technologies Limited

import asyncio
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest
from nicegui import ui
from nicegui.testing import User
from nicegui.testing.user_interaction import UserInteraction

from pyopia_gui import __version__, docker_client, vendored_stats, version_check


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


@pytest.fixture(autouse=True)
def _no_real_docker_introspection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any test that sets a valid project folder triggers refresh_config()'s and
    refresh_explorer()'s background Docker calls - default both to a no-op so tests that
    don't care about that tab's content don't slow down or hit a real Docker daemon. Tests
    that do care override this explicitly with their own monkeypatch.setattr(...) call.
    """
    monkeypatch.setattr(docker_client, "introspect_config_steps", lambda *a, **k: {})

    async def fake_generate_thumbnails(*a: object, **k: object) -> dict[str, str]:
        return {}

    monkeypatch.setattr(docker_client, "generate_thumbnails", fake_generate_thumbnails)


@pytest.fixture(autouse=True)
def _default_project_dir_is_never_real(monkeypatch: pytest.MonkeyPatch) -> None:
    """`user.open("/")` kicks off a real refresh_project_state() against whatever
    DEFAULT_PROJECT_DIR resolves to, *before* a test gets a chance to point
    folder_input at its own tmp_path - if a real project happens to already exist at
    the real default location (e.g. from manual testing on a dev machine), that
    background render races the test's own project load: background Docker/widget
    work for two different projects' `refresh_config()`/`load_steps()` calls can
    interleave, occasionally letting a test grab the wrong render pass's widget.
    Confirmed directly: this exact class of flake reproduced repeatedly with a real
    project at ~/pyopia-gui-projects/demo present, and vanished (reliable across
    repeated runs) with it moved aside - not something CI ever hits (no such
    leftover folder there), but a real hazard for local `uv run pytest` on a
    machine that's also been used for manual testing.

    Uses an env var, not monkeypatch.setattr(main, "DEFAULT_PROJECT_DIR", ...) -
    confirmed that doesn't work: NiceGUI's `user` fixture (nicegui.testing.user_plugin)
    runs main.py fresh per test via `runpy.run_path(..., run_name='__main__')`, an
    isolated execution disconnected from `sys.modules['pyopia_gui.main']` (the module
    object this file's own `main` import refers to) - patching *that* object's
    attribute has no effect on the actual app instance under test. os.environ is real
    process-wide state, so it's what the freshly-run script actually sees too.
    """
    monkeypatch.setenv("PYOPIA_GUI_DEFAULT_PROJECT_DIR", "/nonexistent/path/for/testing")


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

    await user.should_see("Create example project")
    await user.should_see("Run processing")
    await user.should_see("Ready")
    await user.should_see("Browse")


async def test_process_results_config_and_explorer_tabs_start_disabled_for_invalid_default_project(
    user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The real default project folder may or may not exist on the machine running the
    # tests - use an explicitly-invalid one so this test doesn't depend on that.
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = "/nonexistent/path/for/testing"
    await asyncio.sleep(0.2)

    process_tab = user.find(kind=ui.tab, content="5. Process").elements.pop()
    results_tab = user.find(kind=ui.tab, content="6. Results").elements.pop()
    config_tab = user.find(kind=ui.tab, content="3. Configuration").elements.pop()
    explorer_tab = user.find(kind=ui.tab, content="2. Raw data explorer").elements.pop()
    preview_tab = user.find(kind=ui.tab, content="4. Preview").elements.pop()
    assert not process_tab.enabled
    assert not results_tab.enabled
    assert not config_tab.enabled
    assert not explorer_tab.enabled
    assert not preview_tab.enabled


async def test_process_config_and_explorer_tabs_enable_for_a_valid_project(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    _write_config_with_pixel_size(tmp_path)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await asyncio.sleep(0.2)

    process_tab = user.find(kind=ui.tab, content="5. Process").elements.pop()
    results_tab = user.find(kind=ui.tab, content="6. Results").elements.pop()
    config_tab = user.find(kind=ui.tab, content="3. Configuration").elements.pop()
    explorer_tab = user.find(kind=ui.tab, content="2. Raw data explorer").elements.pop()
    preview_tab = user.find(kind=ui.tab, content="4. Preview").elements.pop()
    assert process_tab.enabled
    assert config_tab.enabled
    assert explorer_tab.enabled
    assert preview_tab.enabled
    assert not results_tab.enabled  # no stats file yet


async def test_process_config_and_explorer_tabs_show_the_project_folder_path(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    _write_config_with_pixel_size(tmp_path)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await asyncio.sleep(0.2)

    resolved = str(tmp_path.resolve())
    # Process and Configuration both load eagerly, so this text already appears twice.
    await user.should_see(f"Project: {resolved}")

    user.find(kind=ui.tab, content="2. Raw data explorer").click()
    await asyncio.sleep(0.2)
    await user.should_see(f"Project: {resolved}")


async def test_opening_an_already_processed_project_auto_jumps_to_results(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "read_pinned_version", lambda *a, **k: "9.16.23")
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: [])
    _write_config_with_pixel_size(tmp_path)
    (tmp_path / "processed").mkdir()
    (tmp_path / "processed" / "demo-STATS.nc").write_bytes(b"")

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)

    # refresh_project_state() sets tabs.value only after refresh_results() fully
    # returns (which does further io_bound work after rendering the version label
    # below) - a fixed sleep here raced that on slower CI runners (seen flaking on
    # macOS), so poll for the actual tab switch instead of guessing a duration.
    results_tab = user.find(kind=ui.tab, content="6. Results").elements.pop()
    for _ in range(50):
        if results_tab.tabs.value == "results":
            break
        await asyncio.sleep(0.1)
    assert results_tab.enabled
    assert results_tab.tabs.value == "results"
    await user.should_see("processed with PyOPIA v9.16.23")


async def test_saving_configuration_on_an_already_processed_project_stays_on_config_tab(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A save is not a "the project changed" event - jumping away to Results (the
    # behaviour real project-folder changes and a finished Run processing use)
    # would yank the user off Configuration right after they clicked Save.
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "read_pinned_version", lambda *a, **k: "9.16.23")
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: [])
    monkeypatch.setattr(
        docker_client,
        "introspect_config_steps",
        lambda *a, **k: {
            "steps": {
                "segmentation": {
                    "pipeline_class": "pyopia.process.Segment",
                    "fields": [
                        {
                            "name": "threshold",
                            "current_value": 0.85,
                            "has_default": True,
                            "default": 0.98,
                            "description": "",
                        }
                    ],
                }
            }
        },
    )
    _write_config_with_a_step(tmp_path)
    (tmp_path / "processed").mkdir()
    (tmp_path / "processed" / "demo-STATS.nc").write_bytes(b"")

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)

    results_tab = user.find(kind=ui.tab, content="6. Results").elements.pop()
    for _ in range(50):
        if results_tab.tabs.value == "results":
            break
        await asyncio.sleep(0.1)
    assert results_tab.tabs.value == "results"  # opening it does jump, as before

    results_tab.tabs.value = "config"
    await user.should_see("threshold")
    threshold_input = user.find(kind=ui.number, content="threshold").elements.pop()
    threshold_input.value = 0.5

    user.find(kind=ui.button, content="Save changes").click()
    await user.should_see("Configuration saved")

    assert results_tab.tabs.value == "config"  # saving must not jump tabs


async def test_editing_configuration_shows_unsaved_changes_warning_on_process_tab(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(
        docker_client,
        "introspect_config_steps",
        lambda *a, **k: {
            "steps": {
                "segmentation": {
                    "pipeline_class": "pyopia.process.Segment",
                    "fields": [
                        {
                            "name": "threshold",
                            "current_value": 0.85,
                            "has_default": True,
                            "default": 0.98,
                            "description": "",
                        }
                    ],
                }
            }
        },
    )
    _write_config_with_a_step(tmp_path)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await user.should_see("threshold")

    await user.should_not_see("unsaved changes")

    threshold_input = user.find(kind=ui.number, content="threshold").elements.pop()
    threshold_input.value = 0.5
    await user.should_see("unsaved changes")

    user.find(kind=ui.button, content="Save changes").click()
    await user.should_see("Configuration saved")
    await user.should_not_see("unsaved changes")


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
    # Not main.DEFAULT_PROJECT_DIR - that's a different, separately-imported module
    # object than the one the runpy-executed app under test actually reads (see
    # _default_project_dir_is_never_real's docstring); the env var it's overridden
    # to for every test is the actual source of truth here.
    assert Path(folder_input.value) == Path("/nonexistent/path/for/testing")


async def test_create_warns_if_folder_already_exists(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)

    user.find(kind=ui.button, content="Create example project").click()

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

    user.find(kind=ui.button, content="Create example project").click()

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

    user.find(kind=ui.button, content="Create example project").click()
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

    user.find(kind=ui.button, content="Create example project").click()
    await user.should_see("Create a new PyOPIA project here?")

    user.find(kind=ui.button, content="Create here").click()


async def test_create_lets_user_choose_pyopia_version(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: ["9.16.23", "9.16.20"])
    target = tmp_path / "new-project"
    calls: list[list[str]] = []

    async def fake_run_streamed(command: list[str], on_line: Callable[[str], None]) -> int:
        calls.append(command)
        return 0

    monkeypatch.setattr(docker_client, "run_streamed", fake_run_streamed)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(target)

    user.find(kind=ui.button, content="Create example project").click()
    await user.should_see("Create a new PyOPIA project here?")

    version_select = user.find(kind=ui.select, content="PyOPIA version").elements.pop()
    version_select.set_value("9.16.20")
    user.find(kind=ui.button, content="Create here").click()
    await asyncio.sleep(0.2)  # let on_create()'s coroutine run the (mocked) docker command

    assert any("ghcr.io/nimmo-smith-technologies/pyopia:9.16.20" in command for command in calls)

    await user.should_see("Example project created")


async def test_running_right_after_create_does_not_ask_for_version_again(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The version was already chosen moments ago via the create dialog - nothing's been
    # processed yet for on_run() to read a pin back from, so it must reuse that choice
    # silently rather than opening the "Choose a PyOPIA version" picker a second time.
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "read_pinned_version", lambda *a, **k: None)
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: ["9.16.23", "9.16.20"])
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

    user.find(kind=ui.button, content="Create example project").click()
    await user.should_see("Create a new PyOPIA project here?")
    version_select = user.find(kind=ui.select, content="PyOPIA version").elements.pop()
    version_select.set_value("9.16.20")
    user.find(kind=ui.button, content="Create here").click()
    await user.should_see("Example project created")

    user.find(kind=ui.button, content="Run processing").click()
    await asyncio.sleep(0.2)

    await user.should_not_see("Choose a PyOPIA version")
    assert any("ghcr.io/nimmo-smith-technologies/pyopia:9.16.20" in command for command in calls[1:])


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

    user.find(kind=ui.button, content="Run processing").click()

    await user.should_see("Couldn't pull the PyOPIA image")


def _write_config_with_pixel_size(tmp_path: Path, output_datafile: str = "processed/demo") -> None:
    # append=false, not the default (true) - several tests here exercise the
    # process -> merge-mfdata flow, which is only actually run when append=false
    # (see docker_client.output_uses_append); append=true writes the combined file
    # directly from `process`, with no merge step at all.
    tmp_path.joinpath("config.toml").write_text(
        f'[general]\npixel_size = 24\n\n[steps.output]\noutput_datafile = "{output_datafile}"\nappend = false\n'
    )


async def test_run_shows_pyopia_version_after_successful_processing(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: [])
    monkeypatch.setattr(docker_client, "read_pinned_version", lambda *a, **k: "9.16.23")
    _write_config_with_pixel_size(tmp_path)

    async def fake_run_streamed(command: list[str], on_line: Callable[[str], None]) -> int:
        if "process" in command:
            on_line("PYOPIA VERSION 9.16.23")
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

    user.find(kind=ui.button, content="Run processing").click()
    await _click_through_pinned_version_dialog_if_shown(user)

    await user.should_see("processed with PyOPIA v9.16.23")


async def test_rerun_clears_stale_results_from_previous_run(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: [])
    monkeypatch.setattr(docker_client, "read_pinned_version", lambda *a, **k: "9.16.23")
    _write_config_with_pixel_size(tmp_path)
    run_count = {"n": 0}

    async def fake_run_streamed(command: list[str], on_line: Callable[[str], None]) -> int:
        if "process" in command:
            run_count["n"] += 1
            if run_count["n"] == 1:
                on_line("PYOPIA VERSION 9.16.23")
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

    user.find(kind=ui.button, content="Run processing").click()
    await _click_through_pinned_version_dialog_if_shown(user)
    await user.should_see("processed with PyOPIA v9.16.23")
    await user.should_see("Done")


async def test_run_processing_skips_merge_mfdata_when_output_appends_directly(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # With append=true (the default), `process` already writes the single combined
    # file directly - there's nothing for merge-mfdata to do, and PyOPIA's own
    # merge-mfdata crashes outright (ZeroDivisionError) against an empty file list
    # rather than a no-op, confirmed directly. Always running it unconditionally used
    # to report every append=true run as a failed merge, even though processing had
    # already succeeded correctly.
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: [])
    monkeypatch.setattr(docker_client, "read_pinned_version", lambda *a, **k: "9.16.23")
    tmp_path.joinpath("config.toml").write_text(
        '[general]\npixel_size = 24\n\n[steps.output]\noutput_datafile = "processed/demo"\nappend = true\n'
    )
    merge_calls = {"n": 0}

    async def fake_run_streamed(command: list[str], on_line: Callable[[str], None]) -> int:
        if "process" in command:
            on_line("PYOPIA VERSION 9.16.23")
            (tmp_path / "processed").mkdir(exist_ok=True)
            (tmp_path / "processed" / "demo-STATS.nc").write_bytes(b"")
            return 0
        if "merge-mfdata" in command:
            merge_calls["n"] += 1
            return 1  # would fail if it were ever called - it shouldn't be
        return 0

    monkeypatch.setattr(docker_client, "run_streamed", fake_run_streamed)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)

    user.find(kind=ui.button, content="Run processing").click()
    await _click_through_pinned_version_dialog_if_shown(user)
    await user.should_see("Done")

    assert merge_calls["n"] == 0


async def test_successful_rerun_removes_stale_montage(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A montage built from a previous run's stats no longer necessarily matches fresh
    # ones from a rerun - it should be removed (not left displayed) until regenerated.
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: [])
    monkeypatch.setattr(docker_client, "read_pinned_version", lambda *a, **k: "9.16.23")
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

    user.find(kind=ui.button, content="Run processing").click()
    await _click_through_pinned_version_dialog_if_shown(user)
    await user.should_see("Done")

    assert not (tmp_path / "montage.png").exists()
    await user.should_see("Generate montage")
    await user.should_not_see("Regenerate montage")


async def test_run_processing_clears_stale_output_folder_before_running(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # PyOPIA's own merge step has no way to tell a fresh run's per-image files apart
    # from an old run's - it just globs everything matching the pattern - so a stale
    # leftover from a previous run/config could otherwise get silently merged into
    # what looks like a fresh result. Clearing the output folder before a run removes
    # that risk, rather than relying on PyOPIA's own conflict-rename, which only
    # covers the single combined file, not per-image ones.
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: [])
    monkeypatch.setattr(docker_client, "read_pinned_version", lambda *a, **k: "9.16.23")
    _write_config_with_pixel_size(tmp_path)
    (tmp_path / "processed").mkdir()
    stale_file = tmp_path / "processed" / "demo-Image-D20220101T000000-STATS.nc"
    stale_file.write_bytes(b"stale, from an earlier run/config")

    async def fake_run_streamed(command: list[str], on_line: Callable[[str], None]) -> int:
        if "merge-mfdata" in command:
            (tmp_path / "processed").mkdir(exist_ok=True)
            (tmp_path / "processed" / "demo-STATS.nc").write_bytes(b"")
        return 0

    monkeypatch.setattr(docker_client, "run_streamed", fake_run_streamed)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)

    user.find(kind=ui.button, content="Run processing").click()
    await _click_through_pinned_version_dialog_if_shown(user)
    await user.should_see("Done")

    assert not stale_file.exists()


async def test_results_tab_distinguishes_particle_detections_from_raw_image_count(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # images_with_particles is *not* "images processed" - an image with zero
    # detections contributes no rows to the stats file at all, so it can't be told
    # apart from "wasn't processed" using the stats file alone. Cross-checking
    # against the project's real raw file count is what actually makes this
    # unambiguous, instead of reading like a processing shortfall.
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "read_pinned_version", lambda *a, **k: None)
    tmp_path.joinpath("config.toml").write_text(
        '[general]\nraw_files = "images/*.silc"\npixel_size = 24\n\n'
        '[steps.output]\noutput_datafile = "processed/demo"\n'
    )
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    for i in range(10):
        (images_dir / f"frame{i:02d}.silc").write_bytes(b"")
    (tmp_path / "processed").mkdir()
    (tmp_path / "processed" / "demo-STATS.nc").write_bytes(b"")

    summary = vendored_stats.StatsSummary(
        particle_count=103, images_with_particles=5, d50_microns=42.5, dias=[], number_distribution=[]
    )
    monkeypatch.setattr(vendored_stats, "summarize", lambda *a, **k: summary)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)

    await user.should_see("103 particles found across 5 of 10 raw images")
    await user.should_see("the rest had none detected")


async def test_results_tab_offers_regenerate_when_a_montage_already_exists(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "read_pinned_version", lambda *a, **k: "9.16.23")
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
    monkeypatch.setattr(docker_client, "read_pinned_version", lambda *a, **k: "9.16.15")
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: ["9.16.23", "9.16.15"])
    (tmp_path / "config.toml").write_text('[steps.output]\noutput_datafile = "processed/demo"\n')
    calls: list[list[str]] = []

    async def fake_run_streamed(command: list[str], on_line: Callable[[str], None]) -> int:
        calls.append(command)
        return 0

    monkeypatch.setattr(docker_client, "run_streamed", fake_run_streamed)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)

    user.find(kind=ui.button, content="Run processing").click()

    await user.should_see("This will run PyOPIA v9.16.15")
    await user.should_see("A newer version (v9.16.23) is available")

    user.find(kind=ui.button, content="Run processing").click()
    await asyncio.sleep(0.2)

    assert any("ghcr.io/nimmo-smith-technologies/pyopia:9.16.15" in command for command in calls)


async def test_run_cancelled_pinned_version_confirmation_does_not_run_docker(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "read_pinned_version", lambda *a, **k: "9.16.15")
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: ["9.16.15"])
    (tmp_path / "config.toml").write_text('[steps.output]\noutput_datafile = "processed/demo"\n')
    calls: list[list[str]] = []

    async def fake_run_streamed(command: list[str], on_line: Callable[[str], None]) -> int:
        calls.append(command)
        return 0

    monkeypatch.setattr(docker_client, "run_streamed", fake_run_streamed)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)

    user.find(kind=ui.button, content="Run processing").click()
    await user.should_see("This will run PyOPIA v9.16.15")

    user.find(kind=ui.button, content="Cancel").click()
    await asyncio.sleep(0.2)

    assert calls == []


async def test_run_prompts_for_version_when_project_has_no_pin_yet(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "read_pinned_version", lambda *a, **k: None)
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: ["9.16.23", "9.16.15"])
    (tmp_path / "config.toml").write_text('[steps.output]\noutput_datafile = "processed/demo"\n')
    calls: list[list[str]] = []

    async def fake_run_streamed(command: list[str], on_line: Callable[[str], None]) -> int:
        calls.append(command)
        return 0

    monkeypatch.setattr(docker_client, "run_streamed", fake_run_streamed)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)

    user.find(kind=ui.button, content="Run processing").click()
    await user.should_see("Choose a PyOPIA version")

    version_select = user.find(kind=ui.select, content="PyOPIA version").elements.pop()
    version_select.set_value("9.16.15")
    user.find(kind=ui.button, content="Use this version").click()
    await asyncio.sleep(0.2)

    assert any("ghcr.io/nimmo-smith-technologies/pyopia:9.16.15" in command for command in calls)


async def test_run_cancelled_version_choice_does_not_run_docker(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "read_pinned_version", lambda *a, **k: None)
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: ["9.16.23"])
    (tmp_path / "config.toml").write_text('[steps.output]\noutput_datafile = "processed/demo"\n')
    calls: list[list[str]] = []

    async def fake_run_streamed(command: list[str], on_line: Callable[[str], None]) -> int:
        calls.append(command)
        return 0

    monkeypatch.setattr(docker_client, "run_streamed", fake_run_streamed)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)

    user.find(kind=ui.button, content="Run processing").click()
    await user.should_see("Choose a PyOPIA version")

    user.find(kind=ui.button, content="Cancel").click()
    await asyncio.sleep(0.2)

    assert calls == []


def _write_config_with_a_step(tmp_path: Path) -> None:
    tmp_path.joinpath("config.toml").write_text(
        '[general]\nraw_files = "images/*.silc"\npixel_size = 24\n\n'
        '[steps.segmentation]\npipeline_class = "pyopia.process.Segment"\nthreshold = 0.85\n\n'
        '[steps.output]\noutput_datafile = "processed/demo"\n'
    )


async def test_config_tab_shows_general_fields_for_a_valid_project(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "introspect_config_steps", lambda *a, **k: {})
    _write_config_with_a_step(tmp_path)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)

    await user.should_see("images/*.silc")
    await user.should_see("Verify this matches your actual instrument")


async def test_config_tab_shows_introspected_step_fields_with_descriptions(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(
        docker_client,
        "introspect_config_steps",
        lambda *a, **k: {
            "steps": {
                "segmentation": {
                    "pipeline_class": "pyopia.process.Segment",
                    "fields": [
                        {
                            "name": "threshold",
                            "current_value": 0.85,
                            "has_default": True,
                            "default": 0.98,
                            "description": "threshold for segmentation",
                        }
                    ],
                }
            }
        },
    )
    _write_config_with_a_step(tmp_path)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)

    await user.should_see("segmentation")
    await user.should_see("threshold for segmentation")


async def test_config_tab_falls_back_to_bare_fields_when_step_introspection_fails(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(
        docker_client,
        "introspect_config_steps",
        lambda *a, **k: {
            "steps": {
                "segmentation": {"pipeline_class": "pyopia.process.Segment", "error": "ModuleNotFoundError: boom"}
            }
        },
    )
    _write_config_with_a_step(tmp_path)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)

    await user.should_see("Couldn't introspect this step")
    # Falls back to the raw key from config.toml itself, not just an error message.
    await user.should_see("threshold")


async def test_save_changes_writes_edited_value_to_config_toml(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(
        docker_client,
        "introspect_config_steps",
        lambda *a, **k: {
            "steps": {
                "segmentation": {
                    "pipeline_class": "pyopia.process.Segment",
                    "fields": [
                        {
                            "name": "threshold",
                            "current_value": 0.85,
                            "has_default": True,
                            "default": 0.98,
                            "description": "",
                        }
                    ],
                }
            }
        },
    )
    _write_config_with_a_step(tmp_path)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await user.should_see("threshold")

    threshold_input = user.find(kind=ui.number, content="threshold").elements.pop()
    threshold_input.value = 0.5

    user.find(kind=ui.button, content="Save changes").click()
    await user.should_see("Configuration saved")

    saved = tomllib.loads((tmp_path / "config.toml").read_text())
    assert saved["steps"]["segmentation"]["threshold"] == 0.5
    assert saved["steps"]["segmentation"]["pipeline_class"] == "pyopia.process.Segment"


async def test_save_changes_omits_a_blank_field_whose_real_default_is_none(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The actual bug that broke real processing on a real project: an unset,
    # None-defaulting field (e.g. StatsToDisc's project_metadata_file) renders as
    # an empty text box, and saving used to write that back as "" - a value
    # PyOPIA's own `is not None` guard treats as genuinely *set*, then crashes
    # trying to open as a file path. Confirmed directly: every real run on that
    # project failed, silently, the moment this field had ever been saved even
    # once, for a field the user never touched. Saving now must omit the key
    # entirely instead, so PyOPIA's own None default actually applies.
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(
        docker_client,
        "introspect_config_steps",
        lambda *a, **k: {
            "steps": {
                "output": {
                    "pipeline_class": "pyopia.io.StatsToDisc",
                    "fields": [
                        {
                            "name": "output_datafile",
                            "current_value": "processed/demo",
                            "has_default": False,
                            "default": None,
                            "description": "",
                        },
                        {
                            "name": "project_metadata_file",
                            "current_value": None,
                            "has_default": True,
                            "default": None,
                            "description": "",
                        },
                    ],
                }
            }
        },
    )
    tmp_path.joinpath("config.toml").write_text(
        '[general]\nraw_files = "images/*.silc"\npixel_size = 24\n\n'
        '[steps.output]\npipeline_class = "pyopia.io.StatsToDisc"\noutput_datafile = "processed/demo"\n'
    )

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await user.should_see("project_metadata_file")

    user.find(kind=ui.button, content="Save changes").click()
    await user.should_see("Configuration saved")

    saved = tomllib.loads((tmp_path / "config.toml").read_text())
    assert "project_metadata_file" not in saved["steps"]["output"]
    assert saved["steps"]["output"]["output_datafile"] == "processed/demo"


async def test_save_changes_keeps_a_non_blank_value_for_a_none_defaulting_field(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(
        docker_client,
        "introspect_config_steps",
        lambda *a, **k: {
            "steps": {
                "output": {
                    "pipeline_class": "pyopia.io.StatsToDisc",
                    "fields": [
                        {
                            "name": "output_datafile",
                            "current_value": "processed/demo",
                            "has_default": False,
                            "default": None,
                            "description": "",
                        },
                        {
                            "name": "project_metadata_file",
                            "current_value": "metadata.json",
                            "has_default": True,
                            "default": None,
                            "description": "",
                        },
                    ],
                }
            }
        },
    )
    tmp_path.joinpath("config.toml").write_text(
        '[general]\nraw_files = "images/*.silc"\npixel_size = 24\n\n'
        '[steps.output]\npipeline_class = "pyopia.io.StatsToDisc"\n'
        'output_datafile = "processed/demo"\nproject_metadata_file = "metadata.json"\n'
    )

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await user.should_see("project_metadata_file")

    user.find(kind=ui.button, content="Save changes").click()
    await user.should_see("Configuration saved")

    saved = tomllib.loads((tmp_path / "config.toml").read_text())
    assert saved["steps"]["output"]["project_metadata_file"] == "metadata.json"


def _write_config_with_a_step_and_classifier(tmp_path: Path) -> None:
    tmp_path.joinpath("config.toml").write_text(
        '[general]\nraw_files = "images/*.silc"\npixel_size = 24\n\n'
        '[steps.classifier]\npipeline_class = "pyopia.classify.Classify"\nmodel_path = "m.keras"\n\n'
        '[steps.segmentation]\npipeline_class = "pyopia.process.Segment"\nthreshold = 0.85\n\n'
        '[steps.output]\npipeline_class = "pyopia.io.StatsToDisc"\noutput_datafile = "processed/demo"\n'
    )


def _classifier_and_segmentation_schema() -> dict:
    return {
        "steps": {
            "classifier": {
                "pipeline_class": "pyopia.classify.Classify",
                "fields": [
                    {
                        "name": "model_path",
                        "current_value": "m.keras",
                        "has_default": False,
                        "default": None,
                        "description": "",
                    }
                ],
            },
            "segmentation": {
                "pipeline_class": "pyopia.process.Segment",
                "fields": [
                    {
                        "name": "threshold",
                        "current_value": 0.85,
                        "has_default": True,
                        "default": 0.98,
                        "description": "",
                    }
                ],
            },
            # Given real fields here too, not omitted - an omitted step falls back
            # to bare key/value editing (render_step's "else" branch), which shows
            # a plain string's raw value unquoted (`_write_config_with_a_step`'s own
            # threshold field is numeric, so existing tests never hit this) - a real,
            # separate, pre-existing bug (unquoted string round-tripped through
            # _toml_value_from_text on save raises TOMLDecodeError) found while
            # writing these tests, not something these tests are about; give this
            # mock real fields so it doesn't accidentally exercise that path.
            "output": {
                "pipeline_class": "pyopia.io.StatsToDisc",
                "fields": [
                    {
                        "name": "output_datafile",
                        "current_value": "processed/demo",
                        "has_default": False,
                        "default": None,
                        "description": "",
                    }
                ],
            },
        }
    }


async def test_order_insensitive_step_shows_an_enable_switch(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "introspect_config_steps", lambda *a, **k: _classifier_and_segmentation_schema())
    _write_config_with_a_step_and_classifier(tmp_path)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await user.should_see("classifier")

    assert len(user.find(kind=ui.switch).elements) == 1


async def test_order_sensitive_step_has_no_enable_switch(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # segmentation's position in the pipeline matters (it must run after
    # reconstruction/background-correction and before statextract) - re-enabling
    # it after a disable couldn't be placed back in the right spot, since TOML
    # loses cross-table ordering once a step moves to steps_disabled and back.
    # Only order-insensitive steps (classifier/initial/createbackground - always
    # constructed during Pipeline.__init__ regardless of position) get a switch.
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "introspect_config_steps", lambda *a, **k: _classifier_and_segmentation_schema())
    _write_config_with_a_step_and_classifier(tmp_path)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await user.should_see("segmentation")

    switches = user.find(kind=ui.switch).elements
    assert len(switches) == 1  # only classifier's, not segmentation's


async def test_disabling_a_step_and_saving_moves_it_to_steps_disabled(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "introspect_config_steps", lambda *a, **k: _classifier_and_segmentation_schema())
    _write_config_with_a_step_and_classifier(tmp_path)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await user.should_see("classifier")

    switch = user.find(kind=ui.switch).elements.pop()
    switch.value = False

    user.find(kind=ui.button, content="Save changes").click()
    await user.should_see("Configuration saved")

    saved = tomllib.loads((tmp_path / "config.toml").read_text())
    assert "classifier" not in saved.get("steps", {})
    assert saved["steps_disabled"]["classifier"]["pipeline_class"] == "pyopia.classify.Classify"
    assert saved["steps"]["segmentation"]["pipeline_class"] == "pyopia.process.Segment"


async def test_enabling_a_step_with_a_blank_required_field_blocks_save(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The actual fix for the original bug: enabling classifier with model_path
    # still blank must be refused, not silently produce a config that breaks the
    # moment Pipeline construction actually loads it.
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(
        docker_client,
        "introspect_config_steps",
        lambda *a, **k: {
            "steps": {
                # A real fields entry, not omitted - see _classifier_and_segmentation_schema's
                # comment on the pre-existing bare-fallback round-trip bug this sidesteps.
                "output": {
                    "pipeline_class": "pyopia.io.StatsToDisc",
                    "fields": [
                        {
                            "name": "output_datafile",
                            "current_value": "processed/demo",
                            "has_default": False,
                            "default": None,
                            "description": "",
                        }
                    ],
                }
            },
            "steps_disabled": {
                "classifier": {
                    "pipeline_class": "pyopia.classify.Classify",
                    "fields": [
                        {
                            "name": "model_path",
                            "current_value": "",
                            "has_default": False,
                            "default": None,
                            "description": "",
                        }
                    ],
                }
            },
        },
    )
    tmp_path.joinpath("config.toml").write_text(
        '[general]\nraw_files = "images/*.silc"\npixel_size = 24\n\n'
        '[steps.output]\npipeline_class = "pyopia.io.StatsToDisc"\noutput_datafile = "processed/demo"\n\n'
        '[steps_disabled.classifier]\npipeline_class = "pyopia.classify.Classify"\nmodel_path = ""\n'
    )
    original_config_text = tmp_path.joinpath("config.toml").read_text()

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await user.should_see("classifier")

    switch = user.find(kind=ui.switch).elements.pop()
    switch.value = True  # enable it, but model_path is still blank

    user.find(kind=ui.button, content="Save changes").click()
    await user.should_see("needs a value before this step can be enabled")

    assert tmp_path.joinpath("config.toml").read_text() == original_config_text


async def test_generate_default_config_button_shows_confirm_dialog(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "introspect_config_steps", lambda *a, **k: {})
    monkeypatch.setattr(docker_client, "read_pinned_version", lambda *a, **k: None)
    _write_config_with_a_step(tmp_path)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await user.should_see("images/*.silc")

    user.find(kind=ui.button, content="Generate default config").click()

    await user.should_see("Generate a default config.toml?")
    await user.should_see("PyOPIA's own bare")


async def test_explorer_tab_shows_no_raw_files_message_when_pattern_unset(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    _write_config_with_pixel_size(tmp_path)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await asyncio.sleep(0.2)
    user.find(kind=ui.tab, content="2. Raw data explorer").click()

    await user.should_see("doesn't set general.raw_files yet")


async def test_explorer_tab_shows_no_raw_files_message_when_none_match(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    _write_config_with_a_step(tmp_path)  # raw_files = "images/*.silc", but no images/ folder

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await asyncio.sleep(0.2)
    user.find(kind=ui.tab, content="2. Raw data explorer").click()

    await user.should_see("No raw files found matching 'images/*.silc'")


async def test_explorer_tab_shows_a_thumbnail_grid_for_raw_files(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    _write_config_with_a_step(tmp_path)
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    (images_dir / "D20220608T184237.407722.silc").write_bytes(b"")
    (images_dir / "D20220608T184238.407874.silc").write_bytes(b"")

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await asyncio.sleep(0.2)
    user.find(kind=ui.tab, content="2. Raw data explorer").click()

    await user.should_see("Page 1 of 1")
    await user.should_see("D20220608T184237.407722.silc")
    await user.should_see("D20220608T184238.407874.silc")


async def test_explorer_tab_pagination_next_and_previous(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    _write_config_with_a_step(tmp_path)
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    for i in range(13):
        (images_dir / f"D2022060{i:02d}T184237.407722.silc").write_bytes(b"")

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await asyncio.sleep(0.2)
    user.find(kind=ui.tab, content="2. Raw data explorer").click()
    await user.should_see("Page 1 of 2")

    previous_button = user.find(kind=ui.button, content="Previous").elements.pop()
    next_button = user.find(kind=ui.button, content="Next").elements.pop()
    assert not previous_button.enabled
    assert next_button.enabled

    user.find(kind=ui.button, content="Next").click()
    await user.should_see("Page 2 of 2")
    assert previous_button.enabled
    assert not next_button.enabled

    user.find(kind=ui.button, content="Previous").click()
    await user.should_see("Page 1 of 2")


async def test_explorer_tab_select_all_on_page_updates_the_selection_count(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    _write_config_with_a_step(tmp_path)
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    (images_dir / "D20220608T184237.407722.silc").write_bytes(b"")
    (images_dir / "D20220608T184238.407874.silc").write_bytes(b"")

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await asyncio.sleep(0.2)
    user.find(kind=ui.tab, content="2. Raw data explorer").click()
    await user.should_see("Page 1 of 1")

    await user.should_see("0 selected")
    user.find(kind=ui.button, content="Select all on this page").click()
    await user.should_see("2 selected")

    user.find(kind=ui.button, content="Clear selection").click()
    await user.should_see("0 selected")


async def test_explorer_tab_apply_and_clear_raw_files_subset(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    _write_config_with_a_step(tmp_path)
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    (images_dir / "D20220608T184237.407722.silc").write_bytes(b"")
    (images_dir / "D20220608T184238.407874.silc").write_bytes(b"")

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await asyncio.sleep(0.2)
    user.find(kind=ui.tab, content="2. Raw data explorer").click()
    await user.should_see("Page 1 of 1")

    user.find(kind=ui.button, content="Select all on this page").click()
    await user.should_see("2 selected")
    user.find(kind=ui.button, content="Use selected as raw_files").click()
    await user.should_see("Filtered to 2 raw image(s)")

    config = docker_client.load_config(tmp_path)
    assert config["general"]["raw_files"] == docker_client.RAW_FILES_SUBSET_FILENAME
    subset_lines = (tmp_path / docker_client.RAW_FILES_SUBSET_FILENAME).read_text().splitlines()
    assert subset_lines == ["images/D20220608T184237.407722.silc", "images/D20220608T184238.407874.silc"]

    user.find(kind=ui.button, content="Clear subset").click()
    await asyncio.sleep(0.2)
    config = docker_client.load_config(tmp_path)
    assert config["general"]["raw_files"] == "images/*.silc"
    assert not (tmp_path / docker_client.RAW_FILES_SUBSET_FILENAME).exists()


async def test_explorer_tab_shows_a_plain_language_hint_for_a_load_mismatch(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)

    async def fake_generate_thumbnails(
        project_dir: Path,
        raw_paths: list[Path],
        on_image_done: Callable[[Path, str | None], None] | None = None,
        **k: object,
    ) -> dict[str, str]:
        error = "OSError: Could not find a backend to open `foo.silc` with iomode `r`."
        if on_image_done:
            on_image_done(raw_paths[0], error)
        return {str(raw_paths[0]): error}

    monkeypatch.setattr(docker_client, "generate_thumbnails", fake_generate_thumbnails)
    _write_config_with_a_step(tmp_path)
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    (images_dir / "D20220608T184237.407722.silc").write_bytes(b"")

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await asyncio.sleep(0.2)
    user.find(kind=ui.tab, content="2. Raw data explorer").click()

    await user.should_see("load step doesn't match")


async def test_explorer_tab_refresh_button_retries_conversion(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    calls = {"n": 0}

    async def fake_generate_thumbnails(project_dir: Path, raw_paths: list[Path], **k: object) -> dict[str, str]:
        calls["n"] += 1
        return {}

    monkeypatch.setattr(docker_client, "generate_thumbnails", fake_generate_thumbnails)
    _write_config_with_a_step(tmp_path)
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    (images_dir / "D20220608T184237.407722.silc").write_bytes(b"")

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await asyncio.sleep(0.2)
    user.find(kind=ui.tab, content="2. Raw data explorer").click()
    await user.should_see("D20220608T184237.407722.silc")
    assert calls["n"] == 1

    user.find(kind=ui.button, content="Refresh").click()
    await asyncio.sleep(0.2)

    assert calls["n"] == 2


async def test_explorer_tab_hides_stale_thumbnail_while_refresh_is_in_progress(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    _write_config_with_a_step(tmp_path)
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    raw_path = images_dir / "D20220608T184237.407722.silc"
    raw_path.write_bytes(b"")

    # Pre-seed a "cached" thumbnail so the page initially shows a real image, not a spinner.
    thumb_path = docker_client.thumbnail_path(tmp_path, raw_path)
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    thumb_path.write_bytes(b"fake png bytes")

    release_conversion = asyncio.Event()

    async def slow_generate_thumbnails(project_dir: Path, raw_paths: list[Path], **k: object) -> dict[str, str]:
        await release_conversion.wait()
        return {}

    monkeypatch.setattr(docker_client, "generate_thumbnails", slow_generate_thumbnails)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await asyncio.sleep(0.2)
    user.find(kind=ui.tab, content="2. Raw data explorer").click()
    await user.should_see(raw_path.name)
    user.find(ui.image)  # the pre-seeded thumbnail is shown initially - raises if absent

    user.find(kind=ui.button, content="Refresh").click()
    await asyncio.sleep(0.2)

    # Conversion is still pending (release_conversion not set yet) - the stale thumbnail
    # must already be gone, not left showing while the real replacement is generated.
    await user.should_not_see(kind=ui.image)

    release_conversion.set()
    await asyncio.sleep(0.2)


async def test_explorer_tab_converts_images_in_sorted_order(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    calls: list[list[Path]] = []

    async def fake_generate_thumbnails(project_dir: Path, raw_paths: list[Path], **k: object) -> dict[str, str]:
        calls.append(raw_paths)
        return {}

    monkeypatch.setattr(docker_client, "generate_thumbnails", fake_generate_thumbnails)
    _write_config_with_a_step(tmp_path)
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    # Created out of alphabetical order, to prove it's sorting - not filesystem/creation
    # order - that determines the order images are actually sent for conversion in (and
    # therefore the order their grid cells fill in, now that each updates individually).
    for name in ("c.silc", "a.silc", "b.silc"):
        (images_dir / name).write_bytes(b"")

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await asyncio.sleep(0.2)
    user.find(kind=ui.tab, content="2. Raw data explorer").click()
    await user.should_see("Page 1 of 1")
    await asyncio.sleep(0.2)

    assert len(calls) == 1
    assert [p.name for p in calls[0]] == ["a.silc", "b.silc", "c.silc"]


def _write_project_with_one_raw_file_and_thumbnail(tmp_path: Path) -> Path:
    """A project with one segmentation step, one raw file, and its cached thumbnail
    already on disk - so the Raw data explorer's "Preview →" affordance renders
    without needing a real Docker thumbnail-generation call. Returns the raw file's path.
    """
    _write_config_with_a_step(tmp_path)
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    raw_path = images_dir / "D20220608T184237.407722.silc"
    raw_path.write_bytes(b"")
    thumb_path = docker_client.thumbnail_path(tmp_path, raw_path)
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    thumb_path.write_bytes(b"fake png bytes")
    return raw_path


async def _select_sample_in_preview(user: User) -> None:
    """Navigate to Explorer, click its "Preview →" affordance, and wait for the
    Preview tab to show the resulting "Run preview" button - the common setup every
    preview-tab test needs before it can exercise Run preview itself.
    """
    user.find(kind=ui.tab, content="2. Raw data explorer").click()
    await user.should_see("Preview →")
    user.find(kind=ui.button, content="Preview →").click()
    await user.should_see("Run preview")


async def test_preview_tab_prompts_for_a_sample_image_before_one_is_selected(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    _write_config_with_a_step(tmp_path)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await asyncio.sleep(0.2)
    user.find(kind=ui.tab, content="4. Preview").click()

    await user.should_see("Pick a sample image from the Raw data explorer tab first")
    await user.should_not_see("Run preview")


async def test_selecting_a_sample_image_in_explorer_navigates_to_preview_with_it_selected(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    raw_path = _write_project_with_one_raw_file_and_thumbnail(tmp_path)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await asyncio.sleep(0.2)

    await _select_sample_in_preview(user)

    preview_tab = user.find(kind=ui.tab, content="4. Preview").elements.pop()
    assert preview_tab.tabs.value == "preview"
    await user.should_see(raw_path.name)


async def test_run_preview_uses_unsaved_configuration_edits(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The single highest-value test for this feature: it validates the actual design
    # decision behind Preview - it reads live Configuration tab widget values, not
    # what's saved to config.toml, so a user can tweak a parameter and re-preview
    # without a Save step in between.
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: [])
    monkeypatch.setattr(
        docker_client,
        "introspect_config_steps",
        lambda *a, **k: {
            "steps": {
                "segmentation": {
                    "pipeline_class": "pyopia.process.Segment",
                    "fields": [
                        {
                            "name": "threshold",
                            "current_value": 0.85,
                            "has_default": True,
                            "default": 0.98,
                            "description": "",
                        }
                    ],
                }
            }
        },
    )
    _write_project_with_one_raw_file_and_thumbnail(tmp_path)
    captured: dict[str, object] = {}

    async def fake_preview_pipeline(
        project_dir: Path, config: dict, sample_raw_path: Path, image: str, **kwargs: object
    ) -> dict:
        captured["config"] = config
        return {
            "ok": True,
            "particle_count": 0,
            "d50_microns": None,
            "saturation": None,
            "background_step_skipped": False,
            "overlay_path": None,
            "slice_paths": None,
            "z_values": None,
        }

    monkeypatch.setattr(docker_client, "preview_pipeline", fake_preview_pipeline)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await user.should_see("threshold")

    threshold_input = user.find(kind=ui.number, content="threshold").elements.pop()
    threshold_input.value = 0.5  # edited, but "Save changes" is never clicked

    await _select_sample_in_preview(user)
    user.find(kind=ui.button, content="Run preview").click()
    await user.should_see("0 particle(s) found")

    assert captured["config"]["steps"]["segmentation"]["threshold"] == 0.5


async def test_run_preview_shows_particle_count_and_d50_on_success(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: [])
    _write_project_with_one_raw_file_and_thumbnail(tmp_path)
    overlay_path = tmp_path / docker_client.PREVIEW_DIR_NAME / "run1" / "overlay.png"
    overlay_path.parent.mkdir(parents=True)
    overlay_path.write_bytes(b"fake overlay")

    async def fake_preview_pipeline(
        project_dir: Path, config: dict, sample_raw_path: Path, image: str, **kwargs: object
    ) -> dict:
        return {
            "ok": True,
            "particle_count": 7,
            "d50_microns": 42.5,
            "saturation": 3.2,
            "background_step_skipped": False,
            "overlay_path": overlay_path,
            "slice_paths": None,
            "z_values": None,
        }

    monkeypatch.setattr(docker_client, "preview_pipeline", fake_preview_pipeline)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await asyncio.sleep(0.2)

    await _select_sample_in_preview(user)
    user.find(kind=ui.button, content="Run preview").click()

    await user.should_see("7 particle(s) found")
    await user.should_see("d50 (median particle size): 42.5 µm")
    await user.should_see("Detected particles")


async def test_run_preview_shows_background_skipped_caveat_when_relevant(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: [])
    _write_project_with_one_raw_file_and_thumbnail(tmp_path)

    async def fake_preview_pipeline(
        project_dir: Path, config: dict, sample_raw_path: Path, image: str, **kwargs: object
    ) -> dict:
        return {
            "ok": True,
            "particle_count": 1,
            "d50_microns": 10.0,
            "saturation": None,
            "background_step_skipped": True,
            "overlay_path": None,
            "slice_paths": None,
            "z_values": None,
        }

    monkeypatch.setattr(docker_client, "preview_pipeline", fake_preview_pipeline)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await asyncio.sleep(0.2)

    await _select_sample_in_preview(user)
    user.find(kind=ui.button, content="Run preview").click()

    await user.should_see("Background correction was skipped for this preview")


async def test_run_preview_does_not_show_background_skipped_caveat_when_not_relevant(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: [])
    _write_project_with_one_raw_file_and_thumbnail(tmp_path)

    async def fake_preview_pipeline(
        project_dir: Path, config: dict, sample_raw_path: Path, image: str, **kwargs: object
    ) -> dict:
        return {
            "ok": True,
            "particle_count": 1,
            "d50_microns": 10.0,
            "saturation": None,
            "background_step_skipped": False,
            "overlay_path": None,
            "slice_paths": None,
            "z_values": None,
        }

    monkeypatch.setattr(docker_client, "preview_pipeline", fake_preview_pipeline)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await asyncio.sleep(0.2)

    await _select_sample_in_preview(user)
    user.find(kind=ui.button, content="Run preview").click()
    await user.should_see("1 particle(s) found")

    await user.should_not_see("Background correction was skipped")


async def test_run_preview_shows_friendly_message_on_pipeline_failure(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: [])
    _write_project_with_one_raw_file_and_thumbnail(tmp_path)

    async def fake_preview_pipeline(
        project_dir: Path, config: dict, sample_raw_path: Path, image: str, **kwargs: object
    ) -> dict:
        return {"ok": False, "error": "ValueError: threshold must be between 0 and 1"}

    monkeypatch.setattr(docker_client, "preview_pipeline", fake_preview_pipeline)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await asyncio.sleep(0.2)

    await _select_sample_in_preview(user)
    user.find(kind=ui.button, content="Run preview").click()

    await user.should_see("ValueError: threshold must be between 0 and 1")


async def test_depth_slider_swaps_slice_image_with_no_further_docker_call(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The actual zero-recompute guarantee this feature exists to provide: once a holo
    # preview has run, dragging the depth slider must never call preview_pipeline again.
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: [])
    _write_project_with_one_raw_file_and_thumbnail(tmp_path)
    run_dir = tmp_path / docker_client.PREVIEW_DIR_NAME / "run1"
    run_dir.mkdir(parents=True)
    slice_paths = [run_dir / f"slice-{i:04d}.png" for i in range(3)]
    for slice_path in slice_paths:
        slice_path.write_bytes(b"fake slice")
    call_count = {"n": 0}

    async def fake_preview_pipeline(
        project_dir: Path, config: dict, sample_raw_path: Path, image: str, **kwargs: object
    ) -> dict:
        call_count["n"] += 1
        return {
            "ok": True,
            "particle_count": 0,
            "d50_microns": None,
            "saturation": None,
            "background_step_skipped": False,
            "overlay_path": None,
            "slice_paths": slice_paths,
            "z_values": [0.0, 0.5, 1.0],
        }

    monkeypatch.setattr(docker_client, "preview_pipeline", fake_preview_pipeline)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await asyncio.sleep(0.2)

    await _select_sample_in_preview(user)
    user.find(kind=ui.button, content="Run preview").click()
    await user.should_see("Depth: 0.50 mm")  # starts on the middle slice (index 1)
    assert call_count["n"] == 1

    slider = user.find(kind=ui.slider).elements.pop()
    slider.value = 0

    await user.should_see("Depth: 0.00 mm")
    assert call_count["n"] == 1  # dragging the slider must never call preview_pipeline again


async def test_depth_slider_does_not_appear_for_a_non_holo_result(
    user: User, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(docker_client, "check_docker", lambda: docker_client.DockerStatus.AVAILABLE)
    monkeypatch.setattr(docker_client, "list_available_versions", lambda **kwargs: [])
    _write_project_with_one_raw_file_and_thumbnail(tmp_path)

    async def fake_preview_pipeline(
        project_dir: Path, config: dict, sample_raw_path: Path, image: str, **kwargs: object
    ) -> dict:
        return {
            "ok": True,
            "particle_count": 2,
            "d50_microns": 10.0,
            "saturation": None,
            "background_step_skipped": False,
            "overlay_path": None,
            "slice_paths": None,
            "z_values": None,
        }

    monkeypatch.setattr(docker_client, "preview_pipeline", fake_preview_pipeline)

    await user.open("/")
    folder_input = user.find(ui.input).elements.pop()
    folder_input.value = str(tmp_path)
    await asyncio.sleep(0.2)

    await _select_sample_in_preview(user)
    user.find(kind=ui.button, content="Run preview").click()
    await user.should_see("2 particle(s) found")

    await user.should_not_see(kind=ui.slider)
