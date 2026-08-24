# Using pyopia-gui

This page covers the app itself once it's installed and running - see
[Installing pyopia-gui](installing.md) if you're not there yet.

## The main screen

Once Docker's ready, pyopia-gui walks you through the stages of a processing run as
tabs - each one only usable once it's actually relevant:

1. **Project** - always available. The **Project folder** field is the folder
   pyopia-gui will create an example project in, and/or process; it starts out
   pointing at a ready-made example location. Click **Browse…** to pick a different
   folder, or type a path directly. **Create example project** downloads a small
   set of example images and a matching configuration file into it.
2. **Raw data explorer** - becomes available once the Project folder field points at
   a valid PyOPIA project. Browse a paginated grid of thumbnails of that project's raw
   images - see [Browsing raw data](#browsing-raw-data) below.
3. **Configuration** - becomes available once the Project folder field points at a
   valid PyOPIA project. Lets you view and edit that project's `config.toml` without
   needing a text editor - see [Editing a project's configuration](#editing-a-projects-configuration)
   below.
4. **Preview** - becomes available once the Project folder field points at a valid
   PyOPIA project. Run the current processing parameters against a single sample
   image to quickly check the effect of a change, without waiting for a full batch
   run - see [Previewing parameter effects on one image](#previewing-parameter-effects-on-one-image)
   below.
5. **Process** - becomes available once the Project folder field points at a valid
   PyOPIA project (a folder with a `config.toml`). **Run processing** runs PyOPIA
   on it - once finished, results are available on the Results tab (including
   generating a montage there, on demand - it isn't built automatically).
   **Starting a run clears the project's existing output folder first**, so old
   results are never left behind to potentially get mixed into new ones. A
   **Processors to use** setting lets you split the run across multiple chunks for
   a speedup on a multi-core machine (requires the project's `steps.output.append`
   setting to be `false`).
6. **Results** - becomes available once that project actually has results (a
   processed stats file). If you point pyopia-gui at an already-processed project,
   it jumps here automatically and shows whatever's already there - see
   [Reviewing results](#reviewing-results) below.

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
   count, d50 (median particle size), and a size-distribution chart. See
   [Reviewing results](#reviewing-results) below for exporting these, and filtering
   by aux data.

## Using your own data

Instead of the example project, you can point pyopia-gui at any folder that already
has a PyOPIA project set up in it (a `config.toml` file, plus your images) - type or
browse to that folder in the **Project folder** field, then use the **Raw data
explorer** tab to check the right images are there, the **Configuration** tab to
review/adjust its settings, and the **Process** tab to run it. Getting your own raw
images into a project folder in the first place currently needs to be done outside
pyopia-gui; once they're there, the **Configuration** tab (below) can generate
PyOPIA's own default `config.toml` for you rather than needing PyOPIA's command-line
tools.

## Browsing raw data

The **Raw data explorer** tab shows a paginated grid of thumbnails for whatever raw
images the project's `config.toml` currently points at (its `general.raw_files`
setting) - a quick way to check the right data is there before processing it. Each
image's filename is shown underneath its thumbnail.

Raw instrument files aren't directly viewable image formats (SilCam's `.silc` and
holo's `.pgm` are raw sensor data, not standard images), so pyopia-gui converts them
to previewable thumbnails the same way PyOPIA's own tools would - the first time you
view a page of images this takes a few seconds, but each thumbnail is cached
afterwards, so revisiting the same page is instant.

You can also narrow a project down to a chosen subset of its raw images: tick
individual thumbnails (or **Select all on this page**, handy for a quick test run
against just a few images) and click **Use selected as raw_files** to point the
project at just those. A banner appears while a subset is active, with a **Clear
subset** button to revert to the original pattern.

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
  and editable, just without descriptions. Each step has an **Enable this step**
  switch above it - switching a step off keeps its settings (nothing is deleted,
  just moved aside) but leaves it out of both processing and Preview until it's
  switched back on; a disabled step shows dimmed with "(disabled)" in its caption.
  Switching a step back on and saving requires every one of its required fields to
  actually have a value - if one's still blank, **Save changes** is blocked with a
  clear message instead of producing a config that fails partway through a run.

Click **Save changes** to write your edits back to `config.toml`. **Generate default
config…** overwrites it entirely with PyOPIA's own bare defaults for a chosen
instrument type (silcam, holo, or uvp) - useful for starting a new project's config
from scratch, or resetting a broken one - after a confirmation dialog, since it
discards any customisation already there. It also asks whether to **enable particle
classification** - leave it unchecked if you don't have a classifier model file
handy, and the generated config keeps the classifier step present-but-disabled
(switch it on later from the Configuration tab once you have a model path) rather
than generating a config that fails the moment you try to use it.

## Previewing parameter effects on one image

Changing a processing parameter and re-running the full pipeline over every raw
image just to see whether it helped is slow. The **Preview** tab runs the pipeline
against **one** sample image instead, using the Configuration tab's *current*
values - including edits you haven't clicked **Save changes** on yet - so you can
tweak a parameter and re-preview in a few seconds without saving or running a full
batch job.

To use it: pick a sample image from the **Raw data explorer** tab (click
**Preview →** on any thumbnail), which switches you to the Preview tab with that
image selected. Click **Run preview** to see the segmented particles outlined on
the image, along with particle count and d50 for that one image - the status line
shows real progress as it runs (which pipeline step it's on, and for holo, how many
depth slices have rendered), since a preview can take anywhere from a few seconds
to around a minute. Adjust a parameter on the **Configuration** tab, switch back,
and click **Run preview** again - no need to save first, or pick the image again.

**For holo projects**, a depth slider also appears - drag it to see the raw
reconstruction at any depth in the sample volume, redrawn instantly with no extra
waiting, since every depth was already reconstructed as part of that one preview
run. This shows the raw reconstruction only, with no particle outlines - those are
on the separate "Detected particles" image above it. A project with a very fine
depth step (`stepZ`) will make that one preview run slower, since every depth is
reconstructed and rendered up front, with no limit on how many.

If your project's config includes a background-correction step, Preview runs it
for real - background correction needs several images to build up an estimate,
so Preview quietly gathers that many real raw images from elsewhere in your
project (preferring the ones just before your chosen sample, or nearby ones if
there aren't enough) to seed it, then runs your actual sample against the result.
Only if your project doesn't have enough other raw images to draw on at all does
Preview fall back to skipping background correction entirely for that run, shown
as a caveat under the result when it happens - treat that particular preview as a
rougher sanity check, not a stand-in for reviewing real results on the
**Results** tab after a full run.

## Reviewing results

The **Results** tab shows whatever's currently on disk for a processed project -
opening pyopia-gui on an already-processed project jumps here automatically.

**Generate montage** builds an image of the detected particles (not built
automatically, since it's a separate step); **Save montage as…** copies it to a
location of your choice. **Export size distribution as CSV…** saves the
diameter/particle-count bins behind the chart further down. **Export to
EcoTaxa…** bundles particle images and stats into a zip ready to import into
[EcoTaxa](https://ecotaxa.obs-vlfr.fr/). Both the montage and the EcoTaxa export
land in the project folder first (Docker can only write inside its own mounted
folder), then offer their own **Save as…** to copy elsewhere.

Further down: particle count, d50 (median particle size), and a size-distribution
chart.

**Filtering by aux data**: if the project's config sets
`steps.output.auxillary_data_file` (e.g. depth or temperature, interpolated onto
each image's timestamp during processing), a **Filter by** control appears above
the montage - pick a variable, set a min/max range, and click **Apply filter** to
restrict the montage, EcoTaxa export, and summary stats/chart to particles within
that range. A banner shows while a filter's active, with a **Clear filter** button
to revert. A filtered montage/EcoTaxa export is saved under its own `-filtered`
filename, so it doesn't overwrite the full-dataset one.

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
