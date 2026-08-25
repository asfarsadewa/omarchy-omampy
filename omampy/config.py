"""Where things live, and what the knobs are allowed to be.

Settings arrive from three places — the shipped defaults, `config.json`, and
whatever the shell last wrote to `state.json` — so validation has to be
forgiving: a bad value gets clamped or dropped with a warning rather than
taking the player down. Nothing in here touches mpv; it is paths and numbers.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import NamedTuple

from . import chain, modes

APP = "omampy"

DEFAULTS = {
    # Directories to scan for records. `~` is expanded at scan time.
    "library": ["~/Music"],
    "recursive": True,
    "band": modes.DEFAULT_MODE,
    "intensity": 0.6,
    # Seed for the noise bed. Pin it and the static is the same every session.
    "seed": 1980,
    "volume": 75,
    "shuffle": False,
    # off | one | all
    "repeat": "all",
    "meter_bands": chain.DEFAULT_METER_BANDS,
    # Rows of block glyphs in the spectrum display.
    "meter_height": 8,
    "mpv": "mpv",
}

REPEAT_MODES = ("off", "one", "all")

MIN_METER_BANDS = 4
MAX_METER_BANDS = 32
MIN_METER_HEIGHT = 3
MAX_METER_HEIGHT = 24
MAX_VOLUME = 130

# `sun_path` in a unix socket address is 108 bytes including the terminator.
# A deep XDG_RUNTIME_DIR can overrun that, and mpv then fails to bind with no
# useful message at all, so we detect it and move the socket somewhere short.
MAX_SOCKET_PATH = 100
SOCKET_NAME = "mpv.sock"

# libavfilter's quoting rules cannot reliably carry a quote or a backslash
# through a filtergraph, and the noise bed's path goes into one. Rather than
# trust the escaping, we refuse to generate files under a directory holding
# either and fall back somewhere we know is safe.
UNSAFE_FILTER_CHARS = "'\\"


class Paths(NamedTuple):
    """Every path the player uses, resolved from the environment once."""

    config_dir: str
    cache_dir: str
    state_dir: str
    runtime_dir: str

    @property
    def config_file(self) -> str:
        return os.path.join(self.config_dir, "config.json")

    @property
    def state_file(self) -> str:
        return os.path.join(self.state_dir, "state.json")

    @property
    def playlist_file(self) -> str:
        return os.path.join(self.state_dir, "playlist.m3u")

    @property
    def socket_file(self) -> str:
        return os.path.join(self.runtime_dir, SOCKET_NAME)

    @property
    def log_file(self) -> str:
        return os.path.join(self.state_dir, "mpv.log")

    @property
    def bed_dir(self) -> str:
        """Where noise beds are cached.

        Normally the cache directory, so a bed survives a reboot; if that
        path cannot go into a filtergraph the beds move to the runtime
        directory instead and are simply regenerated each session.
        """
        return self.cache_dir if filter_safe(self.cache_dir) else self.runtime_dir


def _base(env: dict, key: str, fallback: str) -> str:
    value = str(env.get(key) or "").strip()
    if value and os.path.isabs(value):
        return value
    return os.path.expanduser(fallback)


def filter_safe(path: str) -> bool:
    """True when `path` can be embedded in a filtergraph without ambiguity."""
    return not any(ch in str(path) for ch in UNSAFE_FILTER_CHARS)


def socket_path_fits(directory: str) -> bool:
    """True when a socket in `directory` stays inside the kernel's limit."""
    return len(os.path.join(str(directory), SOCKET_NAME).encode("utf-8")) <= MAX_SOCKET_PATH


def short_runtime_dir(uid: int | None = None) -> str:
    """A guaranteed-short, per-user directory for the socket."""
    if uid is None:
        uid = os.getuid() if hasattr(os, "getuid") else 0
    return os.path.join(tempfile.gettempdir(), "%s-%d" % (APP, uid))


