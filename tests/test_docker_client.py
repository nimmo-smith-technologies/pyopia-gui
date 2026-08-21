# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Nimmo Smith Technologies Limited

import inspect
import io
import json
import platform
import subprocess
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path
from urllib.error import URLError

import pytest

from pyopia_gui import docker_client


def test_generate_config_command_mounts_project_dir_and_passes_args(tmp_path: Path) -> None:
    command = docker_client.generate_config_command(
        tmp_path, "silcam", "images/*.silc", "model.keras", "processed", "demo"
    )

    assert command[:3] == ["docker", "run", "--rm"]
    assert f"{tmp_path}:/workspace" in command
    assert command[-6:] == ["generate-config", "silcam", "images/*.silc", "model.keras", "processed", "demo"]


def test_init_project_command_mounts_parent_dir_and_passes_example_flag(tmp_path: Path) -> None:
    command = docker_client.init_project_command(tmp_path, "demo")

    assert command[:3] == ["docker", "run", "--rm"]
    assert f"{tmp_path}:/workspace" in command
    assert "-w" in command
    assert command[command.index("-w") + 1] == "/workspace"
    assert command[-3:] == ["init-project", "demo", "--example-data"]


def test_process_command_mounts_project_dir_and_passes_config(tmp_path: Path) -> None:
    command = docker_client.process_command(tmp_path, "config.toml")

    assert f"{tmp_path}:/workspace" in command
    assert command[-2:] == ["process", "config.toml"]


def test_volume_args_use_a_fixed_container_path_not_the_host_path(tmp_path: Path) -> None:
    # A Windows host path (C:\Users\...) isn't valid *inside* a Linux container at
    # all - the container side must be a fixed, always-valid Linux path.
    command = docker_client.process_command(tmp_path)

    assert f"{tmp_path}:{tmp_path}" not in command
    assert f"{tmp_path}:/workspace" in command


def test_process_command_omits_user_flag_on_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr("os.getuid", raising=False)

    command = docker_client.process_command(tmp_path)

    assert "--user" not in command


def test_process_command_matches_host_user_on_posix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if not hasattr(__import__("os"), "getuid"):
        pytest.skip("no os.getuid on this platform")

    command = docker_client.process_command(tmp_path)

    assert "--user" in command


def _write_config(project_dir: Path, output_datafile: str = "processed/demo") -> None:
    (project_dir / "config.toml").write_text(f'[steps.output]\noutput_datafile = "{output_datafile}"\n')


def test_merge_mfdata_command_uses_output_datafile_directory(tmp_path: Path) -> None:
    _write_config(tmp_path, output_datafile="processed/demo")

    command = docker_client.merge_mfdata_command(tmp_path)

    assert command[-2:] == ["merge-mfdata", "processed"]


def test_merge_mfdata_command_handles_output_datafile_with_no_subfolder(tmp_path: Path) -> None:
    _write_config(tmp_path, output_datafile="demo")

    command = docker_client.merge_mfdata_command(tmp_path)

    assert command[-2:] == ["merge-mfdata", "."]


def test_make_montage_command_passes_stats_file(tmp_path: Path) -> None:
    command = docker_client.make_montage_command(tmp_path, "processed/demo-STATS.nc")

    assert command[-2:] == ["make-montage", "processed/demo-STATS.nc"]


def test_stats_filename_reads_output_datafile_from_config(tmp_path: Path) -> None:
    _write_config(tmp_path, output_datafile="processed/demo")

    assert docker_client.stats_filename(tmp_path) == "processed/demo-STATS.nc"


