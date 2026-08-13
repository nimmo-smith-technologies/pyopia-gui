# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Nimmo Smith Technologies Limited

import platform
import subprocess
import sys
from pathlib import Path

import pytest

from pyopia_gui import docker_client


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


def test_interpret_failure_recognises_manifest_unknown() -> None:
    lines = ["manifest for ghcr.io/sintef/pyopia:nonexistent not found: manifest unknown"]

    assert docker_client.interpret_failure(lines) is not None


def test_interpret_failure_recognises_daemon_unreachable() -> None:
    lines = ["Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?"]

    assert docker_client.interpret_failure(lines) is not None


def test_interpret_failure_recognises_stall() -> None:
    lines = [
        "No output received for 180s - this usually means a network operation "
        "(like pulling the Docker image) has stalled. Stopping."
    ]

    assert docker_client.interpret_failure(lines) is not None


def test_interpret_failure_returns_none_for_unrecognised_output() -> None:
    lines = ["PYOPIA VERSION 2.16.23", "LOAD CONFIG", "some unrelated error nobody has seen before"]

    assert docker_client.interpret_failure(lines) is None


def test_extract_pyopia_version_reads_real_process_output() -> None:
    # Actual first lines of `docker run ... process config.toml` output, captured earlier.
    lines = ["PYOPIA VERSION 2.16.23", "LOAD CONFIG", "OBTAIN IMAGE LIST"]

    assert docker_client.extract_pyopia_version(lines) == "2.16.23"


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
@pytest.mark.parametrize("status", [docker_client.DockerStatus.NOT_INSTALLED, docker_client.DockerStatus.NOT_RUNNING])
def test_setup_guidance_is_non_empty_for_every_status_and_platform(
    monkeypatch: pytest.MonkeyPatch, os_name: str, status: docker_client.DockerStatus
) -> None:
    monkeypatch.setattr(platform, "system", lambda: os_name)

    assert docker_client.setup_guidance(status)


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
