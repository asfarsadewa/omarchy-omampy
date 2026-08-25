"""Synthesise the static.

ffmpeg can band-limit and saturate in real time but it has no good way to
produce Poisson-distributed crackle, so the noise bed is generated here, in
plain Python, written to a WAV once, cached, and then looped into the graph by
`amovie`. Doing it this way keeps the interesting part — the statistics of the
noise — in code that a test can pin down, and costs nothing at playback time.

A bed is fully determined by (band, intensity, seed, seconds, rate). The same
inputs always produce byte-identical audio, which is what makes the cache safe
and the tests meaningful.
"""

from __future__ import annotations

import array
import hashlib
import math
import os
import random
import wave

from . import modes

BED_SECONDS = 12.0
BED_RATE = 22050
# Length of the loop crossfade. Long enough to hide the seam in broadband
# noise, short enough not to eat a crackle whole.
LOOP_FADE_SECONDS = 0.25
PEAK = 0.9
DEFAULT_SEED = 1980

# The bed is regenerated per intensity step, so intensity is quantised to keep
# the cache to a handful of files per band instead of one per slider pixel.
INTENSITY_STEPS = 10


def quantize_intensity(intensity: float) -> float:
    """Snap intensity to the grid the bed cache is keyed on.

    Halves round up rather than to even: a slider sitting exactly between two
    steps should not land on a different one depending on which pair it is
    between.
    """
    value = max(0.0, min(1.0, float(intensity)))
    step = math.floor(value * INTENSITY_STEPS + 0.5)
    return round(step / INTENSITY_STEPS, 3)


def _one_pole_highpass(samples: list[float], rate: int, cutoff: float) -> None:
    """In-place single-pole high-pass. Gentle on purpose: the steep skirts are
    the audible chain's job, this only stops the hiss sounding like rumble."""
    if cutoff <= 0:
        return
    a = math.exp(-2.0 * math.pi * cutoff / rate)
    prev_in = 0.0
    prev_out = 0.0
    for i, x in enumerate(samples):
        y = a * (prev_out + x - prev_in)
        prev_in = x
        prev_out = y
        samples[i] = y


def _one_pole_lowpass(samples: list[float], rate: int, cutoff: float) -> None:
    """In-place single-pole low-pass."""
    if cutoff <= 0 or cutoff >= rate / 2:
        return
    a = 1.0 - math.exp(-2.0 * math.pi * cutoff / rate)
    state = 0.0
    for i, x in enumerate(samples):
        state += a * (x - state)
        samples[i] = state


def _normalize(samples: list[float], peak: float = PEAK) -> None:
    """Scale in place so the loudest sample sits at `peak`."""
    loudest = 0.0
    for x in samples:
        if x > loudest:
            loudest = x
        elif -x > loudest:
            loudest = -x
    if loudest <= 0.0:
        return
    gain = peak / loudest
    for i in range(len(samples)):
        samples[i] *= gain


def _loop_crossfade(samples: list[float], fade_len: int) -> list[float]:
    """Fold the tail back over the head so the WAV loops without a click.

    The returned buffer is `fade_len` samples shorter than the input: the tail
    is not appended, it is mixed into the opening, so playing the result on
    repeat is continuous.
    """
    n = len(samples)
    if fade_len <= 0 or n <= fade_len * 2:
        return list(samples)
    body = samples[: n - fade_len]
    tail = samples[n - fade_len :]
    for i in range(fade_len):
        # Equal-power crossfade: constant noise energy across the seam, where
        # a linear fade would dip audibly.
        t = (i + 0.5) / fade_len
        body[i] = body[i] * math.sin(t * math.pi / 2) + tail[i] * math.cos(t * math.pi / 2)
    return body


def seamless_frequency(hz: float, seconds: float) -> float:
    """Nudge `hz` to the nearest frequency with a whole number of cycles.

    A hum that does not close its last cycle clicks once per loop, which is
    exactly the artefact the hum is meant to replace.
    """
    if hz <= 0 or seconds <= 0:
        return 0.0
    cycles = max(1, round(hz * seconds))
    return cycles / seconds


