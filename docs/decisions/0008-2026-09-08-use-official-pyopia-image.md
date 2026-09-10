# ADR 0008 — Switch back to PyOPIA's official Docker image

**Date:** 8 September 2026
**Status:** Accepted, supersedes [ADR 0006](0006-2026-08-13-mirror-pyopia-image.md)
**Decider:** Alex Nimmo Smith, Nimmo Smith Technologies Limited

---

## Context

ADR 0006 recorded that `ghcr.io/sintef/pyopia` wasn't publicly pullable, and had
pyopia-gui default to a mirror image we built and published ourselves instead
(`ghcr.io/nimmo-smith-technologies/pyopia`), until that was fixed upstream.

[SINTEF/pyopia#424](https://github.com/SINTEF/pyopia/issues/424) is now resolved:
PyOPIA's v2.17.0 release publishes `ghcr.io/sintef/pyopia` as a public image. The
condition ADR 0006 was waiting on no longer holds.

---

## Decision

Default to `ghcr.io/sintef/pyopia` again. Remove the mirror-publishing workflow
(`.github/workflows/publish-pyopia-mirror.yml`) and the mirror-specific code in
`docker_client.py`. `PYOPIA_GUI_DOCKER_IMAGE` still exists as a general-purpose
override (pinning to an exact tag, or a locally-built image).

One wrinkle: PyOPIA's own `__version__` (and the version pyopia-gui reads back
from a project's stats file to pin a rerun) is bare, e.g. `"2.17.0"`, but the
official image's published tags are `v`-prefixed (`v2.17.0`), matching PyOPIA's
git tags rather than its Python version string. `image_for_version()` and
`list_available_versions()` now account for this - the former adds the `v` back
on when building an image reference, the latter strips it back off so returned
versions stay in the bare form the rest of pyopia-gui already expects.

---

## Alternatives considered

**Keep the mirror as a fallback.** Leave the mirror-publishing workflow in place
and only change the *default* image, in case the official image regresses to
private again. Rejected: two working, indefinitely-maintained paths to the same
image is exactly the ongoing-maintenance cost ADR 0006 flagged as a trade-off -
worth accepting temporarily, not indefinitely once it's no longer needed at all.

---

## Consequences

**Positive:**
- pyopia-gui now depends on PyOPIA's own published image directly, with no extra
  infrastructure of our own to keep in sync with new PyOPIA releases.
- One less GitHub Actions workflow, and one less thing that can silently drift
  out of date.

**Negative / trade-offs:**
- If `ghcr.io/sintef/pyopia` ever becomes unavailable again, restoring a mirror
  means re-adding the workflow this ADR just removed - not a large effort, but
  not free either.

---

*This record is part of the pyopia-gui design decision log. See
`docs/decisions/` for the full index.*
