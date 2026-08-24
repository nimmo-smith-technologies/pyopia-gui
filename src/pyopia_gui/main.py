# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Nimmo Smith Technologies Limited

import math
import os
import shutil
import tomllib
import webbrowser
from collections.abc import Callable
from pathlib import Path

import tomli_w
from nicegui import background_tasks, ui
from nicegui import run as nicegui_run

from pyopia_gui import __version__, docker_client, vendored_stats, version_check

# Overridable via env var, same pattern as docker_client.PYOPIA_IMAGE - not a
# user-facing feature, but the only way to override this at all: NiceGUI's test
# harness (nicegui.testing.user_plugin) runs this whole file fresh per test via
# `runpy.run_path(..., run_name='__main__')`, an isolated execution disconnected
# from `sys.modules['pyopia_gui.main']` - a test monkeypatching this module's
# DEFAULT_PROJECT_DIR attribute directly has no effect on the app instance it's
# actually testing. os.environ is real process-wide global state, so it's the one
# thing a test can actually reach.
DEFAULT_PROJECT_DIR = Path(
    os.environ.get("PYOPIA_GUI_DEFAULT_PROJECT_DIR", str(Path.home() / "pyopia-gui-projects" / "demo"))
)
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

# The Configuration tab only offers an enable/disable switch for "classifier".
# PyOPIA's Pipeline.__init__ default `initial_steps=['initial', 'classifier',
# 'createbackground']` names two other steps that are *also* order-independent
# by the same mechanism (always constructed during __init__, regardless of dict
# position) - deliberately not offered as toggleable anyway:
# - "initial" (holo's Initial step) - always required when present. It sets up
#   `data['holo_recon_params']`, which Reconstruct needs; disabling it would
#   break every later holo step, not skip something optional.
# - "createbackground" - checked directly: no PyOPIA-shipped `generate_config`
#   (silcam/holo/uvp) ever emits a step with this name, and no class in the
#   codebase matches it either - it's a reserved default with nothing real to
#   attach a toggle to today.
# Every OTHER step is a real, sequential pipeline stage whose position matters
# (e.g. `reconstruct` must run before `segmentation`) - re-enabling one of those
# after disabling it can't be placed back at its correct position (TOML has no
# way to remember "this step's original position relative to steps in the
# *other* table" once it's moved out to steps_disabled and back).
_ORDER_INSENSITIVE_STEP_NAMES = frozenset({"classifier"})


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


async def _confirm_generate_config(project_dir: Path, config: dict) -> tuple[bool, dict[str, object] | None]:
    """Ask for the instrument type (and confirm-before-overwrite) for a fresh default config.

    Pre-fills from the project's existing config where possible - most projects only need
    to pick the instrument, not retype paths PyOPIA already knows about. Returns
    (confirmed, generate_config_command kwargs plus "classifier_enabled"); kwargs is None
    if cancelled.
    """
    general = config.get("general") if isinstance(config.get("general"), dict) else {}
    steps = config.get("steps") if isinstance(config.get("steps"), dict) else {}
    load_class = (steps.get("load") or {}).get("pipeline_class", "") if isinstance(steps.get("load"), dict) else ""
    default_instrument = next((i for i in ("silcam", "holo", "uvp") if i in load_class), "silcam")
    classifier_step = steps.get("classifier") if isinstance(steps.get("classifier"), dict) else {}
    existing_model_path = classifier_step.get("model_path", "")

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
        classifier_checkbox = ui.checkbox("Enable particle classification", value=bool(existing_model_path))
        model_path_input = ui.input("Classifier model path", value=existing_model_path).classes("w-full")
        model_path_input.bind_visibility_from(classifier_checkbox, "value")
        model_path_input.tooltip(
            "Path to a .keras classifier model file, relative to the project folder - "
            "used for silcam, holo, and uvp alike"
        )
        outfolder_input = ui.input("Output folder", value="processed").classes("w-full")
        output_prefix_input = ui.input("Output filename prefix", value=project_dir.name).classes("w-full")

        def try_submit() -> None:
            if classifier_checkbox.value and not model_path_input.value.strip():
                ui.notify("Classifier model path is required when classification is enabled", type="negative")
                return
            dialog.submit(True)

        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=lambda: dialog.submit(False))
            ui.button("Generate", on_click=try_submit)
    confirmed = bool(await dialog)
    if not confirmed:
        return False, None
    return True, {
        "instrument": instrument_select.value,
        "raw_files": raw_files_input.value,
        "model_path": model_path_input.value if classifier_checkbox.value else "",
        "outfolder": outfolder_input.value,
        "output_prefix": output_prefix_input.value,
        "classifier_enabled": classifier_checkbox.value,
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
            ui.button("Cancel", on_click=lambda: dialog.submit(False))
            ui.button("Create here", on_click=lambda: dialog.submit(True))
    confirmed = bool(await dialog)
    chosen_version = version_select.value if (confirmed and version_select) else None
    return confirmed, chosen_version


def _render_folder_browser(start_dir: Path) -> dict[str, Path]:
    """Render a path label plus a clickable folder listing, for use inside an
    already-open `ui.dialog()`/`ui.card()` context - shared by `_open_folder_browser`
    and `_choose_save_location` below, rather than duplicating the same navigation
    logic for each.

    Falls back to `start_dir`'s parent, then the home folder, if `start_dir` doesn't
    exist. Returns a live `{"path": Path}` dict for the currently browsed-to folder -
    a dict (not a bare `Path`) since it's mutated by the listing's own click handlers
    after this function returns, so the caller can still read the current value later
    (e.g. from a "Save here" button's own `on_click`).
    """
    if not start_dir.is_dir():
        start_dir = start_dir.parent if start_dir.parent.is_dir() else Path.home()
    current = {"path": start_dir}
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
    return current


def _open_folder_browser(folder_input: ui.input) -> None:
    """Open a dialog for browsing the server's filesystem and picking a folder."""
    with ui.dialog() as dialog, ui.card().classes("w-full max-w-lg"):
        current = _render_folder_browser(Path(folder_input.value.strip()).expanduser())
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=dialog.close).tooltip(
                "Close without changing the project folder"
            )
            ui.button(
                "Select this folder",
                on_click=lambda: (folder_input.set_value(str(current["path"])), dialog.close()),
            ).tooltip("Use the folder shown above as the project folder")

    dialog.open()