def generate(band_name: str, intensity: float, *, seed: int = DEFAULT_SEED,
             seconds: float = BED_SECONDS, rate: int = BED_RATE) -> list[float]:
    """Build one loopable noise bed as floats in -1..1.

    Returns an empty list for a band that has no static (FM) or an intensity
    of zero — the caller then simply omits the bed from the graph.
    """
    spec = modes.mode(band_name)
    intensity = quantize_intensity(intensity)
    if spec["band"] is None or intensity <= 0.0:
        return []

    # A composite string seed so that changing band or intensity gives a
    # genuinely different bed rather than a shifted copy of the same one.
    rng = random.Random("omampy|%d|%s|%.3f" % (int(seed), modes.normalize(band_name), intensity))
    low, high = spec["band"]
    n = int(round(seconds * rate))
    if n <= 0:
        return []

    # --- hiss: white noise squeezed into the band the receiver can pass
    samples = [rng.gauss(0.0, 1.0) for _ in range(n)]
    _one_pole_highpass(samples, rate, low)
    _one_pole_lowpass(samples, rate, high)
    _normalize(samples, 1.0)
    hiss_level = spec["hiss"]
    for i in range(n):
        samples[i] *= hiss_level

    # --- crackle: sparse exponential bursts, Poisson-ish in time. Both the
    # rate and the reach scale with intensity, so turning the knob up makes
    # the band sound further away rather than merely louder.
    burst_count = int(spec["crackle_rate"] * seconds * intensity)
    for _ in range(burst_count):
        start = rng.randrange(n)
        length = max(8, int(rate * rng.uniform(0.004, 0.022)))
        amplitude = rng.uniform(0.4, 1.0)
        for k in range(length):
            idx = start + k
            if idx >= n:
                break
            samples[idx] += amplitude * math.exp(-6.0 * k / length) * rng.gauss(0.0, 1.0)

    fade_len = int(round(LOOP_FADE_SECONDS * rate))
    samples = _loop_crossfade(samples, fade_len)

    # --- mains hum, added after the crossfade so its period divides the final
    # loop length exactly.
    if spec["hum"] > 0 and spec["hum_hz"] > 0:
        final_seconds = len(samples) / rate
        hz = seamless_frequency(spec["hum_hz"], final_seconds)
        level = spec["hum"] * intensity
        step = 2.0 * math.pi * hz / rate
        for i in range(len(samples)):
            samples[i] += level * math.sin(step * i)

    _normalize(samples, PEAK)
    return samples


def to_pcm16(samples: list[float]) -> array.array:
    """Convert floats to clipped signed 16-bit PCM."""
    out = array.array("h", bytes(2 * len(samples)))
    for i, x in enumerate(samples):
        v = int(x * 32767.0)
        out[i] = -32767 if v < -32767 else (32767 if v > 32767 else v)
    return out


def write_wav(path: str, samples: list[float], rate: int = BED_RATE) -> str:
    """Write a mono 16-bit WAV, atomically, and return the path."""
    pcm = to_pcm16(samples)
    tmp = path + ".partial"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with wave.open(tmp, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(rate))
        handle.writeframes(pcm.tobytes())
    os.replace(tmp, path)
    return path


def bed_filename(band_name: str, intensity: float, *, seed: int = DEFAULT_SEED,
                 seconds: float = BED_SECONDS, rate: int = BED_RATE) -> str:
    """Cache filename for a bed. Same inputs, same name, forever."""
    band = modes.normalize(band_name)
    key = "%s|%.3f|%d|%.3f|%d|v1" % (band, quantize_intensity(intensity), int(seed),
                                     float(seconds), int(rate))
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    return "bed-%s-%s.wav" % (band, digest)


def ensure(cache_dir: str, band_name: str, intensity: float, *,
           seed: int = DEFAULT_SEED, seconds: float = BED_SECONDS,
           rate: int = BED_RATE) -> str | None:
    """Return a path to the bed for these settings, generating it if needed.

    Returns None when the band has no static to add, which the graph builder
    reads as "leave the bed out".
    """
    spec = modes.mode(band_name)
    if spec["band"] is None or quantize_intensity(intensity) <= 0.0:
        return None
    path = os.path.join(cache_dir, bed_filename(band_name, intensity, seed=seed,
                                                seconds=seconds, rate=rate))
    if os.path.exists(path) and os.path.getsize(path) > 44:
        return path
    samples = generate(band_name, intensity, seed=seed, seconds=seconds, rate=rate)
    if not samples:
        return None
    return write_wav(path, samples, rate)
