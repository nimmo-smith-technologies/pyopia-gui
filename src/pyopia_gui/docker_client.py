# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Nimmo Smith Technologies Limited

import asyncio
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

PYOPIA_IMAGE = os.environ.get("PYOPIA_GUI_DOCKER_IMAGE", "ghcr.io/sintef/pyopia:latest")


def is_docker_available() -> bool:
    """Whether the `docker` CLI is installed and its daemon is reachable."""
    try:
        subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            timeout=5,
            check=True,
        )
        return True
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def _volume_args(directory: Path) -> list[str]:
    """Mount `directory` into the container at the same path, and set it as the working dir.

    Keeping host and container paths identical is what lets a config.toml with paths
    under `directory` resolve unchanged inside the container.
    """
    resolved = str(directory.resolve())
    return ["-v", f"{resolved}:{resolved}", "-w", resolved]


def _user_args() -> list[str]:
    """Match the container process to the host user, so output files aren't root-owned.

    os.getuid()/getgid() don't exist on Windows - Docker Desktop there has no
    equivalent host-UID concept, so there's nothing to pass.
    """
    if not hasattr(os, "getuid"):
        return []
    return ["--user", f"{os.getuid()}:{os.getgid()}"]


def init_project_command(parent_dir: Path, project_name: str) -> list[str]:
    """Build the command to create a new example PyOPIA project named `project_name` under `parent_dir`."""
    return [
        "docker",
        "run",
        "--rm",
        *_volume_args(parent_dir),
        PYOPIA_IMAGE,
        "init-project",
        project_name,
        "--example-data",
    ]


def process_command(project_dir: Path, config_filename: str = "config.toml") -> list[str]:
    """Build the command to run PyOPIA processing against `config_filename` inside `project_dir`."""
    return [
        "docker",
        "run",
        "--rm",
        *_user_args(),
        *_volume_args(project_dir),
        PYOPIA_IMAGE,
        "process",
        config_filename,
    ]


def merge_mfdata_command(project_dir: Path, path_to_data: str = "processed") -> list[str]:
    """Build the command to merge per-image STATS.nc files under `path_to_data` into one.

    `process` writes one -STATS.nc file per input image; make-montage needs the single
    combined file this produces.
    """
    return [
        "docker",
        "run",
        "--rm",
        *_user_args(),
        *_volume_args(project_dir),
        PYOPIA_IMAGE,
        "merge-mfdata",
        path_to_data,
    ]


def make_montage_command(project_dir: Path, stats_filename: str) -> list[str]:
    """Build the command to create montage.png from a processed STATS.nc file."""
    return [
        "docker",
        "run",
        "--rm",
        *_user_args(),
        *_volume_args(project_dir),
        PYOPIA_IMAGE,
        "make-montage",
        stats_filename,
    ]


def stats_filename(project_name: str) -> str:
    """The STATS.nc path an example project's generated config writes to, relative to the project dir.

    Matches the `output_datafile = processed/<project_name>` convention PyOPIA's own
    `init-project`-generated config uses (see pyopia.instrument.silcam.generate_config).
    """
    return f"processed/{project_name}-STATS.nc"


async def run_streamed(command: list[str], on_line: Callable[[str], None]) -> int:
    """Run `command`, calling `on_line` for each combined stdout/stderr line as it arrives.

    Returns the process's exit code.
    """
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert process.stdout is not None
    async for raw_line in process.stdout:
        on_line(raw_line.decode(errors="replace").rstrip("\r\n"))
    return await process.wait()
