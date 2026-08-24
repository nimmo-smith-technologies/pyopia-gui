# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Nimmo Smith Technologies Limited

import asyncio
import importlib
import inspect
import json
import os
import platform
import re
import subprocess
import tomllib
import urllib.request
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from urllib.error import URLError

import tomli_w

# ghcr.io/sintef/pyopia isn't currently publicly pullable
# (https://github.com/SINTEF/pyopia/issues/424), so this defaults to a mirror we
# publish ourselves (see .github/workflows/publish-pyopia-mirror.yml and
# docs/decisions/0006-2026-08-13-mirror-pyopia-image.md) until that's fixed upstream.
_MIRROR_REPO = "nimmo-smith-technologies/pyopia"
PYOPIA_IMAGE = os.environ.get("PYOPIA_GUI_DOCKER_IMAGE", f"ghcr.io/{_MIRROR_REPO}:latest")


def image_for_version(version: str | None) -> str:
    """The image reference to use for a specific PyOPIA `version`, or the default if None.

    Ignores `version` entirely when PYOPIA_GUI_DOCKER_IMAGE is set - a manual override
    already names a complete image:tag (possibly a different registry entirely), and
    shouldn't be second-guessed by our own mirror-specific version tagging.
    """
    override = os.environ.get("PYOPIA_GUI_DOCKER_IMAGE")
    if override is not None:
        return override
    if not version:
        return PYOPIA_IMAGE
    return f"ghcr.io/{_MIRROR_REPO}:{version}"


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
            # Generous on purpose: a short timeout can misreport NOT_RUNNING on a
            # Windows machine with flaky WSL2 networking even while Docker Desktop
            # itself reports "Engine running".
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

Then run `newgrp docker` (or reboot - a plain log out/in doesn't always pick up the new
group membership), and click **Recheck**.\
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
Docker is installed but isn't reachable. If you just installed it, your user's `docker`
group membership may not have taken effect yet - a plain log out/in doesn't always do it,
so run this in a terminal instead:

```
newgrp docker
```

(or just reboot). Otherwise, start Docker with:

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


def init_project_command(parent_dir: Path, project_name: str, image: str = PYOPIA_IMAGE) -> list[str]:
    """Build the command to create a new example PyOPIA project named `project_name` under `parent_dir`."""
    return [
        "docker",
        "run",
        "--rm",
        *_volume_args(parent_dir),
        image,
        "init-project",
        project_name,
        "--example-data",
    ]


def generate_config_command(
    project_dir: Path,
    instrument: str,
    raw_files: str,
    model_path: str,
    outfolder: str,
    output_prefix: str,
    image: str = PYOPIA_IMAGE,
) -> list[str]:
    """Build the command to write a fresh default `<instrument>-config.toml` into `project_dir`.

    Writes alongside any existing config, not over it - the caller is responsible for
    replacing the project's real config file with this output, after confirming with the
    user (this drops any hand-added keys, e.g. `project_metadata_file`, that `init-project`
    layers on top of `generate-config`'s own bare output).
    """
    return [
        "docker",
        "run",
        "--rm",
        *_user_args(),
        *_volume_args(project_dir),
        image,
        "generate-config",
        instrument,
        raw_files,
        model_path,
        outfolder,
        output_prefix,
    ]


def process_command(
    project_dir: Path,
    config_filename: str = "config.toml",
    image: str = PYOPIA_IMAGE,
    num_chunks: int = 1,
    strategy: str = "block",
) -> list[str]:
    """Build the command to run PyOPIA processing against `config_filename` inside `project_dir`.

    `num_chunks`/`strategy` map directly to PyOPIA's own `process --num-chunks`/`--strategy`
    (split the dataset into that many chunks and process them in parallel via
    `multiprocessing` - unaffected by running inside Docker, since multiprocessing within
    one container works the same as on the host). Only appended when `num_chunks` asks for
    more than one chunk, so the default call is byte-for-byte what it always was.
    """
    command = [
        "docker",
        "run",
        "--rm",
        *_user_args(),
        *_volume_args(project_dir),
        image,
        "process",
        config_filename,
    ]
    if num_chunks > 1:
        command += ["--num-chunks", str(num_chunks), "--strategy", strategy]
    return command


def merge_mfdata_command(
    project_dir: Path, config_filename: str = "config.toml", image: str = PYOPIA_IMAGE
) -> list[str]:
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
        image,
        "merge-mfdata",
        path_to_data,
    ]


def make_montage_command(project_dir: Path, stats_filename: str, image: str = PYOPIA_IMAGE) -> list[str]:
    """Build the command to create montage.png from a processed STATS.nc file."""
    return [
        "docker",
        "run",
        "--rm",
        *_user_args(),
        *_volume_args(project_dir),
        image,
        "make-montage",
        stats_filename,
    ]


def _load_config(project_dir: Path, config_filename: str) -> dict:
    with (project_dir / config_filename).open("rb") as f:
        return tomllib.load(f)


def load_config(project_dir: Path, config_filename: str = "config.toml") -> dict:
    """The project's parsed config.toml as a plain dict - the public counterpart to `write_config`."""
    return _load_config(project_dir, config_filename)


def write_config(project_dir: Path, config: dict, config_filename: str = "config.toml") -> None:
    """Write `config` back to the project's config file, overwriting whatever's there."""
    with (project_dir / config_filename).open("wb") as f:
        tomli_w.dump(config, f)


def set_step_enabled(config: dict, step_name: str, *, enabled: bool) -> dict:
    """Move `step_name` between config's `steps` and `steps_disabled` tables.

    PyOPIA's `Pipeline` only ever reads `config["steps"]`, so a step under
    `steps_disabled` is invisible to a real run while still being kept around
    for the Configuration tab to show and re-enable later.

    Returns a new dict (doesn't mutate `config`). A no-op copy if `step_name`
    isn't present in the table it would be moved from.
    """
    new_config = json.loads(json.dumps(config))
    source_key = "steps_disabled" if enabled else "steps"
    dest_key = "steps" if enabled else "steps_disabled"
    source = new_config.get(source_key)
    if not isinstance(source, dict) or step_name not in source:
        return new_config
    new_config.setdefault(dest_key, {})[step_name] = source.pop(step_name)
    return new_config


