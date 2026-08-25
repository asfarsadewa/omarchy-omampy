"""The libavfilter graph that turns a track into a broadcast.

mpv is handed one `--af=@omampy:lavfi=[...]` graph and does everything in real
time. The graph has two halves:

  * the signal path — downmix, band-limit, soft-clip, fade, mix the noise bed,
    level it, and hand it to the speakers;
  * the probe — the finished audio is split into N bands, and those bands are
    merged *alongside* an untouched copy of the signal into one wide frame so
    that `astats` can measure them all at once. A final `pan` selects the
    untouched channels back out, so the probe is inaudible. Because the
    measurement rides the filter's own output frames, mpv exposes it on
    `af-metadata/omampy` over the IPC socket we already hold — no fifo, no
    second file descriptor, and nothing that can stall the audio thread if
    the UI goes away.

Everything here is a pure string builder, so the graph can be asserted on in
tests without going near an audio device.
"""

from __future__ import annotations

from . import modes

# mpv filter label. `af-metadata/<label>` and `af set @<label>:...` both key
# off it, so it has to stay stable across a band switch.
FILTER_LABEL = "omampy"

# Sample format the probe forces before `amerge`. Without an explicit
# `aformat` on every branch libavfilter cannot pick a common layout and the
# whole graph fails to configure.
PROBE_FORMAT = "sample_fmts=fltp:channel_layouts=mono"

# Each `highpass`/`lowpass` is 2 poles; three in series give the 6-pole
# skirts the offline renderer used.
BAND_STAGES = 3

DEFAULT_METER_BANDS = 14

# Analysis range for the spectrum when the band itself is unlimited (FM).
CLEAN_ANALYSIS_RANGE = (60.0, 10_000.0)


# libavfilter unescapes twice on the way in: once when the graph is split
# into filters, and again when a filter splits its own arguments. Escaping
# has to be applied in that same order, innermost first, or a path with a
# colon in it silently truncates.
_ARG_SPECIALS = "\\':"
_GRAPH_SPECIALS = "\\[],;"


def _escape_level(text: str, specials: str) -> str:
    return "".join("\\" + ch if ch in specials else ch for ch in text)


def escape_value(value: str) -> str:
    """Escape a string for use as a filter argument inside a filtergraph.

    Verified against ffmpeg for the characters that turn up in real paths —
    colons, commas, brackets, and spaces. Quotes and backslashes are escaped
    too, but libavfilter's quoting rules make them unreliable at any depth,
    so `config.filter_safe` keeps them out of generated paths in the first
    place rather than trusting this to carry them.
    """
    return _escape_level(_escape_level(str(value), _ARG_SPECIALS), _GRAPH_SPECIALS)


def band_edges(low: float, high: float, count: int) -> list[tuple[float, float]]:
    """Split `low`..`high` into `count` logarithmically spaced bands.

    Log spacing is what makes a spectrum look like music rather than a single
    blob on the left. The lowest band is opened down to DC so nothing below
    `low` is lost — that is where the kick lives.
    """
    if count < 1:
        raise ValueError("count must be >= 1")
    if not (0 < low < high):
        raise ValueError("need 0 < low < high, got low=%r high=%r" % (low, high))
    ratio = (high / low) ** (1.0 / count)
    edges = [low * (ratio ** i) for i in range(count + 1)]
    bands = [(edges[i], edges[i + 1]) for i in range(count)]
    bands[0] = (0.0, bands[0][1])
    return bands


def analysis_range(band_name: str) -> tuple[float, float]:
    """The frequency span the spectrum should cover for a given band."""
    spec = modes.mode(band_name)
    if spec["band"] is None:
        return CLEAN_ANALYSIS_RANGE
    low, high = spec["band"]
    return (max(40.0, low * 0.5), high)


def keep_channels(band_name: str) -> int:
    """How many channels the audible signal occupies inside the probe merge.

    The probe measures `astats` channel 1..keep for the signal itself and the
    bands after that, so the reader needs this to find where the bands start.
    """
    return 1 if modes.mode(band_name)["mono"] else 2


