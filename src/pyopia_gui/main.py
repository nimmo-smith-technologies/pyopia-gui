# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Nimmo Smith Technologies Limited

from pathlib import Path

from nicegui import ui

from pyopia_gui import docker_client

DEFAULT_PROJECT_DIR = Path.home() / "pyopia-gui-projects" / "demo"
REPO_URL = "https://github.com/nimmo-smith-technologies/pyopia-gui"


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


@ui.page("/")
def index() -> None:
    with ui.header().classes("items-center justify-between"):
        ui.label("pyopia-gui").classes("text-2xl")
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

    log = ui.log(max_lines=500).classes("w-full h-64 bg-black text-white")
    log.tooltip("Raw output from PyOPIA - useful for troubleshooting if something goes wrong")
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

    async def run_streamed_to_log(command: list[str]) -> int:
        log.push("$ " + " ".join(command))
        return await docker_client.run_streamed(command, log.push)

    async def on_create() -> None:
        project_dir = Path(folder_input.value.strip()).expanduser()
        if project_dir.exists():
            ui.notify(
                f"{project_dir} already exists - pick a new folder, or click "
                "'Run processing' if it's already a PyOPIA project.",
                type="negative",
            )
            return

        create_button.disable()
        set_status("Creating example project…", busy=True)
        parent_dir = project_dir.parent
        parent_dir.mkdir(parents=True, exist_ok=True)
        command = docker_client.init_project_command(parent_dir, project_dir.name)
        exit_code = await run_streamed_to_log(command)
        if exit_code == 0:
            set_status("Example project created", busy=False)
            ui.notify("Example project created", type="positive")
        else:
            set_status("Failed to create example project - see log below", busy=False)
            ui.notify("Failed to create example project - see log", type="negative")
        create_button.enable()

    async def on_run() -> None:
        project_dir = Path(folder_input.value.strip()).expanduser()
        error = docker_client.validate_project(project_dir)
        if error:
            ui.notify(error, type="negative")
            return

        run_button.disable()
        set_status("Running processing (this can take a few minutes)…", busy=True)
        exit_code = await run_streamed_to_log(docker_client.process_command(project_dir))
        if exit_code != 0:
            set_status("Processing failed - see log below", busy=False)
            ui.notify("Processing failed - see log", type="negative")
            run_button.enable()
            return
        ui.notify("Processing complete", type="positive")

        set_status("Merging results…", busy=True)
        merge_exit_code = await run_streamed_to_log(docker_client.merge_mfdata_command(project_dir))
        if merge_exit_code != 0:
            set_status("Merging processed stats failed - see log below", busy=False)
            ui.notify("Merging processed stats failed - see log", type="negative")
            run_button.enable()
            return

        set_status("Building montage…", busy=True)
        montage_command = docker_client.make_montage_command(project_dir, docker_client.stats_filename(project_dir))
        montage_exit_code = await run_streamed_to_log(montage_command)
        if montage_exit_code == 0:
            montage.set_source(str(project_dir / "montage.png"))
            montage.visible = True
            set_status("Done - see your results below", busy=False)
        else:
            set_status("Montage creation failed - see log below", busy=False)
            ui.notify("Montage creation failed - see log", type="negative")
        run_button.enable()

    create_button.on_click(on_create)
    run_button.on_click(on_run)


def run() -> None:
    ui.run(title="pyopia-gui", reload=False)


if __name__ in {"__main__", "__mp_main__"}:
    run()
