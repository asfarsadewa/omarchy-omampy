"""Reading the spectrum back out of the filter graph.

The probe merges the audible signal and its band-split copies into one wide
frame, so a single `astats` measures everything at once and mpv hands the
result back on `af-metadata/omampy` as flat strings:

    {"lavfi.astats.1.RMS_level": "-27.53",   # the signal itself
     "lavfi.astats.2.RMS_level": "-31.77",   # band 1 (lowest)
     ...}

This module turns that dictionary into normalised 0..1 bar heights: parse,
clamp the dB range, tilt the top end up so music does not look like a slope,
and smooth with a fast attack and slow decay so bars snap to a beat and fall
back like a real VU. All of it is pure — no sockets here.
"""

from __future__ import annotations

import math
import re
from typing import Iterable

# Everything below the floor is silence, everything above the ceiling is
# pinned. The window is deliberately narrow: the signal has already been
# compressed and limited by the time the probe sees it.
DB_FLOOR = -62.0
DB_CEIL = -14.0

# Music loses roughly 3 dB per octave going up, so without a tilt the right
# half of the spectrum never moves. This is a straight ramp in dB applied
# across the bands, lowest to highest.
DEFAULT_TILT_DB = 14.0

SILENT = float("-inf")

_RMS_KEY_RE = re.compile(r"^lavfi\.astats\.(\d+)\.RMS_level$")


def to_db(value) -> float:
    """Parse one astats reading, mapping every spelling of silence to -inf."""
    if isinstance(value, (int, float)):
        number = float(value)
        return SILENT if math.isnan(number) or math.isinf(number) and number > 0 else number
    text = str(value).strip().lower()
    if text in ("-inf", "-infinity"):
        return SILENT
    try:
        number = float(text)
    except ValueError:
        return SILENT
    if math.isnan(number) or math.isinf(number):
        return SILENT
    return number


def parse_channels(metadata) -> dict[int, float]:
    """Pull `{channel_number: dB}` out of an af-metadata payload.

    Channel numbers are astats' own 1-based indices. Keys that are not RMS
    readings — astats emits plenty of others when asked — are ignored.
    """
    out: dict[int, float] = {}
    if not isinstance(metadata, dict):
        return out
    for key, value in metadata.items():
        match = _RMS_KEY_RE.match(str(key))
        if match:
            out[int(match.group(1))] = to_db(value)
    return out


def split_levels(metadata, band_count: int, keep_channels: int = 1) -> tuple[float, list[float]]:
    """Separate the signal reading from the per-band readings.

    Returns `(signal_db, band_dbs)`. The first `keep_channels` channels are
    the audible signal (mono or stereo); the bands follow, lowest first.
    Missing channels read as silence rather than raising, so a frame that
    arrives mid-reconfigure just renders as an empty display.
    """
    if band_count < 1:
        raise ValueError("band_count must be >= 1")
    if keep_channels < 1:
        raise ValueError("keep_channels must be >= 1")
    channels = parse_channels(metadata)
    signal = max((channels.get(i + 1, SILENT) for i in range(keep_channels)), default=SILENT)
    bands = [channels.get(keep_channels + i + 1, SILENT) for i in range(band_count)]
    return signal, bands


def tilt_gains(bands: int, amount_db: float = DEFAULT_TILT_DB) -> list[float]:
    """Per-band dB boost, zero at the bottom rising to `amount_db` at the top."""
    if bands < 1:
        raise ValueError("bands must be >= 1")
    if bands == 1:
        return [0.0]
    return [amount_db * i / (bands - 1) for i in range(bands)]


def db_to_unit(db: float, floor: float = DB_FLOOR, ceil: float = DB_CEIL) -> float:
    """Map a dB level onto 0..1, clamped at both ends."""
    if ceil <= floor:
        raise ValueError("ceil must be above floor")
    if db == float("-inf") or math.isnan(db):
        return 0.0
    return max(0.0, min(1.0, (db - floor) / (ceil - floor)))


def normalize(levels: Iterable[float], *, floor: float = DB_FLOOR,
              ceil: float = DB_CEIL, tilt_db: float = DEFAULT_TILT_DB) -> list[float]:
    """Turn one frame of dB readings into tilted 0..1 bar heights."""
    values = list(levels)
    gains = tilt_gains(len(values), tilt_db) if values else []
    return [db_to_unit(db + gain, floor, ceil) for db, gain in zip(values, gains)]


class Smoother:
    """Fast-attack, slow-decay envelope per band, with falling peak markers.

    `attack` and `decay` are the fraction of the remaining distance covered
    per update — 1.0 is instant, 0.0 never moves.
    """

    def __init__(self, bands: int, *, attack: float = 0.6, decay: float = 0.18,
                 peak_decay: float = 0.03):
        if bands < 1:
            raise ValueError("bands must be >= 1")
        for name, value in (("attack", attack), ("decay", decay), ("peak_decay", peak_decay)):
            if not 0.0 <= value <= 1.0:
                raise ValueError("%s must be within 0..1, got %r" % (name, value))
        self.bands = int(bands)
        self.attack = float(attack)
        self.decay = float(decay)
        self.peak_decay = float(peak_decay)
        self.values = [0.0] * self.bands
        self.peaks = [0.0] * self.bands

    def update(self, targets: Iterable[float]) -> list[float]:
        """Step the envelopes toward `targets` and return the new values."""
        incoming = list(targets)
        for i in range(self.bands):
            target = incoming[i] if i < len(incoming) else 0.0
            target = max(0.0, min(1.0, target))
            current = self.values[i]
            rate = self.attack if target > current else self.decay
            current += (target - current) * rate
            # Snap tiny residuals to zero so a stopped player renders as an
            # empty console instead of a row of stuck one-pixel bars.
            self.values[i] = 0.0 if current < 1e-4 else current
            if self.values[i] >= self.peaks[i]:
                self.peaks[i] = self.values[i]
            else:
                self.peaks[i] = max(self.values[i], self.peaks[i] - self.peak_decay)
        return list(self.values)

    def silence(self) -> list[float]:
        """Decay toward zero — used while paused or between tracks."""
        return self.update([0.0] * self.bands)