def test_pixel_size_reads_general_config(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text("[general]\npixel_size = 24\n")

    assert docker_client.pixel_size(tmp_path) == 24


def test_image_for_version_uses_mirror_tag(tmp_path: Path) -> None:
    assert docker_client.image_for_version("9.16.20") == "ghcr.io/nimmo-smith-technologies/pyopia:9.16.20"


def test_image_for_version_falls_back_to_default_when_none() -> None:
    assert docker_client.image_for_version(None) == docker_client.PYOPIA_IMAGE


def test_image_for_version_ignores_version_when_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYOPIA_GUI_DOCKER_IMAGE", "ghcr.io/sintef/pyopia:latest")

    assert docker_client.image_for_version("9.16.20") == "ghcr.io/sintef/pyopia:latest"


def _fake_response(payload: object) -> io.BytesIO:
    return io.BytesIO(json.dumps(payload).encode())


def test_list_available_versions_sorts_newest_first_and_skips_non_version_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(request: urllib.request.Request, timeout: float) -> io.BytesIO:
        if "token" in request.full_url:
            return _fake_response({"token": "fake-token"})
        return _fake_response({"tags": ["latest", "main", "9.16.20", "9.16.23", "9.9.1"]})

    monkeypatch.setattr(docker_client.urllib.request, "urlopen", fake_urlopen)

    assert docker_client.list_available_versions() == ["9.16.23", "9.16.20", "9.9.1"]


def test_list_available_versions_returns_empty_on_network_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_url_error(request: urllib.request.Request, timeout: float) -> None:
        raise URLError("offline")

    monkeypatch.setattr(docker_client.urllib.request, "urlopen", raise_url_error)

    assert docker_client.list_available_versions() == []


def test_list_available_versions_returns_empty_on_unexpected_response(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: urllib.request.Request, timeout: float) -> io.BytesIO:
        if "token" in request.full_url:
            return _fake_response({"token": "fake-token"})
        return _fake_response({"unexpected": "shape"})

    monkeypatch.setattr(docker_client.urllib.request, "urlopen", fake_urlopen)

    assert docker_client.list_available_versions() == []


def test_read_pinned_version_returns_none_when_no_stats_file_yet(tmp_path: Path) -> None:
    _write_config(tmp_path)

    assert docker_client.read_pinned_version(tmp_path) is None


def test_read_pinned_version_returns_none_for_invalid_project(tmp_path: Path) -> None:
    assert docker_client.read_pinned_version(tmp_path) is None


def test_read_pinned_version_reads_version_from_existing_stats_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, output_datafile="processed/demo")
    stats_path = tmp_path / "processed" / "demo-STATS.nc"
    stats_path.parent.mkdir(parents=True)
    stats_path.write_bytes(b"")

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(command, returncode=0, stdout="9.16.23\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert docker_client.read_pinned_version(tmp_path) == "9.16.23"


def test_read_pinned_version_returns_none_when_docker_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_config(tmp_path, output_datafile="processed/demo")
    stats_path = tmp_path / "processed" / "demo-STATS.nc"
    stats_path.parent.mkdir(parents=True)
    stats_path.write_bytes(b"")

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(command, returncode=1, stdout="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert docker_client.read_pinned_version(tmp_path) is None


def test_write_config_round_trips_through_read(tmp_path: Path) -> None:
    original = {"general": {"pixel_size": 24.5}, "steps": {"output": {"output_datafile": "processed/demo"}}}

    docker_client.write_config(tmp_path, original)

    assert docker_client._load_config(tmp_path, "config.toml") == original


def test_write_config_overwrites_existing_file(tmp_path: Path) -> None:
    _write_config(tmp_path, output_datafile="old/path")

    docker_client.write_config(tmp_path, {"steps": {"output": {"output_datafile": "new/path"}}})

    assert docker_client._output_datafile(tmp_path, "config.toml") == "new/path"


def test_parse_numpydoc_params_extracts_names_and_descriptions() -> None:
    doc = """Summary line.

    Parameters
    ----------
    threshold : float, optional
        segmentation threshold, by default 0.98
    fill_holes : bool
        fills holes if True

    Returns
    -------
    data : Data
        the result
    """

    params = docker_client.parse_numpydoc_params(inspect.cleandoc(doc))

    assert params == {
        "threshold": "segmentation threshold, by default 0.98",
        "fill_holes": "fills holes if True",
    }


def test_parse_numpydoc_params_returns_empty_for_no_docstring() -> None:
    assert docker_client.parse_numpydoc_params(None) == {}


def test_parse_numpydoc_params_returns_empty_when_no_parameters_section() -> None:
    doc = """Just a summary, no Parameters section at all.

    Returns
    -------
    data : Data
        the result
    """

    assert docker_client.parse_numpydoc_params(inspect.cleandoc(doc)) == {}


def test_parse_numpydoc_params_stops_at_the_next_section_when_last() -> None:
    # "Parameters" as the final section (no "Returns" after it) - end should be len(lines),
    # not crash or swallow trailing unrelated content.
    doc = """Summary.

    Parameters
    ----------
    average_window : int
        number of images to use
    """

    assert docker_client.parse_numpydoc_params(inspect.cleandoc(doc)) == {"average_window": "number of images to use"}


def test_docstring_summary_stops_at_the_first_blank_line() -> None:
    doc = """A step that merges holo-specific statistics into output stats.

    Parameters
    ----------
    None
    """

    assert (
        docker_client.docstring_summary(inspect.cleandoc(doc))
        == "A step that merges holo-specific statistics into output stats."
    )


def test_docstring_summary_strips_sphinx_cross_reference_markup() -> None:
    doc = "A class that calls :func:`pyopia.background.correct_im_accurate` internally."

    assert (
        docker_client.docstring_summary(doc) == "A class that calls pyopia.background.correct_im_accurate internally."
    )


def test_docstring_summary_returns_empty_string_for_no_docstring() -> None:
    assert docker_client.docstring_summary(None) == ""


def test_introspect_config_steps_returns_empty_dict_on_docker_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path)

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(command, returncode=1, stdout="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert docker_client.introspect_config_steps(tmp_path) == {}


def test_introspect_config_steps_returns_empty_dict_on_unparseable_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path)

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(command, returncode=0, stdout="not json")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert docker_client.introspect_config_steps(tmp_path) == {}


def test_introspect_config_steps_parses_json_from_the_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path)
    expected = {"segmentation": {"pipeline_class": "pyopia.process.Segment", "fields": [{"name": "threshold"}]}}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        assert "--entrypoint" in command
        return subprocess.CompletedProcess(command, returncode=0, stdout=json.dumps(expected))

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert docker_client.introspect_config_steps(tmp_path) == expected