def _output_datafile(project_dir: Path, config_filename: str) -> str:
    """The `steps.output.output_datafile` prefix from the project's config, e.g. "processed/demo"."""
    return _load_config(project_dir, config_filename)["steps"]["output"]["output_datafile"]


def pixel_size(project_dir: Path, config_filename: str = "config.toml") -> float:
    """The `general.pixel_size` (microns per pixel) from the project's config.

    Needed to convert the raw pixel measurements in a project's stats file into real-world
    units (see vendored_stats.py) - the same config key PyOPIA's own CLI reads for montage
    and plotting (`config["general"]["pixel_size"]` in pyopia/cli.py).
    """
    return _load_config(project_dir, config_filename)["general"]["pixel_size"]


def stats_filename(project_dir: Path, config_filename: str = "config.toml") -> str:
    """The path to the merged STATS.nc file `merge-mfdata` will produce, relative to the project dir."""
    return f"{_output_datafile(project_dir, config_filename)}-STATS.nc"


def output_directory(project_dir: Path, config_filename: str = "config.toml") -> Path:
    """The real folder `steps.output.output_datafile` writes into, e.g. `processed/`
    for `output_datafile = "processed/demo"` - the same directory `merge_mfdata_command`
    already computes (`os.path.dirname`), exposed here as a real `Path` for callers that
    need to act on the folder itself (e.g. clearing stale output before a fresh run).
    """
    return project_dir / (os.path.dirname(_output_datafile(project_dir, config_filename)) or ".")


def output_uses_append(project_dir: Path, config_filename: str = "config.toml") -> bool:
    """Whether the project's output step writes directly into one combined -STATS.nc
    file (`append = true`, `pyopia.io.StatsToDisc`'s own default) rather than one file
    per raw image (`append = false`).

    `merge-mfdata` is only meaningful in the `append = false` case - with
    `append = true` there's nothing to merge, and PyOPIA's own `merge-mfdata`
    raises `ZeroDivisionError` on a folder with no per-image files. Callers
    should skip the merge step entirely when this returns True.
    Defaults to True (matching `StatsToDisc.__init__`) if the `append` key
    isn't set, or the config/step can't be read at all.
    """
    try:
        output_step = _load_config(project_dir, config_filename)["steps"]["output"]
    except (KeyError, TypeError, OSError, tomllib.TOMLDecodeError):
        return True
    return bool(output_step.get("append", True))


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def list_available_versions(timeout: float = 5.0) -> list[str]:
    """Published PyOPIA versions on the mirror image, newest first (e.g. ["9.16.23", "9.16.20"]).

    Best-effort only: any failure (offline, registry error, unexpected response) returns an
    empty list rather than raising, so callers can fall back to the default image instead.
    Uses the registry's anonymous token flow directly (the same one `docker pull` itself
    uses for a public image) rather than the `docker` CLI, since there's no `docker
    images ls-remote` equivalent - listing what's on a registry needs the registry API.
    """
    try:
        token_request = urllib.request.Request(f"https://ghcr.io/token?scope=repository:{_MIRROR_REPO}:pull")
        with urllib.request.urlopen(token_request, timeout=timeout) as response:  # noqa: S310 fixed https:// URL above
            token = json.load(response)["token"]
        tags_request = urllib.request.Request(
            f"https://ghcr.io/v2/{_MIRROR_REPO}/tags/list", headers={"Authorization": f"Bearer {token}"}
        )
        with urllib.request.urlopen(tags_request, timeout=timeout) as response:  # noqa: S310 fixed https:// URL above
            tags = json.load(response)["tags"]
    except (URLError, OSError, ValueError, KeyError):
        return []
    versions = []
    for tag in tags:
        try:
            versions.append((_version_tuple(tag), tag))
        except ValueError:
            continue  # not a version tag (e.g. "latest", "main") - skip it
    versions.sort(reverse=True)
    return [tag for _, tag in versions]


def read_pinned_version(project_dir: Path, config_filename: str = "config.toml") -> str | None:
    """The PyOPIA version already recorded in this project's own stats file, if any exists.

    PyOPIA writes its own version into every stats file it produces
    (`xstats.attrs["PyOPIA_version"]` in pyopia/io.py) - reading it back from there, rather
    than pyopia-gui keeping its own separate record, ties a project's pinned version to what
    actually produced its real output data. Returns None if there's no stats file yet (a new
    or not-yet-processed project) or if it can't be read for any reason.
    """
    try:
        relative_stats_path = stats_filename(project_dir, config_filename)
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError):
        return None
    if not (project_dir / relative_stats_path).is_file():
        return None
    command = [
        "docker",
        "run",
        "--rm",
        # The image's own ENTRYPOINT is ["pyopia"] - override it for this one call, since
        # we need to run python directly, not pass "python" to pyopia as a subcommand name.
        "--entrypoint",
        "python",
        *_volume_args(project_dir),
        PYOPIA_IMAGE,
        "-c",
        "import sys, xarray; print(xarray.open_dataset(sys.argv[1]).attrs['PyOPIA_version'])",
        f"{_CONTAINER_WORKDIR}/{relative_stats_path}",
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=30, text=True, **_no_console_kwargs())
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def resolve_pipeline_class(pipeline_class: str):
    """Import and return the class a `pipeline_class` dotted path (e.g.
    'pyopia.process.Segment') names.

    Same resolution PyOPIA's own `pipeline.py` uses internally to load a step's class.
    Defined as a real top-level function, not embedded script text, so it has real unit
    tests independent of Docker/PyOPIA - its source is embedded verbatim into the
    Docker-side scripts below via `inspect.getsource`, so what's tested is what runs.
    """
    classname = pipeline_class.rsplit(".", 1)[-1]
    modulename = pipeline_class.rsplit(".", 1)[0]
    return getattr(importlib.import_module(modulename), classname)


