# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Nimmo Smith Technologies Limited

import subprocess
import sys
from pathlib import Path

import pytest

from pyopia_gui import docker_client


def test_init_project_command_mounts_parent_dir_and_passes_example_flag(tmp_path: Path) -> None:
    command = docker_client.init_project_command(tmp_path, "demo")

    assert command[:3] == ["docker", "run", "--rm"]
    assert f"{tmp_path}:{tmp_path}" in command
    assert command[-3:] == ["init-project", "demo", "--example-data"]


def test_process_command_mounts_project_dir_and_passes_config(tmp_path: Path) -> None:
    command = docker_client.process_command(tmp_path, "config.toml")

    assert f"{tmp_path}:{tmp_path}" in command
    assert command[-2:] == ["process", "config.toml"]


def test_process_command_omits_user_flag_on_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr("os.getuid", raising=False)

    command = docker_client.process_command(tmp_path)

    assert "--user" not in command


def test_process_command_matches_host_user_on_posix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if not hasattr(__import__("os"), "getuid"):
        pytest.skip("no os.getuid on this platform")

    command = docker_client.process_command(tmp_path)

    assert "--user" in command


def test_merge_mfdata_command_passes_processed_folder(tmp_path: Path) -> None:
    command = docker_client.merge_mfdata_command(tmp_path)

    assert command[-2:] == ["merge-mfdata", "processed"]


def test_make_montage_command_passes_stats_file(tmp_path: Path) -> None:
    command = docker_client.make_montage_command(tmp_path, "processed/demo-STATS.nc")

    assert command[-2:] == ["make-montage", "processed/demo-STATS.nc"]


def test_stats_filename_matches_init_project_output_convention() -> None:
    assert docker_client.stats_filename("demo") == "processed/demo-STATS.nc"


def test_is_docker_available_false_when_docker_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("no docker")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert docker_client.is_docker_available() is False


def test_is_docker_available_true_when_docker_responds(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args, returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert docker_client.is_docker_available() is True


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