def test_resolve_pipeline_class_imports_and_returns_the_named_class() -> None:
    assert docker_client.resolve_pipeline_class("pathlib.PurePosixPath") is __import__("pathlib").PurePosixPath


def test_thumbnail_path_serves_browser_viewable_extensions_directly(tmp_path: Path) -> None:
    raw_path = tmp_path / "images" / "frame.png"

    assert docker_client.thumbnail_path(tmp_path, raw_path) == raw_path


def test_thumbnail_path_uses_cache_folder_for_other_extensions(tmp_path: Path) -> None:
    raw_path = tmp_path / "images" / "frame.silc"

    result = docker_client.thumbnail_path(tmp_path, raw_path)

    assert result == tmp_path / docker_client.THUMBNAIL_DIR_NAME / "frame.png"


async def test_generate_thumbnails_skips_docker_entirely_for_browser_viewable_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail_if_called(command: list[str], on_line: Callable[[str], None]) -> int:
        raise AssertionError("should not shell out to Docker for an already-viewable file")

    monkeypatch.setattr(docker_client, "run_streamed", fail_if_called)
    raw_path = tmp_path / "images" / "frame.png"

    assert await docker_client.generate_thumbnails(tmp_path, [raw_path]) == {}


async def test_generate_thumbnails_returns_an_error_per_file_on_docker_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_run_streamed(command: list[str], on_line: Callable[[str], None]) -> int:
        return 1

    monkeypatch.setattr(docker_client, "run_streamed", fake_run_streamed)
    raw_path = tmp_path / "images" / "frame.silc"

    errors = await docker_client.generate_thumbnails(tmp_path, [raw_path])

    assert str(raw_path) in errors


async def test_generate_thumbnails_reports_progress_and_maps_container_errors_back_to_host_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok_path = tmp_path / "images" / "ok.silc"
    bad_path = tmp_path / "images" / "bad.silc"
    progress_calls: list[tuple[int, int]] = []
    done_calls: list[tuple[Path, str | None]] = []

    async def fake_run_streamed(command: list[str], on_line: Callable[[str], None]) -> int:
        # The container only ever sees /workspace-relative paths, not the host ones.
        on_line(
            "THUMBNAIL_DONE "
            + json.dumps({"done": 1, "total": 2, "raw_path": "/workspace/images/ok.silc", "error": None})
        )
        on_line(
            "THUMBNAIL_DONE "
            + json.dumps({"done": 2, "total": 2, "raw_path": "/workspace/images/bad.silc", "error": "OSError: boom"})
        )
        return 0

    monkeypatch.setattr(docker_client, "run_streamed", fake_run_streamed)

    errors = await docker_client.generate_thumbnails(
        tmp_path,
        [ok_path, bad_path],
        on_progress=lambda done, total: progress_calls.append((done, total)),
        on_image_done=lambda raw_path, error: done_calls.append((raw_path, error)),
    )

    assert errors == {str(bad_path): "OSError: boom"}
    assert progress_calls == [(1, 2), (2, 2)]
    assert done_calls == [(ok_path, None), (bad_path, "OSError: boom")]


