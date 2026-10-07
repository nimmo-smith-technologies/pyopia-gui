# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Nimmo Smith Technologies Limited

"""A marker file in a project folder saying a processing run is using it.

Two runs writing into one folder interleave their results in a single stats file, and
nothing inside one app process can see another app instance (or another machine sharing the
folder), so the marker lives in the folder itself. It's created atomically, refreshed every
few seconds while the run goes on, and removed when it ends. If the app is killed mid-run the
marker simply stops being refreshed: it then counts as stale - and is replaced without
asking - once it's old *and* the run's container isn't still running (an orphaned container
would otherwise keep writing into the folder). Anything else needs an explicit `clear`.
"""

import json
import os
import platform
import time
from datetime import datetime
from pathlib import Path

from pyopia_gui import docker_client

LOCK_FILENAME = ".pyopia_gui_running"
HEARTBEAT_SECONDS = 5
STALE_AFTER_SECONDS = 30


def _path(project_dir: Path) -> Path:
    return project_dir / LOCK_FILENAME


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _is_stale(path: Path, info: dict) -> bool:
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return True  # it vanished since we looked
    if age < STALE_AFTER_SECONDS:
        return False
    container = info.get("container")
    return not (isinstance(container, str) and docker_client.container_is_running(container))


def acquire(project_dir: Path, token: str, container: str | None = None) -> dict | None:
    """Mark `project_dir` as in use by the run identified by `token`.

    Returns None once marked, or - if another run holds it and it isn't stale - that
    holder's recorded details (empty if its file can't be read), so the caller can say so
    and offer `clear`.
    """
    path = _path(project_dir)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            info = _read(path)
            if not _is_stale(path, info):
                return info
            path.unlink(missing_ok=True)
            continue
        with os.fdopen(fd, "w") as f:
            json.dump({"token": token, "host": platform.node(), "started": time.time(), "container": container}, f)
        return None
    return _read(path)


def touch(project_dir: Path, token: str) -> None:
    """Show the run `token` is still going (only if it still holds the marker)."""
    path = _path(project_dir)
    if _read(path).get("token") == token:
        try:
            os.utime(path)
        except OSError:
            pass


def release(project_dir: Path, token: str) -> None:
    """Remove the marker if the run `token` still holds it (it may have been cleared and retaken)."""
    path = _path(project_dir)
    if _read(path).get("token") == token:
        path.unlink(missing_ok=True)


def clear(project_dir: Path) -> None:
    """Remove the marker whoever holds it."""
    _path(project_dir).unlink(missing_ok=True)


def describe(info: dict) -> str:
    """A short phrase for who holds the marker, e.g. "started at 14:05 on another-machine"."""
    parts = []
    started = info.get("started")
    if isinstance(started, int | float):
        parts.append(f"started at {datetime.fromtimestamp(started):%H:%M}")
    host = info.get("host")
    if isinstance(host, str) and host and host != platform.node():
        parts.append(f"on {host}")
    return " ".join(parts) or "start time unknown"
