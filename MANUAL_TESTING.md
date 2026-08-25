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
- [ ] Tick a few individual thumbnails (in any order) and click **Use
      selected as raw_files** - a "Filtered to N of M raw image(s)" banner
      appears, and `raw_files_subset.txt` lists them in chronological
      (dataset) order, not click order.
- [ ] **Select all on this page** ticks every thumbnail on the current page;
      **Clear selection** unticks all (including ones selected on a previous
      page).
- [ ] **Clear subset** (shown in the banner) restores `general.raw_files` to
      its original pattern and removes `raw_files_subset.txt`.

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
      changes** - blocked with a clear message ("leaving model_path blank
      doesn't work here"), config.toml unchanged. This is a real Docker call
      (actually attempts constructing the class), not a guess from the field's
      default value alone - takes a couple of seconds, not instant.
- [ ] With `model_path` still blank (not saved), pick a sample and click
      **Run preview** on the Preview tab - blocked the same way, before any
      container even starts (status stays "Ready", no "Running preview…").
- [ ] Fill in a real `model_path`, save - moves back to active
      `[steps.classifier]`, and this save is instant again (no blank
      None-defaulting field left to verify).
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
- [ ] Set **Processors to use** above 1 - **Chunking strategy** becomes
      enabled (disabled again back at 1). With `append = true` still set,
      **Run processing** is refused with a clear notify *before* clearing the
      output folder (existing results must survive the refusal). Set
      `append = false` and rerun - completes normally with `--num-chunks`/
      `--strategy` in the logged command, and correct results.

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
- [ ] **Save montage as…** opens a folder-browsing dialog (starting at the
      project folder), navigating into a subfolder works, and **Save here**
      actually copies the file there.
- [ ] **Export size distribution as CSV…** writes a real CSV (header row
      `diameter_um,particle_count`, one row per bin) to the chosen location.
- [ ] **Export to EcoTaxa…** produces a real zip (particle PNGs +
      `ecotaxa_particle_statistics.tsv`); **Save EcoTaxa export as…** copies
      it elsewhere.
- [ ] On a project with `steps.output.auxillary_data_file` configured, a
      **Filter by** control appears with the declared aux column(s) (e.g.
      `depth`); on one without, it doesn't appear at all.
- [ ] Enter a real min/max and click **Apply filter** - particle count, d50,
      and the chart all narrow to match; a "Filtered to particles with ..."
      banner appears with a **Clear filter** button.
- [ ] With a filter active, **Generate montage** and **Export to EcoTaxa…**
      write to `montage-filtered.png`/`ecotaxa_export-filtered.zip` (not the
      unfiltered filenames) and contain only the filtered particle count.
- [ ] **Clear filter** reverts particle count/d50/chart back to the full
      dataset.
- [ ] Leaving Min or Max blank, or Min greater than Max, refuses **Apply
      filter** with a clear message instead of running anything.

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
- [ ] Same, but for a field whose real default is **not** `None` (e.g.
      `load`'s `image_format`, which defaults to `'infer'`) - blank must
      still be **omitted**, not written as `""`. (Confirmed real, serious
      bug found this way too: a blank `image_format` written as `""` isn't
      the same as PyOPIA's own `'infer'` default - `SilCamLoad` doesn't
      special-case an empty string, so every image failed to load until
      this was fixed.)
- [ ] A blank **required** field (no real default at all) on an
      order-sensitive step (i.e. one with no Enable switch, e.g. `output`'s
      `output_datafile`) blocks **Save changes** with a clear message,
      same as it already does for a toggleable step like `classifier` -
      config.toml stays unchanged. (Previously only toggleable steps were
      checked at all; a blank required field on any other step saved
      silently, and a blank *number* field would crash the save outright
      since TOML has no null type.)
- [ ] A blank field whose own default is `None` (e.g. `classifier`'s
      `model_path`) is only safe to omit if PyOPIA's own class actually
      tolerates it - `has_default=True`/`default=None` looks identical for
      `model_path` (crashes without it) and `project_metadata_file` (fine
      without it) from introspection alone, so this can't be told apart by
      guessing. Saving/previewing a step with one of these fields blank now
      makes one real Docker call to actually attempt construction and
      catches the difference for real - see "On the silcam demo" above for
      the concrete repro.