def clamp_intensity(value) -> float:
    """Coerce anything user-supplied into the 0..1 the chain expects."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise ValueError("intensity must be a number, got %r" % (value,))
    if f != f:  # NaN
        raise ValueError("intensity must be a number, got NaN")
    return max(0.0, min(1.0, f))


def _repeat(filter_expr: str, times: int) -> list[str]:
    return [filter_expr] * max(0, int(times))


def signal_filters(band_name: str, intensity: float) -> list[str]:
    """The audible colouring, in order, for one band at one intensity.

    Returns an empty list for a band that does nothing (FM), which is what
    lets the caller collapse the graph down to a pass-through.
    """
    spec = modes.mode(band_name)
    intensity = clamp_intensity(intensity)
    out: list[str] = []

    if spec["mono"]:
        # `aformat` alone cannot downmix; aresample (auto-inserted by
        # libavfilter for a layout change) can, and handles mono sources too.
        out.append("aresample=%d" % int(spec["rate"]))
        out.append("aformat=sample_fmts=fltp:channel_layouts=mono")

    if spec["tilt_db"]:
        out.append("treble=f=%g:g=%g" % (spec["tilt_hz"], spec["tilt_db"]))

    if spec["band"] is not None:
        low, high = spec["band"]
        out.extend(_repeat("highpass=f=%g:p=2" % low, BAND_STAGES))
        out.extend(_repeat("lowpass=f=%g:p=2" % high, BAND_STAGES))

    if spec["drive"] > 1.0:
        out.append("asoftclip=type=tanh:param=%g" % spec["drive"])

    fade = spec["fade_depth"] * intensity
    if fade > 0.001:
        # `tremolo` will not go below 0.1 Hz; a slower drift than that reads
        # as no drift at all over a three-minute track anyway.
        out.append("tremolo=f=%g:d=%g" % (max(0.1, spec["fade_rate"]), min(1.0, fade)))

    return out


def bed_weight(band_name: str, intensity: float) -> float:
    """Mix level for the noise bed, 0 when the band or intensity silences it."""
    spec = modes.mode(band_name)
    intensity = clamp_intensity(intensity)
    if spec["band"] is None:
        return 0.0
    # The bed is peak-normalised at generation time, so this is the only place
    # its loudness is decided. 0.55 at full intensity sits under the music
    # without burying it.
    return round(0.55 * intensity, 4)


def probe_graph(pad_in: str, pad_out: str, bands: list[tuple[float, float]],
                channels: int) -> str:
    """Build the metering section: split, band-filter, merge, measure, unmerge.

    `channels` is the channel count of the audible signal, which is preserved
    exactly — the bands are extra channels that `pan` drops on the way out.
    """
    if not bands:
        raise ValueError("probe needs at least one band")
    if channels not in (1, 2):
        raise ValueError("probe supports mono or stereo signal, got %r" % channels)
    count = len(bands)
    parts = ["[%s]asplit=2[keep][probe]" % pad_in,
             "[probe]asplit=%d%s" % (count, "".join("[pb%d]" % i for i in range(count)))]
    for i, (low, high) in enumerate(bands):
        stage = []
        if low > 0:
            stage.append("highpass=f=%g:p=2" % low)
        stage.append("lowpass=f=%g:p=2" % high)
        stage.append("aformat=" + PROBE_FORMAT)
        parts.append("[pb%d]%s[pm%d]" % (i, ",".join(stage), i))

    layout = "mono" if channels == 1 else "stereo"
    # Selecting the kept channels back out by index is what makes the probe
    # bit-exact rather than a reconstruction from the bands.
    selector = "|".join("c%d=c%d" % (c, c) for c in range(channels))
    parts.append(
        "[keep]"
        + "".join("[pm%d]" % i for i in range(count))
        + "amerge=inputs=%d," % (count + 1)
        + "astats=metadata=1:reset=1:measure_overall=none:measure_perchannel=RMS_level,"
        + "pan=%s|%s[%s]" % (layout, selector, pad_out)
    )
    return ";".join(parts)


def build_graph(
    band_name: str,
    intensity: float,
    *,
    bed_path: str | None = None,
    meter_bands: int = DEFAULT_METER_BANDS,
) -> str:
    """Assemble the whole graph for one band at one intensity.

    `bed_path` is optional — without it the static is dropped. `meter_bands`
    of 0 omits the probe entirely, which is what `omampy chain --no-meter`
    prints when you only want to hear the effect.
    """
    intensity = clamp_intensity(intensity)
    chain = signal_filters(band_name, intensity)
    weight = bed_weight(band_name, intensity)
    use_bed = bool(bed_path) and weight > 0.0
    meter_bands = max(0, int(meter_bands))

    sections: list[str] = []

    if use_bed:
        sections.append("[in]" + ",".join(chain or ["anull"]) + "[sig]")
        sections.append(
            "amovie=%s:loop=0,volume=%g,aformat=%s[bed]"
            % (escape_value(bed_path), weight, PROBE_FORMAT)
        )
        # Riding gain after the static is added stops a crackle spiking the
        # output, and pushes the whole thing to that flat broadcast level.
        sections.append(
            "[sig][bed]amix=inputs=2:duration=first:normalize=0:weights=1 1,"
            "acompressor=threshold=0.5:ratio=3:attack=5:release=180:makeup=1.4,"
            "alimiter=limit=0.95[body]"
        )
    elif chain:
        sections.append("[in]" + ",".join(chain) + "[body]")
    elif meter_bands < 1:
        return "[in]anull[out]"
    else:
        sections.append("[in]anull[body]")

    if meter_bands < 1:
        sections.append("[body]anull[out]")
        return ";".join(sections)

    low, high = analysis_range(band_name)
    sections.append(probe_graph("body", "out", band_edges(low, high, meter_bands),
                                keep_channels(band_name)))
    return ";".join(sections)


def af_argument(graph: str, label: str = FILTER_LABEL) -> str:
    """Wrap a graph the way mpv's `--af` and `af set` expect it."""
    return "@%s:lavfi=[%s]" % (label, graph)
