# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Nimmo Smith Technologies Limited

import asyncio
import os
import platform
import re
import subprocess
import tomllib
from collections.abc import Callable
from enum import Enum
from pathlib import Path

# ghcr.io/sintef/pyopia isn't currently publicly pullable
# (https://github.com/SINTEF/pyopia/issues/424), so this defaults to a mirror we
# publish ourselves (see .github/workflows/publish-pyopia-mirror.yml and
# docs/decisions/0006-2026-08-13-mirror-pyopia-image.md) until that's fixed upstream.
PYOPIA_IMAGE = os.environ.get("PYOPIA_GUI_DOCKER_IMAGE", "ghcr.io/nimmo-smith-technologies/pyopia:latest")


class DockerStatus(Enum):
    NOT_INSTALLED = "not_installed"
    NOT_RUNNING = "not_running"
    AVAILABLE = "available"


def _no_console_kwargs() -> dict:
    """Extra subprocess kwargs that stop a console window flashing on Windows.

    The packaged app (native_app.py) is windowed - it has no console of its own -
    so by default Windows allocates a brand new console window for every console
    subprocess (docker.exe) it spawns, flashing on screen for each invocation.
    CREATE_NO_WINDOW is Windows-only (doesn't exist in the subprocess module on
    other platforms), so this is only returned there.
    """
    if platform.system() == "Windows":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def check_docker() -> DockerStatus:
    """Check whether the `docker` CLI is installed and its daemon is reachable."""
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            # Generous on purpose: seen a real case of this reporting NOT_RUNNING
            # under a 5s timeout on a Windows machine with flaky WSL2 networking,
            # while Docker Desktop itself said "Engine running" the whole time.
            timeout=15,
            **_no_console_kwargs(),
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
Docker isn't installed. Download and install Docker Desktop for Mac using the button
below, open it once, then click **Recheck**.\
"""

_WINDOWS_INSTALL_STEPS = """\
Docker isn't installed. Download and install Docker Desktop for Windows using the
button below - it will guide you through enabling WSL2 if needed - then click
**Recheck**.\
"""

_FALLBACK_INSTALL_STEPS = """\
Docker isn't installed. Use the button below for install instructions for your
platform, then click **Recheck**.\
"""

DOCKER_DESKTOP_URL = "https://www.docker.com/products/docker-desktop/"
DOCKER_GET_STARTED_URL = "https://docs.docker.com/get-docker/"

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


def setup_guidance_url(status: DockerStatus) -> str | None:
    """The install/download URL relevant to `status`, or None if there isn't one.

    Kept separate from `setup_guidance()`'s text rather than embedded as a markdown
    link: in the native (packaged) app, clicking a link navigates the app's own
    embedded window away to that page, with no back button to return from. The
    caller should instead wire this to opening the OS's actual default browser.
    """
    if status != DockerStatus.NOT_INSTALLED:
        return None
    os_name = platform.system()
    if os_name == "Linux":
        return None  # install is a terminal command here, not a webpage
    if os_name in ("Darwin", "Windows"):
        return DOCKER_DESKTOP_URL
    return DOCKER_GET_STARTED_URL


_CONTAINER_WORKDIR = "/workspace"


def _volume_args(directory: Path) -> list[str]:
    """Mount `directory` into the container at a fixed path, and set it as the working dir.

    The container side is always /workspace, regardless of host OS - not the host's
    own path. Containers are Linux regardless of host OS, so a Windows host path
    (e.g. C:\\Users\\...) isn't a valid path *inside* the container at all. A fixed
    path works identically on every host and keeps relative paths in config.toml
    (e.g. "images/*.silc") resolving correctly, since PyOPIA resolves them against
    its own working directory.
    """
    resolved = str(directory.resolve())
    return ["-v", f"{resolved}:{_CONTAINER_WORKDIR}", "-w", _CONTAINER_WORKDIR]


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


_IMAGE_PULL_FAILURE_MARKERS = (
    "pull access denied",
    "error from registry: denied",
    "manifest unknown",
    "requested access to the resource is denied",
    "unable to find image",
)

_DAEMON_UNREACHABLE_MARKERS = ("cannot connect to the docker daemon",)
_STALL_MARKERS = ("no output received for",)


def interpret_failure(output_lines: list[str]) -> str | None:
    """Give a plain-language explanation for a recognised Docker failure in `output_lines`.

    Returns None if nothing recognisable was found, so the caller can fall back to a
    generic "see the log" message.
    """
    combined = "\n".join(output_lines).lower()
    if any(marker in combined for marker in _IMAGE_PULL_FAILURE_MARKERS):
        return (
            f"Couldn't pull the PyOPIA image ({PYOPIA_IMAGE}) - it may be private, "
            "renamed, or removed, or you may not have network access. See the README "
            "for how to build it locally instead."
        )
    if any(marker in combined for marker in _DAEMON_UNREACHABLE_MARKERS):
        return "Lost contact with Docker partway through - check it's still running, then try again."
    if any(marker in combined for marker in _STALL_MARKERS):
        return (
            "This stalled with no progress for a while - usually a network problem (a stuck image "
            "download is the most common cause, especially over VPN or on Windows/WSL2). Check your "
            "connection, then try again."
        )
    return None


_PYOPIA_VERSION_PATTERN = re.compile(r"PYOPIA VERSION (\S+)")


def extract_pyopia_version(output_lines: list[str]) -> str | None:
    """Read the PyOPIA version out of `pyopia process`'s own output, if present.

    `process` prints "PYOPIA VERSION x.y.z" as its first line - reading it from the
    actual run's output ties the reported version to what really processed the data,
    rather than a separate (and potentially stale) version check.
    """
    for line in output_lines:
        match = _PYOPIA_VERSION_PATTERN.search(line)
        if match:
            return match.group(1)
    return None


INACTIVITY_TIMEOUT_SECONDS = 180


async def run_streamed(command: list[str], on_line: Callable[[str], None]) -> int:
    """Run `command`, calling `on_line` for each combined stdout/stderr line as it arrives.

    Returns the process's exit code. If no output arrives for
    `INACTIVITY_TIMEOUT_SECONDS`, the process is killed and this returns -1 instead
    of hanging forever - real case seen: a stalled Docker image pull (stuck on
    "pulling fs layer" with a flaky WSL2 network) otherwise left the app waiting
    indefinitely with no feedback and no way to recover short of restarting it.
    A real, working run - even a slow one - keeps producing output well within
    this window; a multi-minute total silence means something has actually stuck.
    """
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        **_no_console_kwargs(),
    )
    assert process.stdout is not None
    while True:
        try:
            raw_line = await asyncio.wait_for(process.stdout.readline(), timeout=INACTIVITY_TIMEOUT_SECONDS)
        except TimeoutError:
            process.kill()
            await process.wait()
            on_line(
                f"No output received for {INACTIVITY_TIMEOUT_SECONDS}s - this usually means a network "
                "operation (like pulling the Docker image) has stalled. Stopping."
            )
            return -1
        if not raw_line:
            break
        on_line(raw_line.decode(errors="replace").rstrip("\r\n"))
    return await process.wait()
