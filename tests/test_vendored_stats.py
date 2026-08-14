# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Nimmo Smith Technologies Limited

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from pyopia_gui import vendored_stats


def test_get_size_bins_returns_ascending_bins() -> None:
    dias, bin_limits = vendored_stats.get_size_bins()

    assert len(dias) == 52
    assert len(bin_limits) == 53
    assert np.all(np.diff(dias) > 0)
    assert np.all(np.diff(bin_limits) > 0)


def test_nd_from_stats_counts_particles_into_size_bins() -> None:
    # Two particles at pixel_size=1 land at equivalent_diameter 2.72 and 3.21 microns -
    # both inside the smallest size bin (limit ~2.48-2.92um) and the next one up.
    stats = pd.DataFrame({"equivalent_diameter": [2.72, 3.21, np.nan]})

    dias, number_distribution = vendored_stats.nd_from_stats(stats, pixel_size=1.0)

    assert dias[0] == 2.72
    assert number_distribution.sum() == 2  # the nan is dropped, not counted


def test_vd_from_nd_computes_sphere_volume() -> None:
    # A single 2-micron-diameter particle: volume = (4/3)*pi*(1e-6m)^3 = ~4.19e-18 m^3,
    # converted to micro-litres (*1e9) and divided by the default sample_volume=1.0.
    dias = np.array([2.0])
    number_distribution = np.array([1.0])

    volume_distribution = vendored_stats.vd_from_nd(number_distribution, dias)

    expected_microlitres = (4 / 3 * np.pi * (1e-6) ** 3) * 1e9
    assert volume_distribution[0] == pytest.approx(expected_microlitres, rel=1e-6)


def test_d50_from_vd_interpolates_median() -> None:
    # Three equal-volume bins - cumulative sum is [1/3, 2/3, 1.0]. 0.5 falls halfway
    # between the first two points (10, 1/3) and (20, 2/3), so linear interpolation
    # gives 15.0, not the midpoint bin's own dias value.
    dias = np.array([10.0, 20.0, 30.0])
    volume_distribution = np.array([1.0, 1.0, 1.0])

    d50 = vendored_stats.d50_from_vd(volume_distribution, dias)

    assert d50 == 15.0


def test_count_images_in_stats_counts_unique_timestamps() -> None:
    stats = pd.DataFrame({"timestamp": ["2026-01-01T00:00:00", "2026-01-01T00:00:00", "2026-01-01T00:00:01"]})

    assert vendored_stats.count_images_in_stats(stats) == 2


def test_summarize_reads_a_real_stats_file_end_to_end(tmp_path: Path) -> None:
    # A minimal but real -STATS.nc file, written the same way PyOPIA's own output is
    # shaped (root-group dataset, one row per detected particle) - exercises the real
    # xarray/h5netcdf read path, not just the pure-numpy/pandas functions above.
    stats_path = tmp_path / "demo-STATS.nc"
    dataset = xr.Dataset(
        {
            "equivalent_diameter": ("index", [2.72, 3.21, 4.0]),
            "timestamp": ("index", pd.to_datetime(["2026-01-01T00:00:00"] * 3)),
        },
        coords={"index": [0, 1, 2]},
    )
    dataset.to_netcdf(stats_path, engine="h5netcdf")

    summary = vendored_stats.summarize(str(stats_path), pixel_size=1.0)

    assert summary.particle_count == 3
    assert summary.images_with_particles == 1
    assert summary.d50_microns > 0
    assert summary.number_distribution.sum() == 3
