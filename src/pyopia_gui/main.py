# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Nimmo Smith Technologies Limited

import os
import tomllib
import webbrowser
from pathlib import Path

import tomli_w
from nicegui import background_tasks, ui
from nicegui import run as nicegui_run

from pyopia_gui import __version__, docker_client, vendored_stats, version_check

DEFAULT_PROJECT_DIR = Path.home() / "pyopia-gui-projects" / "demo"
REPO_URL = "https://github.com/nimmo-smith-technologies/pyopia-gui"
LICENSE_URL = f"{REPO_URL}/blob/main/LICENSE"
THIRD_PARTY_LICENSES_URL = f"{REPO_URL}/blob/main/THIRD_PARTY_LICENSES.md"

# Failure modes for reading/computing a project's summary stats: a different pinned
# PyOPIA version's stats schema not matching what's vendored (KeyError), a stats file
# still being written by a concurrent run or otherwise unreadable (OSError/ValueError),
# or a malformed config.toml (TOMLDecodeError/TypeError, matching docker_client's own
# config-reading error handling).
_STATS_READ_ERRORS = (KeyError, ValueError, OSError, tomllib.TOMLDecodeError, TypeError)

# The `[general]` config keys the Configuration tab hand-labels itself, rather than
# introspecting - they're not tied to any pipeline_class (see docker_client's
# introspect_config_steps), so there's no class docstring to pull a description from.
_GENERAL_LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]


def _toml_value_from_text(text: str) -> object:
    """Parse a single TOML value (e.g. `["a", "b"]`, `true`, `12`) typed as free text.

    Reuses TOML's own value grammar (via a throwaway `key = ...` wrapper) rather than
    hand-rolling a parser, so anything a real config.toml could hold (lists, inline
    tables, numbers, strings) round-trips the same way it would if hand-edited in a
    text editor.
    """
    return tomllib.loads(f"_ = {text}")["_"]


def _text_from_toml_value(value: object) -> str:
    """The inverse of `_toml_value_from_text` - how a non-scalar value is shown for editing."""
    return tomli_w.dumps({"_": value}).removeprefix("_ = ").strip()


async def _confirm_generate_config(project_dir: Path, config: dict) -> tuple[bool, dict[str, str] | None]:
    """Ask for the instrument type (and confirm-before-overwrite) for a fresh default config.

    Pre-fills from the project's existing config where possible - most projects only need
    to pick the instrument, not retype paths PyOPIA already knows about. Returns
    (confirmed, generate_config_command kwargs); kwargs is None if cancelled.
    """
    general = config.get("general") if isinstance(config.get("general"), dict) else {}
    steps = config.get("steps") if isinstance(config.get("steps"), dict) else {}
    load_class = (steps.get("load") or {}).get("pipeline_class", "") if isinstance(steps.get("load"), dict) else ""
    default_instrument = next((i for i in ("silcam", "holo", "uvp") if i in load_class), "silcam")
    classifier_step = steps.get("classifier") if isinstance(steps.get("classifier"), dict) else {}

    with ui.dialog() as dialog, ui.card():
        ui.label("Generate a default config.toml?").classes("text-lg font-medium")
        ui.label(
            "This overwrites the project's current config.toml with PyOPIA's own bare "
            "defaults for the instrument type chosen below. Any values you've customised - "
            "including ones added outside PyOPIA's defaults, like metadata/auxiliary-data "
            "file links - will be lost."
        ).classes("text-sm text-gray-500")
        instrument_select = ui.select(["silcam", "holo", "uvp"], value=default_instrument, label="Instrument type")
        instrument_select.classes("w-full")
        raw_files_input = ui.input("Raw files pattern", value=general.get("raw_files", "images/*.silc")).classes(
            "w-full"
        )
        model_path_input = ui.input("Classifier model path", value=classifier_step.get("model_path", "")).classes(
            "w-full"
        )
        model_path_input.tooltip("Only used for silcam - leave blank for holo/uvp")
        outfolder_input = ui.input("Output folder", value="processed").classes("w-full")
        output_prefix_input = ui.input("Output filename prefix", value=project_dir.name).classes("w-full")
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
            ui.button("Generate", on_click=lambda: dialog.submit(True))
    confirmed = bool(await dialog)
    if not confirmed:
        return False, None
    return True, {
        "instrument": instrument_select.value,
        "raw_files": raw_files_input.value,
        "model_path": model_path_input.value,
        "outfolder": outfolder_input.value,
        "output_prefix": output_prefix_input.value,
    }


