# Using pyopia-gui

pyopia-gui is a graphical front end for [PyOPIA](https://github.com/SINTEF/pyopia), a
toolbox for processing particle images from ocean instruments (SilCam, holographic
imaging, UVP). It runs PyOPIA's own Docker image for you and shows you the results,
without needing to work with config files or a command line.

## Before you start

Whichever way you get pyopia-gui running (see below), you'll need
**[Docker](https://docs.docker.com/get-started/get-docker/)** installed and running -
pyopia-gui uses PyOPIA's own Docker image to do the actual image processing. If it
isn't installed or running, pyopia-gui tells you exactly what to do the first time you
open it - see [Docker isn't ready yet](#docker-isnt-ready-yet) below.

!!! note "About the PyOPIA image"
    PyOPIA's own official Docker image is currently private
    ([tracking issue](https://github.com/SINTEF/pyopia/issues/424)), so pyopia-gui
    uses a mirror we publish ourselves in the meantime - no extra steps needed, this
    is handled automatically. See the
    [README](https://github.com/nimmo-smith-technologies/pyopia-gui#readme) if you'd
    rather point it at the official image once that's public again, or one you've
    built yourself.

## Getting pyopia-gui

### Option A: Download the app (no install needed)

No Python or terminal needed for this option. Go to the
[Releases page](https://github.com/nimmo-smith-technologies/pyopia-gui/releases),
open the **Assets** section for the release at the top (click it to expand the list
of downloads - it's collapsed by default), and download the file for your operating
system:

- **Windows**: download `pyopia-gui.exe` and double-click it.
- **Mac**: download `pyopia-gui-macos.zip`, unzip it, and double-click
  `pyopia-gui.app`. **Apple Silicon only for now** - on an Intel Mac, use
  [Option B](#option-b-run-from-source) instead.
- **Linux**: download `pyopia-gui-linux.zip`, unzip it, and run `./pyopia-gui`. If it
  fails to open with a `qt.qpa.plugin: Could not load the Qt platform plugin "xcb"`
  error, install `libxcb-cursor0` (e.g. `sudo apt install libxcb-cursor0` on
  Debian/Ubuntu-based distros).

!!! note "This is still an early alpha"
    The downloadable app is new and less tested than running from source - if you hit
    something unexpected, [Option B](#option-b-run-from-source) is the more
    battle-tested path, and we'd appreciate a
    [bug report](https://github.com/nimmo-smith-technologies/pyopia-gui/issues) either
    way.

### Option B: Run from source

Needs [uv](https://docs.astral.sh/uv/getting-started/installation/) (a Python package
manager) installed first. Then, from a terminal, in the pyopia-gui project folder:

```bash
uv sync --group dev --group docs
uv run pyopia-gui
```

This starts pyopia-gui and prints a web address (something like
`http://localhost:8080`) - open that in your browser.

## Docker isn't ready yet

If Docker isn't installed, or isn't running, pyopia-gui shows you exactly what's wrong
and what to do about it - the instructions are specific to your operating system
(Linux, Mac, or Windows). Once you've followed them, click **Recheck**.

A couple of things worth knowing before you start, especially on Windows:

### The Docker Hub account prompt

Docker Desktop's installer asks you to sign in or create a free Docker Hub account.
pyopia-gui doesn't need this - it never talks to Docker Hub, only to GitHub's
container registry - so look for a "skip" or "continue without signing in" option.
If you do create one, it's a low-stakes account: no payment details needed, nothing
sensitive stored there, so ordinary password hygiene is enough - no need to treat it
like a banking password.

### Windows: WSL2

Docker Desktop on Windows needs WSL2 (Windows Subsystem for Linux) installed. Recent
versions of Docker Desktop detect if it's missing and offer to set it up for you, but
if you're prompted separately, or Docker Desktop says WSL isn't installed:

1. Open PowerShell **as Administrator** (right-click it → "Run as administrator") and
   run:
   ```powershell
   wsl --install
   ```
2. **Restart your computer** - this step matters, Docker Desktop won't detect WSL2
   until you do.
3. After restarting, WSL finishes installing its default Ubuntu environment and asks
   you to create a Unix username and password. This is local to that WSL environment
   on your own machine only - it's not a Microsoft account, isn't sent anywhere, and
   isn't used for anything outside WSL itself, so ordinary/simple is fine. You don't
   need to remember or use it for pyopia-gui either - Docker Desktop only needs the
   WSL2 platform to exist, not that particular login.
4. Relaunch Docker Desktop.

If `wsl --install` itself fails:

- **Check virtualization is enabled in your BIOS/UEFI** (Task Manager → Performance
  tab → CPU → "Virtualization"). It's off by default on some machines, and WSL2 can't
  work without it - if it's off, no software fix will help until it's enabled in the
  firmware settings.
- **Make sure Windows Update is fully up to date** - `wsl --install` can fail on a
  system that's missed prerequisite updates.
- **Try the manual two-step method** instead of the all-in-one command:
  ```powershell
  dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
  dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
  ```
  then restart and try `wsl --install` again.
- If it still fails with no clear reason, check **Event Viewer** (Windows Logs →
  Application, or Applications and Services Logs → Microsoft → Windows → Lxss) for
  the actual underlying error - "Catastrophic failure" is just Windows' generic
  wrapper message and doesn't say what really went wrong.

### Mac: "docker: command not found" or a credentials error

If Docker Desktop shows as running but pyopia-gui still says Docker isn't
installed, or you see `docker: command not found` in a terminal, or later an
error like `error getting credentials - err: exec: "docker-credential-desktop"
executable file not found in $PATH`, Docker Desktop's command-line tools never
got linked onto your PATH - normally a one-time step during its first launch
that needs your Mac password, which is easy to miss or dismiss. Add its bundled
tools to your PATH directly:

```bash
echo 'export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

Then open a new terminal (or `source ~/.zshrc` in your current one) and try
again.

### Linux: "permission denied" talking to Docker

If `docker --version` prints a version but pyopia-gui still says Docker isn't
ready, or a terminal shows something like "permission denied while trying to
connect to the Docker API", your user account isn't in the `docker` group yet
- by default only `root` can talk to the Docker daemon:

```bash
sudo usermod -aG docker $USER
```

Then either **reboot**, or run `newgrp docker` in your current terminal - a
plain log out/log back in doesn't reliably pick up the new group membership on
every desktop environment.

## The main screen

Once Docker's ready, pyopia-gui walks you through the stages of a processing run as
tabs - each one only usable once it's actually relevant:

1. **Project** - always available. The **Project folder** field is the folder
   pyopia-gui will create an example project in, and/or process; it starts out
   pointing at a ready-made example location. Click **Browse…** to pick a different
   folder, or type a path directly. **Create example project** downloads a small
   set of example images and a matching configuration file into it.
2. **Raw data explorer** - shown but disabled for now ("coming soon") - planned but
   not built yet.
3. **Configuration** - becomes available once the Project folder field points at a
   valid PyOPIA project. Lets you view and edit that project's `config.toml` without
   needing a text editor - see [Editing a project's configuration](#editing-a-projects-configuration)
   below.
4. **Process** - becomes available once the Project folder field points at a valid
   PyOPIA project (a folder with a `config.toml`). **Run processing** runs PyOPIA
   on it, then builds a montage image of the particles found.
5. **Results** - becomes available once that project actually has results (a
   processed stats file). If you point pyopia-gui at an already-processed project,
   it jumps here automatically and shows whatever's already there.

Below the tabs, a **status line** shows what's currently happening, and a **log
panel** shows PyOPIA's own output in detail - useful if something goes wrong and you
want to see exactly what happened. Both stay visible no matter which tab you're on.

The pyopia-gui version is shown in the header at all times - it also checks for a
newer release and shows a link to it there if one's available - alongside an
**About** link with the license and third-party attributions. Hovering over any
element on the page shows a short explanation too.

## Trying it out

The quickest way to see pyopia-gui working:

1. Click **Create example project**. This downloads some example data - it can
   take a little while the first time, since it also needs to download PyOPIA's
   Docker image if you don't already have it.
2. Switch to the **Process** tab (now enabled) and click **Run processing**.
3. Once processing finishes, pyopia-gui switches to the **Results** tab automatically.
   It shows the exact PyOPIA version that produced the results - read from the
   project's own output, so it's always an accurate record, useful if you need to
   report which version of PyOPIA your results came from - plus a **Generate montage**
   button (montages aren't built automatically) and summary statistics: particle
   count, d50 (median particle size), and a size-distribution chart.

## Using your own data

Instead of the example project, you can point pyopia-gui at any folder that already
has a PyOPIA project set up in it (a `config.toml` file, plus your images) - type or
browse to that folder in the **Project folder** field, then use the **Configuration**
tab to review/adjust its settings and the **Process** tab to run it. Getting your own
raw images into a project folder in the first place currently needs to be done outside
pyopia-gui (an in-app way to do this is planned - see the **Raw data explorer** tab
above); once they're there, the **Configuration** tab (below) can generate PyOPIA's own
default `config.toml` for you rather than needing PyOPIA's command-line tools.

## Editing a project's configuration

The **Configuration** tab shows a project's `config.toml`, grouped into **General**
settings and one section per processing step:

- **General** - `raw_files` (which images to process), `pixel_size`, and logging
  settings. **`pixel_size` needs checking, not just trusting** - it depends on your
  specific instrument and lens setup (holo setups especially have many sub-variants
  with different values), and pyopia-gui has no way to verify it's correct for your
  actual hardware.
- **Processing steps** - one collapsible section per pipeline step (e.g.
  `segmentation`, `statextract`), each showing its actual parameters with the same
  descriptions PyOPIA's own documentation gives them - read directly from the exact
  PyOPIA version this project uses, so they're always accurate for it. If a step's
  parameters can't be read this way for some reason, its raw values are still shown
  and editable, just without descriptions.

Click **Save changes** to write your edits back to `config.toml`. **Generate default
config…** overwrites it entirely with PyOPIA's own bare defaults for a chosen
instrument type (silcam, holo, or uvp) - useful for starting a new project's config
from scratch, or resetting a broken one - after a confirmation dialog, since it
discards any customisation already there.

## Choosing (and switching) a PyOPIA version

The first time a project is processed - whether created via **1. Create example
project** or pointed at your own not-yet-processed data - pyopia-gui asks which PyOPIA
version to use. From then on, that same project always reuses exactly that version,
even after newer ones are published, so reprocessing or resuming a dataset later never
silently switches versions partway through and produces inconsistent results.

To deliberately switch a project to a different version, move or delete its existing
results (the `...-STATS.nc` file named in `config.toml`'s `output_datafile`) before
clicking **Run processing** again - with no existing results to stay consistent
with, pyopia-gui asks you to choose a version again.

## If something goes wrong

- **A message about the PyOPIA image** - pyopia-gui explains what it thinks went
  wrong (e.g. the image couldn't be downloaded), both as a pop-up message and directly
  in the log panel where it happened.
- **"This folder already exists"** - shown if you click **Create example project**
  pointing at a folder that's already there. Either pick a different, new folder, or
  if that folder already has a project in it, just click **Run processing**
  instead.
- For anything else, the log panel shows PyOPIA's own detailed output, which usually
  explains what happened.
