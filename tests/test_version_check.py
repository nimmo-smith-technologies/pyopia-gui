# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Nimmo Smith Technologies Limited

import io
import json
from urllib.error import URLError

import pytest

from pyopia_gui import version_check


def _fake_response(payload: object) -> io.BytesIO:
    return io.BytesIO(json.dumps(payload).encode())


def test_check_for_newer_release_returns_tag_when_newer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        version_check.urllib.request, "urlopen", lambda *a, **k: _fake_response([{"tag_name": "v0.3.0"}])
    )

    assert version_check.check_for_newer_release("0.2.0") == "v0.3.0"


def test_check_for_newer_release_returns_none_when_current(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        version_check.urllib.request, "urlopen", lambda *a, **k: _fake_response([{"tag_name": "v0.2.0"}])
    )

    assert version_check.check_for_newer_release("0.2.0") is None


def test_check_for_newer_release_returns_none_when_older(monkeypatch: pytest.MonkeyPatch) -> None:
    # Real case: someone overrides PYOPIA_GUI_DOCKER_IMAGE or otherwise runs an older tag
    # locally than what's actually published - must not claim a newer release exists.
    monkeypatch.setattr(
        version_check.urllib.request, "urlopen", lambda *a, **k: _fake_response([{"tag_name": "v0.1.0"}])
    )

    assert version_check.check_for_newer_release("0.2.0") is None


def test_check_for_newer_release_returns_none_on_network_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_url_error(*args: object, **kwargs: object) -> None:
        raise URLError("offline")

    monkeypatch.setattr(version_check.urllib.request, "urlopen", raise_url_error)

    assert version_check.check_for_newer_release("0.2.0") is None


def test_check_for_newer_release_returns_none_for_empty_releases_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(version_check.urllib.request, "urlopen", lambda *a, **k: _fake_response([]))

    assert version_check.check_for_newer_release("0.2.0") is None


def test_check_for_newer_release_returns_none_for_unparseable_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        version_check.urllib.request, "urlopen", lambda *a, **k: _fake_response([{"tag_name": "not-a-version"}])
    )

    assert version_check.check_for_newer_release("0.2.0") is None
