# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Nimmo Smith Technologies Limited

import json
import urllib.request
from urllib.error import URLError

RELEASES_API_URL = "https://api.github.com/repos/nimmo-smith-technologies/pyopia-gui/releases"
RELEASES_PAGE_URL = "https://github.com/nimmo-smith-technologies/pyopia-gui/releases"


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.removeprefix("v").split("."))


def check_for_newer_release(current_version: str, timeout: float = 3.0) -> str | None:
    """Return the latest published release's tag if it's newer than `current_version`, else None.

    Best-effort only: any failure (offline, rate-limited, unexpected response shape) is
    treated the same as "nothing newer" - a failed update check should never interrupt or
    alarm anyone just trying to use the app. Reads the releases list rather than GitHub's
    `/releases/latest` endpoint, since that endpoint excludes prereleases and every release
    published so far is marked prerelease (alpha).
    """
    try:
        request = urllib.request.Request(RELEASES_API_URL, headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 fixed https:// URL above
            releases = json.load(response)
    except (URLError, OSError, ValueError):
        return None
    if not releases:
        return None
    latest_tag = releases[0].get("tag_name", "")
    try:
        if _version_tuple(latest_tag) > _version_tuple(current_version):
            return latest_tag
    except ValueError:
        return None
    return None
