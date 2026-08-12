# Contributing to pyopia-gui

Thanks for thinking about contributing. This project exists to make PyOPIA
more accessible to people who'd rather work with a graphical interface than a
config file and command line - it gets better every time someone improves the
code, fixes a bug, or writes up something that wasn't clear.

## The deal

pyopia-gui is released under the GNU Affero General Public License v3.0
(AGPL-3.0) - see [LICENSE](LICENSE). Whatever you contribute goes out under
the same licence as the rest of the project.

You keep the copyright in what you contribute. We don't ask you to sign your
rights over to anyone - contributing here doesn't hand your work to Nimmo
Smith Technologies Limited, it simply adds it to the shared, openly-licensed
project. That's the whole point: what goes in stays open, for you and for
everyone after you.

## Signing off your work (DCO)

Rather than a contributor licence agreement, pyopia-gui uses the **Developer
Certificate of Origin** - a lightweight, widely-used way of confirming that
what you're contributing is yours to give. There's nothing separate to sign;
you just add a `Signed-off-by` line to each commit, which `git` does for you
with `-s`:

```
git commit -s -m "Describe your change"
```

That appends a line like:

```
Signed-off-by: Your Name <you@example.com>
```

By signing off you're certifying, in plain terms, that you wrote the
contribution (or otherwise have the right to submit it) and that you're happy
for it to be included under the project's licence. The full, canonical text
is at developercertificate.org.

Please use a real name and a working email - the sign-off is a record of
provenance, and keeping that record clean is something this project cares
about.

## How to contribute

1. **For anything substantial, open an issue first.** A quick discussion
   before you build saves everyone effort, and it's the best way to check a
   change fits the direction of the project.
2. **Fork, branch, and work in small, clear commits.** Sign each one off
   (`-s`).
3. **Open a pull request** describing what you changed and why. Link the
   issue if there is one. Pull requests are reviewed and merged by the
   maintainer before landing on `main`.
4. **New files need an SPDX header** identifying their licence:

   ```
   SPDX-License-Identifier: AGPL-3.0-or-later
   SPDX-FileCopyrightText: 2026 Nimmo Smith Technologies Limited
   ```

## Questions

Please review existing Issues and Discussions first, to see whether what
you're about to ask has already been answered. Otherwise, open a new **Issue**
for something concrete, or start a new **Discussion** for general questions or
feature requests.