def parse_numpydoc_params(doc: str | None) -> dict[str, str]:
    """Pull {param_name: description} out of a numpydoc-style docstring's "Parameters" section.

    numpydoc sections look like "Heading\\n----...\\n" - find every such heading, then take
    the lines between the "Parameters" heading and whichever heading comes next (usually
    "Returns"). Embedded verbatim into `_INTROSPECT_STEPS_SCRIPT` below via
    `inspect.getsource`, so what's unit-tested here is what actually runs.
    """
    if not doc:
        return {}
    lines = doc.splitlines()
    headers = [
        (lines[i].strip(), i)
        for i in range(len(lines) - 1)
        if lines[i].strip() and lines[i + 1].strip() and set(lines[i + 1].strip()) == {"-"}
    ]
    start = end = None
    for idx, (name, i) in enumerate(headers):
        if name == "Parameters":
            start = i + 2
            end = headers[idx + 1][1] if idx + 1 < len(headers) else len(lines)
            break
    if start is None:
        return {}
    params: dict[str, str] = {}
    current: str | None = None
    desc: list[str] = []
    for line in lines[start:end]:
        if line.strip() and not line[:1].isspace():
            if current:
                params[current] = " ".join(desc).strip()
            current, desc = line.strip().split(":", 1)[0].split()[0], []
        elif current and line.strip():
            desc.append(line.strip())
    if current:
        params[current] = " ".join(desc).strip()
    return params


def docstring_summary(doc: str | None) -> str:
    """The introductory paragraph of a numpydoc-style docstring, before any
    "Parameters"/"Returns" section. Strips Sphinx cross-reference markup
    (`:class:`x``, `:func:`x``) down to the bare name, since that's meant for
    rendered docs, not a plain label in the Configuration tab.
    """
    if not doc:
        return ""
    paragraph: list[str] = []
    for line in doc.splitlines():
        if not line.strip():
            break
        paragraph.append(line.strip())
    return re.sub(r":\w+:`([^`]+)`", r"\1", " ".join(paragraph))


# Runs inside the project's own pinned PyOPIA image, so the parameter schema it reports
# always matches the exact version actually processing this project - no local copy of
# PyOPIA's step classes to keep in sync (unlike vendored_stats.py, see ADR 0007).
# Everything below `parse_numpydoc_params` has to be stdlib-only: this only has whatever's
# already installed in PyOPIA's own image to work with, not pyopia-gui's own dependencies.
_INTROSPECT_STEPS_SCRIPT = f"""
import importlib, inspect, json, re, sys, tomllib

{inspect.getsource(resolve_pipeline_class)}

{inspect.getsource(parse_numpydoc_params)}

{inspect.getsource(docstring_summary)}

def jsonable(value):
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value

with open(sys.argv[1], "rb") as f:
    config = tomllib.load(f)

def introspect_table(table):
    table_result = {{}}
    for step_name, step in (table or {{}}).items():
        pipeline_class = step.get("pipeline_class") if isinstance(step, dict) else None
        if not pipeline_class:
            continue
        try:
            cls = resolve_pipeline_class(pipeline_class)
            doc = inspect.getdoc(cls)
            descriptions = parse_numpydoc_params(doc)
            summary = docstring_summary(doc)
            fields = []
            for name, param in inspect.signature(cls.__init__).parameters.items():
                if name == "self" or param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
                    continue
                has_default = param.default is not inspect.Parameter.empty
                fields.append({{
                    "name": name,
                    "current_value": jsonable(step.get(name)),
                    "has_default": has_default,
                    "default": jsonable(param.default) if has_default else None,
                    "description": descriptions.get(name, ""),
                }})
            table_result[step_name] = {{"pipeline_class": pipeline_class, "summary": summary, "fields": fields}}
        except Exception as e:
            table_result[step_name] = {{"pipeline_class": pipeline_class, "error": f"{{type(e).__name__}}: {{e}}"}}
    return table_result

result = {{
    "steps": introspect_table(config.get("steps")),
    "steps_disabled": introspect_table(config.get("steps_disabled")),
}}

print(json.dumps(result))
"""


def introspect_config_steps(project_dir: Path, config_filename: str = "config.toml", image: str = PYOPIA_IMAGE) -> dict:
    """Per-step parameter schema for `config_filename`, introspected from the pinned PyOPIA image.

    Returns {"steps": {step_name: {...}}, "steps_disabled": {step_name: {...}}} - both
    tables (see `set_step_enabled`) are introspected the same way, so a disabled step's
    fields can still be shown/edited before it's re-enabled. Returns {} on any failure
    (Docker error, timeout, unparseable output) - callers should treat a missing
    "steps"/"steps_disabled" key as {} via `.get(..., {})`.

    One `docker run` for the whole config: each step's `pipeline_class` is imported and
    inspected (`inspect.signature` + its own docstring) inside the container, so the
    fields/descriptions shown always match the exact PyOPIA version this project uses. A
    step whose class can't be imported gets {"error": ...} instead of {"fields": ...} -
    callers should fall back to bare key/value editing for that step alone.
    """
    command = [
        "docker",
        "run",
        "--rm",
        "--entrypoint",
        "python",
        *_volume_args(project_dir),
        image,
        "-c",
        _INTROSPECT_STEPS_SCRIPT,
        f"{_CONTAINER_WORKDIR}/{config_filename}",
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=60, text=True, **_no_console_kwargs())
    except (subprocess.TimeoutExpired, OSError):
        return {}
    if result.returncode != 0:
        return {}
    try:
        return json.loads(result.stdout)
    except ValueError:
        return {}


THUMBNAIL_DIR_NAME = ".pyopia_gui_thumbnails"
_BROWSER_VIEWABLE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp"}