def paths_from_env(env: dict | None = None, uid: int | None = None) -> Paths:
    """Resolve XDG locations, falling back to the documented defaults.

    The runtime directory holds the mpv control socket. Without an
    `XDG_RUNTIME_DIR` we use the cache directory, and if either is too deep
    for a unix socket address we move just the socket to a short path under
    the temp directory.
    """
    env = dict(os.environ if env is None else env)
    config_dir = os.path.join(_base(env, "XDG_CONFIG_HOME", "~/.config"), APP)
    cache_dir = os.path.join(_base(env, "XDG_CACHE_HOME", "~/.cache"), APP)
    state_dir = os.path.join(_base(env, "XDG_STATE_HOME", "~/.local/state"), APP)
    runtime_root = str(env.get("XDG_RUNTIME_DIR") or "").strip()
    runtime_dir = os.path.join(runtime_root, APP) if os.path.isabs(runtime_root) else cache_dir
    if not socket_path_fits(runtime_dir) or not filter_safe(runtime_dir):
        runtime_dir = short_runtime_dir(uid)
    return Paths(config_dir, cache_dir, state_dir, runtime_dir)


def _clamp_int(value, low: int, high: int, fallback: int) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, number))


def validate(raw: dict | None, warnings: list | None = None) -> dict:
    """Merge `raw` over the defaults, coercing every field into range.

    Unknown keys are dropped. Anything that cannot be coerced falls back to
    its default and appends a line to `warnings` if one was passed in.
    """
    def warn(message: str) -> None:
        if warnings is not None:
            warnings.append(message)

    settings = dict(DEFAULTS)
    settings["library"] = list(DEFAULTS["library"])
    if not isinstance(raw, dict):
        if raw is not None:
            warn("settings must be an object; using defaults")
        return settings

    for key, value in raw.items():
        if key not in DEFAULTS:
            warn("ignoring unknown setting %r" % key)
            continue

        if key == "library":
            if isinstance(value, str):
                value = [value]
            if not isinstance(value, (list, tuple)):
                warn("library must be a list of directories")
                continue
            dirs = [str(v) for v in value if str(v).strip()]
            settings["library"] = dirs or list(DEFAULTS["library"])
        elif key == "band":
            try:
                settings["band"] = modes.normalize(value)
            except modes.UnknownMode as exc:
                warn(str(exc))
        elif key == "intensity":
            try:
                settings["intensity"] = chain.clamp_intensity(value)
            except ValueError:
                warn("intensity must be a number between 0 and 1")
        elif key == "seed":
            try:
                settings["seed"] = int(value)
            except (TypeError, ValueError):
                warn("seed must be an integer")
        elif key == "volume":
            settings["volume"] = _clamp_int(value, 0, MAX_VOLUME, DEFAULTS["volume"])
        elif key == "repeat":
            text = str(value).strip().lower()
            if text in REPEAT_MODES:
                settings["repeat"] = text
            else:
                warn("repeat must be one of: %s" % ", ".join(REPEAT_MODES))
        elif key == "meter_bands":
            settings["meter_bands"] = _clamp_int(value, MIN_METER_BANDS, MAX_METER_BANDS,
                                                 DEFAULTS["meter_bands"])
        elif key == "meter_height":
            settings["meter_height"] = _clamp_int(value, MIN_METER_HEIGHT, MAX_METER_HEIGHT,
                                                  DEFAULTS["meter_height"])
        elif key in ("recursive", "shuffle"):
            settings[key] = bool(value)
        elif key == "mpv":
            text = str(value).strip()
            settings["mpv"] = text or DEFAULTS["mpv"]

    return settings


def load(path: str, warnings: list | None = None) -> dict:
    """Read and validate a settings file; a missing file is not an error."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        return validate(None)
    except (OSError, ValueError) as exc:
        if warnings is not None:
            warnings.append("could not read %s: %s" % (path, exc))
        return validate(None)
    return validate(raw, warnings)


def save(path: str, settings: dict) -> str:
    """Write settings atomically, keeping only recognised keys."""
    clean = {key: settings[key] for key in DEFAULTS if key in settings}
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".partial"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(clean, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, path)
    return path