async def _confirm_create(project_dir: Path) -> tuple[bool, str | None]:
    """Ask the user to confirm the exact resolved path before creating anything there.

    The Docker mount already limits what a run can touch on the host to this one
    folder - the real risk isn't the container reaching further than that, it's a
    person landing somewhere unintended via the folder browser (one click too many
    on "up") and not realising before something gets created there. Showing the
    full resolved path and requiring an explicit click catches that without
    blocking any particular location - including legitimate ones like an external
    drive's own root.

    Also lets the user pick which PyOPIA version this new project should use, if the
    mirror's published versions are reachable - a new project's version is never chosen
    automatically, since someone may deliberately want to match an older project rather
    than always get the newest. Returns (confirmed, chosen_version); chosen_version is
    None if there was nothing to choose from (offline, or PYOPIA_GUI_DOCKER_IMAGE
    already overrides the image entirely) or the dialog was cancelled.
    """
    versions: list[str] = []
    if "PYOPIA_GUI_DOCKER_IMAGE" not in os.environ:
        versions = await nicegui_run.io_bound(docker_client.list_available_versions)

    with ui.dialog() as dialog, ui.card():
        ui.label("Create a new PyOPIA project here?").classes("text-lg font-medium")
        ui.label(str(project_dir)).classes("font-mono text-sm bg-gray-100 p-2 rounded break-all")
        ui.label("This creates a new folder at the exact path above and downloads example data into it.").classes(
            "text-sm text-gray-500"
        )
        version_select = None
        if versions:
            version_select = ui.select(versions, value=versions[0], label="PyOPIA version").classes("w-full")
            version_select.tooltip(
                "Which PyOPIA version to use for this project - it'll keep using this same version "
                "for consistency, even after newer ones become available"
            )
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
            ui.button("Create here", on_click=lambda: dialog.submit(True))
    confirmed = bool(await dialog)
    chosen_version = version_select.value if (confirmed and version_select) else None
    return confirmed, chosen_version


def _open_folder_browser(folder_input: ui.input) -> None:
    """Open a dialog for browsing the server's filesystem and picking a folder."""
    start_dir = Path(folder_input.value.strip()).expanduser()
    if not start_dir.is_dir():
        start_dir = start_dir.parent if start_dir.parent.is_dir() else Path.home()
    current = {"path": start_dir}

    with ui.dialog() as dialog, ui.card().classes("w-full max-w-lg"):
        path_label = ui.label().classes("text-sm text-gray-500")
        listing = ui.column().classes("w-full max-h-96 overflow-y-auto")

        def go_to(path: Path) -> None:
            current["path"] = path
            refresh()

        def refresh() -> None:
            path_label.set_text(str(current["path"]))
            listing.clear()
            with listing, ui.list().props("bordered separator"):
                if current["path"].parent != current["path"]:
                    with (
                        ui.item(on_click=lambda: go_to(current["path"].parent))
                        .props("clickable")
                        .tooltip("Go up to the parent folder")
                    ):
                        ui.item_label("⬆ ..")
                try:
                    subdirs = sorted(p for p in current["path"].iterdir() if p.is_dir() and not p.name.startswith("."))
                except PermissionError:
                    ui.item_label("Permission denied").classes("text-red")
                    return
                for entry in subdirs:
                    with ui.item(on_click=lambda e=entry: go_to(e)).props("clickable"):
                        ui.item_label(f"📁 {entry.name}")

        refresh()
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=dialog.close).props("flat").tooltip(
                "Close without changing the project folder"
            )
            ui.button(
                "Select this folder",
                on_click=lambda: (folder_input.set_value(str(current["path"])), dialog.close()),
            ).tooltip("Use the folder shown above as the project folder")

    dialog.open()


async def _choose_version(versions: list[str]) -> str | None:
    """Ask the user to pick a PyOPIA version from `versions`, defaulting to the newest.

    Returns the chosen version, or None if cancelled.
    """
    with ui.dialog() as dialog, ui.card():
        ui.label("Choose a PyOPIA version").classes("text-lg font-medium")
        ui.label(
            "This project has no processed results yet, so there's nothing to stay consistent "
            "with - pick a version now and it'll keep using this same one from here on."
        ).classes("text-sm text-gray-500")
        version_select = ui.select(versions, value=versions[0], label="PyOPIA version").classes("w-full")
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat")
            ui.button("Use this version", on_click=lambda: dialog.submit(version_select.value))
    return await dialog


