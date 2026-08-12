# ADR 0002 — Separate repository from PyOPIA

**Date:** 12 August 2026
**Status:** Accepted
**Decider:** Alex Nimmo Smith, Nimmo Smith Technologies Limited

---

## Context

[PyOPIA](https://github.com/SINTEF/pyopia) is a general-purpose, co-maintained
scientific processing library. A GUI for it is an application layer on top -
different dependencies, different release cadence, different audience - not
a core part of the processing toolbox itself.

---

## Decision

Host the GUI as its own repository, `pyopia-gui`, rather than inside the
PyOPIA repository.

---

## Consequences

**Positive:**
- Keeps PyOPIA's own dependency footprint and review process focused on the
  core library, rather than bringing in a GUI framework and its dependencies.
- pyopia-gui can iterate independently, at its own pace.
- Consistent with how PyOPIA's own Docker image is already published as a
  separate release artifact rather than bundled into the core library - the
  GUI is another application layer on top, following the same pattern.
- pyopia-gui talks to PyOPIA the same way any external user would (its CLI,
  via the Docker image), rather than depending on internals - keeping the
  two projects loosely coupled.

**Negative / trade-offs:**
- Discoverability requires a deliberate link from PyOPIA's own documentation;
  a separate repository is not automatically found by people already using
  PyOPIA.

---

*This record is part of the pyopia-gui design decision log. See
`docs/decisions/` for the full index.*
