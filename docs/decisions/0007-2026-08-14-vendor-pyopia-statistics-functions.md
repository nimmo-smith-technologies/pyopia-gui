# ADR 0007 — Vendor a local copy of PyOPIA's statistics functions for the Results tab

**Date:** 14 August 2026
**Status:** Accepted
**Decider:** Alex Nimmo Smith, Nimmo Smith Technologies Limited

---

## Context

pyopia-gui's Results tab shows summary statistics and plots of a project's
particle data (particle count, d50, a size-distribution chart) alongside the
existing montage. PyOPIA's own Python library already has everything needed
to compute these (`d50_from_stats`, `nd_from_stats`, `vd_from_stats`,
`count_images_in_stats`, `get_size_bins` in `pyopia/statistics.py`, all pure
numpy/pandas) - but none of it is exposed via PyOPIA's CLI. Only `process`,
`merge-mfdata`, `make-montage`, `convert-raw-images`, and
`export-to-ecotaxa` are real subcommands.

This runs against ADR 0005's Docker-only principle: pyopia-gui orchestrates
PyOPIA entirely via its CLI/Docker image, and never imports PyOPIA as a
Python library or runs its processing logic outside a container. That
principle exists for good reasons (keeps pyopia-gui loosely coupled,
guarantees results match what the CLI/Docker image actually produces) and
isn't being abandoned here - but there's no CLI command to shell out to for
this specific, narrow need.

---

## Decision

Vendor (copy, adapt, and maintain locally) the specific BSD-3-Clause-licensed
functions needed for the Results tab's summary statistics into
`src/pyopia_gui/vendored_stats.py`, and read a project's `-STATS.nc` file
directly from the host filesystem to compute them - not via Docker.

This is a narrow, explicit exception to ADR 0005, scoped specifically to
**read-only analysis of already-produced output**. It never touches
processing itself: nothing here re-runs, reprocesses, or modifies a
project's data, only reads a file PyOPIA's own `process`/`merge-mfdata`
commands already wrote. The intent is to migrate to a real PyOPIA CLI
command once one exists and drop this file - tracked in
[pyopia-gui#3](https://github.com/nimmo-smith-technologies/pyopia-gui/issues/3)
(this repo) and requested upstream at
[SINTEF/pyopia#427](https://github.com/SINTEF/pyopia/issues/427).

License attribution: see `THIRD_PARTY_LICENSES.md` at the repo root, and the
header comment in `vendored_stats.py` itself (which records the exact
PyOPIA commit vendored from, for future diffing).

---

## Alternatives considered

**Wait for a PyOPIA CLI command, ship the Results tab without stats/plots
until then.** Keeps ADR 0005's principle fully intact with no exception, but
leaves the Results tab genuinely thinner (montage only) for an unknown
amount of time, waiting on an upstream change this project doesn't control
the timeline of.

**Run the vendored code inside Docker instead of on the host**, e.g. via a
one-off `docker run --entrypoint python <image> -c "..."` snippet reading
the mounted stats file, similar to how `read_pinned_version()` already reads
a single attribute this way. Keeps everything inside the container boundary,
but the vendored functions themselves still wouldn't exist in PyOPIA's own
image - it'd just move the copy-paste problem into an inline script instead
of a proper local module, without the benefit of real local testability
(`tests/test_vendored_stats.py`) or IDE/type support, for a computation this
lightweight (pure numpy/pandas, no heavy processing) it doesn't need
Docker's isolation for anyway.

---

## Consequences

**Positive:**
- Results tab ships with real summary statistics and plots now, not blocked
  on an upstream change.
- Reading directly on the host is fast (no container startup) for a
  computation that's genuinely lightweight.
- Fully covered by unit tests, including a real netCDF read
  (`tests/test_vendored_stats.py`), independent of Docker/PyOPIA being
  installed at all.

**Negative / trade-offs:**
- **Version drift risk**: the vendored functions are a single, unversioned
  snapshot, while different pyopia-gui projects can be pinned to different
  PyOPIA versions (see the version-pinning design in `docker_client.py`). If
  a pinned project's PyOPIA version has a different stats-file schema than
  what's vendored, computing summary stats could fail or (worse) silently
  produce wrong numbers. Mitigated by wrapping the read/compute call site in
  error handling with a plain-language message, but not eliminated - a real
  reason to prioritise the CLI migration once possible, not just a
  formality.
- Ongoing maintenance: `vendored_stats.py` needs manual updates if PyOPIA's
  stats-file schema or these functions' logic changes upstream, since there
  is no automatic mechanism keeping the copy in sync.
- Reads the stats file directly on the host, not through the same
  `/workspace` Docker mount boundary the rest of the app uses - a
  deliberate, narrow exception (read-only, not reprocessing), not a general
  loosening of the Docker-only principle.

---

*This record is part of the pyopia-gui design decision log. See
`docs/decisions/` for the full index.*
