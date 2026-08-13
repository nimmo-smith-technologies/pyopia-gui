# Using pyopia-gui

pyopia-gui is a graphical front end for [PyOPIA](https://github.com/SINTEF/pyopia), a
toolbox for processing particle images from ocean instruments (SilCam, holographic
imaging, UVP). It runs PyOPIA's own Docker image for you and shows you the results,
without needing to work with config files or a command line.

## Before you start

You'll need two things installed on your computer:

- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** - used to install
  and run pyopia-gui itself.
- **[Docker](https://docs.docker.com/get-started/get-docker/)** - pyopia-gui uses
  PyOPIA's own Docker image to do the actual image processing, so it needs Docker
  installed and running. If it isn't, pyopia-gui tells you exactly what to do the
  first time you open it - see [Docker isn't ready yet](#docker-isnt-ready-yet) below.

!!! note "About the PyOPIA image"
    PyOPIA's own official Docker image is currently private
    ([tracking issue](https://github.com/SINTEF/pyopia/issues/424)), so pyopia-gui
    uses a mirror we publish ourselves in the meantime - no extra steps needed, this
    is handled automatically. See the
    [README](https://github.com/nimmo-smith-technologies/pyopia-gui#readme) if you'd
    rather point it at the official image once that's public again, or one you've
    built yourself.

## Starting pyopia-gui

From a terminal, in the pyopia-gui project folder:

```bash
uv sync
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
3. Relaunch Docker Desktop.

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

## The main screen

Once Docker's ready, you'll see:

- **Project folder** - the folder pyopia-gui will create an example project in, and/or
  process. It starts out pointing at a ready-made example location. Click
  **Browse…** to pick a different folder on your computer, or type a path directly.
- **1. Create example project** - downloads a small set of example images and a
  matching configuration file into the project folder above, so you have something to
  try immediately without needing your own data.
- **2. Run processing** - runs PyOPIA on whatever's in the project folder, then builds
  a montage image of the particles it found.
- A **status line** showing what's currently happening, and a **log panel** underneath
  showing PyOPIA's own output in detail - useful if something goes wrong and you want
  to see exactly what happened.

The pyopia-gui version is shown in the header at all times. Hovering over any element
on the page shows a short explanation too.

## Trying it out

The quickest way to see pyopia-gui working:

1. Click **1. Create example project**. This downloads some example data - it can
   take a little while the first time, since it also needs to download PyOPIA's Docker
   image if you don't already have it.
2. Once that finishes, click **2. Run processing**.
3. Once processing itself finishes, the exact PyOPIA version that produced the
   results appears on the page - read straight from that run's own output, so it's
   always an accurate record of what actually processed the data, useful if you need
   to report which version of PyOPIA your results came from.
4. When everything's done, a montage image of the particles found in the example data
   appears at the bottom of the page.

## Using your own data

Instead of the example project, you can point pyopia-gui at any folder that already
has a PyOPIA project set up in it (a `config.toml` file, plus your images) - type or
browse to that folder in the **Project folder** field, then click **2. Run
processing**. Setting up a PyOPIA project from your own data currently needs PyOPIA's
own command-line tools (see [PyOPIA's documentation](https://pyopia.readthedocs.io));
an in-app way to do this is planned.

## If something goes wrong

- **A message about the PyOPIA image** - pyopia-gui explains what it thinks went
  wrong (e.g. the image couldn't be downloaded), both as a pop-up message and directly
  in the log panel where it happened.
- **"This folder already exists"** - shown if you click **1. Create example project**
  pointing at a folder that's already there. Either pick a different, new folder, or
  if that folder already has a project in it, just click **2. Run processing**
  instead.
- For anything else, the log panel shows PyOPIA's own detailed output, which usually
  explains what happened.
