# ADR 0005 — Docker-only processing backend

**Date:** 13 August 2026
**Status:** Accepted
**Decider:** Alex Nimmo Smith, Nimmo Smith Technologies Limited

---

## Context

pyopia-gui aims to be installable by non-expert science users with as little
friction as possible, ideally down to a single downloadable app (see ADR 0001
on NiceGUI's native-app support). Docker is itself a real piece of that
install friction: on top of installing pyopia-gui, a user also needs Docker
installed, its daemon running, and (on Linux) correct permissions - real
setup steps, not a single click.

That friction raised the question of whether pyopia-gui should avoid Docker
entirely for a simpler "newbie" install path, by bundling PyOPIA's own Python
dependencies directly into the packaged pyopia-gui app instead.

---

## Decision

Keep **Docker as the only way pyopia-gui runs PyOPIA processing**. Do not add
a bundled-Python fallback that runs PyOPIA's dependencies directly on the
host.

---

## Alternatives considered

**Bundle PyOPIA's dependencies into the packaged app**, running processing
in-process or via a bundled Python environment instead of a container. This
would remove Docker as a separate install step. However, it trades away
Docker's environment-level guarantee - a pinned, byte-identical processing
environment regardless of host - for whatever OS, kernel, and system
libraries the bundled dependencies happen to run on top of on a given
machine. For a tool whose whole point is producing reproducible scientific
measurements, that's a direct regression, not just an engineering
simplification.

---

## Consequences

**Positive:**
- The processing environment stays exactly reproducible - pinned down to OS
  libraries, not just Python package versions - independent of the host
  machine, directly serving PyOPIA's science outputs.
- Consistent with ADR 0002: pyopia-gui already talks to PyOPIA via its
  published Docker image, the same way any external user would.
- Avoids maintaining a second, parallel packaging of PyOPIA's dependency
  stack (including heavy optional ML extras) inside pyopia-gui itself.

**Negative / trade-offs:**
- Docker remains a real install prerequisite. Getting it properly set up is
  non-trivial and platform-dependent (elevated privileges, WSL2 on Windows,
  build tooling not always present out of the box) - "auto-install" for
  pyopia-gui therefore has to include a guided, multi-platform Docker
  setup/detection experience inside the app itself, rather than being able
  to design around Docker's absence.
- A container invocation per processing run adds process/network overhead
  compared to an in-process call.

---

*This record is part of the pyopia-gui design decision log. See
`docs/decisions/` for the full index.*
