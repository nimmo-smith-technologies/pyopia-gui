# ADR 0001 — GUI framework: NiceGUI

**Date:** 12 August 2026
**Status:** Accepted
**Decider:** Alex Nimmo Smith, Nimmo Smith Technologies Limited

---

## Context

pyopia-gui needs to give users a way to configure, launch, and monitor PyOPIA
processing runs - orchestrated via PyOPIA's own Docker image - and review the
resulting particle statistics, without needing to hand-edit config files or
work directly with the command line.

The core interaction this needs to support well is inherently asynchronous:
start a long-running external process (a Docker container doing real image
processing), and reflect its live progress and logs back to the user as it
runs.

---

## Decision

Use **NiceGUI** as the GUI framework.

---

## Alternatives considered

**Streamlit** - the largest community of the options considered, simplest to
learn, and backed by a well-resourced company. However, its execution model
reruns the whole script on each interaction, which is awkward for reflecting
live output from a long-running external process - achievable, but via
workarounds rather than a natural fit.

**Panel** (HoloViz/Anaconda) - the strongest scientific plotting integration
of the three, particularly for the xarray-based data PyOPIA produces.
Shares Streamlit's rerun-style execution model for the interactive parts,
so has the same awkwardness for live process monitoring.

---

## Consequences

**Positive:**
- NiceGUI's async/event-driven model is a natural fit for starting a Docker
  job and streaming its live output back to the interface, rather than
  requiring polling workarounds.
- Can also run as an installed desktop application (via `native=True`), not
  only as a browser-accessed web app, on desktop operating systems.

**Negative / trade-offs:**
- Smaller community and less mature ecosystem than Streamlit.
- Steeper learning curve for anyone used to Streamlit's simpler,
  script-based model, since NiceGUI is callback/event-driven.

---

*This record is part of the pyopia-gui design decision log. See
`docs/decisions/` for the full index.*