def list_raw_files(project_dir: Path, raw_files_pattern: str) -> list[Path]:
    """The project's raw files matching `raw_files_pattern` (config.toml's own
    `general.raw_files`), sorted - the same listing the Raw data explorer's thumbnail
    grid uses for itself, factored out here so Preview's background-correction context
    (see `preview_pipeline`'s `context_raw_paths`) can find a sample's preceding files
    without duplicating this.

    A `.txt`-suffixed pattern is an explicit file list rather than a glob - PyOPIA's own
    `FilesToProcess` reads it the same way (one path per line, order preserved as
    written, not re-sorted) - see `apply_raw_files_subset` below, which is the only
    thing that writes one.
    """
    if raw_files_pattern.endswith(".txt"):
        list_path = project_dir / raw_files_pattern
        if not list_path.is_file():
            return []
        lines = [line.strip() for line in list_path.read_text().splitlines() if line.strip()]
        return [project_dir / line for line in lines]
    return sorted(project_dir.glob(raw_files_pattern))


# Written by apply_raw_files_subset() below, at the project root (a real path
# PyOPIA's own FilesToProcess reads directly, not app-internal bookkeeping).
RAW_FILES_SUBSET_FILENAME = "raw_files_subset.txt"

# App-internal bookkeeping only, never read by PyOPIA - the general.raw_files pattern
# a subset replaced, so Explorer's "Clear subset" can restore the real original rather
# than whatever the most recent subset happened to be.
_RAW_FILES_ORIGINAL_PATTERN_FILENAME = ".raw_files_original_pattern"


def raw_files_original_pattern(project_dir: Path) -> str | None:
    """The `general.raw_files` pattern a subset replaced, if one is currently active - see
    `apply_raw_files_subset`. None if no subset was ever applied (or it's since been cleared).
    """
    path = project_dir / _RAW_FILES_ORIGINAL_PATTERN_FILENAME
    return path.read_text().strip() if path.is_file() else None


def apply_raw_files_subset(project_dir: Path, config: dict, selected_paths: list[Path]) -> dict:
    """Narrow the project to just `selected_paths` (already ordered to match their
    original raw-files order - chunk/background-correction steps depend on chronological
    order, not click order) by writing them to RAW_FILES_SUBSET_FILENAME and pointing
    `general.raw_files` at it.

    Stashes whatever pattern this replaces (once, the first time) so a later subset -
    picked from what's already a filtered view - can still be cleared back to the real
    original pattern, not the previous subset file.

    Returns a new config dict (doesn't mutate `config`), for the caller to write back.
    """
    current_pattern = (config.get("general") or {}).get("raw_files")
    if current_pattern and current_pattern != RAW_FILES_SUBSET_FILENAME:
        (project_dir / _RAW_FILES_ORIGINAL_PATTERN_FILENAME).write_text(current_pattern)
    lines = [str(p.relative_to(project_dir)) for p in selected_paths]
    (project_dir / RAW_FILES_SUBSET_FILENAME).write_text("\n".join(lines) + "\n")
    new_config = json.loads(json.dumps(config))
    new_config.setdefault("general", {})["raw_files"] = RAW_FILES_SUBSET_FILENAME
    return new_config


def clear_raw_files_subset(project_dir: Path, config: dict) -> dict | None:
    """Restore `general.raw_files` to the pattern a subset (see `apply_raw_files_subset`)
    replaced, and remove the subset file and bookkeeping alongside it.

    Returns a new config dict, or None if there's no stashed original pattern to restore
    (config unchanged in that case) - e.g. `raw_files` was never actually narrowed via a
    subset, so there's nothing to revert.
    """
    original = raw_files_original_pattern(project_dir)
    if original is None:
        return None
    new_config = json.loads(json.dumps(config))
    new_config.setdefault("general", {})["raw_files"] = original
    (project_dir / RAW_FILES_SUBSET_FILENAME).unlink(missing_ok=True)
    (project_dir / _RAW_FILES_ORIGINAL_PATTERN_FILENAME).unlink(missing_ok=True)
    return new_config


def select_background_context(raw_paths: list[Path], sample: Path, required: int) -> list[Path]:
    """Pick `required` real raw files from `raw_paths` to seed a background-correction
    step before running `sample` through it - preferring the files immediately
    preceding `sample` (matching what a real sequential run would have accumulated by
    then), and only reaching for files after it to fill the remainder when there
    aren't enough preceding ones (e.g. a sample near the start of the file list).
    Not always symmetric: `CorrectBackgroundAccurate`'s moving-average stack only
    needs this many distinct images seeding it, not any particular order.

    Returns `[]` if `sample` isn't in `raw_paths`, or fewer than `required` other
    files exist to draw from at all - the caller falls back to substituting the
    background step away in that case.
    """
    if required <= 0 or sample not in raw_paths:
        return []
    sample_index = raw_paths.index(sample)
    preceding = raw_paths[:sample_index]
    following = raw_paths[sample_index + 1 :]
    if len(preceding) >= required:
        return preceding[-required:]
    context = preceding + following[: required - len(preceding)]
    return context if len(context) == required else []


def thumbnail_path(project_dir: Path, raw_path: Path) -> Path:
    """Where the preview for `raw_path` (a raw file under `project_dir`) lives.

    Already browser-viewable raw files (e.g. UVP's own .png images) are served directly
    from their real path, no conversion needed. Everything else (silcam .silc, holo
    .pgm, ...) gets a cached thumbnail under THUMBNAIL_DIR_NAME, generated on demand by
    `generate_thumbnails` - deliberately not PyOPIA's own `images_converted/` name,
    which is a different output folder produced by `convert-raw-images`.
    """
    if raw_path.suffix.lower() in _BROWSER_VIEWABLE_EXTENSIONS:
        return raw_path
    return project_dir / THUMBNAIL_DIR_NAME / f"{raw_path.stem}.png"


