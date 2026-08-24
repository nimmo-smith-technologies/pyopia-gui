# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Nimmo Smith Technologies Limited

"""Summary statistics for a PyOPIA project's own -STATS.nc output.

The functions below are adapted from SINTEF/pyopia's `pyopia/statistics.py` and
`pyopia/io.py` (commit 79ef4b08c8729718a399b6cd7b26b957d40dba62 on `main`),
licensed BSD-3-Clause - see THIRD_PARTY_LICENSES.md at the repo root for the
full license text and copyright notice.

PyOPIA's own Python library already has this logic, but none of it is exposed
via PyOPIA's CLI yet (only `process`/`merge-mfdata`/`make-montage`/etc. are
real subcommands) - see ADR 0007
(docs/decisions/0007-2026-08-14-vendor-pyopia-statistics-functions.md) for why
pyopia-gui vendors a local copy here instead of running this via Docker, and
the linked tracking issue for the plan to migrate to a real PyOPIA CLI command
once one exists, dropping this file.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
import xarray as xr


def load_stats_as_dataframe(stats_path: str) -> pd.DataFrame:
    """Load a project's own `-STATS.nc` file as a plain particle-level DataFrame."""
    with xr.open_dataset(stats_path, engine="h5netcdf") as xstats:
        return xstats.load().to_dataframe()


def get_size_bins() -> tuple[np.ndarray, np.ndarray]:
    """Log-spaced size bins for particle-size-distribution analysis (LISST-100x binning, 52 bins)."""
    bin_limits = np.zeros(53, dtype=np.float64)
    bin_limits[0] = 2.72 * 0.91
    for bin_number in np.arange(1, 53, 1):
        bin_limits[bin_number] = bin_limits[bin_number - 1] * 1.180

    dias = np.zeros(52, dtype=np.float64)
    dias[0] = 2.72
    for bin_number in np.arange(1, 52, 1):
        dias[bin_number] = dias[bin_number - 1] * 1.180

    return dias, bin_limits


def nd_from_stats(stats: pd.DataFrame, pixel_size: float) -> tuple[np.ndarray, np.ndarray]:
    """Number distribution (particle count per size bin) from a project's stats."""
    ecd = stats["equivalent_diameter"] * pixel_size
    ecd = ecd[~np.isnan(ecd.values)]

    dias, bin_limits_um = get_size_bins()
    number_distribution, _ = np.histogram(ecd, bin_limits_um)

    return dias, np.float64(number_distribution)


def vd_from_nd(number_distribution: np.ndarray, dias: np.ndarray, sample_volume: float = 1.0) -> np.ndarray:
    """Volume distribution (micro-litres per sample volume) from a number distribution."""
    dias_m = dias * 1e-6  # microns -> metres
    particle_volume = 4 / 3 * np.pi * (dias_m / 2) ** 3  # m^3
    total_particle_volume = particle_volume * number_distribution * 1e9  # micro-litres
    return total_particle_volume / sample_volume


def vd_from_stats(stats: pd.DataFrame, pixel_size: float) -> tuple[np.ndarray, np.ndarray]:
    """Volume distribution (micro-litres per sample volume) from a project's stats."""
    dias, number_distribution = nd_from_stats(stats, pixel_size)
    return dias, vd_from_nd(number_distribution, dias)


def d50_from_vd(volume_distribution: np.ndarray, dias: np.ndarray) -> float:
    """Median particle size (d50, in microns) from a volume distribution."""
    cumulative_vd = np.cumsum(volume_distribution / np.sum(volume_distribution))
    return float(np.interp(0.5, cumulative_vd, dias))


def d50_from_stats(stats: pd.DataFrame, pixel_size: float) -> float:
    """Median particle size (d50, in microns) from a project's stats."""
    dias, volume_distribution = vd_from_stats(stats, pixel_size)
    return d50_from_vd(volume_distribution, dias)


def count_images_in_stats(stats: pd.DataFrame) -> int:
    """Number of raw images that produced at least one detected particle.

    Not the total number of images processed - an image with zero detections
    contributes no rows here and is invisible to this count.
    """
    return len(pd.to_datetime(stats["timestamp"]).unique())


@dataclass
class StatsSummary:
    particle_count: int
    images_with_particles: int
    d50_microns: float
    dias: np.ndarray
    number_distribution: np.ndarray


def summarize(
    stats_path: str, pixel_size: float, aux_filter: tuple[str, float, float] | None = None
) -> StatsSummary:
    """Compute the Results tab's summary statistics from a project's own -STATS.nc file.

    `aux_filter`, if given, is an (aux column name, min, max) tuple - e.g.
    `("depth", 1.5, 10.0")` - restricting the summary to particles whose value for
    that column (see `docker_client.aux_data_columns`) falls within `[min, max]`,
    the same restriction `docker_client.make_montage_command`'s own `filter_variable`
    applies for the montage, so the two stay consistent with each other.

    Raises on any read/schema failure (e.g. a stats file from an incompatible PyOPIA
    version, or one still being written by a concurrent run) - the caller is
    responsible for turning that into a plain-language message, same as other
    Docker/file-based failures in this app.
    """
    stats = load_stats_as_dataframe(stats_path)
    if aux_filter is not None:
        column, low, high = aux_filter
        stats = stats[stats[column].between(low, high)]
    dias, number_distribution = nd_from_stats(stats, pixel_size)
    volume_distribution = vd_from_nd(number_distribution, dias)
    return StatsSummary(
        particle_count=len(stats),
        images_with_particles=count_images_in_stats(stats),
        d50_microns=d50_from_vd(volume_distribution, dias),
        dias=dias,
        number_distribution=number_distribution,
    )