def test_validate_project_missing_config(tmp_path: Path) -> None:
    assert docker_client.validate_project(tmp_path) == f"No config.toml found in {tmp_path}"


def test_validate_project_invalid_toml(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text("this is not valid toml [[[")

    error = docker_client.validate_project(tmp_path)

    assert error is not None
    assert "isn't valid TOML" in error


def test_validate_project_missing_output_datafile_key(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text("[general]\nraw_files = 'images/*.silc'\n")

    error = docker_client.validate_project(tmp_path)

    assert error is not None
    assert "output_datafile" in error


def test_validate_project_valid_config(tmp_path: Path) -> None:
    _write_config(tmp_path)

    assert docker_client.validate_project(tmp_path) is None


def test_interpret_failure_recognises_real_denied_pull_output() -> None:
    # Actual output captured from `docker run` against the currently-private ghcr.io/sintef/pyopia.
    lines = [
        "Unable to find image 'ghcr.io/sintef/pyopia:latest' locally",
        "docker: Error response from daemon: error from registry: denied",
        "denied",
    ]

    message = docker_client.interpret_failure(lines)

    assert message is not None
    assert docker_client.PYOPIA_IMAGE in message


def test_interpret_failure_recognises_pull_access_denied() -> None:
    lines = ["docker: pull access denied for pyopia, repository does not exist or may require 'docker login'"]

    assert docker_client.interpret_failure(lines) is not None


def test_interpret_failure_recognises_daemon_unreachable() -> None:
    lines = ["Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?"]

    assert docker_client.interpret_failure(lines) is not None


def test_interpret_failure_does_not_blame_a_successful_pull_for_a_later_stall() -> None:
    # Real case: Docker always prints "Unable to find image ... locally" on any
    # first-time run, pull or no pull failure - it's not itself a failure signal.
    # A run that pulled fine and then stalled during the *next* step (e.g. PyOPIA's
    # own silent, unprogressed example-data download) must be reported as a stall,
    # not misdiagnosed as a failed image pull.
    lines = [
        "Unable to find image 'ghcr.io/nimmo-smith-technologies/pyopia:latest' locally",
        "latest: Pulling from nimmo-smith-technologies/pyopia",
        "Pull complete",
        "Status: Downloaded newer image for ghcr.io/nimmo-smith-technologies/pyopia:latest",
        "No output received for 600s - this usually means a network operation "
        "(like pulling the Docker image) has stalled. Stopping.",
    ]

    message = docker_client.interpret_failure(lines)

    assert message is not None
    assert "stalled" in message
    assert "Couldn't pull" not in message


def test_interpret_failure_recognises_stall() -> None:
    lines = [
        "No output received for 180s - this usually means a network operation "
        "(like pulling the Docker image) has stalled. Stopping."
    ]

    assert docker_client.interpret_failure(lines) is not None


def test_interpret_failure_returns_none_for_unrecognised_output() -> None:
    lines = ["PYOPIA VERSION 9.16.23", "LOAD CONFIG", "some unrelated error nobody has seen before"]

    assert docker_client.interpret_failure(lines) is None


def test_interpret_thumbnail_error_recognises_a_load_class_format_mismatch() -> None:
    # The real error a mismatched steps.load.pipeline_class produces (e.g. holo's Load
    # pointed at silcam .silc files) - imageio can't recognise the raw format at all.
    error = "OSError: Could not find a backend to open `/workspace/images/foo.silc`` with iomode `r`."

    hint = docker_client.interpret_thumbnail_error(error)

    assert hint is not None
    assert "load step doesn't match" in hint


def test_interpret_thumbnail_error_returns_none_for_unrecognised_error() -> None:
    assert docker_client.interpret_thumbnail_error("PermissionError: something else entirely") is None


def test_extract_pyopia_version_reads_real_process_output() -> None:
    # Actual first lines of `docker run ... process config.toml` output, captured earlier.
    lines = ["PYOPIA VERSION 9.16.23", "LOAD CONFIG", "OBTAIN IMAGE LIST"]

    assert docker_client.extract_pyopia_version(lines) == "9.16.23"


def test_extract_pyopia_version_returns_none_when_absent() -> None:
    lines = ["LOAD CONFIG", "OBTAIN IMAGE LIST"]

    assert docker_client.extract_pyopia_version(lines) is None


def test_check_docker_not_installed_when_docker_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("no docker")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert docker_client.check_docker() is docker_client.DockerStatus.NOT_INSTALLED


def test_check_docker_not_running_when_daemon_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args, returncode=1)

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert docker_client.check_docker() is docker_client.DockerStatus.NOT_RUNNING


def test_check_docker_not_running_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd="docker", timeout=5)

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert docker_client.check_docker() is docker_client.DockerStatus.NOT_RUNNING


