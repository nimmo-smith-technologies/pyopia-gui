# ADR 0009 — Compute Results summary statistics inside PyOPIA's image

**Date:** 7 October 2026
**Status:** Accepted, supersedes [ADR 0007](0007-2026-08-14-vendor-pyopia-statistics-functions.md)
**Decider:** Alex Nimmo Smith, Nimmo Smith Technologies Limited

---

## Context

ADR 0007 vendored a local copy of PyOPIA's statistics functions so the Results tab
could show particle count, d50 and a size-distribution chart, because PyOPIA had no
CLI command for them and ADR 0005 keeps processing logic inside PyOPIA's image.
It planned to drop the copy once PyOPIA exposed this itself.

PyOPIA 2.18.0 added `pyopia.statistics.summary_from_stats` (and a `summary-stats`
command built on it, closing
[SINTEF/pyopia#427](https://github.com/SINTEF/pyopia/issues/427)).

---

## Decision

Run `summary_from_stats` inside the project's own PyOPIA image (`docker_client.summarize_stats`)
and delete `vendored_stats.py` along with the host-side numpy, pandas, xarray, h5netcdf
and h5py dependencies it needed.

It is run as a short script rather than the `summary-stats` command itself, because the
Results tab's aux-data filter must be applied to the particles before summarising and
the command has no filter option (unlike `make-montage` and `export-to-ecotaxa`). Once
`summary-stats` gains one, this becomes a plain CLI call.

Checked against the vendored implementation on a real processed project: particle count,
image count, d50 and all 52 size-bin counts were identical.

---

## Consequences

**Positive:**
- One implementation of the statistics, maintained by PyOPIA - no drift from a copy.
- The packaged app no longer carries numpy, pandas, xarray or HDF5 libraries: a
  smaller download and less memory.
- No third-party source code is vendored any more.

**Negative / trade-offs:**
- The Results tab now waits roughly 2 seconds for a container to start each time it
  computes the summary (including each time a filter is applied); it was instant before.
- Projects processed with a PyOPIA version before 2.18.0 can no longer show summary
  statistics until reprocessed with a newer version - the Results tab says so.
- Needs the project's image locally, as montages and exports already do.

---

*This record is part of the pyopia-gui design decision log. See
`docs/decisions/` for the full index.*
