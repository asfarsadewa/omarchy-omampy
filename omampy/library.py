"""Finding and ordering the local records.

OMAMPY only ever plays files off the disk — there is no network path in this
program at all. This module walks the configured directories, keeps the files
whose extensions we can decode, guesses an artist and title from the filename,
and writes the result out as an M3U for mpv to load in one go. Letting mpv own
the playlist means track advance, gapless, and repeat are its problem, not
ours; ordering is the part worth keeping here.
"""

from __future__ import annotations

import os
import random
import re
from typing import Iterable, NamedTuple, Sequence

# Everything ffmpeg decodes happily and that people actually keep in a music
# folder. Deliberately excludes video containers: this is a radio, not a
# player of last resort.
AUDIO_EXTS = frozenset({
    ".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".flac", ".wav",
    ".wma", ".aiff", ".aif", ".alac", ".mka", ".ape", ".wv", ".mp2",
})

_NUM_RE = re.compile(r"(\d+)")
# "01 - ", "01. ", "01_", "1 " at the head of a filename.
_TRACKNO_RE = re.compile(r"^\s*(\d{1,3})\s*[-._)\]]?\s+")
_TRACKNO_BARE_RE = re.compile(r"^\s*(\d{1,3})[-._]\s*")
# The separator people actually use between artist and title.
_SPLIT_RE = re.compile(r"\s+[-–—]\s+")


class Track(NamedTuple):
    """One file on disk, plus what we could work out about it."""

    path: str
    artist: str
    title: str
    ext: str
    size: int

    @property
    def display(self) -> str:
        """`Artist — Title`, or just the title when there is no artist."""
        return "%s — %s" % (self.artist, self.title) if self.artist else self.title


def is_audio_file(path: str, exts: Iterable[str] = AUDIO_EXTS) -> bool:
    """True when `path` has an extension we can decode."""
    return os.path.splitext(str(path))[1].lower() in set(exts)


def natural_key(text: str) -> tuple:
    """Sort key that reads embedded numbers as numbers.

    Without it `track10.mp3` files before `track2.mp3`, which is wrong on
    every album ever pressed.
    """
    parts = _NUM_RE.split(str(text).lower())
    key = []
    for i, part in enumerate(parts):
        if i % 2:
            key.append((0, int(part), ""))
        elif part:
            key.append((1, 0, part))
    return tuple(key)


def clean_stem(stem: str) -> str:
    """Tidy a filename stem into something worth showing on a dial."""
    text = str(stem).replace("_", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_track_name(stem: str) -> tuple[str, str]:
    """Guess `(artist, title)` from a filename stem.

    Handles the shapes that actually turn up in a music folder: a leading
    track number, `Artist - Title`, and `Artist - 03 - Title`. Anything it
    cannot split becomes a title with no artist, which is the honest answer.
    """
    text = clean_stem(stem)
    if not text:
        return ("", "")
    parts = _SPLIT_RE.split(text)
    if len(parts) >= 2:
        head = parts[0].strip()
        tail = " - ".join(p.strip() for p in parts[1:]).strip()
        # `03 - Title`: the leading field is a track number, not an artist.
        if head.isdigit():
            return ("", _strip_track_number(tail))
        # `Artist - 03 - Title`: drop the number sitting in the middle.
        return (head, _strip_track_number(tail))
    return ("", _strip_track_number(text))


def _strip_track_number(text: str) -> str:
    """Remove a leading track number, unless that is all there is."""
    for pattern in (_TRACKNO_RE, _TRACKNO_BARE_RE):
        stripped = pattern.sub("", text, count=1).strip()
        if stripped:
            return stripped
    return text.strip()


def track_from_path(path: str, size: int = 0) -> Track:
    """Build a Track from a path without touching the filesystem."""
    stem, ext = os.path.splitext(os.path.basename(str(path)))
    artist, title = parse_track_name(stem)
    return Track(str(path), artist, title or stem, ext.lower(), int(size))


def scan(directories: Sequence[str], *, recursive: bool = True,
         exts: Iterable[str] = AUDIO_EXTS, follow_symlinks: bool = False,
         limit: int = 0) -> list[Track]:
    """Walk `directories` and return every audio file found, in natural order.

    Duplicate paths (from overlapping or symlinked directories) are collapsed;
    unreadable directories are skipped rather than raising, because one bad
    mount should not empty the dial.
    """
    exts = set(exts)
    seen: set[str] = set()
    found: list[Track] = []
    for directory in directories:
        root = os.path.expanduser(str(directory))
        if not os.path.isdir(root):
            continue
        if recursive:
            walker = os.walk(root, followlinks=follow_symlinks, onerror=lambda _e: None)
        else:
            try:
                walker = [(root, [], os.listdir(root))]
            except OSError:
                continue
        for base, dirnames, filenames in walker:
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for name in sorted(filenames, key=natural_key):
                if name.startswith("."):
                    continue
                if not is_audio_file(name, exts):
                    continue
                full = os.path.join(base, name)
                real = os.path.realpath(full)
                if real in seen:
                    continue
                seen.add(real)
                try:
                    size = os.path.getsize(full)
                except OSError:
                    continue
                found.append(track_from_path(full, size))
                if limit and len(found) >= limit:
                    return sort_tracks(found)
    return sort_tracks(found)


def sort_tracks(tracks: Sequence[Track]) -> list[Track]:
    """Order by path, naturally."""
    return sorted(tracks, key=lambda t: natural_key(t.path))


def shuffled(tracks: Sequence[Track], seed) -> list[Track]:
    """A reproducible shuffle — the same seed always deals the same order."""
    order = list(tracks)
    random.Random(str(seed)).shuffle(order)
    return order


def m3u_lines(tracks: Sequence[Track]) -> list[str]:
    """Render an extended M3U as a list of lines.

    Paths are written verbatim; mpv resolves them as-is, and every path we
    hand it is already absolute.
    """
    lines = ["#EXTM3U"]
    for track in tracks:
        label = track.display.replace("\n", " ").replace("\r", " ")
        lines.append("#EXTINF:-1,%s" % label)
        lines.append(track.path)
    return lines


def write_m3u(path: str, tracks: Sequence[Track]) -> str:
    """Write the playlist atomically and return its path."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".partial"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write("\n".join(m3u_lines(tracks)) + "\n")
    os.replace(tmp, path)
    return path


def read_m3u(path: str) -> list[str]:
    """Read back the file paths from an M3U, ignoring its comments."""
    out: list[str] = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if text and not text.startswith("#"):
                    out.append(text)
    except OSError:
        return []
    return out
