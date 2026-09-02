# pyopia-gui

**An open-source graphical interface for [PyOPIA](https://github.com/SINTEF/pyopia).**

PyOPIA is a Python toolbox for processing and analysing particle images from
ocean instruments (SilCam, holographic imaging, UVP). `pyopia-gui` provides a
graphical front end for configuring, running, and reviewing PyOPIA processing
jobs, without needing to work directly with config files and the command line.

> **Status:** Usable end-to-end - create a project, explore raw data,
> configure processing, preview its effect on a single image, run it, and
> review results. Still early and evolving, so bug reports and feedback are
> very welcome.

## What this is (and isn't)

`pyopia-gui` is a client that orchestrates PyOPIA - it launches and monitors
PyOPIA processing runs (via PyOPIA's own Docker image) and helps visualise the
results. It is not a fork or reimplementation of PyOPIA itself; PyOPIA remains
the processing engine, developed and maintained at
[SINTEF/pyopia](https://github.com/SINTEF/pyopia).

## Getting started

Just want to use pyopia-gui, without installing Python or using a terminal? See the
[installing guide](docs/installing.md#option-a-download-the-app-no-install-needed) instead - it
walks through downloading a ready-to-run copy. The steps below are for running (and
developing) pyopia-gui from source.

Requires [uv](https://docs.astral.sh/uv/) and [Docker](https://docs.docker.com/get-docker/)
(pyopia-gui orchestrates PyOPIA's own Docker image to run processing).

```bash
uv sync --group dev --group docs   # install dependencies
uv run pyopia-gui                  # run the app
uv run pytest                      # run the tests
uv run ruff check .                # lint
uv run mkdocs serve                # preview the docs locally
```

> **Note:** `ghcr.io/sintef/pyopia` isn't currently publicly pullable ([upstream
> issue](https://github.com/SINTEF/pyopia/issues/424)). Until that's fixed,
> pyopia-gui defaults to a mirror we publish ourselves at
> `ghcr.io/nimmo-smith-technologies/pyopia` (see
> [ADR 0006](docs/decisions/0006-2026-08-13-mirror-pyopia-image.md)) - no extra
> steps needed. If you'd rather use the official image once it's public again, or
> build your own from source, override it:
> ```bash
> PYOPIA_GUI_DOCKER_IMAGE=ghcr.io/sintef/pyopia:latest uv run pyopia-gui
> ```

> **Note:** pyopia-gui binds to `localhost` only by default - there's no login of any
> kind, so anyone who can reach it has full control (including arbitrary `docker run`
> access). Only override this if you deliberately want it reachable from other
> machines on a network you trust:
> ```bash
> PYOPIA_GUI_HOST=0.0.0.0 uv run pyopia-gui
> ```

Once it's running, open the URL it prints in your browser. The "Project folder"
field controls both what "Create example project" creates and what "Run
processing" processes - it starts out pointing at a canned example project you
can create with one click, but you can browse to (or type) any folder with its
own PyOPIA `config.toml` at any time.

## Building a native app (experimental)

pyopia-gui can also be bundled into a standalone, double-click-to-run app with
[PyInstaller](https://pyinstaller.org/) - no `uv`, Python, or terminal needed to
*use* the result, though building it still does:

```bash
uv sync --group native
uv run nicegui-pack --name pyopia-gui --onefile --windowed src/pyopia_gui/native_app.py
```

The built app appears under `dist/`. `.github/workflows/build-native.yml` builds it
for Linux, macOS (Apple Silicon only), and Windows in CI and publishes it to the
[Releases page](https://github.com/nimmo-smith-technologies/pyopia-gui/releases) on a
tagged version. For downloading and running a pre-built copy, including per-platform
setup notes, see the
[installing guide](docs/installing.md#option-a-download-the-app-no-install-needed) instead of
building your own. The downloadable app is newer and less tested than running from
source (see [Getting started](#getting-started) above), so if you hit something
unexpected, running from source is the more battle-tested fallback.

## License

`pyopia-gui` is released under the **GNU Affero General Public License v3.0**
(AGPL-3.0) - see [LICENSE](LICENSE). In short: you're free to use, study,
modify and redistribute this software, including running it as a hosted
service, provided that modifications - including to a version offered over a
network - are made available under the same licence.

It also includes some third-party code under its own license - see
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).

## Contributing

Contributions are welcome - see [CONTRIBUTING.md](CONTRIBUTING.md).

---

pyopia-gui is a project of Nimmo Smith Technologies Limited.
Copyright © 2026 Nimmo Smith Technologies Limited and contributors.
