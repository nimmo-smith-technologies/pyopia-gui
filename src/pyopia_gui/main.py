# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Nimmo Smith Technologies Limited

import os
import webbrowser
from pathlib import Path

from nicegui import background_tasks, ui
from nicegui import run as nicegui_run

from pyopia_gui import __version__, docker_client, version_check

DEFAULT_PROJECT_DIR = Path.home() / "pyopia-gui-projects" / "demo"
REPO_URL = "https://github.com/nimmo-smith-technologies/pyopia-gui"


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
    versions = (
        []
        if "PYOPIA_GUI_DOCKER_IMAGE" in os.environ
        else await nicegui_run.io_bound(docker_client.list_available_versions)
    )

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


async def _show_update_if_newer(update_link: ui.link) -> None:
    latest = await nicegui_run.io_bound(version_check.check_for_newer_release, __version__)
    if latest:
        update_link.text = f"{latest} available ↗"
        update_link.visible = True


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

    with ui.row().classes("w-full items-center gap-2"):
        folder_input = ui.input("Project folder", value=str(DEFAULT_PROJECT_DIR)).classes("grow")
        folder_input.tooltip("The PyOPIA project folder to create or process - must contain a config.toml")
        browse_button = ui.button("Browse…", on_click=lambda: _open_folder_browser(folder_input))
        browse_button.tooltip("Browse this computer's folders to pick an existing project")
    ui.label(
        "Determines where the example project below gets created, and what folder processing "
        "runs against - point it at your own data any time."
    ).classes("text-sm text-gray-500")

    with ui.row().classes("items-center gap-2"):
        spinner = ui.spinner(size="md")
        spinner.visible = False
        status_label = ui.label("Ready").classes("text-md font-medium")
        status_label.tooltip("The current step in the create/process workflow below")

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
    pyopia_version_label = ui.label().classes("text-sm text-gray-500")
    pyopia_version_label.tooltip("The PyOPIA version that actually processed the data below")
    pyopia_version_label.visible = False
    montage = ui.image().classes("w-full max-w-2xl")
    montage.tooltip("A montage of example particles found while processing")
    montage.visible = False

    create_button = ui.button("1. Create example project")
    create_button.tooltip(
        "Downloads a small example dataset and sets up a ready-to-run PyOPIA project in the folder above"
    )
    run_button = ui.button("2. Run processing")
    run_button.tooltip("Runs PyOPIA processing on the folder above, then builds a montage of the particles found")

    def set_status(text: str, *, busy: bool) -> None:
        status_label.set_text(text)
        spinner.visible = busy

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

    async def resolve_run_image(project_dir: Path) -> str:
        """Which PyOPIA image to process `project_dir` with.

        Never picks a version automatically if one's already in play: if this project has
        existing output, reuses exactly the version that produced it, so reprocessing or
        resuming a dataset never silently switches versions partway through. Only a brand
        new project (handled in on_create, via the version picker) ever chooses freely.
        """
        if "PYOPIA_GUI_DOCKER_IMAGE" in os.environ:
            return docker_client.PYOPIA_IMAGE
        pinned = await nicegui_run.io_bound(docker_client.read_pinned_version, project_dir)
        if not pinned:
            return docker_client.PYOPIA_IMAGE
        note = f"Using PyOPIA v{pinned} - matches this project's existing results"
        newest_available = await nicegui_run.io_bound(docker_client.list_available_versions)
        if newest_available and newest_available[0] != pinned:
            note += f" (a newer version, v{newest_available[0]}, is available for new projects)"
        log.push(note)
        return docker_client.image_for_version(pinned)

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
        set_status("Creating example project…", busy=True)
        parent_dir = project_dir.parent
        parent_dir.mkdir(parents=True, exist_ok=True)
        image = docker_client.image_for_version(chosen_version)
        command = docker_client.init_project_command(parent_dir, project_dir.name, image=image)
        exit_code, lines = await run_streamed_to_log(command)
        if exit_code == 0:
            set_status("Example project created", busy=False)
            ui.notify("Example project created", type="positive")
        else:
            report_failure(lines, "Failed to create example project")
        create_button.enable()

    async def on_run() -> None:
        project_dir = Path(folder_input.value.strip()).expanduser()
        error = docker_client.validate_project(project_dir)
        if error:
            ui.notify(error, type="negative")
            return

        run_button.disable()
        pyopia_version_label.visible = False
        set_status("Checking PyOPIA version…", busy=True)
        image = await resolve_run_image(project_dir)

        set_status("Running processing (this can take a few minutes)…", busy=True)
        exit_code, lines = await run_streamed_to_log(docker_client.process_command(project_dir, image=image))
        if exit_code != 0:
            report_failure(lines, "Processing failed")
            run_button.enable()
            return
        ui.notify("Processing complete", type="positive")

        pyopia_version = docker_client.extract_pyopia_version(lines)
        if pyopia_version:
            pyopia_version_label.set_text(f"Processed with PyOPIA v{pyopia_version}")
            pyopia_version_label.visible = True

        set_status("Merging results…", busy=True)
        merge_exit_code, merge_lines = await run_streamed_to_log(
            docker_client.merge_mfdata_command(project_dir, image=image)
        )
        if merge_exit_code != 0:
            report_failure(merge_lines, "Merging processed stats failed")
            run_button.enable()
            return

        set_status("Building montage…", busy=True)
        montage_command = docker_client.make_montage_command(
            project_dir, docker_client.stats_filename(project_dir), image=image
        )
        montage_exit_code, montage_lines = await run_streamed_to_log(montage_command)
        if montage_exit_code == 0:
            montage.set_source(str(project_dir / "montage.png"))
            montage.visible = True
            set_status("Done - see your results below", busy=False)
        else:
            report_failure(montage_lines, "Montage creation failed")
        run_button.enable()

    create_button.on_click(on_create)
    run_button.on_click(on_run)


def run() -> None:
    ui.run(title="pyopia-gui", reload=False)


if __name__ in {"__main__", "__mp_main__"}:
    run()