def test_check_docker_available_when_docker_responds(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args, returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert docker_client.check_docker() is docker_client.DockerStatus.AVAILABLE


def test_setup_guidance_is_empty_for_available_status() -> None:
    assert docker_client.setup_guidance(docker_client.DockerStatus.AVAILABLE) == ""


@pytest.mark.parametrize("os_name", ["Linux", "Darwin", "Windows", "SomeOtherOS"])
def test_setup_guidance_not_installed_is_non_empty_for_every_platform(
    monkeypatch: pytest.MonkeyPatch, os_name: str
) -> None:
    # Each platform is a genuinely distinct return statement here.
    monkeypatch.setattr(platform, "system", lambda: os_name)

    assert docker_client.setup_guidance(docker_client.DockerStatus.NOT_INSTALLED)


@pytest.mark.parametrize("os_name", ["Linux", "SomeOtherOS"])
def test_setup_guidance_not_running_is_non_empty(monkeypatch: pytest.MonkeyPatch, os_name: str) -> None:
    # Only two real branches for NOT_RUNNING (Linux vs. everything else) - Darwin/Windows
    # would just re-exercise the same "everything else" branch as SomeOtherOS.
    monkeypatch.setattr(platform, "system", lambda: os_name)

    assert docker_client.setup_guidance(docker_client.DockerStatus.NOT_RUNNING)


def test_setup_guidance_has_no_embedded_links(monkeypatch: pytest.MonkeyPatch) -> None:
    # A markdown link inside the native app's window would navigate the app's own
    # embedded webview away from itself, with no way back - any URL must come from
    # setup_guidance_url() instead, wired to open the OS's real browser.
    monkeypatch.setattr(platform, "system", lambda: "Windows")

    assert "](http" not in docker_client.setup_guidance(docker_client.DockerStatus.NOT_INSTALLED)


def test_setup_guidance_url_is_none_when_available() -> None:
    assert docker_client.setup_guidance_url(docker_client.DockerStatus.AVAILABLE) is None


def test_setup_guidance_url_is_none_when_not_running() -> None:
    assert docker_client.setup_guidance_url(docker_client.DockerStatus.NOT_RUNNING) is None


def test_setup_guidance_url_is_none_on_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    # Linux install is a terminal command, not a webpage to link to.
    monkeypatch.setattr(platform, "system", lambda: "Linux")

    assert docker_client.setup_guidance_url(docker_client.DockerStatus.NOT_INSTALLED) is None


@pytest.mark.parametrize("os_name", ["Darwin", "Windows"])
def test_setup_guidance_url_points_at_docker_desktop(monkeypatch: pytest.MonkeyPatch, os_name: str) -> None:
    monkeypatch.setattr(platform, "system", lambda: os_name)

    assert (
        docker_client.setup_guidance_url(docker_client.DockerStatus.NOT_INSTALLED) == docker_client.DOCKER_DESKTOP_URL
    )


def test_setup_guidance_url_falls_back_for_unknown_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "SomeOtherOS")

    assert (
        docker_client.setup_guidance_url(docker_client.DockerStatus.NOT_INSTALLED)
        == docker_client.DOCKER_GET_STARTED_URL
    )


async def test_run_streamed_yields_lines_and_returns_exit_code() -> None:
    lines: list[str] = []
    command = [sys.executable, "-c", "print('first'); print('second')"]

    exit_code = await docker_client.run_streamed(command, lines.append)

    assert lines == ["first", "second"]
    assert exit_code == 0


async def test_run_streamed_returns_nonzero_exit_code_on_failure() -> None:
    command = [sys.executable, "-c", "import sys; sys.exit(3)"]

    exit_code = await docker_client.run_streamed(command, lambda _line: None)

    assert exit_code == 3


async def test_run_streamed_times_out_on_prolonged_inactivity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_client, "INACTIVITY_TIMEOUT_SECONDS", 0.2)
    lines: list[str] = []
    # Sleeps well past the (patched, tiny) inactivity timeout without printing anything -
    # simulates a genuinely stalled operation (e.g. a stuck image pull).
    command = [sys.executable, "-c", "import time; time.sleep(5)"]

    exit_code = await docker_client.run_streamed(command, lines.append)

    assert exit_code == -1
    assert any("No output received for" in line for line in lines)
