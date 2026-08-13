# pyopia-gui

**An open-source graphical interface for [PyOPIA](https://github.com/SINTEF/pyopia).**

PyOPIA is a Python toolbox for processing and analysing particle images from
ocean instruments (SilCam, holographic imaging, UVP). `pyopia-gui` provides a
graphical front end for configuring, running, and reviewing PyOPIA processing
jobs, without needing to work directly with config files and the command line.

> **Status:** Early development. Not yet ready for general use; expect things
> to move and change. [ Update this line as the project matures. ]

## What this is (and isn't)

`pyopia-gui` is a client that orchestrates PyOPIA - it launches and monitors
PyOPIA processing runs (via PyOPIA's own Docker image) and helps visualise the
results. It is not a fork or reimplementation of PyOPIA itself; PyOPIA remains
the processing engine, developed and maintained at
[SINTEF/pyopia](https://github.com/SINTEF/pyopia).

## Getting started

Requires [uv](https://docs.astral.sh/uv/) and [Docker](https://docs.docker.com/get-docker/)
(pyopia-gui orchestrates PyOPIA's own Docker image to run processing).

```bash
uv sync --all-groups   # install dependencies
uv run pyopia-gui      # run the app
uv run pytest          # run the tests
uv run ruff check .    # lint
uv run mkdocs serve    # preview the docs locally
```

> **Note:** `ghcr.io/sintef/pyopia` isn't currently publicly pullable ([upstream
> issue](https://github.com/SINTEF/pyopia/issues/424)). Until that's fixed, build
> it locally from PyOPIA's own source and point pyopia-gui at it:
> ```bash
> docker build -t pyopia:local --build-arg UID=$(id -u) --build-arg GID=$(id -g) /path/to/pyopia
> PYOPIA_GUI_DOCKER_IMAGE=pyopia:local uv run pyopia-gui
> ```

Once it's running, open the URL it prints in your browser. The "Project folder"
field controls both what "Create example project" creates and what "Run
processing" processes - it starts out pointing at a canned example project you
can create with one click, but you can browse to (or type) any folder with its
own PyOPIA `config.toml` at any time.

## License

`pyopia-gui` is released under the **GNU Affero General Public License v3.0**
(AGPL-3.0) - see [LICENSE](LICENSE). In short: you're free to use, study,
modify and redistribute this software, including running it as a hosted
service, provided that modifications - including to a version offered over a
network - are made available under the same licence.

## Contributing

Contributions are welcome - see [CONTRIBUTING.md](CONTRIBUTING.md).

---

pyopia-gui is a project of Nimmo Smith Technologies Limited.
Copyright © 2026 Nimmo Smith Technologies Limited and contributors.