# Runs inside the project's own pinned PyOPIA image - loads each raw file the same way
# PyOPIA's own `convert-raw-images` CLI command does (steps.load.pipeline_class, called
# once per file) and lets matplotlib's imsave() handle the per-instrument-type array
# normalization (uint8 RGB for silcam, float grayscale for holo, ...) rather than
# hand-rolling that per format. One Docker call converts a whole batch, not one call per
# image, since container startup - not the actual conversion - dominates a single call's
# cost. Prints a result line after *each* image (not just a
# running count, and not just a final summary at the end) so the caller can update that
# one image's own preview as soon as it's ready, rather than only once the whole batch
# finishes.
_GENERATE_THUMBNAILS_SCRIPT = f"""
import importlib, json, os, sys, tomllib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image

{inspect.getsource(resolve_pipeline_class)}

with open(sys.argv[1], "rb") as f:
    config = tomllib.load(f)
load_step = config["steps"]["load"]
cls = resolve_pipeline_class(load_step["pipeline_class"])
loader = cls(**{{k: v for k, v in load_step.items() if k != "pipeline_class"}})

requests = json.loads(sys.argv[2])
for i, (raw_path, out_path) in enumerate(requests):
    # Write matplotlib's full-res output to a separate temp path, then read *that* and
    # save the resized thumbnail to out_path - reading and writing the same path in one
    # step risks corrupt/truncated PNGs on some filesystems (e.g. a Docker bind mount),
    # since PIL's Image.open() keeps a lazy reference to the file it's still open on
    # when the save() back to that same path happens.
    tmp_path = out_path + ".tmp"
    error = None
    try:
        data = {{"filename": raw_path}}
        loader(data)
        # format="png" explicitly - imsave otherwise infers the format from tmp_path's
        # own extension (".tmp"), which isn't a format it recognises.
        plt.imsave(tmp_path, data["imraw"], format="png")
        with Image.open(tmp_path) as img:
            img.thumbnail((320, 320))
            img.convert("RGB").save(out_path)
    except Exception as e:
        error = f"{{type(e).__name__}}: {{e}}"
        # Never leave a broken/partial file at out_path on failure - the caller's own
        # cache check is just "does a file exist here", so a stale leftover would
        # otherwise be silently treated as a valid cached thumbnail forever after.
        if os.path.exists(out_path):
            os.remove(out_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    print(
        "THUMBNAIL_DONE "
        + json.dumps({{"done": i + 1, "total": len(requests), "raw_path": raw_path, "error": error}}),
        flush=True,
    )
"""


async def generate_thumbnails(
    project_dir: Path,
    raw_paths: list[Path],
    config_filename: str = "config.toml",
    image: str = PYOPIA_IMAGE,
    on_progress: Callable[[int, int], None] | None = None,
    on_image_done: Callable[[Path, str | None], None] | None = None,
) -> dict[str, str]:
    """Generate cached preview thumbnails for `raw_paths` (paths under `project_dir`).

    One Docker call for the whole batch, not one per image (container startup
    dominates the cost of a single call). Raw files already browser-viewable are
    skipped (see `thumbnail_path`). Streamed via `run_streamed`: `on_progress(done,
    total)` and `on_image_done(raw_path, error)` are both called as each image
    finishes, so the caller can update the overall progress bar and that image's own
    preview immediately, not only once the whole batch completes.

    Returns {str(raw_path): error_message} for any image that failed to convert - a
    missing entry means it succeeded and `thumbnail_path(project_dir, raw_path)` now
    exists on disk.
    """
    to_convert = [p for p in raw_paths if p.suffix.lower() not in _BROWSER_VIEWABLE_EXTENSIONS]
    if not to_convert:
        return {}
    thumb_dir = project_dir / THUMBNAIL_DIR_NAME
    thumb_dir.mkdir(exist_ok=True)
    requests = [
        (
            # .as_posix(), not str() - on Windows, relative_to() returns backslash-separated
            # components, which would otherwise land in a Linux container path unchanged
            # and never match the real /workspace/... path the container itself reports back.
            f"{_CONTAINER_WORKDIR}/{p.relative_to(project_dir).as_posix()}",
            f"{_CONTAINER_WORKDIR}/{THUMBNAIL_DIR_NAME}/{p.stem}.png",
        )
        for p in to_convert
    ]
    command = [
        "docker",
        "run",
        "--rm",
        *_user_args(),
        "--entrypoint",
        "python",
        *_volume_args(project_dir),
        image,
        "-c",
        _GENERATE_THUMBNAILS_SCRIPT,
        f"{_CONTAINER_WORKDIR}/{config_filename}",
        json.dumps(requests),
    ]

    container_to_host = {container_path: p for (container_path, _), p in zip(requests, to_convert, strict=True)}
    errors: dict[str, str] = {}

    def on_line(line: str) -> None:
        if not line.startswith("THUMBNAIL_DONE "):
            return
        payload = json.loads(line.removeprefix("THUMBNAIL_DONE "))
        if on_progress:
            on_progress(payload["done"], payload["total"])
        host_path = container_to_host.get(payload["raw_path"])
        if host_path is None:
            return  # not one of ours - shouldn't happen, but don't crash the callback on it
        if payload["error"]:
            errors[str(host_path)] = payload["error"]
        if on_image_done:
            on_image_done(host_path, payload["error"])

    exit_code = await run_streamed(command, on_line)
    if exit_code != 0:
        return {str(p): errors.get(str(p), "Docker call failed - see the log for details") for p in to_convert}
    return errors


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
            "This stalled with no progress for a while - usually a network problem (a stuck "
            "download, either of the Docker image or of the example data, is the most common "
            "cause, especially over VPN or on Windows/WSL2). Check your connection, then try again."
        )
    return None


_THUMBNAIL_LOAD_MISMATCH_MARKERS = ("could not find a backend",)


