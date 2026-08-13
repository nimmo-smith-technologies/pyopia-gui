# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Nimmo Smith Technologies Limited

import asyncio
import os
import platform
import subprocess
import tomllib
from collections.abc import Callable
from enum import Enum
from pathlib import Path

PYOPIA_IMAGE = os.environ.get("PYOPIA_GUI_DOCKER_IMAGE", "ghcr.io/sintef/pyopia:latest")


class DockerStatus(Enum):
    NOT_INSTALLED = "not_installed"
    NOT_RUNNING = "not_running"
    AVAILABLE = "available"


def check_docker() -> DockerStatus:
    """Check whether the `docker` CLI is installed and its daemon is reachable."""
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            timeout=5,
        )
    except FileNotFoundError:
        return DockerStatus.NOT_INSTALLED
    except subprocess.TimeoutExpired:
        return DockerStatus.NOT_RUNNING
    return DockerStatus.AVAILABLE if result.returncode == 0 else DockerStatus.NOT_RUNNING


_LINUX_INSTALL_STEPS = """\
Docker isn't installed. Open a terminal and run:

```
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

Then log out and back in (so the permission change takes effect), and click **Recheck**.\
"""

_MACOS_INSTALL_STEPS = """\
Docker isn't installed. Download and install
[Docker Desktop for Mac](https://www.docker.com/products/docker-desktop/), open it once,
then click **Recheck**.\
"""

_WINDOWS_INSTALL_STEPS = """\
Docker isn't installed. Download and install
[Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/) - it will
guide you through enabling WSL2 if needed - then click **Recheck**.\
"""

_FALLBACK_INSTALL_STEPS = """\
Docker isn't installed. See [docs.docker.com/get-docker](https://docs.docker.com/get-docker/)
for your platform, then click **Recheck**.\
"""

_LINUX_NOT_RUNNING_STEPS = """\
Docker is installed but isn't reachable. If you just installed it, log out and back in so
your user's `docker` group membership takes effect. Otherwise, start it with:

```
sudo systemctl start docker
```

Then click **Recheck**.\
"""

_DESKTOP_NOT_RUNNING_STEPS = """\
Docker is installed but isn't running. Open Docker Desktop and wait for it to finish
starting, then click **Recheck**.\
"""


def setup_guidance(status: DockerStatus) -> str:
    """Plain-language, platform-specific markdown guidance for a non-AVAILABLE Docker status."""
    os_name = platform.system()  # 'Linux', 'Darwin', 'Windows'

    if status == DockerStatus.NOT_INSTALLED:
        if os_name == "Linux":
            return _LINUX_INSTALL_STEPS
        if os_name == "Darwin":
            return _MACOS_INSTALL_STEPS
        if os_name == "Windows":
            return _WINDOWS_INSTALL_STEPS
        return _FALLBACK_INSTALL_STEPS

    if status == DockerStatus.NOT_RUNNING:
        return _LINUX_NOT_RUNNING_STEPS if os_name == "Linux" else _DESKTOP_NOT_RUNNING_STEPS

    return ""


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


def merge_mfdata_command(project_dir: Path, config_filename: str = "config.toml") -> list[str]:
    """Build the command to merge per-image STATS.nc files into the single combined file.

    `process` writes one -STATS.nc file per input image; make-montage needs the single
    combined file this produces. The folder to merge is the directory part of the
    project's own `steps.output.output_datafile`, so this works for any project's config,
    not just ones created via `init-project`.
    """
    path_to_data = os.path.dirname(_output_datafile(project_dir, config_filename)) or "."
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


def _load_config(project_dir: Path, config_filename: str) -> dict:
    with (project_dir / config_filename).open("rb") as f:
        return tomllib.load(f)


def _output_datafile(project_dir: Path, config_filename: str) -> str:
    """The `steps.output.output_datafile` prefix from the project's config, e.g. "processed/demo"."""
    return _load_config(project_dir, config_filename)["steps"]["output"]["output_datafile"]


def stats_filename(project_dir: Path, config_filename: str = "config.toml") -> str:
    """The path to the merged STATS.nc file `merge-mfdata` will produce, relative to the project dir."""
    return f"{_output_datafile(project_dir, config_filename)}-STATS.nc"


def validate_project(project_dir: Path, config_filename: str = "config.toml") -> str | None:
    """Check that `project_dir` looks like a usable PyOPIA project.

    Returns a plain-language error message, or None if the project looks OK.
    """
    if not (project_dir / config_filename).is_file():
        return f"No {config_filename} found in {project_dir}"
    try:
        config = _load_config(project_dir, config_filename)
    except tomllib.TOMLDecodeError as e:
        return f"{config_filename} isn't valid TOML: {e}"
    try:
        config["steps"]["output"]["output_datafile"]
    except (KeyError, TypeError):
        return f"{config_filename} is missing steps.output.output_datafile"
    return None


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
