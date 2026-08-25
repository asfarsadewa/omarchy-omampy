"""OMAMPY — a retro AM/SW radio player for the Omarchy shell.

The package is deliberately dependency-free: every module below is importable
with a stock CPython 3.11+ and no site-packages at all. All heavy lifting —
decoding, resampling, filtering, playback — is delegated to ``mpv``, which
Omarchy already ships. What lives here is the part worth testing: the band
models, the libavfilter graph we hand to mpv, the noise bed we synthesise, the
metering maths, and the block-glyph rendering that draws the console.
"""

__version__ = "0.1.0"

APP_NAME = "omampy"
PLUGIN_ID = "asfarsadewa.omampy"