def interpret_thumbnail_error(error: str) -> str | None:
    """Give a plain-language explanation for a recognised `generate_thumbnails` failure.

    Returns None if nothing recognisable was found, so the caller can fall back to the
    raw error. The one pattern recognised so far: the project's
    `steps.load.pipeline_class` not matching its raw files' actual format (e.g. a holo
    loader pointed at silcam .silc files) surfaces as an image-library "no backend"
    error that means nothing to a non-expert user.
    """
    if any(marker in error.lower() for marker in _THUMBNAIL_LOAD_MISMATCH_MARKERS):
        return (
            "Couldn't read this file with the project's current load settings - this "
            "usually means the Configuration tab's load step doesn't match this "
            "project's actual raw file format. Check steps.load.pipeline_class there."
        )
    return None


PREVIEW_DIR_NAME = ".pyopia_gui_preview"


def required_background_context(config: dict) -> int:
    """How many preceding raw files a background-correction step in `config` needs
    before it can produce a corrected image - the `average_window` of any step whose
    `pipeline_class` is under `pyopia.background.*`, or 0 if no such step is
    configured. Defaults to 1 (matching `CorrectBackgroundAccurate.__init__`) if
    `average_window` itself isn't set.

    Used by the Preview tab to gather that many preceding raw files as
    `preview_pipeline`'s `context_raw_paths`, so background correction can run for
    real instead of always being substituted away.
    """
    steps = config.get("steps")
    if not isinstance(steps, dict):
        return 0
    for step in steps.values():
        if isinstance(step, dict) and str(step.get("pipeline_class", "")).startswith("pyopia.background."):
            return int(step.get("average_window", 1))
    return 0


def _substitute_background_steps(config: dict) -> tuple[dict, bool]:
    """Replace any step whose `pipeline_class` is under `pyopia.background.*` with
    `CorrectBackgroundNone` (PyOPIA's own documented no-op substitute) - the fallback
    preview path, used only when there aren't enough preceding raw files to seed the
    real background step (see `required_background_context`). A background step
    needs several images (`average_window`) before it produces anything at all, so a
    lone preview image can never satisfy it on its own.

    Matched by `pipeline_class` module prefix, not dict key name - a project's
    background step can be named anything, or be absent entirely. Doesn't mutate
    `config`. Returns `(new_config, any_step_was_replaced)` so the caller can show a
    caveat only when it's actually relevant. Embedded verbatim into
    `_PREVIEW_PIPELINE_SCRIPT` below via `inspect.getsource`, so what's unit-tested
    here is what actually runs.
    """
    new_config = json.loads(json.dumps(config))
    steps = new_config.get("steps")
    if not isinstance(steps, dict):
        return new_config, False
    replaced = False
    for name, step in steps.items():
        if isinstance(step, dict) and str(step.get("pipeline_class", "")).startswith("pyopia.background."):
            steps[name] = {"pipeline_class": "pyopia.background.CorrectBackgroundNone"}
            replaced = True
    return new_config, replaced


def _remove_output_steps(config: dict) -> dict:
    """Drop any step whose `pipeline_class` is under `pyopia.io.*` (e.g. `StatsToDisc`)
    entirely, for single-image preview purposes only.

    Left in place, an output step would write a real STATS.nc file as an unwanted side
    effect of a mere preview (or overwrite the project's real accumulated output), or
    fail outright since preview never runs the CLI's own "prepare folders" step.
    Preview only needs `pipeline.data` in memory, so the step is dropped outright
    rather than substituted with a no-op class. Matched by `pipeline_class` module
    prefix, not step name, same as `_substitute_background_steps`. Doesn't mutate
    `config`; embedded the same tested-then-embedded way.
    """
    new_config = json.loads(json.dumps(config))
    steps = new_config.get("steps")
    if not isinstance(steps, dict):
        return new_config
    new_config["steps"] = {
        name: step
        for name, step in steps.items()
        if not (isinstance(step, dict) and str(step.get("pipeline_class", "")).startswith("pyopia.io."))
    }
    return new_config


