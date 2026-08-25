"""The command line the shell plugin drives.

Every QML action in the panel ends up here. The commands are deliberately
one-shot and stateless — they connect to mpv's socket, do one thing, and exit
— with the single exception of `watch`, which holds a connection open and
streams the console as newline-delimited JSON for the UI to paint.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

from . import __version__, chain, config, library, meter, modes, noisebed, player, render
from .mpvipc import MpvError

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_UNAVAILABLE = 3

# How often `watch` re-reads mpv's properties. The spectrum updates far
# faster; the title and the clock do not need to.
STATUS_INTERVAL = 0.2
# Seconds per marquee step.
SCROLL_INTERVAL = 0.16


class Session:
    """Resolved paths plus the effective settings for one invocation.

    Settings are layered: shipped defaults, then `config.json` (what the user
    chose to write down), then `state.json` (what they last twiddled in the
    UI). Only the last of those is ever written back.
    """

    def __init__(self, env: dict | None = None):
        self.paths = config.paths_from_env(env)
        self.warnings: list[str] = []
        self.settings: dict = {}
        self.reload()

    def reload(self) -> dict:
        """Re-read the settings files and rebuild the effective settings.

        `watch` runs for as long as the shell does, so it cannot read these
        once at startup: a band change writes `state.json` from a separate
        one-shot process, and a stream that never looks again would keep
        drawing the band it was born with while the audio played another.
        """
        self.warnings = []
        settings = config.load(self.paths.config_file, self.warnings)
        state = config.load(self.paths.state_file, self.warnings)
        stored = self._read_raw(self.paths.state_file)
        for key in stored:
            if key in config.DEFAULTS:
                settings[key] = state[key]
        self.settings = settings
        return settings

    def stamps(self) -> tuple:
        """A cheap fingerprint of the settings files, for change detection."""
        return (_stamp(self.paths.config_file), _stamp(self.paths.state_file))

    @staticmethod
    def _read_raw(path: str) -> dict:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, ValueError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def persist(self, **changes) -> None:
        """Merge `changes` into the saved state, keeping the rest intact.

        Only keys that have actually been set are written back. Writing the
        whole validated settings object would bake every default into
        `state.json`, where it would then permanently shadow `config.json`.
        """
        stored = self._read_raw(self.paths.state_file)
        stored.update(changes)
        validated = config.validate(stored)
        touched = {key: validated[key] for key in stored if key in config.DEFAULTS}
        self.settings.update(touched)
        try:
            config.save(self.paths.state_file, touched)
        except OSError as exc:
            self.warnings.append("could not save state: %s" % exc)

    def player(self) -> player.Player:
        return player.Player(self.paths, self.settings)

    def tracks(self) -> list:
        """The current playlist as Track objects, cheap enough to call often."""
        return [library.track_from_path(path)
                for path in library.read_m3u(self.paths.playlist_file)]


def _fail(message: str, code: int = EXIT_UNAVAILABLE) -> int:
    print("omampy: %s" % message, file=sys.stderr)
    return code


def _relative(text: str) -> tuple[float, bool]:
    """Parse `+5`, `-5`, or `50` into `(value, is_relative)`."""
    cleaned = str(text).strip()
    if not cleaned:
        raise ValueError("expected a number")
    relative = cleaned[0] in "+-"
    return (float(cleaned), relative)


# ------------------------------------------------------------------ commands


def cmd_scan(session: Session, args) -> int:
    """Walk the library directories and write the playlist mpv will load."""
    dirs = args.directory or session.settings["library"]
    tracks = library.scan(dirs, recursive=session.settings["recursive"])
    if session.settings["shuffle"]:
        tracks = library.shuffled(tracks, session.settings["seed"])
    try:
        library.write_m3u(session.paths.playlist_file, tracks)
    except OSError as exc:
        return _fail("could not write the playlist: %s" % exc)
    if args.json:
        print(json.dumps({"count": len(tracks),
                          "playlist": session.paths.playlist_file,
                          "tracks": [t._asdict() | {"display": t.display} for t in tracks]}))
    else:
        print("%d track%s from %s" % (len(tracks), "" if len(tracks) == 1 else "s",
                                      ", ".join(dirs)))
        if not tracks:
            print("nothing to play — check `library` in %s" % session.paths.config_file)
    return EXIT_OK


def cmd_start(session: Session, args) -> int:
    """Bring the receiver up, scanning first if there is no playlist yet."""
    if not os.path.exists(session.paths.playlist_file) or args.rescan:
        code = cmd_scan(session, argparse.Namespace(directory=None, json=False))
        if code != EXIT_OK:
            return code
    control = session.player()
    try:
        started = control.start(session.paths.playlist_file)
    except player.PlayerError as exc:
        return _fail(str(exc))
    if not started:
        print("already on air")
        return EXIT_OK
    if args.paused:
        try:
            with control.client() as mpv:
                mpv.set("pause", True)
        except (player.PlayerError, MpvError):
            pass
    print("on air — %s, intensity %d%%" % (modes.mode(session.settings["band"])["title"],
                                           round(session.settings["intensity"] * 100)))
    return EXIT_OK


def cmd_stop(session: Session, _args) -> int:
    """Shut the receiver down."""
    control = session.player()
    if not control.is_running():
        print("already off air")
        return EXIT_OK
    try:
        with control.client() as mpv:
            mpv.command("quit")
    except (player.PlayerError, MpvError):
        pass
    print("off air")
    return EXIT_OK


def _with_mpv(session: Session, action) -> int:
    """Run `action(mpv)` against a live receiver, mapping failures to exits."""
    control = session.player()
    try:
        with control.client() as mpv:
            action(control, mpv)
    except player.PlayerError as exc:
        return _fail(str(exc))
    except MpvError as exc:
        return _fail("mpv refused: %s" % exc)
    return EXIT_OK


def cmd_transport(session: Session, args) -> int:
    """play / pause / toggle / next / prev / stop-at-end, as one family."""
    name = args.command

    def action(_control, mpv):
        if name == "toggle":
            mpv.command("cycle", "pause")
        elif name == "pause":
            mpv.set("pause", True)
        elif name == "resume":
            mpv.set("pause", False)
        elif name == "next":
            mpv.command("playlist-next", "force")
        elif name == "prev":
            mpv.command("playlist-prev", "force")
        elif name == "play":
            if args.index is not None:
                mpv.set("playlist-pos", max(0, int(args.index)))
            mpv.set("pause", False)

    return _with_mpv(session, action)


def cmd_seek(session: Session, args) -> int:
    """Move within the current track."""
    def action(_control, mpv):
        mode = "absolute" if args.absolute else "relative"
        mpv.command("seek", float(args.seconds), mode)
    return _with_mpv(session, action)


def cmd_volume(session: Session, args) -> int:
    """Read or change the output volume, remembering the new level."""
    if args.value is None:
        control = session.player()
        print(control.status()["volume"])
        return EXIT_OK
    try:
        value, relative = _relative(args.value)
    except ValueError:
        return _fail("volume takes a number, optionally signed (e.g. 70, +5, -5)", EXIT_USAGE)

    result: dict = {}

    def action(_control, mpv):
        if relative:
            mpv.command("add", "volume", value)
        else:
            mpv.set("volume", value)
        result["volume"] = mpv.get("volume", value)

    code = _with_mpv(session, action)
    if code == EXIT_OK:
        session.persist(volume=int(round(float(result.get("volume", value)))))
        print(int(round(float(result.get("volume", value)))))
    elif not relative:
        # Remember the setting even with the receiver down, so it takes
        # effect at the next start.
        session.persist(volume=int(round(value)))
        return EXIT_OK
    return code


def cmd_band(session: Session, args) -> int:
    """Switch bands, rebuilding the filter graph in the running receiver."""
    current = session.settings["band"]
    if args.next or args.prev:
        target = modes.cycle(current, 1 if args.next else -1)
    elif args.name:
        try:
            target = modes.normalize(args.name)
        except modes.UnknownMode as exc:
            return _fail(str(exc), EXIT_USAGE)
    else:
        print(current)
        return EXIT_OK

    session.persist(band=target)
    print("%s — %s" % (modes.mode(target)["label"], modes.mode(target)["title"]))
    control = session.player()
    if not control.is_running():
        return EXIT_OK
    return _with_mpv(session, lambda control, mpv: control.apply_chain(mpv))


def cmd_intensity(session: Session, args) -> int:
    """Read or change how hard the static is pushed."""
    if args.value is None:
        print("%.2f" % session.settings["intensity"])
        return EXIT_OK
    try:
        value, relative = _relative(args.value)
    except ValueError:
        return _fail("intensity takes a number 0..1, optionally signed", EXIT_USAGE)
    target = chain.clamp_intensity(session.settings["intensity"] + value if relative else value)
    session.persist(intensity=target)
    print("%.2f" % target)
    control = session.player()
    if not control.is_running():
        return EXIT_OK
    return _with_mpv(session, lambda control, mpv: control.apply_chain(mpv))


def cmd_repeat(session: Session, args) -> int:
    """Read or change the repeat mode."""
    if args.cycle:
        order = config.REPEAT_MODES
        target = order[(order.index(session.settings["repeat"]) + 1) % len(order)]
    elif args.mode:
        target = str(args.mode).lower()
        if target not in config.REPEAT_MODES:
            return _fail("repeat must be one of: %s" % ", ".join(config.REPEAT_MODES), EXIT_USAGE)
    else:
        print(session.settings["repeat"])
        return EXIT_OK
    session.persist(repeat=target)
    print(target)
    control = session.player()
    if not control.is_running():
        return EXIT_OK
    return _with_mpv(session, lambda control, mpv: control.apply_repeat(mpv))


def cmd_shuffle(session: Session, args) -> int:
    """Reshuffle (or un-shuffle) and reload the playlist."""
    if args.state is None:
        target = not session.settings["shuffle"]
    else:
        target = str(args.state).lower() in ("on", "yes", "true", "1")
    session.persist(shuffle=target)
    code = cmd_scan(session, argparse.Namespace(directory=None, json=False))
    if code != EXIT_OK:
        return code
    control = session.player()
    if control.is_running():
        _with_mpv(session, lambda _c, mpv: mpv.command(
            "loadlist", session.paths.playlist_file, "replace"))
    print("shuffle %s" % ("on" if target else "off"))
    return EXIT_OK


def cmd_status(session: Session, args) -> int:
    """Print what the receiver is doing, as JSON or as the drawn console."""
    control = session.player()
    status = control.status()
    if args.json:
        print(json.dumps(status))
        return EXIT_OK
    if args.ascii:
        values = [0.0] * session.settings["meter_bands"]
        if status["running"]:
            # A snapshot is more useful with the real spectrum in it.
            try:
                with control.client() as mpv:
                    values = meter.normalize(control.levels(mpv)[1])
            except (player.PlayerError, MpvError):
                pass
        drawn = player.console(status, values, tracks=session.tracks(),
                               width=args.width, height=session.settings["meter_height"])
        print("\n".join(drawn["lines"]))
        return EXIT_OK
    if not status["running"]:
        print("off air")
        return EXIT_OK
    print("%s  %s  [%s %d%%]  %s / %s" % (
        player.STATUS_TAGS.get(status["state"], "?"), status["display"] or "—",
        status["bandLabel"], round(status["intensity"] * 100),
        render.fmt_time(status["position"]), render.fmt_time(status["duration"])))
    return EXIT_OK


def cmd_watch(session: Session, args) -> int:
    """Stream the console as newline-delimited JSON, one object per frame.

    This is what the panel reads. It outlives every other command, so each
    pass re-checks the things another process may have changed underneath it
    — the settings and the playlist — before drawing anything. It reconnects
    on its own if the receiver goes away, so the UI never has to know whether
    mpv is up.
    """
    control = session.player()
    bands = int(session.settings["meter_bands"])
    smoother = meter.Smoother(bands)
    interval = 1.0 / max(1.0, min(60.0, float(args.hz)))
    height = args.height or session.settings["meter_height"]

    tracks = session.tracks()
    playlist_stamp = _stamp(session.paths.playlist_file)
    settings_stamps = session.stamps()
    mpv = None
    status = player.status_from_props(None, session.settings)
    signal = 0.0
    last_status = 0.0
    started = time.monotonic()
    deadline = started + args.duration if args.duration else None

    try:
        while True:
            now = time.monotonic()
            if deadline and now >= deadline:
                return EXIT_OK

            # --- what has changed underneath us, before we draw ------------
            stamp = _stamp(session.paths.playlist_file)
            if stamp != playlist_stamp:
                tracks = session.tracks()
                playlist_stamp = stamp

            stamps = session.stamps()
            if stamps != settings_stamps:
                session.reload()
                settings_stamps = stamps
                # The Player keeps its own copy of the settings, and the
                # smoother is sized by them.
                control = session.player()
                if int(session.settings["meter_bands"]) != bands:
                    bands = int(session.settings["meter_bands"])
                    smoother = meter.Smoother(bands)
                # Redraw against the new settings at once rather than waiting
                # for the next status poll, so the band switch moves the
                # moment the band does.
                last_status = 0.0

            # --- what the receiver is doing -------------------------------
            if mpv is None and control.is_running():
                try:
                    mpv = control.client(timeout=1.0)
                except player.PlayerError:
                    mpv = None

            if mpv is not None:
                try:
                    if now - last_status >= STATUS_INTERVAL:
                        status = player.status_from_props(
                            mpv.get_many(player.STATUS_PROPS), session.settings)
                        last_status = now
                    signal_db, band_db = control.levels(mpv)
                    signal = meter.db_to_unit(signal_db)
                    targets = (meter.normalize(band_db)
                               if status["state"] == player.STATE_PLAYING
                               else [0.0] * bands)
                except MpvError:
                    mpv.close()
                    mpv = None
                    status = player.status_from_props(None, session.settings)
                    targets = [0.0] * bands
                    signal = 0.0
            else:
                # Rebuilt every pass rather than once before the loop: with
                # the receiver down this is the only thing keeping the band
                # and the settings on screen current.
                status = player.status_from_props(None, session.settings)
                targets = [0.0] * bands
                signal = 0.0

            values = smoother.update(targets)
            offset = int((now - started) / SCROLL_INTERVAL)
            frame = player.console(status, values, smoother.peaks, tracks=tracks,
                                   width=args.width, height=height, offset=offset,
                                   playlist_rows=args.rows, signal=signal)
            frame["status"] = status
            frame["levels"] = [round(v, 4) for v in values]
            sys.stdout.write(json.dumps(frame, separators=(",", ":")) + "\n")
            sys.stdout.flush()

            rest = interval - (time.monotonic() - now)
            if rest > 0:
                time.sleep(rest)
    except (BrokenPipeError, KeyboardInterrupt):
        return EXIT_OK
    finally:
        if mpv is not None:
            mpv.close()


def _stamp(path: str) -> tuple:
    """Modification time and size, or zeroes when the file is not there.

    Nanosecond mtime plus size catches a rewrite that lands inside the same
    second, which two commands in quick succession routinely do.
    """
    try:
        info = os.stat(path)
    except OSError:
        return (0, 0)
    return (info.st_mtime_ns, info.st_size)


def cmd_chain(session: Session, args) -> int:
    """Print the libavfilter graph, for debugging or for piping into ffmpeg."""
    band = args.band or session.settings["band"]
    intensity = session.settings["intensity"] if args.intensity is None else args.intensity
    try:
        band = modes.normalize(band)
        intensity = chain.clamp_intensity(intensity)
    except (modes.UnknownMode, ValueError) as exc:
        return _fail(str(exc), EXIT_USAGE)
    bed = None
    if not args.no_bed:
        try:
            bed = noisebed.ensure(session.paths.bed_dir, band, intensity,
                                  seed=int(session.settings["seed"]))
        except OSError as exc:
            return _fail("could not write the noise bed: %s" % exc)
    graph = chain.build_graph(band, intensity, bed_path=bed,
                              meter_bands=0 if args.no_meter else session.settings["meter_bands"])
    print(chain.af_argument(graph) if args.af else graph)
    return EXIT_OK


def cmd_bed(session: Session, args) -> int:
    """Generate (or locate) the cached noise bed for a band."""
    band = modes.normalize(args.band or session.settings["band"])
    intensity = session.settings["intensity"] if args.intensity is None else args.intensity
    try:
        path = noisebed.ensure(session.paths.bed_dir, band, chain.clamp_intensity(intensity),
                               seed=int(session.settings["seed"]))
    except OSError as exc:
        return _fail("could not write the noise bed: %s" % exc)
    if path is None:
        print("%s has no static" % modes.mode(band)["label"])
        return EXIT_OK
    print(path)
    return EXIT_OK


def cmd_doctor(session: Session, _args) -> int:
    """Check the things that actually stop this working."""
    ok = True
    binary = session.settings["mpv"]
    found = shutil.which(binary)
    print("mpv            %s" % (found or "MISSING — install mpv"))
    ok = ok and bool(found)
    dirs = [os.path.expanduser(d) for d in session.settings["library"]]
    for directory in dirs:
        exists = os.path.isdir(directory)
        print("library        %s %s" % (directory, "" if exists else "(missing)"))
        ok = ok and exists
    tracks = session.tracks()
    print("playlist       %s (%d tracks)" % (session.paths.playlist_file, len(tracks)))
    print("socket         %s %s" % (session.paths.socket_file,
                                    "(live)" if session.player().is_running() else "(down)"))
    print("cache          %s" % session.paths.cache_dir)
    for warning in session.warnings:
        print("warning        %s" % warning)
    return EXIT_OK if ok else EXIT_UNAVAILABLE


# -------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    """The whole command surface, in one place."""
    parser = argparse.ArgumentParser(
        prog="omampy",
        description="Play local audio through a 1980s AM/shortwave receiver.")
    parser.add_argument("--version", action="version", version="omampy " + __version__)
    subs = parser.add_subparsers(dest="command", required=True)

    start = subs.add_parser("start", help="bring the receiver on air")
    start.add_argument("--paused", action="store_true", help="start without playing")
    start.add_argument("--rescan", action="store_true", help="rebuild the playlist first")
    start.set_defaults(handler=cmd_start)

    subs.add_parser("stop", help="take the receiver off air").set_defaults(handler=cmd_stop)

    scan = subs.add_parser("scan", help="rebuild the playlist from the library")
    scan.add_argument("directory", nargs="*", help="directories to scan (default: config)")
    scan.add_argument("--json", action="store_true", help="print the full track list")
    scan.set_defaults(handler=cmd_scan)

    for name, help_text in (("toggle", "play or pause"), ("pause", "pause"),
                            ("resume", "resume"), ("next", "next track"),
                            ("prev", "previous track")):
        sub = subs.add_parser(name, help=help_text)
        sub.set_defaults(handler=cmd_transport, index=None)

    play = subs.add_parser("play", help="play, optionally jumping to a track")
    play.add_argument("index", nargs="?", type=int, help="playlist position (0-based)")
    play.set_defaults(handler=cmd_transport)

    seek = subs.add_parser("seek", help="move within the current track")
    seek.add_argument("seconds", type=float)
    seek.add_argument("--absolute", action="store_true", help="seek to, not by")
    seek.set_defaults(handler=cmd_seek)

    volume = subs.add_parser("volume", help="read or set the volume")
    volume.add_argument("value", nargs="?", help="0..130, or +N / -N")
    volume.set_defaults(handler=cmd_volume)

    band = subs.add_parser("band", help="read or switch the band")
    band.add_argument("name", nargs="?", help=" / ".join(modes.ORDER))
    band.add_argument("--next", action="store_true", help="next band on the switch")
    band.add_argument("--prev", action="store_true", help="previous band")
    band.set_defaults(handler=cmd_band)

    intensity = subs.add_parser("intensity", help="read or set the static level")
    intensity.add_argument("value", nargs="?", help="0..1, or +N / -N")
    intensity.set_defaults(handler=cmd_intensity)

    repeat = subs.add_parser("repeat", help="read or set the repeat mode")
    repeat.add_argument("mode", nargs="?", choices=config.REPEAT_MODES)
    repeat.add_argument("--cycle", action="store_true", help="advance to the next mode")
    repeat.set_defaults(handler=cmd_repeat)

    shuffle = subs.add_parser("shuffle", help="reshuffle or restore the playlist order")
    shuffle.add_argument("state", nargs="?", choices=("on", "off"))
    shuffle.set_defaults(handler=cmd_shuffle)

    status = subs.add_parser("status", help="what the receiver is doing")
    status.add_argument("--json", action="store_true")
    status.add_argument("--ascii", action="store_true", help="draw the console")
    status.add_argument("--width", type=int, default=player.DEFAULT_WIDTH)
    status.set_defaults(handler=cmd_status)

    watch = subs.add_parser("watch", help="stream console frames as NDJSON")
    watch.add_argument("--hz", type=float, default=20.0, help="frames per second")
    watch.add_argument("--width", type=int, default=player.DEFAULT_WIDTH)
    watch.add_argument("--height", type=int, default=0, help="spectrum rows")
    watch.add_argument("--rows", type=int, default=player.DEFAULT_PLAYLIST_ROWS,
                       help="playlist rows")
    watch.add_argument("--duration", type=float, default=0.0,
                       help="stop after N seconds (0 = forever)")
    watch.set_defaults(handler=cmd_watch)

    graph = subs.add_parser("chain", help="print the libavfilter graph")
    graph.add_argument("--band")
    graph.add_argument("--intensity", type=float)
    graph.add_argument("--no-meter", action="store_true", help="omit the metering probe")
    graph.add_argument("--no-bed", action="store_true", help="omit the noise bed")
    graph.add_argument("--af", action="store_true", help="wrap it as an mpv --af argument")
    graph.set_defaults(handler=cmd_chain)

    bed = subs.add_parser("bed", help="generate the cached noise bed")
    bed.add_argument("--band")
    bed.add_argument("--intensity", type=float)
    bed.set_defaults(handler=cmd_bed)

    subs.add_parser("doctor", help="check mpv, the library, and the socket") \
        .set_defaults(handler=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    session = Session()
    try:
        return args.handler(session, args)
    except KeyboardInterrupt:
        return EXIT_OK
    except BrokenPipeError:
        return EXIT_OK
