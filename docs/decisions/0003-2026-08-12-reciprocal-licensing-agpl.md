# ADR 0003 — Reciprocal licensing (AGPL-3.0)

**Date:** 12 August 2026
**Status:** Accepted
**Decider:** Alex Nimmo Smith, Nimmo Smith Technologies Limited

---

## Context

pyopia-gui needed a licence. The guiding principle was that improvements to
openly-released work should stay available to the community that helped
build it - a reciprocal ("share-alike") approach, rather than a permissive
one.

---

## Decision

Release pyopia-gui under the **GNU Affero General Public License v3.0**
(AGPL-3.0).

---

## Alternatives considered

**MIT / permissive licence** - would maximise ease of adoption and
integration into other projects. Not chosen, in favour of a reciprocal
approach that keeps improvements to this project in the open.

**GPL-3.0** (without the "Affero" network clause) - the same reciprocal
principle for distributed software, but does not extend to software that is
modified and then only run as a network service rather than distributed.
AGPL was chosen so that the reciprocal principle applies consistently,
regardless of how a modified version is made available to others.

---

## Consequences

**Positive:**
- Modifications to pyopia-gui - including a version offered as a hosted
  service rather than distributed as software - must be made available
  under the same licence, keeping improvements in the open.

**Negative / trade-offs:**
- AGPL is sometimes avoided by downstream integrators who are more cautious
  of copyleft obligations than they would be with a permissive licence.

---

*This record is part of the pyopia-gui design decision log. See
`docs/decisions/` for the full index.*