# Runs inside the project's own pinned PyOPIA image, against exactly one raw file (plus,
# when available, real preceding raw files to seed background correction - see
# context_paths below). `config` travels in as a JSON argv string, not a file - it may be
# the Configuration tab's current *unsaved* widget values, not what's on disk in
# config.toml, and a background-substituted version should never be written into the
# user's own project folder. For a holo project, every slice of the reconstructed depth
# stack (`data['im_stack']`) is saved too - `Reconstruct` keeps the whole stack in memory
# and `Focus` never discards it, so this is a real, zero-recompute depth-slider dataset
# once this one Docker call finishes, not something that needs recomputing per slider
# position.
_PREVIEW_PIPELINE_SCRIPT = f"""
import json, logging, os, sys, uuid
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from PIL import Image
import pyopia.pipeline

{inspect.getsource(_substitute_background_steps)}

{inspect.getsource(_remove_output_steps)}

# PyOPIA's own Pipeline already logs a real, meaningful progress trail via the
# stdlib root logger - "Initialising pipeline", "Running pipeline step: X" for
# each step in turn, etc. (pyopia/pipeline.py) - forwarding it as-is, prefixed so
# the host side can tell it apart from the one final JSON result line, gives real
# per-step progress on a run that can otherwise take 30+ seconds with no
# indication of what's happening, with no changes needed inside PyOPIA itself.
class _ProgressHandler(logging.Handler):
    def emit(self, record):
        print("PREVIEW_PROGRESS " + record.getMessage(), flush=True)

logging.getLogger().addHandler(_ProgressHandler())
logging.getLogger().setLevel(logging.INFO)

config = json.loads(sys.argv[1])
sample_path = sys.argv[2]
context_paths = json.loads(sys.argv[3])

if context_paths:
    # Enough real preceding raw files were found to seed the actual configured
    # background step for real - see required_background_context()/preview_pipeline's
    # context_raw_paths. Nothing to substitute; the step runs as genuinely configured.
    background_step_skipped = False
else:
    config, background_step_skipped = _substitute_background_steps(config)
config = _remove_output_steps(config)

run_id = uuid.uuid4().hex[:8]
run_dir = os.path.join("{PREVIEW_DIR_NAME}", run_id)
os.makedirs(run_dir, exist_ok=True)

try:
    pipeline = pyopia.pipeline.Pipeline(config)
    for context_path in context_paths:
        # Seeds the background step's moving-average stack, same as a real batch
        # run processing these files in order would - each of these calls is
        # expected to return early (Data.skip_next_steps) once it reaches the
        # background step, since the stack isn't full yet; only the *last*
        # (sample_path) call below should actually complete it.
        pipeline.run(context_path)
    pipeline.run(sample_path)
except Exception as e:
    print(json.dumps({{"ok": False, "error": f"{{type(e).__name__}}: {{e}}"}}))
    sys.exit(0)

data = pipeline.data

if context_paths and data.get("im_corrected") is None:
    # The real background step still didn't produce a corrected image despite
    # being given what should have been enough context - the caller's count of
    # preceding files didn't actually match what this step needed (e.g. config
    # changed between gathering context and this call). Report it plainly rather
    # than silently continuing with an im_corrected that was never produced.
    print(json.dumps({{
        "ok": False,
        "error": "Background correction did not complete with the preceding raw files given - "
                 "try a different sample image.",
    }}))
    sys.exit(0)

stats = data.get("stats")
image_stats = data.get("image_stats")

particle_count = None
d50_microns = None
saturation = None
if image_stats is not None and len(image_stats) > 0:
    row = image_stats.iloc[0]
    if "particle_count" in row and row["particle_count"] == row["particle_count"]:
        particle_count = int(row["particle_count"])
    if "d50" in row and row["d50"] == row["d50"]:
        d50_microns = float(row["d50"])
    if "saturation" in row and row["saturation"] == row["saturation"]:
        saturation = float(row["saturation"])
if particle_count is None:
    # image_stats was empty/missing, but stats (per-particle rows) still tells us how
    # many particles were found - "zero particles found" is a normal outcome here, not
    # an error, so this still reports a real count rather than falling through to None.
    particle_count = int(len(stats)) if stats is not None else 0

# For holo, im_focussed (each detected particle pasted in at its own best-focus
# crop, everything else blank) is what actually shows "detected particles" -
# im_corrected there is still just the raw, unfocused interference pattern, not
# a meaningful particle image. Falls back to im_corrected for silcam/uvp, where
# there's no im_focussed and im_corrected already *is* the real particle image.
overlay_source = data.get("im_focussed")
if overlay_source is None:
    overlay_source = data.get("im_corrected")
overlay_filename = None
if overlay_source is not None:
    fig, ax = plt.subplots()
    ax.imshow(np.asarray(overlay_source), cmap="gray")
    if stats is not None:
        for _, row in stats.iterrows():
            if all(k in row.index for k in ("minr", "minc", "maxr", "maxc")):
                ax.add_patch(Rectangle(
                    (row["minc"], row["minr"]),
                    row["maxc"] - row["minc"],
                    row["maxr"] - row["minr"],
                    fill=False, edgecolor="red", linewidth=1,
                ))
    ax.axis("off")
    overlay_filename = "overlay.png"
    # A single, non-interleaved savefig straight to this run's own fresh, unique path -
    # nothing ever reads it before this script has finished and printed its result, so
    # there's no partial-file window to guard against here (unlike generate_thumbnails,
    # where a cached thumbnail is read back by a later, independent request).
    fig.savefig(os.path.join(run_dir, overlay_filename), bbox_inches="tight", pad_inches=0)
    plt.close(fig)

slice_filenames = None
z_values = None
im_stack = data.get("im_stack")
if im_stack is not None:
    slice_filenames = []
    n_slices = im_stack.shape[2]
    for i in range(n_slices):
        if i % 10 == 0 or i == n_slices - 1:
            print(f"PREVIEW_PROGRESS Rendering depth slice {{i + 1}} of {{n_slices}}", flush=True)
        # Normalized per-slice (each slice's own min/max), not against the whole
        # stack's range - matches how a depth-stack viewer conventionally shows each
        # slice at its own best contrast, since a single global range would make most
        # slices look nearly blank next to whichever one happens to have the widest range.
        arr = np.asarray(im_stack[:, :, i], dtype=np.float64)
        arr_min, arr_max = float(arr.min()), float(arr.max())
        normalized = (arr - arr_min) / (arr_max - arr_min) * 255 if arr_max > arr_min else np.zeros_like(arr)
        # Inverted - im_stack's own raw convention is high value = particle, but
        # PyOPIA itself displays/interprets reconstructions the other way round
        # (holo.py's Focus step explicitly does `1 - im_focussed` before storing
        # it) - dark particles on a bright background, matching what a user
        # would see from any of PyOPIA's own real output, not the raw inverse.
        normalized = 255 - normalized
        slice_filename = f"slice-{{i:04d}}.png"
        Image.fromarray(normalized.astype("uint8")).save(os.path.join(run_dir, slice_filename))
        slice_filenames.append(slice_filename)
    recon_params = data.get("holo_recon_params")
    if recon_params is not None:
        try:
            # Same formula PyOPIA's own MergeStats uses for stats['z'] (pyopia/instrument/holo.py)
            # - real mm, not the internal FFT kernel's metres-with-refractive-index version.
            candidate_z_values = list(
                np.arange(recon_params["minZ"], recon_params["maxZ"] + recon_params["stepZ"], recon_params["stepZ"])
            )
        except (KeyError, TypeError):
            candidate_z_values = None
        # Floating-point np.arange can disagree by one element between this (unscaled,
        # mm) computation and the one create_kernel() actually used to size im_stack
        # (scaled to metres before its own arange) - if the counts don't match, showing
        # no depth labels is safer than silently mislabeling/misaligning slices.
        if candidate_z_values is not None and len(candidate_z_values) == im_stack.shape[2]:
            z_values = candidate_z_values

print(json.dumps({{
    "ok": True,
    "particle_count": particle_count,
    "d50_microns": d50_microns,
    "saturation": saturation,
    "background_step_skipped": background_step_skipped,
    "run_id": run_id,
    "overlay_filename": overlay_filename,
    "slice_filenames": slice_filenames,
    "z_values": z_values,
}}))
"""