async def _confirm_pinned_version(pinned: str, newest: str | None) -> bool:
    """Show which PyOPIA version a reprocessing run will use, and flag if a newer one exists.

    Purely informational plus a confirm/cancel gate - the version itself is never chosen
    here (see resolve_run_image's docstring on reproducibility): this only makes sure
    it's always clear, every time, exactly what's about to run. Returns False if cancelled.
    """
    with ui.dialog() as dialog, ui.card():
        ui.label(f"This will run PyOPIA v{pinned}").classes("text-lg font-medium")
        if newest and newest != pinned:
            ui.label(
                f"A newer version (v{newest}) is available, but this project keeps using the "
                "version its existing results were produced with, for consistency. Start a new "
                "project, or clear this project's previous output, if you want to use the newer "
                "version instead."
            ).classes("text-sm text-gray-500")
        else:
            ui.label("This matches the version its existing results were produced with.").classes(
                "text-sm text-gray-500"
            )
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
            ui.button("Run processing", on_click=lambda: dialog.submit(True)).mark("confirm-pinned-version")
    return bool(await dialog)


async def _show_update_if_newer(update_link: ui.link) -> None:
    latest = await nicegui_run.io_bound(version_check.check_for_newer_release, __version__)
    if latest:
        update_link.text = f"{latest} available ↗"
        update_link.visible = True


def _show_about_dialog() -> None:
    with ui.dialog() as dialog, ui.card():
        ui.label("About pyopia-gui").classes("text-lg font-medium")
        ui.label(f"Version {__version__}").classes("text-sm text-gray-500")
        ui.label(
            "Released under the GNU Affero General Public License v3.0 (AGPL-3.0) - "
            "free to use, study, modify and redistribute, including as a hosted service, "
            "provided modifications are shared under the same license."
        ).classes("text-sm")
        with ui.row().classes("gap-4"):
            ui.link("License ↗", LICENSE_URL, new_tab=True)
            ui.link("Third-party licenses ↗", THIRD_PARTY_LICENSES_URL, new_tab=True)
        with ui.row().classes("w-full justify-end"):
            ui.button("Close", on_click=dialog.close).props("flat")
    dialog.open()