async def _choose_save_location(start_dir: Path, default_filename: str) -> Path | None:
    """Ask the user to pick a folder and filename to save a file to, browsing the
    server's filesystem starting from `start_dir`. Returns the full destination path,
    or None if cancelled.
    """
    with ui.dialog() as dialog, ui.card().classes("w-full max-w-lg"):
        current = _render_folder_browser(start_dir)
        filename_input = ui.input("Filename", value=default_filename).classes("w-full")
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=lambda: dialog.submit(None))
            ui.button(
                "Save here",
                on_click=lambda: dialog.submit(current["path"] / filename_input.value.strip()),
            ).tooltip("Save to the folder shown above, using the filename to the left")
    return await dialog


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
            ui.button("Cancel", on_click=lambda: dialog.submit(None))
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
            ui.button("Cancel", on_click=lambda: dialog.submit(False))
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
            ui.button("Close", on_click=dialog.close)
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
        preview_tab = ui.tab("preview", label="4. Preview")
        process_tab = ui.tab("process", label="5. Process")
        results_tab = ui.tab("results", label="6. Results")
    process_tab.disable()
    results_tab.disable()
    config_tab.disable()
    explorer_tab.disable()
    preview_tab.disable()

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
            explorer_container = ui.column().classes("w-full gap-4")

        with ui.tab_panel("config"):
            config_container = ui.column().classes("w-full gap-4")

        with ui.tab_panel("preview"):
            preview_container = ui.column().classes("w-full gap-4")

        with ui.tab_panel("process"):
            process_project_label = ui.label().classes("font-mono text-sm text-gray-500 break-all")
            ui.label(
                "Runs PyOPIA on the project folder above - once finished, results are "
                "available on the Results tab (including generating a montage there, on demand)."
            ).classes("text-sm text-gray-500")
            ui.label(
                "⚠ Starting a run clears this project's existing output folder first - old "
                "results aren't left behind to potentially get mixed into the new ones."
            ).classes("text-xs text-orange-600")
            config_dirty_warning = ui.label(
                "⚠ The Configuration tab has unsaved changes - Run processing uses what's saved "
                "in config.toml, not your edits. Save changes there first if you want them included."
            ).classes("text-sm text-orange-600")
            config_dirty_warning.visible = False
            with ui.row().classes("items-center gap-2"):
                num_chunks_input = ui.number("Processors to use", value=1, min=1, precision=0).classes("w-40")
                num_chunks_input.tooltip(
                    "Split the dataset into this many chunks and process them in parallel - "
                    "a real speedup on a multi-core machine. Leave at 1 for today's single-chunk behaviour."
                )
                strategy_select = ui.select(["block", "interleave"], value="block", label="Chunking strategy")
                strategy_select.classes("w-40")
                strategy_select.tooltip(
                    "block: each chunk gets a contiguous run of images. interleave: chunks take "
                    "every Nth image instead - use this if particle concentration drifts steadily "
                    "over the dataset, so each chunk still sees a representative spread."
                )
            ui.label(
                "Using more than one processor requires steps.output.append = false, set on the "
                "Configuration tab - PyOPIA writes one file per chunk in that mode, then merges them."
            ).classes("text-xs text-gray-500 -mt-3")

            def update_strategy_enabled(*_args: object) -> None:
                strategy_select.set_enabled((num_chunks_input.value or 1) > 1)

            num_chunks_input.on_value_change(update_strategy_enabled)
            update_strategy_enabled()

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

    # The Results tab's active (column, min, max) aux-data filter, if any - keyed by
    # str(project_dir), same convention as chosen_versions_this_session above. Not
    # persisted to config.toml (it's a display/export restriction, not a pipeline
    # parameter), so it resets on a full page reload, same as other page-session state.
    results_filter_state: dict[str, tuple[str, float, float] | None] = {}

    def set_config_dirty(dirty: bool) -> None:
        """Flag whether the Configuration tab has edits not yet written to config.toml -
        shown on the Process tab specifically, since that's the moment it actually
        matters: Run processing uses whatever's on disk, not live widget values (unlike
        Preview, which reads current widget values directly - see build_config_from_widgets).
        """
        config_dirty_warning.visible = dirty

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

        If the project has existing output, reuses exactly the version that produced it,
        so reprocessing never silently switches versions partway through. Otherwise asks
        explicitly (same picker as on_create), unless that choice was already made earlier
        this session, in which case it's reused silently rather than asked again.
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

            aux_columns = await nicegui_run.io_bound(docker_client.aux_data_columns, project_dir)
            active_filter = results_filter_state.get(str(project_dir))

            if aux_columns:

                async def apply_filter() -> None:
                    low, high = filter_min_input.value, filter_max_input.value
                    if low is None or high is None:
                        ui.notify("Enter both a min and max value to filter by", type="negative")
                        return
                    if low > high:
                        ui.notify("Min must not be greater than max", type="negative")
                        return
                    results_filter_state[str(project_dir)] = (filter_column_select.value, float(low), float(high))
                    await refresh_results(project_dir)

                async def clear_filter() -> None:
                    results_filter_state[str(project_dir)] = None
                    await refresh_results(project_dir)

                with ui.row().classes("items-center gap-2"):
                    filter_column_select = ui.select(
                        aux_columns, value=(active_filter[0] if active_filter else aux_columns[0]), label="Filter by"
                    ).classes("w-32")
                    filter_min_input = ui.number("Min", value=(active_filter[1] if active_filter else None)).classes(
                        "w-24"
                    )
                    filter_max_input = ui.number("Max", value=(active_filter[2] if active_filter else None)).classes(
                        "w-24"
                    )
                    ui.button("Apply filter", on_click=apply_filter).tooltip(
                        "Restrict the montage, EcoTaxa export, and summary stats below to particles "
                        "whose aux-data value falls within this range"
                    )
                if active_filter:
                    column, low, high = active_filter
                    with ui.row().classes("items-center gap-2"):
                        ui.label(f"⚠ Filtered to particles with {column} between {low} and {high}.").classes(
                            "text-sm text-orange-600"
                        )
                        ui.button("Clear filter", on_click=clear_filter).props("dense")

            montage_filename = "montage-filtered.png" if active_filter else "montage.png"
            montage_path = project_dir / montage_filename
            ecotaxa_filename = "ecotaxa_export-filtered.zip" if active_filter else "ecotaxa_export.zip"
            ecotaxa_path = project_dir / ecotaxa_filename

            async def generate_montage() -> None:
                image = await image_for_existing_project(project_dir)
                set_status("Building montage…", busy=True)
                command = docker_client.make_montage_command(
                    project_dir,
                    docker_client.stats_filename(project_dir),
                    image=image,
                    output_filename=montage_filename,
                    filter_variable=active_filter,
                )
                exit_code, lines = await run_streamed_to_log(command)
                if exit_code == 0:
                    set_status("Montage created", busy=False)
                    await refresh_results(project_dir)
                else:
                    report_failure(lines, "Montage creation failed")

            async def save_montage_as() -> None:
                destination = await _choose_save_location(project_dir, montage_filename)
                if destination is None:
                    return
                try:
                    await nicegui_run.io_bound(shutil.copy, montage_path, destination)
                except OSError as e:
                    ui.notify(f"Couldn't save montage: {e}", type="negative")
                    return
                ui.notify(f"Montage saved to {destination}", type="positive")

            if montage_path.is_file():
                ui.image(str(montage_path)).classes("w-full max-w-2xl")
                ui.label(str(montage_path)).classes("font-mono text-xs text-gray-500 break-all")
                with ui.row().classes("items-center gap-2"):
                    ui.button("Regenerate montage", on_click=generate_montage).tooltip(
                        "Builds a new montage - particles are placed randomly, so each one looks "
                        "different even from the same results"
                    )
                    ui.button("Save montage as…", on_click=save_montage_as).tooltip(
                        "Copy the montage image to a location of your choice"
                    )
            else:
                ui.button("Generate montage", on_click=generate_montage).tooltip(
                    "Builds a montage image of the particles found, from this project's existing results"
                    + (" matching the current filter" if active_filter else "")
                )

            async def export_to_ecotaxa() -> None:
                image = await image_for_existing_project(project_dir)
                set_status("Building EcoTaxa export…", busy=True)
                command = docker_client.export_to_ecotaxa_command(
                    project_dir,
                    docker_client.stats_filename(project_dir),
                    ecotaxa_filename,
                    image=image,
                    filter_variable=active_filter,
                )
                exit_code, lines = await run_streamed_to_log(command)
                if exit_code == 0:
                    set_status("EcoTaxa export created", busy=False)
                    await refresh_results(project_dir)
                else:
                    report_failure(lines, "EcoTaxa export failed")

            async def save_ecotaxa_export_as() -> None:
                destination = await _choose_save_location(project_dir, ecotaxa_filename)
                if destination is None:
                    return
                try:
                    await nicegui_run.io_bound(shutil.copy, ecotaxa_path, destination)
                except OSError as e:
                    ui.notify(f"Couldn't save EcoTaxa export: {e}", type="negative")
                    return
                ui.notify(f"EcoTaxa export saved to {destination}", type="positive")

            with ui.row().classes("items-center gap-2"):
                if ecotaxa_path.is_file():
                    ui.label(str(ecotaxa_path)).classes("font-mono text-xs text-gray-500 break-all")
                    ui.button("Regenerate EcoTaxa export", on_click=export_to_ecotaxa)
                    ui.button("Save EcoTaxa export as…", on_click=save_ecotaxa_export_as).tooltip(
                        "Copy the EcoTaxa export zip to a location of your choice"
                    )
                else:
                    ui.button("Export to EcoTaxa…", on_click=export_to_ecotaxa).tooltip(
                        "Bundle particle images and stats into a zip file ready to import into "
                        "https://ecotaxa.obs-vlfr.fr/"
                    )

            try:
                px_size = docker_client.pixel_size(project_dir)
                summary = await nicegui_run.io_bound(
                    vendored_stats.summarize, str(stats_path), px_size, active_filter
                )
            except _STATS_READ_ERRORS as e:
                ui.label(f"Couldn't compute summary statistics: {e}").classes("text-sm text-red")
            else:
                if summary is None:
                    # io_bound() returns None (rather than raising) if this call was
                    # cancelled or the app is shutting down - nothing to show, and no
                    # error either, since there's likely no page left to show it on.
                    return
                # images_with_particles is *not* "images processed": PyOPIA's own
                # write_stats() writes nothing at all for an image with zero
                # detections, so that case is indistinguishable from "wasn't
                # processed" using the stats file alone. Cross-checking against the
                # project's current raw file count (best effort - falls back to the
                # old wording if that count can't be read, or is smaller than
                # images_with_particles) makes that distinction clear instead of
                # reading like a processing shortfall.
                total_raw_files = None
                try:
                    raw_config = await nicegui_run.io_bound(docker_client.load_config, project_dir)
                    raw_files_pattern = (raw_config.get("general") or {}).get("raw_files")
                    if raw_files_pattern:
                        raw_paths = await nicegui_run.io_bound(
                            docker_client.list_raw_files, project_dir, raw_files_pattern
                        )
                        total_raw_files = len(raw_paths)
                except (OSError, tomllib.TOMLDecodeError):
                    pass
                if total_raw_files and total_raw_files >= summary.images_with_particles:
                    if total_raw_files == summary.images_with_particles:
                        images_phrase = f"across all {total_raw_files} raw images"
                    else:
                        images_phrase = (
                            f"across {summary.images_with_particles} of {total_raw_files} raw images "
                            "(the rest had none detected)"
                        )
                else:
                    images_phrase = f"across {summary.images_with_particles} images with detected particles"
                ui.label(f"{summary.particle_count} particles found {images_phrase}").classes("text-md")
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

                async def export_size_distribution_csv() -> None:
                    destination = await _choose_save_location(project_dir, "size_distribution.csv")
                    if destination is None:
                        return
                    try:
                        await nicegui_run.io_bound(
                            docker_client.write_size_distribution_csv,
                            str(destination),
                            summary.dias,
                            summary.number_distribution,
                        )
                    except OSError as e:
                        ui.notify(f"Couldn't export size distribution: {e}", type="negative")
                        return
                    ui.notify(f"Size distribution exported to {destination}", type="positive")

                ui.button(
                    "Export size distribution as CSV…", on_click=export_size_distribution_csv
                ).tooltip("Save the diameter/particle-count bins shown above to a CSV file")

    # Published by refresh_config() each time it (re)builds the Configuration tab's
    # widgets, so the Preview tab can read current - possibly unsaved - parameter
    # values without a second, duplicate parameter-editing UI. "build_config" is None
    # whenever there's no valid, loaded config to build one from.
    config_widgets_state: dict[str, Path | Callable[[], dict | None] | None] = {
        "project_dir": None,
        "build_config": None,
    }

    async def refresh_config(project_dir: Path) -> None:
        """(Re)build the Configuration tab's content from the project's current config.toml."""
        config_container.clear()
        config_widgets_state["project_dir"] = None
        config_widgets_state["build_config"] = None
        set_config_dirty(False)  # a fresh load from disk is clean by definition
        if docker_client.validate_project(project_dir) is not None:
            with config_container:
                ui.label(f"Project: {project_dir}").classes("font-mono text-sm text-gray-500 break-all")
                ui.label("No valid project selected.").classes("text-sm text-gray-500")
            return

        try:
            config = await nicegui_run.io_bound(docker_client.load_config, project_dir)
        except (OSError, tomllib.TOMLDecodeError) as e:
            with config_container:
                ui.label(f"Project: {project_dir}").classes("font-mono text-sm text-gray-500 break-all")
                ui.label(f"Couldn't read config.toml: {e}").classes("text-sm text-red")
            return
        if config is None:
            return  # io_bound cancellation guard, same reasoning as refresh_results()

        with config_container:
            ui.label(f"Project: {project_dir}").classes("font-mono text-sm text-gray-500 break-all")
            general = config.get("general") if isinstance(config.get("general"), dict) else {}

            async def generate_default_config() -> None:
                confirmed, params = await _confirm_generate_config(project_dir, config)
                if not confirmed or params is None:
                    return
                classifier_enabled = params.pop("classifier_enabled")
                image = await image_for_existing_project(project_dir)
                set_status("Generating default config…", busy=True)
                command = docker_client.generate_config_command(project_dir, image=image, **params)
                exit_code, lines = await run_streamed_to_log(command)
                if exit_code != 0:
                    report_failure(lines, "Generating default config failed")
                    return
                generated_path = project_dir / f"{params['instrument']}-config.toml"
                generated_path.replace(project_dir / "config.toml")
                if not classifier_enabled:
                    # generate-config always emits an active [steps.classifier] table,
                    # even with a blank model_path - Classify.__init__ loads a model
                    # unconditionally, so a blank path breaks pipeline construction
                    # outright. Move it out of the active steps table so the file that
                    # actually lands as config.toml never has a broken step in it.
                    written = await nicegui_run.io_bound(docker_client.load_config, project_dir)
                    written = docker_client.set_step_enabled(written, "classifier", enabled=False)
                    await nicegui_run.io_bound(docker_client.write_config, project_dir, written)
                set_status("Default config generated", busy=False)
                ui.notify("Default config generated", type="positive")
                await refresh_config(project_dir)

            with ui.row().classes("w-full justify-between items-center"):
                ui.label("General").classes("text-lg font-medium")
                generate_button = ui.button("Generate default config…", on_click=generate_default_config)
                generate_button.tooltip(
                    "Overwrite this project's config.toml with PyOPIA's own bare defaults for a chosen instrument type"
                )

            def mark_dirty(*_args: object) -> None:
                set_config_dirty(True)

            def track(element: ui.element) -> ui.element:
                element.on_value_change(mark_dirty)
                return element

            raw_files_input = track(ui.input("raw_files", value=general.get("raw_files", "")).classes("w-full"))
            pixel_size_input = track(
                ui.number("pixel_size (µm/pixel)", value=general.get("pixel_size")).classes("w-full")
            )
            ui.label(
                "⚠ Verify this matches your actual instrument/lens setup - pixel size varies per "
                "physical instrument (holo setups especially have many sub-variants) and isn't "
                "something pyopia-gui can check for you."
            ).classes("text-xs text-orange-600 -mt-3")
            log_level_select = track(
                ui.select(_GENERAL_LOG_LEVELS, value=general.get("log_level", "INFO"), label="log_level")
            )
            log_level_select.classes("w-full")
            log_file_input = track(ui.input("log_file", value=general.get("log_file") or "").classes("w-full"))
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
            # name -> the "Enable this step" switch shown above each step's expansion -
            # whichever table (steps vs steps_disabled) it ends up in on save follows this,
            # not which table it was originally loaded from.
            step_enabled: dict[str, ui.switch] = {}
            # name -> that step's introspected field schema (has_default/default per field) -
            # build_config_from_widgets() needs this to validate a step being enabled
            # actually has every required field filled in, not just to build the input widgets.
            step_schema_fields: dict[str, list[dict]] = {}

            steps = config.get("steps") if isinstance(config.get("steps"), dict) else {}
            disabled_steps = config.get("steps_disabled") if isinstance(config.get("steps_disabled"), dict) else {}
            # For pipeline_class lookup in build_config_from_widgets() regardless of which
            # table a step currently lives in - a step is never in both at once.
            all_steps_by_name = {**steps, **disabled_steps}

            async def load_steps() -> None:
                schema = await nicegui_run.io_bound(docker_client.introspect_config_steps, project_dir)
                steps_spinner.visible = False
                active_schema = schema.get("steps", {}) if schema else {}
                disabled_schema = schema.get("steps_disabled", {}) if schema else {}

                def render_step(step_name: str, step: dict, info: dict, *, enabled: bool) -> None:
                    can_toggle = step_name in _ORDER_INSENSITIVE_STEP_NAMES
                    if can_toggle:
                        switch = track(ui.switch("Enable this step", value=enabled))
                        step_enabled[step_name] = switch
                    step_schema_fields[step_name] = info.get("fields", [])
                    caption = step["pipeline_class"] if enabled else f"{step['pipeline_class']} (disabled)"
                    expansion = ui.expansion(step_name, caption=caption).classes("w-full border rounded")
                    if not enabled:
                        expansion.classes("opacity-50")
                    with expansion:
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
                                        element = ui.input(name, value=_text_from_toml_value(value)).classes("w-full")
                                        value = "raw"
                                    if field["description"]:
                                        ui.label(field["description"]).classes("text-xs text-gray-500")
                                track(element)
                                fields[name] = (element, type(value) if value != "raw" else "raw")
                        else:
                            # Introspection failed for this step - fall back to bare
                            # key/value text editing rather than blocking the whole tab.
                            if "error" in info:
                                ui.label(f"Couldn't introspect this step: {info['error']}").classes("text-xs text-red")
                            for name, current in step.items():
                                if name == "pipeline_class":
                                    continue
                                shown = current if isinstance(current, str) else _text_from_toml_value(current)
                                fields[name] = (track(ui.input(name, value=shown).classes("w-full")), "raw")

                with steps_column:
                    for step_name, step in steps.items():
                        if not isinstance(step, dict) or "pipeline_class" not in step:
                            continue
                        render_step(step_name, step, active_schema.get(step_name, {}), enabled=True)
                    for step_name, step in disabled_steps.items():
                        if not isinstance(step, dict) or "pipeline_class" not in step:
                            continue
                        if step_name not in _ORDER_INSENSITIVE_STEP_NAMES:
                            # Shouldn't happen via this UI (only order-insensitive steps
                            # can be disabled through it) - if config.toml was hand-edited
                            # to put something else here, still show it so it isn't
                            # invisible, just without a switch (matches the "no toggle
                            # for order-sensitive steps" rule, whichever table it's in).
                            render_step(step_name, step, disabled_schema.get(step_name, {}), enabled=True)
                            continue
                        render_step(step_name, step, disabled_schema.get(step_name, {}), enabled=False)

            background_tasks.create(load_steps(), name="config-introspect")

            def build_config_from_widgets() -> dict | None:
                """The config dict implied by the Configuration tab's current widget
                values - not necessarily what's saved to config.toml. Returns None
                (after ui.notify-ing the parse error) if a "raw" TOML-literal field
                fails to parse. Published via config_widgets_state so the Preview tab
                can read live, possibly-unsaved parameter values without a second,
                duplicate parameter-editing UI.
                """
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

                def field_has_real_default(step_name: str, name: str) -> bool:
                    field_info = next((f for f in step_schema_fields.get(step_name, []) if f["name"] == name), None)
                    return field_info is not None and field_info.get("has_default", False)

                def first_missing_required_field(step_name: str, step_config: dict) -> str | None:
                    """The name of the first field with no real default (PyOPIA's own class
                    construction requires one) left blank/unset in `step_config`, or None if
                    every such field is filled. TOML also has no null type, so a required
                    field can never be written as the Python `None` a blank number input
                    produces - it must be caught here instead, before config.toml either
                    fails to write at all or ends up with a value PyOPIA can't run against.
                    """
                    for field in step_schema_fields.get(step_name, []):
                        if field["has_default"]:
                            continue
                        value = step_config.get(field["name"])
                        if value is None or value == "":
                            return field["name"]
                    return None

                for step_name, fields in step_inputs.items():
                    step_config = {"pipeline_class": all_steps_by_name[step_name]["pipeline_class"]}
                    for name, (element, kind) in fields.items():
                        if kind is bool:
                            step_config[name] = element.value
                            continue
                        if kind == "raw":
                            try:
                                step_config[name] = _toml_value_from_text(element.value)
                            except tomllib.TOMLDecodeError as e:
                                ui.notify(f"{step_name}.{name}: {e}", type="negative")
                                return None
                            continue
                        if kind is int:
                            value = int(element.value) if element.value is not None else None
                        elif kind is float:
                            value = float(element.value) if element.value is not None else None
                        else:
                            value = element.value
                        # A blank/unset value for a field with a real default - whatever
                        # that default actually is (None, 'infer', a number, ...) - means
                        # "leave this unset", not "write this literal blank/null". PyOPIA
                        # steps guard on `is not None` (e.g. StatsToDisc's
                        # project_metadata_file) or switch on the exact string 'infer'
                        # (SilCamLoad's image_format), so writing "" instead breaks either
                        # way; omitting the key lets PyOPIA's own default actually apply.
                        if (value is None or value == "") and field_has_real_default(step_name, name):
                            continue
                        step_config[name] = value
                    switch = step_enabled.get(step_name)
                    if switch is None:
                        # Order-sensitive step - no switch, always active.
                        missing = first_missing_required_field(step_name, step_config)
                        if missing:
                            ui.notify(f"{step_name}.{missing} needs a value before it can be saved", type="negative")
                            return None
                        updated["steps"][step_name] = step_config
                        continue
                    enabled = switch.value
                    if enabled:
                        missing = first_missing_required_field(step_name, step_config)
                        if missing:
                            ui.notify(
                                f"{step_name}.{missing} needs a value before this step can be enabled",
                                type="negative",
                            )
                            return None
                        updated["steps"][step_name] = step_config
                    else:
                        updated.setdefault("steps_disabled", {})[step_name] = step_config
                return updated

            async def save_changes() -> None:
                updated = build_config_from_widgets()
                if updated is None:
                    return
                try:
                    await nicegui_run.io_bound(docker_client.write_config, project_dir, updated)
                except OSError as e:
                    ui.notify(f"Couldn't save config.toml: {e}", type="negative")
                    return
                ui.notify("Configuration saved", type="positive")
                set_config_dirty(False)
                await refresh_project_state(is_project_change=False)

            config_widgets_state["project_dir"] = project_dir
            config_widgets_state["build_config"] = build_config_from_widgets

            ui.button("Save changes", on_click=save_changes).classes("mt-2")

    _EXPLORER_PAGE_SIZE = 12

    async def refresh_explorer(project_dir: Path) -> None:
        """(Re)build the Raw data explorer tab: a paginated grid of raw-image thumbnails
        for whatever `general.raw_files` currently matches.
        """
        explorer_container.clear()
        if docker_client.validate_project(project_dir) is not None:
            with explorer_container:
                ui.label(f"Project: {project_dir}").classes("font-mono text-sm text-gray-500 break-all")
                ui.label("No valid project selected.").classes("text-sm text-gray-500")
            return

        try:
            config = await nicegui_run.io_bound(docker_client.load_config, project_dir)
        except (OSError, tomllib.TOMLDecodeError) as e:
            with explorer_container:
                ui.label(f"Project: {project_dir}").classes("font-mono text-sm text-gray-500 break-all")
                ui.label(f"Couldn't read config.toml: {e}").classes("text-sm text-red")
            return
        if config is None:
            return  # io_bound cancellation guard, same reasoning as refresh_results()

        general = config.get("general") if isinstance(config.get("general"), dict) else {}
        raw_files_pattern = general.get("raw_files")

        with explorer_container:
            ui.label(f"Project: {project_dir}").classes("font-mono text-sm text-gray-500 break-all")
            if not raw_files_pattern:
                ui.label("This project's config.toml doesn't set general.raw_files yet.").classes(
                    "text-sm text-gray-500"
                )
                return

            raw_paths = docker_client.list_raw_files(project_dir, raw_files_pattern)
            if not raw_paths:
                ui.label(f"No raw files found matching '{raw_files_pattern}'.").classes("text-sm text-gray-500")
                return

            async def clear_subset() -> None:
                current_config = await nicegui_run.io_bound(docker_client.load_config, project_dir)
                restored = docker_client.clear_raw_files_subset(project_dir, current_config)
                if restored is None:
                    return
                await nicegui_run.io_bound(docker_client.write_config, project_dir, restored)
                ui.notify("Restored the full raw_files pattern", type="positive")
                await refresh_config(project_dir)
                await refresh_explorer(project_dir)

            if raw_files_pattern == docker_client.RAW_FILES_SUBSET_FILENAME:
                original_pattern = docker_client.raw_files_original_pattern(project_dir)
                with ui.row().classes("items-center gap-2"):
                    ui.label(
                        f"⚠ Filtered to {len(raw_paths)} raw image(s) via a selected subset"
                        + (f" (originally '{original_pattern}')" if original_pattern else "")
                        + "."
                    ).classes("text-sm text-orange-600")
                    if original_pattern:
                        ui.button("Clear subset", on_click=clear_subset).props("dense")

            page_count = math.ceil(len(raw_paths) / _EXPLORER_PAGE_SIZE)
            state = {"page": 0}
            # Selected raw files for a subset, kept across page navigation within this one
            # Explorer load (reset, like `state` above, each time refresh_explorer runs) -
            # a checkbox's checked state on any given page is just `raw_path in selected`.
            selected: set[Path] = set()

            with ui.row().classes("items-center gap-2"):
                previous_button = ui.button("Previous")
                next_button = ui.button("Next")
                refresh_button = ui.button("Refresh")
                refresh_button.tooltip(
                    "Reconvert every image on this page from scratch, ignoring any "
                    "already-cached thumbnails - use this after changing config.toml's "
                    "load step, since old previews from before the change won't update "
                    "on their own"
                )
                page_label = ui.label().classes("text-sm text-gray-500")

            with ui.row().classes("items-center gap-2"):
                select_all_button = ui.button("Select all on this page")
                select_all_button.tooltip("e.g. for a quick test run against just this page, rather than everything")
                clear_selection_button = ui.button("Clear selection")
                use_subset_button = ui.button("Use selected as raw_files")
                use_subset_button.tooltip(
                    "Narrow this project to just the selected images - e.g. to process a "
                    "chosen slice of a larger dataset. A button to revert appears above once applied."
                )
                selection_label = ui.label("0 selected").classes("text-sm text-gray-500")

            def update_selection_controls() -> None:
                selection_label.set_text(f"{len(selected)} selected")
                use_subset_button.set_enabled(bool(selected))

            def toggle_selected(raw_path: Path, checked: bool) -> None:
                if checked:
                    selected.add(raw_path)
                else:
                    selected.discard(raw_path)
                update_selection_controls()

            async def select_all_on_page() -> None:
                page = state["page"]
                page_paths = raw_paths[page * _EXPLORER_PAGE_SIZE : (page + 1) * _EXPLORER_PAGE_SIZE]
                selected.update(page_paths)
                update_selection_controls()
                await show_page()

            async def clear_selection() -> None:
                selected.clear()
                update_selection_controls()
                await show_page()

            async def use_selected_as_subset() -> None:
                if not selected:
                    return
                # Chronological (raw_paths) order, not selection-click order - chunking and
                # background-correction both depend on processing files in sequence.
                ordered = [p for p in raw_paths if p in selected]
                current_config = await nicegui_run.io_bound(docker_client.load_config, project_dir)
                new_config = docker_client.apply_raw_files_subset(project_dir, current_config, ordered)
                await nicegui_run.io_bound(docker_client.write_config, project_dir, new_config)
                ui.notify(f"raw_files narrowed to the {len(ordered)} selected image(s)", type="positive")
                await refresh_config(project_dir)
                await refresh_explorer(project_dir)

            progress_label = ui.label().classes("text-sm text-gray-500")
            progress_label.visible = False
            progress_bar = ui.linear_progress(value=0, show_value=False)
            progress_bar.visible = False
            grid = ui.grid(columns=4).classes("w-full gap-2")

            async def show_page(force: bool = False) -> None:
                page = state["page"]
                page_label.set_text(f"Page {page + 1} of {page_count} ({len(raw_paths)} raw files)")
                previous_button.set_enabled(page > 0)
                next_button.set_enabled(page < page_count - 1)

                page_paths = raw_paths[page * _EXPLORER_PAGE_SIZE : (page + 1) * _EXPLORER_PAGE_SIZE]
                # Ordered the same way page_paths is (not a set) - this is the order images are
                # actually sent for conversion, and each one's grid cell now fills in as soon as
                # *that* image is done, so converting out of order would visibly fill the grid
                # out of order too, even though every cell's own position stays correctly sorted.
                to_convert = (
                    list(page_paths)
                    if force
                    else [p for p in page_paths if not docker_client.thumbnail_path(project_dir, p).is_file()]
                )
                to_convert_set = set(to_convert)  # membership checks only, not iteration

                def render_cell(raw_path: Path, *, pending: bool, error: str | None) -> None:
                    """Add a raw file's current content into the calling `with cell:` block -
                    its thumbnail/error, or a spinner while it's still pending (re)conversion,
                    rather than a stale thumbnail in the process of being replaced, which could
                    otherwise look like an up to date result when it's actually about to be
                    overwritten. Always includes a selection checkbox, regardless of
                    pending/error/loaded state, so "Select all on this page" works even
                    while thumbnails are still converting.
                    """
                    checkbox = ui.checkbox(
                        value=raw_path in selected, on_change=lambda e, p=raw_path: toggle_selected(p, e.value)
                    ).props("dense")
                    checkbox.tooltip("Select this image for a raw_files subset")
                    if pending:
                        ui.spinner(size="md")
                    elif error:
                        hint = docker_client.interpret_thumbnail_error(error) or error
                        ui.icon("broken_image", size="lg").classes("text-red").tooltip(hint)
                    else:
                        thumb_path = docker_client.thumbnail_path(project_dir, raw_path)
                        if thumb_path.is_file():
                            ui.image(thumb_path).classes("w-32 h-32 object-cover rounded")
                            preview_link = ui.button("Preview →", on_click=lambda p=raw_path: use_in_preview(p)).props(
                                "dense size=sm"
                            )
                            preview_link.tooltip("Use this image on the Preview tab")
                    ui.label(raw_path.name).classes("text-xs text-gray-500 break-all text-center")

                grid.clear()
                cells: dict[Path, ui.column] = {}
                with grid:
                    for raw_path in page_paths:
                        with ui.column().classes("items-center gap-1") as cell:
                            render_cell(raw_path, pending=raw_path in to_convert_set, error=None)
                        cells[raw_path] = cell

                if to_convert:

                    def update_progress(done: int, total: int) -> None:
                        progress_bar.set_value(done / total)
                        progress_label.set_text(f"Converting raw image {done} of {total}…")

                    def update_cell(raw_path: Path, error: str | None) -> None:
                        cells[raw_path].clear()
                        with cells[raw_path]:
                            render_cell(raw_path, pending=False, error=error)

                    progress_bar.set_value(0)
                    progress_label.set_text(f"Converting raw image 0 of {len(to_convert)}…")
                    progress_bar.visible = True
                    progress_label.visible = True
                    await docker_client.generate_thumbnails(
                        project_dir, to_convert, on_progress=update_progress, on_image_done=update_cell
                    )
                    progress_bar.visible = False
                    progress_label.visible = False

            async def go_previous() -> None:
                state["page"] -= 1
                await show_page()

            async def go_next() -> None:
                state["page"] += 1
                await show_page()

            previous_button.on_click(go_previous)
            next_button.on_click(go_next)
            refresh_button.on_click(lambda: show_page(force=True))
            select_all_button.on_click(select_all_on_page)
            clear_selection_button.on_click(clear_selection)
            use_subset_button.on_click(use_selected_as_subset)
            update_selection_controls()
            await show_page()

    # Converting a page of raw-image thumbnails is comparatively slow (a real Docker
    # call per page) - loaded lazily, only once the Explorer tab is actually opened,
    # rather than eagerly on every project-folder change like Configuration's (much
    # cheaper, one call for the whole config) content is. Tracks which project_dir the
    # currently-shown content was loaded for, so switching tabs back and forth doesn't
    # keep reloading unnecessarily.
    explorer_state: dict[str, Path | None] = {"project_dir": None, "loaded_for": None}

    async def load_explorer_if_needed() -> None:
        project_dir = explorer_state["project_dir"]
        if tabs.value == "explorer" and project_dir is not None and explorer_state["loaded_for"] != project_dir:
            explorer_state["loaded_for"] = project_dir
            await refresh_explorer(project_dir)

    tabs.on_value_change(lambda: background_tasks.create(load_explorer_if_needed(), name="explorer-lazy-load"))

    # "run_dir" tracks the on-disk folder (project_dir / PREVIEW_DIR_NAME / <run id>)
    # holding the most recent successful preview's overlay/slice images, so it can be
    # deleted once a newer run's images have replaced it on screen - never before, so
    # a still-displayed image is never pulled out from under the browser mid-view.
    preview_state: dict[str, Path | None] = {"project_dir": None, "selected_sample": None, "run_dir": None}

    async def use_in_preview(raw_path: Path) -> None:
        preview_state["selected_sample"] = raw_path
        tabs.value = "preview"
        if preview_state["project_dir"] is not None:
            await refresh_preview(preview_state["project_dir"])

    async def refresh_preview(project_dir: Path) -> None:
        """(Re)build the Preview tab: a prompt to pick a sample image (via the Raw
        data explorer tab's "Preview →" button on any thumbnail), or the selected
        sample plus a "Run preview" button and the last result, if any.
        """
        preview_container.clear()
        if docker_client.validate_project(project_dir) is not None:
            with preview_container:
                ui.label(f"Project: {project_dir}").classes("font-mono text-sm text-gray-500 break-all")
                ui.label("No valid project selected.").classes("text-sm text-gray-500")
            return

        def go_to_explorer() -> None:
            tabs.value = "explorer"

        with preview_container:
            ui.label(f"Project: {project_dir}").classes("font-mono text-sm text-gray-500 break-all")
            sample = preview_state["selected_sample"]
            if sample is None:
                ui.label("Pick a sample image from the Raw data explorer tab first.").classes("text-sm text-gray-500")
                ui.button("Go to Raw data explorer", on_click=go_to_explorer)
                return

            ui.label(sample.name).classes("text-sm font-medium")
            thumb_path = docker_client.thumbnail_path(project_dir, sample)
            if thumb_path.is_file():
                ui.image(thumb_path).classes("w-32 h-32 object-cover rounded")

            result_container = ui.column().classes("w-full gap-2")

            def render_result(result: dict) -> None:
                result_container.clear()
                overlay_path = result.get("overlay_path")
                slice_paths = result.get("slice_paths")
                z_values = result.get("z_values")
                if overlay_path is not None:
                    preview_state["run_dir"] = overlay_path.parent
                elif slice_paths:
                    preview_state["run_dir"] = slice_paths[0].parent
                with result_container:
                    if result["background_step_skipped"]:
                        ui.label(
                            "⚠ Background correction was skipped for this preview - the project "
                            "doesn't have enough other raw files to build a real background "
                            "estimate alongside this one (it needs several images, same as a real "
                            "run would). Treat this preview's segmentation/stats as approximate."
                        ).classes("text-xs text-orange-600")
                    if slice_paths:
                        start_index = len(slice_paths) // 2
                        slice_image = ui.image(slice_paths[start_index]).classes(
                            "w-full max-w-2xl border border-gray-300"
                        )
                        depth_label = ui.label().classes("text-sm text-gray-500")

                        def show_slice(index: int) -> None:
                            slice_image.set_source(slice_paths[index])
                            if z_values:
                                depth_label.set_text(f"Depth: {z_values[index]:.2f} mm")
                            else:
                                depth_label.set_text(f"Slice {index + 1} of {len(slice_paths)}")

                        ui.slider(
                            min=0,
                            max=len(slice_paths) - 1,
                            step=1,
                            value=start_index,
                            on_change=lambda e: show_slice(int(e.value)),
                        )
                        show_slice(start_index)
                        ui.label(
                            "Raw reconstruction at each depth - dragging redraws instantly, "
                            "no particle outlines shown here."
                        ).classes("text-xs text-gray-500")
                    if overlay_path is not None and overlay_path.is_file():
                        ui.image(overlay_path).classes("w-full max-w-2xl border border-gray-300")
                        ui.label("Detected particles").classes("text-xs text-gray-500")
                    ui.label(f"{result['particle_count']} particle(s) found").classes("text-md")
                    if result["d50_microns"] is not None:
                        ui.label(f"d50 (median particle size): {result['d50_microns']:.1f} µm").classes("text-md")
                    else:
                        ui.label("d50: n/a - no particles found").classes("text-md")
                    if result["saturation"] is not None:
                        ui.label(f"Saturation: {result['saturation']:.1f}%").classes("text-md")

            async def run_preview() -> None:
                build_config = config_widgets_state["build_config"]
                if build_config is None or config_widgets_state["project_dir"] != project_dir:
                    ui.notify("Configuration is still loading - try again in a moment", type="warning")
                    return
                config = build_config()
                if config is None:
                    return  # a bad "raw" field already notified the user, same as save_changes()
                run_button.disable()
                image = await resolve_run_image(project_dir)
                if image is None:
                    run_button.enable()
                    return

                # Real background correction needs several real raw files to seed its
                # moving-average stack - gather as many as the configured step actually
                # needs (preferring files preceding this sample, falling back to
                # following ones too if needed - see select_background_context). Falls
                # back to no context (preview_pipeline substitutes the step away
                # instead) if there aren't enough, or general.raw_files isn't set.
                context_raw_paths: list[Path] = []
                required_context = docker_client.required_background_context(config)
                if required_context > 0:
                    general = config.get("general") if isinstance(config.get("general"), dict) else {}
                    raw_files_pattern = general.get("raw_files")
                    if raw_files_pattern:
                        raw_paths = docker_client.list_raw_files(project_dir, raw_files_pattern)
                        context_raw_paths = docker_client.select_background_context(raw_paths, sample, required_context)

                set_status("Running preview…", busy=True)

                def on_preview_progress(message: str) -> None:
                    set_status(f"Running preview… {message}", busy=True)

                result = await docker_client.preview_pipeline(
                    project_dir,
                    config,
                    sample,
                    image,
                    on_progress=on_preview_progress,
                    context_raw_paths=context_raw_paths,
                )
                run_button.enable()
                if not result["ok"]:
                    message = docker_client.interpret_preview_error(result["error"]) or result["error"]
                    log.push(f"→ preview error: {message}", classes="text-yellow-300 font-bold")
                    set_status(message, busy=False)
                    ui.notify(message, type="negative")
                    return
                set_status("Preview ready", busy=False)
                old_run_dir = preview_state["run_dir"]
                render_result(result)
                if old_run_dir is not None and old_run_dir.is_dir():
                    shutil.rmtree(old_run_dir, ignore_errors=True)

            run_button = ui.button("Run preview", on_click=run_preview)
            run_button.tooltip(
                "Runs the current processing parameters - including any unsaved "
                "Configuration tab edits - against this one image only"
            )

    async def refresh_project_state(*, is_project_change: bool = True) -> None:
        """Update tab availability for the current project folder, and jump to Results
        if it already has output - opening an already-processed project should show
        whatever's available immediately, not require a fresh run to see it. This jump
        happens before Configuration's own (slower) content load, so it's never delayed
        behind it - Explorer's own content loads lazily instead, see above.

        `is_project_change` distinguishes a real project-folder change from a
        save-triggered refresh of the *same* project (`save_changes()` passes
        `is_project_change=False`) - jumping to Results, or silently clearing
        whatever sample image was picked on the Preview tab, right after clicking
        Save changes would be jarring and isn't what a save is actually for.
        """
        project_dir = Path(folder_input.value.strip()).expanduser().resolve()
        process_project_label.set_text(f"Project: {project_dir}")
        is_valid = docker_client.validate_project(project_dir) is None
        process_tab.set_enabled(is_valid)
        config_tab.set_enabled(is_valid)
        explorer_tab.set_enabled(is_valid)
        preview_tab.set_enabled(is_valid)
        explorer_state["project_dir"] = project_dir if is_valid else None
        explorer_state["loaded_for"] = None  # force a fresh load next time Explorer is opened
        if is_project_change:
            # A sample picked in a previous project (or a previous visit to this
            # one) is no longer meaningful once the project folder changes - reset
            # it rather than let a stale selection silently persist across an
            # unrelated project.
            preview_state["project_dir"] = project_dir if is_valid else None
            preview_state["selected_sample"] = None
        elif not is_valid:
            preview_state["project_dir"] = None
            preview_state["selected_sample"] = None

        try:
            has_results = is_valid and (project_dir / docker_client.stats_filename(project_dir)).is_file()
        except _STATS_READ_ERRORS:
            has_results = False

        if has_results:
            results_tab.enable()
            await refresh_results(project_dir)
            if is_project_change:
                tabs.value = "results"
        else:
            results_tab.disable()

        if is_valid:
            await refresh_config(project_dir)
        await refresh_preview(project_dir)
        await load_explorer_if_needed()  # covers already being on the Explorer tab

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

        num_chunks = int(num_chunks_input.value or 1)
        strategy = strategy_select.value
        if num_chunks > 1 and await nicegui_run.io_bound(docker_client.output_uses_append, project_dir):
            # PyOPIA's own check_chunks() rejects num_chunks > 1 against append=true outright -
            # caught here, before the output folder below is cleared, so a misconfigured run
            # fails without destroying existing results for nothing.
            ui.notify(
                "Using more than one processor requires steps.output.append = false "
                "(set on the Configuration tab) - processing not started.",
                type="negative",
                multi_line=True,
            )
            set_status("Ready", busy=False)
            run_button.enable()
            return

        # Clear this project's real output folder before running, not just the UI's own
        # stale state below - PyOPIA's own per-image STATS output (used when the
        # config's output step has append=false) has no way to tell a fresh run's files
        # apart from an old run's when merging: merge-mfdata just globs every
        # *Image-D*-STATS.nc file sitting in the folder, with no freshness check at all.
        # A narrowed raw_files pattern, a removed/renamed raw image, or a run that failed
        # partway through could otherwise leave stale per-image files that silently get
        # merged into what looks like a fresh, current result. PyOPIA's own
        # conflict-rename safety net only covers the single combined -STATS.nc file,
        # not the per-image ones.
        output_dir = await nicegui_run.io_bound(docker_client.output_directory, project_dir)
        await nicegui_run.io_bound(shutil.rmtree, output_dir, ignore_errors=True)

        # Clear everything left over from a previous run, now that this one's actually
        # starting - otherwise a new run can look like it's continuing an old one, or a
        # failed rerun can leave a stale (and no longer accurate) montage/stats on the
        # Results tab.
        log.clear()
        results_container.clear()
        with results_container:
            ui.label("Processing is running…").classes("text-sm text-gray-500")
        set_status("Running processing (this can take a few minutes)…", busy=True)
        exit_code, lines = await run_streamed_to_log(
            docker_client.process_command(project_dir, image=image, num_chunks=num_chunks, strategy=strategy)
        )
        if exit_code != 0:
            report_failure(lines, "Processing failed")
            run_button.enable()
            return
        ui.notify("Processing complete", type="positive")

        # merge-mfdata combines per-image files into one - only meaningful when the
        # output step's append=false (per-image files). With the default append=true,
        # `process` already wrote the single combined file directly; there's nothing
        # to merge, and PyOPIA's own merge-mfdata raises ZeroDivisionError against an
        # empty file list rather than a no-op, so it must be skipped in that case.
        uses_append = await nicegui_run.io_bound(docker_client.output_uses_append, project_dir)
        if not uses_append:
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
