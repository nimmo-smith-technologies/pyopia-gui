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


def process_command(project_dir: Path, config_filename: str = "config.toml", image: str = PYOPIA_IMAGE) -> list[str]:
    """Build the command to run PyOPIA processing against `config_filename` inside `project_dir`."""
    return [
        "docker",
        "run",
        "--rm",
        *_user_args(),
        *_volume_args(project_dir),
        image,
        "process",
        config_filename,
    ]


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

    Same resolution PyOPIA's own `pipeline.py` uses internally to load a step's class -
    reused here (for introspection and thumbnail generation) rather than reinvented, so
    both stay consistent with how PyOPIA itself loads pipeline steps. Real unit tests
    (tests/test_docker_client.py) resolve stdlib classes rather than PyOPIA ones, so they
    don't need PyOPIA installed; its source is embedded verbatim into the Docker-side
    scripts below via `inspect.getsource`, so what's tested is what runs.
    """
    classname = pipeline_class.rsplit(".", 1)[-1]
    modulename = pipeline_class.rsplit(".", 1)[0]
    return getattr(importlib.import_module(modulename), classname)


def parse_numpydoc_params(doc: str | None) -> dict[str, str]:
    """Pull {param_name: description} out of a numpydoc-style docstring's "Parameters" section.

    numpydoc sections look like "Heading\\n----...\\n" - find every such heading, then take
    the lines between the "Parameters" heading and whichever heading comes next (usually
    "Returns"). A real, defined top-level function (not just embedded script text) so it has
    real unit tests (tests/test_docker_client.py) against synthetic docstrings, independent of
    Docker/PyOPIA being installed at all - its source is embedded verbatim into
    `_INTROSPECT_STEPS_SCRIPT` below via `inspect.getsource`, so what's tested is what runs.
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
    """The introductory paragraph of a numpydoc-style docstring - just the plain-language
    "what does this step do" text PyOPIA's own class docstrings open with, before any
    "Required keys"/other detail. Strips Sphinx cross-reference markup (`:class:`x``,
    `:func:`x``) down to the bare name, since that's meant for rendered docs, not a plain
    label in the Configuration tab. Same tested-then-embedded pattern as `parse_numpydoc_params`.
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

result = {{}}
for step_name, step in (config.get("steps") or {{}}).items():
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
        result[step_name] = {{"pipeline_class": pipeline_class, "summary": summary, "fields": fields}}
    except Exception as e:
        result[step_name] = {{"pipeline_class": pipeline_class, "error": f"{{type(e).__name__}}: {{e}}"}}

print(json.dumps(result))
"""


def introspect_config_steps(project_dir: Path, config_filename: str = "config.toml", image: str = PYOPIA_IMAGE) -> dict:
    """Per-step parameter schema for `config_filename`, introspected from the pinned PyOPIA image.

    One `docker run` for the whole config, not one per step - each step's `pipeline_class`
    is imported and inspected (`inspect.signature` + its own docstring) inside the container,
    so the fields/descriptions shown always match the exact PyOPIA version this project uses.
    A step whose class can't be imported or introspected gets {"error": ...} instead of
    {"fields": ...} - callers should fall back to bare key/value editing for that step alone,
    not fail the whole tab (see refresh_results()'s _STATS_READ_ERRORS handling for the same
    per-item-fallback pattern).
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


def thumbnail_path(project_dir: Path, raw_path: Path) -> Path:
    """Where the preview for `raw_path` (a raw file under `project_dir`) lives.

    Already browser-viewable raw files (e.g. UVP's own raw images, which are already
    .png - pyopia/instrument/uvp.py) are served directly from their real path, no
    conversion needed. Everything else (silcam .silc, holo .pgm, ...) gets a cached
    thumbnail under THUMBNAIL_DIR_NAME, generated on demand by `generate_thumbnails` -
    a dedicated, dot-prefixed cache folder, deliberately not PyOPIA's own
    `images_converted/` name (that's a different, full-resolution output produced by
    PyOPIA's own `convert-raw-images` command, whose `output_folder.mkdir()` has no
    `exist_ok=True` - reusing that name risks a real collision).
    """
    if raw_path.suffix.lower() in _BROWSER_VIEWABLE_EXTENSIONS:
        return raw_path
    return project_dir / THUMBNAIL_DIR_NAME / f"{raw_path.stem}.png"


# Runs inside the project's own pinned PyOPIA image - loads each raw file the same way
# PyOPIA's own `convert-raw-images` CLI command does (steps.load.pipeline_class, called
# once per file) and lets matplotlib's imsave() handle the per-instrument-type array
# normalization (uint8 RGB for silcam, float grayscale for holo, ...) rather than
# hand-rolling that per format. One Docker call converts a whole batch, not one call per
# image - confirmed by testing that container startup, not the actual conversion, is what
# dominates a single call's cost. Prints a result line after *each* image (not just a
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
    # step is a real, confirmed source of corrupt/truncated PNGs on some filesystems
    # (seen over a Docker bind mount), since PIL's Image.open() keeps a lazy reference
    # to the file it's still open on when the save() back to that same path happens.
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

    One Docker call for the whole batch (typically a page's worth of images), not one
    per image - see `_GENERATE_THUMBNAILS_SCRIPT`'s comment for why. Raw files already
    browser-viewable are skipped, no Docker call needed for them (see `thumbnail_path`).
    Streamed via `run_streamed` (not a single blocking call): `on_progress(done, total)`
    and `on_image_done(raw_path, error)` - error is None on success - are both called as
    each image in the batch finishes, so the caller can update the overall progress bar
    *and* that specific image's own preview immediately, not only once the whole batch
    completes.

    Returns {str(raw_path): error_message} for any image that failed to convert - a
    missing entry means it succeeded and `thumbnail_path(project_dir, raw_path)` now
    exists on disk. Callers should show the successfully-converted thumbnails and a
    per-image error for the rest, not fail the whole page over one bad file.
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
    raw error - same calibrated-not-blanket pattern as `interpret_failure`. The one
    pattern recognised so far is a real, confirmed failure mode: the project's
    `steps.load.pipeline_class` doesn't actually match its raw files' format (e.g. a
    holo loader pointed at silcam .silc files), which surfaces as an image-library
    "no backend" error that means nothing to a non-expert user.
    """
    if any(marker in error.lower() for marker in _THUMBNAIL_LOAD_MISMATCH_MARKERS):
        return (
            "Couldn't read this file with the project's current load settings - this "
            "usually means the Configuration tab's load step doesn't match this "
            "project's actual raw file format. Check steps.load.pipeline_class there."
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


# PyOPIA's own "download example data" step (urllib.request.urlretrieve, a ~44MB zip)
# prints no progress at all while it runs - confirmed a real, successful run got killed
# by a too-short timeout here, well before it could finish on an ordinary connection.
INACTIVITY_TIMEOUT_SECONDS = 600


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
                "operation (like pulling the Docker image or downloading example data) has stalled. Stopping."
            )
            return -1
        if not raw_line:
            break
        on_line(raw_line.decode(errors="replace").rstrip("\r\n"))
    return await process.wait()