@ui.page("/")
def index() -> None:
    with ui.header().classes("items-center justify-between"):
        with ui.row().classes("items-baseline gap-2"):
            ui.label("pyopia-gui").classes("text-2xl")
            ui.label(f"v{__version__}").classes("text-sm text-white/70")
            update_link = ui.link("", version_check.RELEASES_PAGE_URL, new_tab=True).classes("text-sm text-yellow-300")
            update_link.visible = False
            update_link.tooltip("A newer version of pyopia-gui is available - opens the Releases page")
            background_tasks.create(_show_update_if_newer(update_link), name="version-check")
        with ui.row().classes("items-center gap-4"):
            ui.link("About", "#").on("click.prevent", _show_about_dialog).classes("text-white")
            ui.link("View on GitHub ↗", REPO_URL, new_tab=True).classes("text-white")

    with ui.footer().classes("justify-center"):
        ui.label(
            "pyopia-gui is a project of Nimmo Smith Technologies Limited. "
            "Copyright © 2026 Nimmo Smith Technologies Limited and contributors."
        ).classes("text-sm")

    docker_status = docker_client.check_docker()
    if docker_status != docker_client.DockerStatus.AVAILABLE:
        ui.label("Docker isn't ready yet").classes("text-lg text-red")
        ui.markdown(docker_client.setup_guidance(docker_status))
        download_url = docker_client.setup_guidance_url(docker_status)
        if download_url:
            download_button = ui.button("Open Docker download page", on_click=lambda: webbrowser.open(download_url))
            download_button.tooltip("Opens in your default browser, not this window")
        recheck_button = ui.button("Recheck", on_click=lambda: ui.navigate.reload())
        recheck_button.tooltip("Re-checks whether Docker is installed and running")
        return

    with ui.tabs().classes("border border-gray-300 rounded-t-lg") as tabs:
        ui.tab("project", label="1. Project")
        explorer_tab = ui.tab("explorer", label="2. Raw data explorer")
        config_tab = ui.tab("config", label="3. Configuration")
        process_tab = ui.tab("process", label="4. Process")
        results_tab = ui.tab("results", label="5. Results")
    process_tab.disable()
    results_tab.disable()
    config_tab.disable()
    explorer_tab.disable()
    explorer_tab.tooltip("Coming soon")

    with ui.tab_panels(tabs, value="project").classes("w-full"):
        with ui.tab_panel("project"):
            with ui.row().classes("w-full items-center gap-2"):
                folder_input = ui.input("Project folder", value=str(DEFAULT_PROJECT_DIR)).classes("grow")
                folder_input.tooltip("The PyOPIA project folder to create or process - must contain a config.toml")
                folder_input.props("debounce=500")
                browse_button = ui.button("Browse…", on_click=lambda: _open_folder_browser(folder_input))
                browse_button.tooltip("Browse this computer's folders to pick an existing project")
            ui.label(
                "Determines where the example project below gets created, and what folder processing "
                "runs against - point it at your own data any time."
            ).classes("text-sm text-gray-500")
            create_button = ui.button("Create example project")
            create_button.tooltip(
                "Downloads a small example dataset and sets up a ready-to-run PyOPIA project in the folder above"
            )

        with ui.tab_panel("explorer"):
            ui.label("Raw data explorer - coming soon.").classes("text-sm text-gray-500")

        with ui.tab_panel("config"):
            config_container = ui.column().classes("w-full gap-4")

        with ui.tab_panel("process"):
            ui.label("Runs PyOPIA on the project folder above, then builds a montage of the particles found.").classes(
                "text-sm text-gray-500"
            )
            run_button = ui.button("Run processing")
            run_button.tooltip("Runs PyOPIA processing on the folder above")

        with ui.tab_panel("results"):
            results_busy_note = ui.label(
                "Processing is running - results below may be about to change once it finishes."
            ).classes("text-sm text-orange-600")
            results_busy_note.visible = False
            results_container = ui.column().classes("w-full gap-4")

    with ui.row().classes("items-center gap-2"):
        spinner = ui.spinner(size="md")
        spinner.visible = False
        status_label = ui.label("Ready").classes("text-md font-medium")
        status_label.tooltip("The current step in the create/process workflow above")

    ui.add_css("""
        .pyopia-log .q-scrollarea__bar {
            opacity: 1;
            background: #e0e0e0;
            border-radius: 4px;
        }
        .pyopia-log .q-scrollarea__bar--horizontal {
            height: 10px;
        }
        .pyopia-log .q-scrollarea__bar--vertical {
            width: 10px;
        }
    """)
    log = ui.log(max_lines=500).classes("pyopia-log w-full h-64 bg-black text-white")
    log.tooltip("Raw output from PyOPIA - useful for troubleshooting if something goes wrong")

    # A version chosen for a brand new project (at create time, or by resolve_run_image's
    # own picker) has nothing written to disk to read it back from until the first
    # successful process/merge - without this, on_run() would ask again immediately
    # after on_create() already asked, since read_pinned_version() still finds nothing.
    # Keyed by str(project_dir); only remembered for this page session, not persisted -
    # once real output exists, the stats file itself takes over as the source of truth.
    chosen_versions_this_session: dict[str, str] = {}

    def set_status(text: str, *, busy: bool) -> None:
        status_label.set_text(text)
        spinner.visible = busy
        results_busy_note.visible = busy

    async def run_streamed_to_log(command: list[str]) -> tuple[int, list[str]]:
        log.push("$ " + " ".join(command))
        lines: list[str] = []

        def on_line(line: str) -> None:
            lines.append(line)
            log.push(line)

        exit_code = await docker_client.run_streamed(command, on_line)
        return exit_code, lines

    def report_failure(lines: list[str], fallback: str) -> None:
        message = docker_client.interpret_failure(lines) or f"{fallback} - see log below"
        log.push(f"→ {message}", classes="text-yellow-300 font-bold")
        set_status(message, busy=False)
        ui.notify(message, type="negative")

    async def resolve_run_image(project_dir: Path) -> str | None:
        """Which PyOPIA image to process `project_dir` with, or None if the user cancelled.

        Never picks a version automatically if one's already in play: if this project has
        existing output, reuses exactly the version that produced it, so reprocessing or
        resuming a dataset never silently switches versions partway through. A project with
        no output yet - whether brand new or pointed at pre-existing, never-processed data -
        gets the same explicit choice as on_create's version picker, for the same reason:
        someone may deliberately want to match a different project's version. But if that
        choice was already made this session (e.g. moments ago at create time) and nothing's
        been processed since, reuse it silently rather than asking again immediately - once
        real output exists, `pinned` below takes over as the source of truth as usual, so
        this only bridges the gap up to the first successful run, not the whole session.
        """
        if "PYOPIA_GUI_DOCKER_IMAGE" in os.environ:
            return docker_client.PYOPIA_IMAGE
        pinned = await nicegui_run.io_bound(docker_client.read_pinned_version, project_dir)
        if pinned:
            newest_available = await nicegui_run.io_bound(docker_client.list_available_versions)
            newest = newest_available[0] if newest_available else None
            if not await _confirm_pinned_version(pinned, newest):
                return None
            return docker_client.image_for_version(pinned)
        remembered = chosen_versions_this_session.get(str(project_dir))
        if remembered:
            return docker_client.image_for_version(remembered)
        versions = await nicegui_run.io_bound(docker_client.list_available_versions)
        if not versions:
            return docker_client.PYOPIA_IMAGE
        chosen = await _choose_version(versions)
        if chosen:
            chosen_versions_this_session[str(project_dir)] = chosen
        return docker_client.image_for_version(chosen) if chosen else None

    async def image_for_existing_project(project_dir: Path) -> str:
        """The image to use for further Docker operations (e.g. generating a montage) on a
        project that already has results - always its pinned version, never a fresh choice,
        since there's nothing to choose between once results already exist.
        """
        if "PYOPIA_GUI_DOCKER_IMAGE" in os.environ:
            return docker_client.PYOPIA_IMAGE
        pinned = await nicegui_run.io_bound(docker_client.read_pinned_version, project_dir)
        return docker_client.image_for_version(pinned)

    async def refresh_results(project_dir: Path) -> None:
        """(Re)build the Results tab's content from whatever's currently on disk."""
        results_container.clear()
        if docker_client.validate_project(project_dir) is not None:
            with results_container:
                ui.label("No valid project selected.").classes("text-sm text-gray-500")
            return

        stats_path = project_dir / docker_client.stats_filename(project_dir)
        if not stats_path.is_file():
            with results_container:
                ui.label("No results yet - run processing first.").classes("text-sm text-gray-500")
            return

        with results_container:
            pinned = await nicegui_run.io_bound(docker_client.read_pinned_version, project_dir)
            if pinned:
                ui.label(f"Project {project_dir} processed with PyOPIA v{pinned}").classes(
                    "font-mono text-sm text-gray-500 break-all"
                )

            async def generate_montage() -> None:
                image = await image_for_existing_project(project_dir)
                set_status("Building montage…", busy=True)
                command = docker_client.make_montage_command(
                    project_dir, docker_client.stats_filename(project_dir), image=image
                )
                exit_code, lines = await run_streamed_to_log(command)
                if exit_code == 0:
                    set_status("Montage created", busy=False)
                    await refresh_results(project_dir)
                else:
                    report_failure(lines, "Montage creation failed")

            montage_path = project_dir / "montage.png"
            if montage_path.is_file():
                ui.image(str(montage_path)).classes("w-full max-w-2xl")
                ui.label(str(montage_path)).classes("font-mono text-xs text-gray-500 break-all")
                ui.button("Regenerate montage", on_click=generate_montage).tooltip(
                    "Builds a new montage - particles are placed randomly, so each one looks different "
                    "even from the same results"
                )
            else:
                ui.button("Generate montage", on_click=generate_montage).tooltip(
                    "Builds a montage image of the particles found, from this project's existing results"
                )

            try:
                px_size = docker_client.pixel_size(project_dir)
                summary = await nicegui_run.io_bound(vendored_stats.summarize, str(stats_path), px_size)
            except _STATS_READ_ERRORS as e:
                ui.label(f"Couldn't compute summary statistics: {e}").classes("text-sm text-red")
            else:
                if summary is None:
                    # io_bound() returns None (rather than raising) if this call was
                    # cancelled or the app is shutting down - nothing to show, and no
                    # error either, since there's likely no page left to show it on.
                    return
                ui.label(
                    f"{summary.particle_count} particles found across "
                    f"{summary.images_with_particles} images with detected particles"
                ).classes("text-md")
                ui.label(f"d50 (median particle size): {summary.d50_microns:.1f} µm").classes("text-md")
                # The size bins are log-spaced (get_size_bins() - each ~1.18x the last), so
                # a log x-axis is what makes them appear evenly spaced, matching the data's
                # real structure - needs a numeric ("value"/"log") axis rather than a
                # "category" one, so points are given as explicit [x, y] pairs.
                chart_options = {
                    "tooltip": {"trigger": "item"},
                    "grid": {"containLabel": True},
                    "xAxis": {
                        "type": "log",
                        "name": "Diameter (µm)",
                        "nameLocation": "middle",
                        "nameGap": 30,
                    },
                    "yAxis": {
                        "type": "value",
                        "name": "Particle count",
                        "nameLocation": "middle",
                        "nameGap": 40,
                        "nameRotate": 90,
                    },
                    "series": [
                        {
                            "type": "line",
                            "symbol": "circle",
                            "data": [
                                [float(dia), float(count)]
                                for dia, count in zip(summary.dias, summary.number_distribution, strict=True)
                            ],
                        }
                    ],
                }
                # nicegui's own CSS hardcodes `.nicegui-echart { height: 16rem }`, which
                # otherwise wins over the aspect-square utility (an explicit height beats
                # aspect-ratio) - override it inline, which takes precedence over both.
                ui.echart(chart_options).classes("w-full max-w-2xl aspect-square").style("height: auto")

    async def refresh_config(project_dir: Path) -> None:
        """(Re)build the Configuration tab's content from the project's current config.toml."""
        config_container.clear()
        if docker_client.validate_project(project_dir) is not None:
            with config_container:
                ui.label("No valid project selected.").classes("text-sm text-gray-500")
            return

        try:
            config = await nicegui_run.io_bound(docker_client.load_config, project_dir)
        except (OSError, tomllib.TOMLDecodeError) as e:
            with config_container:
                ui.label(f"Couldn't read config.toml: {e}").classes("text-sm text-red")
            return
        if config is None:
            return  # io_bound cancellation guard, same reasoning as refresh_results()

        with config_container:
            general = config.get("general") if isinstance(config.get("general"), dict) else {}

            async def generate_default_config() -> None:
                confirmed, params = await _confirm_generate_config(project_dir, config)
                if not confirmed or params is None:
                    return
                image = await image_for_existing_project(project_dir)
                set_status("Generating default config…", busy=True)
                command = docker_client.generate_config_command(project_dir, image=image, **params)
                exit_code, lines = await run_streamed_to_log(command)
                if exit_code != 0:
                    report_failure(lines, "Generating default config failed")
                    return
                generated_path = project_dir / f"{params['instrument']}-config.toml"
                generated_path.replace(project_dir / "config.toml")
                set_status("Default config generated", busy=False)
                ui.notify("Default config generated", type="positive")
                await refresh_config(project_dir)

            with ui.row().classes("w-full justify-between items-center"):
                ui.label("General").classes("text-lg font-medium")
                generate_button = ui.button("Generate default config…", on_click=generate_default_config)
                generate_button.tooltip(
                    "Overwrite this project's config.toml with PyOPIA's own bare defaults for a chosen instrument type"
                )

            raw_files_input = ui.input("raw_files", value=general.get("raw_files", "")).classes("w-full")
            pixel_size_input = ui.number("pixel_size (µm/pixel)", value=general.get("pixel_size")).classes("w-full")
            ui.label(
                "⚠ Verify this matches your actual instrument/lens setup - pixel size varies per "
                "physical instrument (holo setups especially have many sub-variants) and isn't "
                "something pyopia-gui can check for you."
            ).classes("text-xs text-orange-600 -mt-3")
            log_level_select = ui.select(_GENERAL_LOG_LEVELS, value=general.get("log_level", "INFO"), label="log_level")
            log_level_select.classes("w-full")
            log_file_input = ui.input("log_file", value=general.get("log_file") or "").classes("w-full")
            log_file_input.tooltip("Leave blank to log to the console instead of a file")

            ui.separator()

            with ui.row().classes("items-center gap-2"):
                ui.label("Processing steps").classes("text-lg font-medium")
                steps_spinner = ui.spinner(size="sm")
            steps_column = ui.column().classes("w-full gap-2")

            # name -> (input element, the current value's Python type - bool/int/float/str,
            # or "raw" for a list/dict/etc shown as TOML-literal text) - kept per-step so
            # save_changes() knows how to read each field back without re-guessing its type.
            step_inputs: dict[str, dict[str, tuple[ui.element, object]]] = {}

            steps = config.get("steps") if isinstance(config.get("steps"), dict) else {}

            async def load_steps() -> None:
                schema = await nicegui_run.io_bound(docker_client.introspect_config_steps, project_dir)
                steps_spinner.visible = False
                with steps_column:
                    for step_name, step in steps.items():
                        if not isinstance(step, dict) or "pipeline_class" not in step:
                            continue
                        info = schema.get(step_name, {})
                        with ui.expansion(step_name, caption=step["pipeline_class"]).classes("w-full border rounded"):
                            if info.get("summary"):
                                ui.label(info["summary"]).classes("text-sm text-gray-600")
                            fields = step_inputs.setdefault(step_name, {})
                            if "fields" in info:
                                if not info["fields"]:
                                    ui.label("No configurable options for this step.").classes("text-xs text-gray-500")
                                for field in info["fields"]:
                                    name = field["name"]
                                    current = field["current_value"]
                                    value = current if current is not None else field["default"]
                                    with ui.column().classes("w-full gap-0"):
                                        if isinstance(value, bool):
                                            element = ui.checkbox(name, value=value)
                                        elif isinstance(value, int | float):
                                            element = ui.number(name, value=value).classes("w-full")
                                        elif isinstance(value, str) or value is None:
                                            element = ui.input(name, value=value or "").classes("w-full")
                                        else:
                                            element = ui.input(name, value=_text_from_toml_value(value)).classes(
                                                "w-full"
                                            )
                                            value = "raw"
                                        if field["description"]:
                                            ui.label(field["description"]).classes("text-xs text-gray-500")
                                    fields[name] = (element, type(value) if value != "raw" else "raw")
                            else:
                                # Introspection failed for this step - fall back to bare
                                # key/value text editing rather than blocking the whole tab.
                                if "error" in info:
                                    ui.label(f"Couldn't introspect this step: {info['error']}").classes(
                                        "text-xs text-red"
                                    )
                                for name, current in step.items():
                                    if name == "pipeline_class":
                                        continue
                                    shown = current if isinstance(current, str) else _text_from_toml_value(current)
                                    fields[name] = (ui.input(name, value=shown).classes("w-full"), "raw")

            background_tasks.create(load_steps(), name="config-introspect")

            async def save_changes() -> None:
                updated: dict = {
                    "general": {
                        "raw_files": raw_files_input.value,
                        "pixel_size": pixel_size_input.value,
                        "log_level": log_level_select.value,
                    },
                    "steps": {},
                }
                if log_file_input.value:
                    updated["general"]["log_file"] = log_file_input.value
                for step_name, fields in step_inputs.items():
                    step_config = {"pipeline_class": steps[step_name]["pipeline_class"]}
                    for name, (element, kind) in fields.items():
                        if kind is bool:
                            step_config[name] = element.value
                        elif kind is int:
                            step_config[name] = int(element.value) if element.value is not None else None
                        elif kind is float:
                            step_config[name] = float(element.value) if element.value is not None else None
                        elif kind == "raw":
                            try:
                                step_config[name] = _toml_value_from_text(element.value)
                            except tomllib.TOMLDecodeError as e:
                                ui.notify(f"{step_name}.{name}: {e}", type="negative")
                                return
                        else:
                            step_config[name] = element.value
                    updated["steps"][step_name] = step_config
                try:
                    await nicegui_run.io_bound(docker_client.write_config, project_dir, updated)
                except OSError as e:
                    ui.notify(f"Couldn't save config.toml: {e}", type="negative")
                    return
                ui.notify("Configuration saved", type="positive")
                await refresh_project_state()

            ui.button("Save changes", on_click=save_changes).classes("mt-2")

    async def refresh_project_state() -> None:
        """Update tab availability for the current project folder, and jump to Results
        if it already has output - opening an already-processed project should show
        whatever's available immediately, not require a fresh run to see it.
        """
        project_dir = Path(folder_input.value.strip()).expanduser().resolve()
        if docker_client.validate_project(project_dir) is None:
            process_tab.enable()
            config_tab.enable()
            await refresh_config(project_dir)
        else:
            process_tab.disable()
            config_tab.disable()

        try:
            has_results = (project_dir / docker_client.stats_filename(project_dir)).is_file()
        except _STATS_READ_ERRORS:
            has_results = False

        if has_results:
            results_tab.enable()
            await refresh_results(project_dir)
            tabs.value = "results"
        else:
            results_tab.disable()

    folder_input.on_value_change(lambda: background_tasks.create(refresh_project_state(), name="project-state"))
    background_tasks.create(refresh_project_state(), name="initial-project-state")

    async def on_create() -> None:
        project_dir = Path(folder_input.value.strip()).expanduser().resolve()
        if project_dir.exists():
            ui.notify(
                f"{project_dir} already exists - pick a new folder, or click "
                "'Run processing' if it's already a PyOPIA project.",
                type="negative",
            )
            return

        confirmed, chosen_version = await _confirm_create(project_dir)
        if not confirmed:
            return

        create_button.disable()
        log.clear()
        results_container.clear()
        with results_container:
            ui.label("No results yet - run processing first.").classes("text-sm text-gray-500")
        set_status("Creating example project…", busy=True)
        parent_dir = project_dir.parent
        parent_dir.mkdir(parents=True, exist_ok=True)
        if chosen_version:
            # Remembered so the very first "Run processing" click doesn't ask again -
            # there's nothing on disk yet for it to read this choice back from.
            chosen_versions_this_session[str(project_dir)] = chosen_version
        image = docker_client.image_for_version(chosen_version)
        command = docker_client.init_project_command(parent_dir, project_dir.name, image=image)
        exit_code, lines = await run_streamed_to_log(command)
        if exit_code == 0:
            set_status("Example project created", busy=False)
            ui.notify("Example project created", type="positive")
            await refresh_project_state()
            tabs.value = "process"
        else:
            report_failure(lines, "Failed to create example project")
        create_button.enable()

    async def on_run() -> None:
        project_dir = Path(folder_input.value.strip()).expanduser().resolve()
        error = docker_client.validate_project(project_dir)
        if error:
            ui.notify(error, type="negative")
            return

        run_button.disable()
        set_status("Checking PyOPIA version…", busy=True)
        image = await resolve_run_image(project_dir)
        if image is None:
            set_status("Ready", busy=False)
            run_button.enable()
            return

        # Clear everything left over from a previous run, now that this one's actually
        # starting - otherwise a new run can look like it's continuing an old one, or a
        # failed rerun can leave a stale (and no longer accurate) montage/stats on the
        # Results tab. The old stats file itself isn't deleted here (only overwritten if
        # this run succeeds), so this has to be an explicit clear, not just a re-check of
        # disk state - a stale file would otherwise still be found and redisplayed as-is.
        log.clear()
        results_container.clear()
        with results_container:
            ui.label("Processing is running…").classes("text-sm text-gray-500")
        set_status("Running processing (this can take a few minutes)…", busy=True)
        exit_code, lines = await run_streamed_to_log(docker_client.process_command(project_dir, image=image))
        if exit_code != 0:
            report_failure(lines, "Processing failed")
            run_button.enable()
            return
        ui.notify("Processing complete", type="positive")

        set_status("Merging results…", busy=True)
        merge_exit_code, merge_lines = await run_streamed_to_log(
            docker_client.merge_mfdata_command(project_dir, image=image)
        )
        if merge_exit_code != 0:
            report_failure(merge_lines, "Merging processed stats failed")
            run_button.enable()
            return

        # A previous montage was built from whatever stats existed before this run -
        # now that reprocessing has produced fresh stats, that montage no longer
        # necessarily matches them. Remove it rather than leave a stale one displayed;
        # the Results tab's own "Generate montage" button makes a new one on demand.
        (project_dir / "montage.png").unlink(missing_ok=True)

        set_status("Done", busy=False)
        await refresh_project_state()
        run_button.enable()

    create_button.on_click(on_create)
    run_button.on_click(on_run)


def run() -> None:
    ui.run(title="pyopia-gui", reload=False)


if __name__ in {"__main__", "__mp_main__"}:
    run()
