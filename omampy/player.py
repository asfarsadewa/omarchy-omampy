"""Driving mpv, and describing what it is doing.

The split here is deliberate: everything that decides *what the console says*
is a pure function of an mpv property dictionary, and everything that talks to
a process or a socket is confined to the `Player` class at the bottom. That
way the interesting logic — how a track is named, what the transport bar looks
like at 1:23 of 3:40, which rows of the playlist are on screen — is testable
without a running receiver.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Sequence

from . import chain, library, meter, modes, noisebed, render
from .mpvipc import MpvClient, MpvError, NotRunning, socket_ready

# Properties one status poll asks for. Kept small: this runs many times a
# second while the console is open.
STATUS_PROPS = (
    "pause", "idle-active", "path", "media-title", "metadata",
    "time-pos", "duration", "playlist-pos", "playlist-count",
    "volume", "mute",
)

DEFAULT_WIDTH = 46
DEFAULT_PLAYLIST_ROWS = 5

STATE_PLAYING = "playing"
STATE_PAUSED = "paused"
STATE_IDLE = "idle"
STATE_STOPPED = "stopped"

STATUS_TAGS = {
    STATE_PLAYING: "◉ ON AIR",
    STATE_PAUSED: "▮▮ PAUSED",
    STATE_IDLE: "○ STANDBY",
    STATE_STOPPED: "○ OFF AIR",
}


# --------------------------------------------------------------------- pure


def repeat_properties(repeat: str) -> dict:
    """mpv loop properties for one repeat mode."""
    text = str(repeat or "off").lower()
    return {
        "loop-playlist": "inf" if text == "all" else "no",
        "loop-file": "inf" if text == "one" else "no",
    }


def launch_args(settings: dict, socket_path: str, graph: str,
                playlist_path: str | None = None) -> list[str]:
    """The full mpv command line for a session.

    `--no-config` is not caution for its own sake: the graph and the volume
    are computed here, and a stray `mpv.conf` with its own `af=` would
    silently replace the entire broadcast chain.
    """
    loops = repeat_properties(settings.get("repeat", "all"))
    args = [
        str(settings.get("mpv") or "mpv"),
        "--no-config",
        "--no-video",
        "--no-terminal",
        "--idle=yes",
        "--gapless-audio=yes",
        "--audio-display=no",
        "--audio-client-name=omampy",
        "--msg-level=all=error",
        "--input-ipc-server=" + str(socket_path),
        "--volume=%d" % int(settings.get("volume", 75)),
        "--loop-playlist=" + loops["loop-playlist"],
        "--loop-file=" + loops["loop-file"],
        "--af=" + chain.af_argument(graph),
    ]
    if settings.get("shuffle"):
        args.append("--shuffle")
    if playlist_path:
        args.append("--playlist=" + str(playlist_path))
    return args


def track_names(props: dict) -> tuple[str, str]:
    """Best available `(artist, title)` for whatever is loaded.

    mpv's own tags win when the file carries them; otherwise the filename is
    parsed, which is all a lot of local libraries actually have.
    """
    tags = props.get("metadata") or {}
    if isinstance(tags, dict):
        lowered = {str(k).lower(): str(v) for k, v in tags.items() if v not in (None, "")}
    else:
        lowered = {}
    artist = lowered.get("artist") or lowered.get("album_artist") or ""
    title = lowered.get("title") or ""
    if artist and title:
        return (artist.strip(), title.strip())

    path = props.get("path") or ""
    if path:
        guess = library.track_from_path(str(path))
        return (artist.strip() or guess.artist, title.strip() or guess.title)

    fallback = str(props.get("media-title") or "").strip()
    return (artist.strip(), title.strip() or fallback)


def _number(value, fallback: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return fallback if number != number else number


def status_from_props(props: dict | None, settings: dict) -> dict:
    """Fold raw mpv properties and current settings into one status object.

    `props` of None means the receiver is not running at all, which is a
    state the UI has to render just like any other.
    """
    band = modes.normalize(settings.get("band", modes.DEFAULT_MODE))
    spec = modes.mode(band)
    base = {
        "running": props is not None,
        "state": STATE_STOPPED,
        "path": "",
        "artist": "",
        "title": "",
        "display": "",
        "position": 0.0,
        "duration": 0.0,
        "index": -1,
        "count": 0,
        "volume": int(settings.get("volume", 75)),
        "muted": False,
        "band": band,
        "bandLabel": spec["label"],
        "bandTitle": spec["title"],
        "dialLabel": modes.dial_label(band),
        "intensity": chain.clamp_intensity(settings.get("intensity", 0.6)),
        "repeat": str(settings.get("repeat", "all")),
        "shuffle": bool(settings.get("shuffle")),
    }
    if props is None:
        return base

    idle = bool(props.get("idle-active"))
    has_track = bool(props.get("path"))
    if idle or not has_track:
        base["state"] = STATE_IDLE
    else:
        base["state"] = STATE_PAUSED if bool(props.get("pause")) else STATE_PLAYING

    artist, title = track_names(props)
    base.update({
        "path": str(props.get("path") or ""),
        "artist": artist,
        "title": title,
        "display": ("%s — %s" % (artist, title)) if artist and title else (title or artist),
        "position": max(0.0, _number(props.get("time-pos"))),
        "duration": max(0.0, _number(props.get("duration"))),
        "index": int(_number(props.get("playlist-pos"), -1)),
        "count": int(_number(props.get("playlist-count"), 0)),
        "volume": int(_number(props.get("volume"), base["volume"])),
        "muted": bool(props.get("mute")),
    })
    return base


def playlist_window(tracks: Sequence, index: int, rows: int) -> list[dict]:
    """The slice of the playlist to show, keeping the current track in view.

    Scrolls only when it has to: the current track stays put until it reaches
    the edge of the window, which is far less jumpy to read than centring it.
    """
    if rows < 1:
        raise ValueError("rows must be >= 1")
    total = len(tracks)
    if total == 0:
        return []
    index = max(0, min(total - 1, int(index)))
    half = rows // 2
    start = max(0, min(index - half, total - rows))
    start = max(0, start)
    out = []
    for offset in range(min(rows, total - start)):
        position = start + offset
        track = tracks[position]
        display = track.display if hasattr(track, "display") else str(track)
        out.append({"index": position, "number": position + 1,
                    "display": display, "current": position == index})
    return out


def track_line(entry: dict, width: int) -> str:
    """One playlist row: marker, number, and title, clipped to `width`."""
    marker = "▶" if entry.get("current") else " "
    number = "%02d" % int(entry.get("number", 0))
    prefix = "%s %s " % (marker, number)
    return prefix + render.pad(str(entry.get("display", "")),
                               max(0, width - render.display_width(prefix)))


# Row kinds handed to the UI so it can colour each line without having to
# parse the drawing back apart.
ROW_BLANK = "blank"
ROW_SPECTRUM = "spectrum"
ROW_BAND = "band"
ROW_DIAL = "dial"
ROW_METER = "meter"
ROW_NOW = "now"
ROW_TRANSPORT = "transport"
ROW_TRACK = "track"

# Columns in the bar widget's miniature spectrum.
MINI_COLUMNS = 7


def console(status: dict, values: Sequence[float], peaks: Sequence[float] | None = None,
            *, tracks: Sequence = (), width: int = DEFAULT_WIDTH, height: int = 8,
            offset: int = 0, playlist_rows: int = DEFAULT_PLAYLIST_ROWS,
            signal: float = 0.0) -> dict:
    """Render every piece of the console for one moment in time.

    Returns the receiver as `rows` — each already padded to the inner width
    and tagged with what it is, so the UI can colour a spectrum row
    differently from a track row without re-deriving the layout — plus
    `lines`, the whole thing drawn as one block of text for the terminal and
    the bar tooltip.
    """
    if width < 24:
        raise ValueError("width must be >= 24")
    inner = width - 2
    label_width = 5
    field = inner - label_width

    spectrum = render.spectrum_rows(values, height, peaks)
    band_row = render.band_switch(
        status.get("band", modes.DEFAULT_MODE), modes.ORDER,
        {name: modes.MODES[name]["label"] for name in modes.ORDER})
    dial_label = str(status.get("dialLabel", ""))
    dial_width = max(5, field - render.display_width(dial_label) - 2)
    # The pointer walks the scale as the band switch moves along it.
    position = (modes.ORDER.index(status.get("band", modes.DEFAULT_MODE))
                / max(1, len(modes.ORDER) - 1))
    dial_row = render.dial(position, dial_width) + "  " + dial_label

    meter_width = max(4, (field - 12) // 2)
    signal_row = (render.shaded_row(signal, meter_width, empty="·") + "  VOL "
                  + render.meter_row(status.get("volume", 0) / 100.0, meter_width))
    intensity_row = (render.meter_row(status.get("intensity", 0.0), meter_width)
                     + "  %d%%" % round(status.get("intensity", 0) * 100))

    state = status.get("state", STATE_STOPPED)
    now = status.get("display") or ("— no signal —" if state == STATE_IDLE else "—")
    marker = {STATE_PLAYING: "▶", STATE_PAUSED: "▮▮"}.get(state, "■")
    now_row = "%s %s" % (marker, render.marquee(now, max(1, inner - 3), offset))

    elapsed = render.fmt_time(status.get("position"))
    total = render.fmt_time(status.get("duration"))
    # Indented by two so the bar starts under the title, not under its marker.
    bar_width = max(3, inner - render.display_width(elapsed) - render.display_width(total) - 4)
    transport = "  %s %s %s" % (elapsed, render.progress_bar(status.get("position"),
                                                             status.get("duration"),
                                                             bar_width), total)

    entries = playlist_window(tracks, status.get("index", 0), playlist_rows)

    rows: list[dict] = []

    def add(kind: str, text: str = "", **extra) -> None:
        rows.append(dict({"kind": kind, "text": render.pad(text, inner)}, **extra))

    for line in spectrum:
        # Centred so a 14-band spectrum sits under the middle of a wider
        # console instead of hugging the left border.
        add(ROW_SPECTRUM, render.pad(line, inner, "center"))
    add(ROW_BLANK)
    add(ROW_BAND, "BAND " + render.pad(band_row, field))
    add(ROW_DIAL, "TUNE " + render.pad(dial_row, field))
    add(ROW_METER, "SIG  " + render.pad(signal_row, field))
    add(ROW_METER, "INT  " + render.pad(intensity_row, field))
    add(ROW_BLANK)
    add(ROW_NOW, now_row)
    add(ROW_TRANSPORT, transport)
    if entries:
        add(ROW_BLANK)
        for entry in entries:
            add(ROW_TRACK, track_line(entry, inner),
                index=entry["index"], current=entry["current"])

    tag = STATUS_TAGS.get(state, STATUS_TAGS[STATE_STOPPED])
    lines = render.box([row["text"] for row in rows], width, title="OMAMPY", status=tag)

    return {
        "width": width,
        "inner": inner,
        "rows": rows,
        "top": lines[0],
        "bottom": lines[-1],
        "lines": lines,
        "spectrum": spectrum,
        "mini": "".join(render.spectrum_rows(
            render.downsample(values, MINI_COLUMNS), 1)),
        "bandSwitch": band_row,
        "dial": dial_row,
        "signal": signal_row,
        "intensity": intensity_row,
        "nowPlaying": now_row,
        "transport": transport,
        "elapsed": elapsed,
        "total": total,
        "playlist": [row["text"] for row in rows if row["kind"] == ROW_TRACK],
        "playlistEntries": entries,
        "statusTag": tag,
    }


# ------------------------------------------------------------------- impure


class PlayerError(RuntimeError):
    """Something went wrong starting or reaching the receiver."""


class Player:
    """Everything that touches the mpv process or its socket."""

    def __init__(self, paths, settings: dict):
        self.paths = paths
        self.settings = dict(settings)

    # -- process ---------------------------------------------------------

    def is_running(self) -> bool:
        """True when a receiver is listening on our socket."""
        return socket_ready(self.paths.socket_file)

    def graph(self, *, meter_bands: int | None = None) -> str:
        """Build the current filter graph, generating the noise bed as needed."""
        band = self.settings["band"]
        intensity = self.settings["intensity"]
        bed = None
        try:
            bed = noisebed.ensure(self.paths.bed_dir, band, intensity,
                                  seed=int(self.settings.get("seed", noisebed.DEFAULT_SEED)))
        except OSError:
            # A cache we cannot write is not worth failing playback over; the
            # band simply loses its static.
            bed = None
        bands = self.settings["meter_bands"] if meter_bands is None else meter_bands
        return chain.build_graph(band, intensity, bed_path=bed, meter_bands=bands)

    def start(self, playlist_path: str | None = None, *, wait: float = 6.0) -> bool:
        """Launch mpv if it is not already up. Returns True if it started."""
        if self.is_running():
            return False
        binary = str(self.settings.get("mpv") or "mpv")
        if not shutil.which(binary):
            raise PlayerError(
                "%s not found on PATH — install mpv (it is what actually plays "
                "and filters the audio)" % binary)
        os.makedirs(self.paths.runtime_dir, exist_ok=True)
        os.makedirs(self.paths.state_dir, exist_ok=True)
        # A stale socket file from a killed session stops mpv binding again.
        if os.path.exists(self.paths.socket_file) and not self.is_running():
            try:
                os.unlink(self.paths.socket_file)
            except OSError:
                pass
        args = launch_args(self.settings, self.paths.socket_file, self.graph(), playlist_path)
        with open(os.devnull, "wb") as sink:
            subprocess.Popen(args, stdout=sink, stderr=sink, start_new_session=True)
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if self.is_running():
                return True
            time.sleep(0.05)
        raise PlayerError("mpv did not open %s within %.0fs" % (self.paths.socket_file, wait))

    def client(self, timeout: float = 2.0) -> MpvClient:
        """Open a connection, raising PlayerError when nothing is listening."""
        try:
            return MpvClient(self.paths.socket_file, timeout=timeout).connect()
        except NotRunning as exc:
            raise PlayerError("the receiver is not running (try: omampy start)") from exc

    # -- state -----------------------------------------------------------

    def status(self) -> dict:
        """Poll mpv and fold the result into a status object."""
        if not self.is_running():
            return status_from_props(None, self.settings)
        try:
            with self.client() as mpv:
                props = mpv.get_many(STATUS_PROPS)
        except (PlayerError, MpvError):
            return status_from_props(None, self.settings)
        return status_from_props(props, self.settings)

    def levels(self, mpv: MpvClient) -> tuple[float, list[float]]:
        """Read one metering frame: `(signal_db, band_dbs)`."""
        metadata = mpv.get("af-metadata/" + chain.FILTER_LABEL, {})
        return meter.split_levels(metadata, int(self.settings["meter_bands"]),
                                  chain.keep_channels(self.settings["band"]))

    def apply_chain(self, mpv: MpvClient) -> None:
        """Push a freshly built graph into the running receiver."""
        mpv.command("af", "set", chain.af_argument(self.graph()))

    def apply_repeat(self, mpv: MpvClient) -> None:
        """Push the current repeat mode into the running receiver."""
        for prop, value in repeat_properties(self.settings.get("repeat", "all")).items():
            mpv.set(prop, value)
