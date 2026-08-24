# Manual testing checklist

A working checklist for exercising pyopia-gui by hand against real PyOPIA
projects - not a substitute for the automated test suite (`uv run pytest`),
but a way to check real end-to-end behaviour systematically instead of at
random. Update this alongside any UI/behaviour change, in the same pass as
the code.

## Getting sample data

- **Silcam**: use the **Create example project** button on the Project tab -
  it downloads a real 10-image example dataset for you, no separate setup
  needed.
- **Holo**: pyopia-gui doesn't have a one-click holo example yet - `init-project
  --example-data --instrument holo` currently still downloads silcam data on
  the pinned image (tracked as [pyopia-gui#7](https://github.com/nimmo-smith-technologies/pyopia-gui/issues/7),
  blocked on upstream PyOPIA sample-data work). In the meantime, get real holo
  images from [PyOPIA's own repo](https://github.com/SINTEF/pyopia): clone it,
  then point a project's folder at its `notebooks/holo_test_data_01/` images.
  Use the Configuration tab's **Generate default config…** with instrument
  type "holo" and a matching raw files pattern (e.g. `*.pgm`) to produce the
  `config.toml` itself - no need to hand-copy PyOPIA's own example config.

Start the dev server (`uv run pyopia-gui`) and work top to bottom.

## Project tab

- [ ] Folder field starts pre-filled with a sensible default; **Browse…**
      opens a working folder picker.
- [ ] **Create example project** against a fresh empty folder succeeds and
      switches to the Process tab.
- [ ] Pointing the folder field at an existing valid project enables
      Explorer/Configuration/Preview/Process; an invalid folder disables them.

## Raw data explorer

- [ ] Thumbnail grid loads for both demo projects; pagination (Previous/Next)
      works if a project has >12 raw files.
- [ ] **Refresh** re-converts thumbnails from scratch.
- [ ] Each thumbnail's **Preview →** switches to the Preview tab with that
      image selected.

## Configuration tab

- [ ] General fields (`raw_files`, `pixel_size`, `log_level`, `log_file`)
      show current values and save correctly.
- [ ] Per-step fields render with real descriptions (introspected from the
      pinned image); editing and saving a value round-trips into config.toml.
- [ ] **classifier** is the only step with an **Enable this step** switch;
      no other step shows one.
- [ ] On the silcam demo (broken classifier): switch it off, **Save
      changes** - config.toml gets a `[steps_disabled.classifier]` table, no
      active `[steps.classifier]`. A real **Run processing** afterwards
      succeeds (this used to crash with a Keras/model-path error).
- [ ] Switch classifier back on with `model_path` still blank, click **Save
      changes** - blocked with a clear message, config.toml unchanged.
- [ ] Fill in a real `model_path`, save - moves back to active
      `[steps.classifier]`.
- [ ] **Generate default config…**: checkbox unchecked by default for a
      project with no existing model path, checked if one already exists.
      Unchecked + Generate → classifier lands in `steps_disabled`, not
      broken. Checked with a blank path → blocked before submitting.
- [ ] Edit any field without saving → **Process tab** shows the "unsaved
      changes" warning. Click **Save changes** → warning disappears.
- [ ] Save changes on a project that already has results → stays on the
      Configuration tab (does *not* jump to Results).

## Preview tab

- [ ] No sample selected yet → prompt + "Go to Raw data explorer" shortcut;
      no **Run preview** button.
- [ ] Silcam demo, mid-dataset sample: **Run preview** shows status
      messages while running (not just a static spinner), then an overlay
      image with particles outlined in red and a plausible particle
      count/d50.
- [ ] Real background correction actually ran (no "⚠ Background correction
      was skipped" caveat) for a normal mid-dataset sample - and *also* for
      the very first/last raw file in the list (falls back to nearby files
      on the other side rather than skipping).
- [ ] Only when the whole dataset is too small for the configured
      `average_window` does the skip caveat actually appear.
- [ ] Edit a Configuration field *without* saving, return to Preview, rerun
      - the new value is reflected (proves it reads live widget state, not
      disk).
- [ ] Holo demo: depth slider appears, starts near the middle slice, shows a
      real depth label in mm. Dragging it redraws *instantly* (no spinner,
      no new log activity) - the actual zero-recompute guarantee.
- [ ] Holo "Detected particles" image shows real focused particle crops (not
      a raw hologram interference pattern); depth slices show dark particles
      on a bright background, with a visible border around both images.
- [ ] A deliberately-bad parameter (e.g. a nonsense threshold) surfaces a
      readable error, not a raw traceback.

## Process tab

- [ ] **Run processing** on a project with no pinned version yet prompts for
      a PyOPIA version; on one with existing results, shows the pinned
      version (with a newer-version note if applicable) before running.
- [ ] Real run streams log output live and finishes with a status/notify.
- [ ] A rerun clears stale Results content before the new run's own output
      appears.
- [ ] A persistent warning is visible on this tab explaining that the
      project's output folder gets cleared before each run.
- [ ] Toggle `steps.output.append` in Configuration and save, then run
      processing both ways:
      - `append = true` (default): run completes and shows real results with
        **no** "Merging results…" step at all (there's nothing to merge -
        `process` already wrote the combined file directly).
      - `append = false`: run shows a real "Merging results…" step, and
        still completes with correct results.
      Both must reach "Done" with real particle counts - neither should
      report a "Merging processed stats failed" error.
- [ ] Re-run a project with `append = false` twice in a row without changing
      `raw_files` - the second run's results should not be inflated by
      leftover per-image files from the first (processed/ is actually empty
      before each run, not just overwritten in place).

## Results tab

- [ ] Opening an already-processed project jumps here automatically and
      shows the pinned PyOPIA version, particle count, d50, and the
      size-distribution chart.
- [ ] If some raw images had zero detected particles, the summary line reads
      "N particles found across X of Y raw images (the rest had none
      detected)" - not just a bare "X images with detected particles" that
      could be misread as "only X of Y were processed".
- [ ] **Generate montage** / **Regenerate montage** produce a real montage
      image.

## Configuration tab - field round-tripping

- [ ] A step with an optional field that defaults to `None` (e.g. `output`'s
      `project_metadata_file`/`auxillary_data_file`) - if left blank, saving
      must **omit** the key from config.toml, not write `""`. (Confirmed
      real, serious bug found this way: PyOPIA's own `StatsToDisc` treats a
      blank string as "set", not "unset", and crashes trying to open it as a
      file path - every real processing run on a project silently failed at
      the output step until this was fixed.) Check by saving *any*
      unrelated field on a project that has one of these fields unset, then
      inspecting config.toml directly.
