# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Nimmo Smith Technologies Limited

import json
import os
import time
from pathlib import Path

import pytest

from pyopia_gui import docker_client, run_lock


def _age(path: Path, seconds: float) -> None:
    old = time.time() - seconds
    os.utime(path, (old, old))


@pytest.fixture(autouse=True)
def no_container_running(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_client, "container_is_running", lambda name: False)


def test_acquire_marks_the_project_and_release_removes_it(tmp_path: Path) -> None:
    assert run_lock.acquire(tmp_path, "run-1", "pyopia-gui-aaaa") is None

    recorded = json.loads((tmp_path / run_lock.LOCK_FILENAME).read_text())
    assert recorded["token"] == "run-1"
    assert recorded["container"] == "pyopia-gui-aaaa"

    run_lock.release(tmp_path, "run-1")
    assert not (tmp_path / run_lock.LOCK_FILENAME).exists()


def test_a_second_run_is_refused_and_told_who_holds_it(tmp_path: Path) -> None:
    run_lock.acquire(tmp_path, "run-1", "pyopia-gui-aaaa")

    holder = run_lock.acquire(tmp_path, "run-2", "pyopia-gui-bbbb")

    assert holder is not None
    assert holder["token"] == "run-1"


def test_an_old_marker_with_no_container_running_is_replaced(tmp_path: Path) -> None:
    run_lock.acquire(tmp_path, "run-1", "pyopia-gui-aaaa")
    _age(tmp_path / run_lock.LOCK_FILENAME, run_lock.STALE_AFTER_SECONDS + 5)

    assert run_lock.acquire(tmp_path, "run-2", "pyopia-gui-bbbb") is None
    assert json.loads((tmp_path / run_lock.LOCK_FILENAME).read_text())["token"] == "run-2"


def test_an_old_marker_whose_container_is_still_running_is_not_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The app that started it died, but its container carries on writing into the folder.
    monkeypatch.setattr(docker_client, "container_is_running", lambda name: name == "pyopia-gui-aaaa")
    run_lock.acquire(tmp_path, "run-1", "pyopia-gui-aaaa")
    _age(tmp_path / run_lock.LOCK_FILENAME, run_lock.STALE_AFTER_SECONDS + 5)

    assert run_lock.acquire(tmp_path, "run-2", "pyopia-gui-bbbb") is not None


def test_touch_keeps_a_marker_fresh_only_for_its_own_run(tmp_path: Path) -> None:
    run_lock.acquire(tmp_path, "run-1", "pyopia-gui-aaaa")
    path = tmp_path / run_lock.LOCK_FILENAME
    _age(path, 20)

    run_lock.touch(tmp_path, "someone-else")
    assert time.time() - path.stat().st_mtime > 15
    run_lock.touch(tmp_path, "run-1")
    assert time.time() - path.stat().st_mtime < 5


def test_release_leaves_a_marker_that_another_run_has_since_taken(tmp_path: Path) -> None:
    run_lock.acquire(tmp_path, "run-1", "pyopia-gui-aaaa")
    run_lock.clear(tmp_path)
    run_lock.acquire(tmp_path, "run-2", "pyopia-gui-bbbb")

    run_lock.release(tmp_path, "run-1")

    assert (tmp_path / run_lock.LOCK_FILENAME).exists()


def test_an_unreadable_fresh_marker_still_counts_as_held(tmp_path: Path) -> None:
    (tmp_path / run_lock.LOCK_FILENAME).write_text("not json")

    assert run_lock.acquire(tmp_path, "run-1") == {}


def test_describe_says_when_it_started_and_on_which_other_machine() -> None:
    assert run_lock.describe({"started": time.time(), "host": "lab-pc-7"}).endswith("on lab-pc-7")
    assert run_lock.describe({}) == "start time unknown"
