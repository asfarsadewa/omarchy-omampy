"""Band models.

Each entry describes one position on the receiver's band switch. The numbers
are lifted from the shape of the real thing: medium wave is the wide, warm
broadcast band; shortwave is narrow, fady, and full of static; long wave is
muffled and hums with mains leakage. FM is the odd one out — it is the "off"
position for the whole effect chain, kept as a band so the UI can offer a
clean A/B without a separate bypass switch.

`dial_khz` is cosmetic: it feeds the tuning scale in the UI so the receiver
has a frequency to show. It is not used by any audio maths.
"""

from __future__ import annotations

# Order matters: it is the left-to-right order of the band switch, and the
# order `omampy band --next` cycles through.
ORDER = ("mw", "sw", "lw", "fm")

DEFAULT_MODE = "mw"

MODES = {
    "mw": {
        "label": "MW",
        "title": "Medium wave",
        "dial_khz": 1080.0,
        "dial_unit": "kHz",
        # Audible passband. AM broadcast is generously wide next to shortwave.
        "band": (200.0, 4500.0),
        "mono": True,
        "rate": 22050,
        # tanh soft-clip parameter — the transmitter running a little hot.
        "drive": 2.2,
        # High-shelf tilt in dB above `tilt_hz`; negative rolls the top off.
        "tilt_db": -3.0,
        "tilt_hz": 1500.0,
        # Slow amplitude drift, as the signal wanders in and out.
        "fade_depth": 0.18,
        "fade_rate": 0.12,
        # Noise bed ingredients.
        "hiss": 0.025,
        "crackle_rate": 1.5,
        "hum_hz": 0.0,
        "hum": 0.0,
    },
    "sw": {
        "label": "SW",
        "title": "Shortwave",
        "dial_khz": 9750.0,
        "dial_unit": "kHz",
        "band": (350.0, 2800.0),
        "mono": True,
        "rate": 22050,
        "drive": 3.0,
        "tilt_db": -5.0,
        "tilt_hz": 1500.0,
        "fade_depth": 0.45,
        "fade_rate": 0.17,
        "hiss": 0.05,
        "crackle_rate": 5.0,
        "hum_hz": 0.0,
        "hum": 0.0,
    },
    "lw": {
        "label": "LW",
        "title": "Long wave",
        "dial_khz": 198.0,
        "dial_unit": "kHz",
        "band": (150.0, 2000.0),
        "mono": True,
        "rate": 22050,
        "drive": 2.6,
        "tilt_db": -6.0,
        "tilt_hz": 1200.0,
        "fade_depth": 0.28,
        "fade_rate": 0.09,
        "hiss": 0.035,
        "crackle_rate": 2.5,
        # Long wave sets are famous for picking up the mains.
        "hum_hz": 50.0,
        "hum": 0.02,
    },
    "fm": {
        "label": "FM",
        "title": "Line in (clean)",
        "dial_khz": 98_500.0,
        "dial_unit": "kHz",
        "band": None,
        "mono": False,
        "rate": None,
        "drive": 0.0,
        "tilt_db": 0.0,
        "tilt_hz": 1500.0,
        "fade_depth": 0.0,
        "fade_rate": 0.0,
        "hiss": 0.0,
        "crackle_rate": 0.0,
        "hum_hz": 0.0,
        "hum": 0.0,
    },
}


class UnknownMode(ValueError):
    """Raised for a band name that is not on the switch."""


def normalize(name: str) -> str:
    """Canonicalise a user-supplied band name.

    Accepts any casing and the long spellings, so `--band Shortwave` and
    `--band SW` land in the same place.
    """
    key = str(name or "").strip().lower().replace(" ", "").replace("-", "")
    if key in MODES:
        return key
    aliases = {
        "mediumwave": "mw",
        "medium": "mw",
        "am": "mw",
        "broadcast": "mw",
        "shortwave": "sw",
        "short": "sw",
        "world": "sw",
        "longwave": "lw",
        "long": "lw",
        "clean": "fm",
        "off": "fm",
        "bypass": "fm",
        "line": "fm",
    }
    if key in aliases:
        return aliases[key]
    raise UnknownMode(
        "unknown band %r (expected one of: %s)" % (name, ", ".join(ORDER))
    )


def mode(name: str) -> dict:
    """Return the band model for `name`, resolving aliases."""
    return MODES[normalize(name)]


def is_clean(name: str) -> bool:
    """True when the band applies no radio colouring at all."""
    return mode(name)["band"] is None


def cycle(name: str, step: int = 1) -> str:
    """Move `step` positions along the band switch, wrapping at the ends."""
    idx = ORDER.index(normalize(name))
    return ORDER[(idx + int(step)) % len(ORDER)]


def dial_label(name: str) -> str:
    """Frequency readout for the tuning scale, e.g. ``1080 kHz``/``98.5 MHz``."""
    spec = mode(name)
    khz = float(spec["dial_khz"])
    if khz >= 10_000.0:
        return "%.1f MHz" % (khz / 1000.0)
    if khz >= 1000.0 and spec["label"] == "SW":
        return "%.2f MHz" % (khz / 1000.0)
    return "%g kHz" % khz
