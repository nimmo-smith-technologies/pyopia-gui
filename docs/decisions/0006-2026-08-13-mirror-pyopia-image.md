# ADR 0006 — Publish a mirror of PyOPIA's Docker image as a temporary default

**Date:** 13 August 2026
**Status:** Accepted
**Decider:** Alex Nimmo Smith, Nimmo Smith Technologies Limited

---

## Context

pyopia-gui orchestrates PyOPIA via its published Docker image (ADR 0002, ADR 0005).
That image, `ghcr.io/sintef/pyopia`, is not currently publicly pullable - even
anonymous token issuance for it is denied, which is GHCR's signature for a private
package rather than a missing tag (see
[SINTEF/pyopia#424](https://github.com/SINTEF/pyopia/issues/424), filed but not yet
resolved). Nobody outside SINTEF's GitHub org can currently run PyOPIA processing
through pyopia-gui's default configuration - not because of anything in this project,
but because of that upstream visibility setting.

We don't have admin access to fix the upstream package's visibility ourselves, and
there's no way to know how long it will take SINTEF to do so.

---

## Decision

Build PyOPIA's own, unmodified `Dockerfile` from their public source, and publish the
result under our own GHCR namespace
(`ghcr.io/nimmo-smith-technologies/pyopia`) via a manually-triggered GitHub Actions
workflow. pyopia-gui's default image points at this mirror instead of the upstream
one, until the upstream image is public again - at which point this workflow and the
default should be reverted.

---

## Alternatives considered

**Wait for upstream.** Do nothing on our side and leave the default pointing at the
(currently unusable) upstream image, with the existing `PYOPIA_GUI_DOCKER_IMAGE`
override documented for anyone willing to build the image locally themselves. This
keeps zero extra infrastructure, but leaves pyopia-gui non-functional out of the box
for anyone who isn't comfortable building a Docker image from source - exactly the
non-expert audience this project is meant to serve.

---

## Consequences

**Positive:**
- pyopia-gui works out of the box again for real users, without needing GitHub org
  membership or a local Docker build, while the upstream issue is unresolved.
- The mirror is built from PyOPIA's own published source and `Dockerfile`, unmodified
  - we are not maintaining a fork, just publishing what upstream would if their own
    package were public.
- PyOPIA's BSD-3-Clause license permits this redistribution.

**Negative / trade-offs:**
- Ongoing maintenance: the mirror needs rebuilding for new PyOPIA releases, and this
  workflow (plus the default image it feeds) needs to be removed once upstream is
  fixed, or it will quietly drift out of date.
- Users now depend on our build of PyOPIA rather than SINTEF's own - a boundary worth
  being clear about if anyone asks why the image comes from `nimmo-smith-technologies`
  rather than `sintef`.
- No PyOPIA release currently includes the `Dockerfile` - it postdates `v2.0.3`,
  their latest tagged release - so the mirror is built from their `main` branch
  rather than a pinned release, which is less reproducible than pinning to a tag.
  Worth re-pinning to a real release once PyOPIA cuts one that includes it.

---

*This record is part of the pyopia-gui design decision log. See
`docs/decisions/` for the full index.*
