# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Nimmo Smith Technologies Limited

from pathlib import Path

from nicegui import ui

from pyopia_gui import docker_client

DEFAULT_PROJECTS_DIR = Path.home() / "pyopia-gui-projects"
EXAMPLE_PROJECT_NAME = "demo"


@ui.page("/")
def index() -> None:
    ui.label("pyopia-gui").classes("text-2xl")

    docker_status = docker_client.check_docker()
    if docker_status != docker_client.DockerStatus.AVAILABLE:
        ui.label("Docker isn't ready yet").classes("text-lg text-red")
        ui.markdown(docker_client.setup_guidance(docker_status))
        ui.button("Recheck", on_click=lambda: ui.navigate.reload())
        return

    parent_dir = DEFAULT_PROJECTS_DIR
    project_dir = parent_dir / EXAMPLE_PROJECT_NAME
    already_created = (project_dir / "config.toml").exists()

    ui.label(f"Example project folder: {project_dir}").classes("text-sm text-gray-500")

    log = ui.log(max_lines=500).classes("w-full h-64 bg-black text-white")
    montage = ui.image().classes("w-full max-w-2xl")
    montage.visible = False

    create_button = ui.button("1. Create example project")
    run_button = ui.button("2. Run processing")
    if already_created:
        create_button.disable()
    else:
        run_button.disable()

    async def run_streamed_to_log(command: list[str]) -> int:
        log.push("$ " + " ".join(command))
        return await docker_client.run_streamed(command, log.push)

    async def on_create() -> None:
        create_button.disable()
        parent_dir.mkdir(parents=True, exist_ok=True)
        command = docker_client.init_project_command(parent_dir, EXAMPLE_PROJECT_NAME)
        exit_code = await run_streamed_to_log(command)
        if exit_code == 0:
            ui.notify("Example project created", type="positive")
            run_button.enable()
        else:
            ui.notify("Failed to create example project - see log", type="negative")
            create_button.enable()

    async def on_run() -> None:
        run_button.disable()
        exit_code = await run_streamed_to_log(docker_client.process_command(project_dir))
        if exit_code != 0:
            ui.notify("Processing failed - see log", type="negative")
            run_button.enable()
            return
        ui.notify("Processing complete", type="positive")

        merge_exit_code = await run_streamed_to_log(docker_client.merge_mfdata_command(project_dir))
        if merge_exit_code != 0:
            ui.notify("Merging processed stats failed - see log", type="negative")
            run_button.enable()
            return

        montage_command = docker_client.make_montage_command(
            project_dir, docker_client.stats_filename(EXAMPLE_PROJECT_NAME)
        )
        montage_exit_code = await run_streamed_to_log(montage_command)
        if montage_exit_code == 0:
            montage.set_source(str(project_dir / "montage.png"))
            montage.visible = True
        else:
            ui.notify("Montage creation failed - see log", type="negative")
        run_button.enable()

    create_button.on_click(on_create)
    run_button.on_click(on_run)


def run() -> None:
    ui.run(title="pyopia-gui", reload=False)


if __name__ in {"__main__", "__mp_main__"}:
    run()