async def preview_pipeline(
    project_dir: Path,
    config: dict,
    sample_raw_path: Path,
    image: str = PYOPIA_IMAGE,
    on_progress: Callable[[str], None] | None = None,
    context_raw_paths: list[Path] | None = None,
) -> dict:
    """Run the pipeline described by `config` against exactly one raw file, and return
    its single-image results - particle count/d50/saturation, an overlay image with
    detected particles outlined, and (for a holo project) every depth slice of the
    reconstructed stack, for a zero-recompute depth slider in the UI.

    `config` may be the Configuration tab's current unsaved widget values, not
    necessarily what's on disk - it travels into the container as a JSON argv string,
    not a temp .toml file, since a background-correction-substituted config (see
    `_substitute_background_steps`) shouldn't be written into the user's project folder.

    `context_raw_paths`, if given, are real preceding raw files used to seed a real
    configured background-correction step before running `sample_raw_path` - see
    `required_background_context()` for how many to gather. When there aren't enough
    (or none given), the background step is substituted away instead and
    `background_step_skipped` comes back True in the result.

    A real run can take 30+ seconds (holo reconstruction, many depth slices) -
    `on_progress(message)` is called, if given, for each progress line the container
    reports (PyOPIA's own Pipeline step logging, plus this module's own depth-slice
    render progress), streamed via `run_streamed`.

    Returns one of:
        {"ok": True, "particle_count": int, "d50_microns": float | None,
         "saturation": float | None, "background_step_skipped": bool,
         "overlay_path": Path | None, "slice_paths": list[Path] | None,
         "z_values": list[float] | None}
        {"ok": False, "error": str}
    `error` is the raw "ExceptionType: message" text - callers should run it through
    `interpret_preview_error()` for a friendlier message, falling back to the raw text.
    """
    preview_dir = project_dir / PREVIEW_DIR_NAME
    preview_dir.mkdir(exist_ok=True)
    # .as_posix(), not str() - same Windows-backslash fix already applied in
    # generate_thumbnails, for the same reason.
    context_container_paths = [
        f"{_CONTAINER_WORKDIR}/{p.relative_to(project_dir).as_posix()}" for p in (context_raw_paths or [])
    ]
    command = [
        "docker",
        "run",
        "--rm",
        *_user_args(),
        "--entrypoint",
        "python",
        *_volume_args(project_dir),
        image,
        "-c",
        _PREVIEW_PIPELINE_SCRIPT,
        json.dumps(config),
        f"{_CONTAINER_WORKDIR}/{sample_raw_path.relative_to(project_dir).as_posix()}",
        json.dumps(context_container_paths),
    ]

    result_line: str | None = None

    def on_line(line: str) -> None:
        nonlocal result_line
        if line.startswith("PREVIEW_PROGRESS "):
            if on_progress:
                on_progress(line.removeprefix("PREVIEW_PROGRESS "))
            return
        if line.startswith("{"):
            # The one line that's the final JSON result - matched by shape, not
            # just "not progress-prefixed", since stderr noise (a numpy/matplotlib
            # warning, stdout+stderr are combined by run_streamed) is also
            # unprefixed and shouldn't be mistaken for it.
            result_line = line

    exit_code = await run_streamed(command, on_line)
    if exit_code != 0 or result_line is None:
        return {"ok": False, "error": "Docker call failed - see the log for details"}
    try:
        payload = json.loads(result_line)
    except ValueError:
        return {"ok": False, "error": "Docker call failed - see the log for details"}
    if not payload.get("ok"):
        return {"ok": False, "error": payload.get("error", "Unknown error")}

    run_dir = preview_dir / payload["run_id"]
    overlay_path = run_dir / payload["overlay_filename"] if payload.get("overlay_filename") else None
    slice_paths = [run_dir / name for name in payload["slice_filenames"]] if payload.get("slice_filenames") else None
    return {
        "ok": True,
        "particle_count": payload["particle_count"],
        "d50_microns": payload["d50_microns"],
        "saturation": payload["saturation"],
        "background_step_skipped": payload["background_step_skipped"],
        "overlay_path": overlay_path,
        "slice_paths": slice_paths,
        "z_values": payload["z_values"],
    }


def interpret_preview_error(error: str) -> str | None:
    """Give a plain-language explanation for a recognised `preview_pipeline` failure.

    Returns None (falling back to the raw error) if nothing recognisable was found.
    No patterns are recognised yet - an empty hook, same shape as
    `interpret_thumbnail_error`/`interpret_failure`.
    """
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


# PyOPIA's own "download example data" step (urllib.request.urlretrieve, a ~44MB zip)
# prints no progress at all while it runs, so this must be generous enough not to kill
# a real, still-succeeding download on an ordinary connection.
INACTIVITY_TIMEOUT_SECONDS = 600


async def run_streamed(command: list[str], on_line: Callable[[str], None]) -> int:
    """Run `command`, calling `on_line` for each combined stdout/stderr line as it arrives.

    Returns the process's exit code. If no output arrives for
    `INACTIVITY_TIMEOUT_SECONDS`, the process is killed and this returns -1 instead of
    hanging forever on a stalled network operation (e.g. a stuck Docker image pull)
    with no way to recover short of restarting the app.
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
                "operation (like pulling the Docker image or downloading example data) has stalled. Stopping."
            )
            return -1
        if not raw_line:
            break
        on_line(raw_line.decode(errors="replace").rstrip("\r\n"))
    return await process.wait()
