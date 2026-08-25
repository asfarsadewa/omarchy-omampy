"""Drawing the receiver out of block glyphs.

Every visible part of the console — the spectrum, the tuning scale, the VU
meters, the transport bar, the track list — is rendered here into plain
strings. The QML side does nothing but paint them in a monospace font. Keeping
the drawing in Python means the layout is testable character by character, and
it keeps the UI honestly text-shaped, which is the look Omarchy wears
everywhere else.

All widths are counted in terminal cells, not codepoints, so a CJK track title
does not shove the right-hand border out of line.
"""

from __future__ import annotations

import unicodedata
from typing import Iterable, Sequence

# Nine levels of vertical fill: index 0 is empty, 8 is a full cell.
BLOCKS = " ▁▂▃▄▅▆▇█"
# Four levels of horizontal shading, for meters that read as a ramp.
SHADES = " ░▒▓█"
PEAK_GLYPH = "▔"

BOX = {
    "tl": "┌", "tr": "┐", "bl": "└", "br": "┘",
    "h": "─", "v": "│", "lt": "├", "rt": "┤",
}


def display_width(text: str) -> int:
    """Width of `text` in monospace cells.

    Wide (CJK) and fullwidth forms take two cells; combining marks take none.
    """
    total = 0
    for ch in str(text):
        if unicodedata.combining(ch):
            continue
        total += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return total


def truncate(text: str, width: int, ellipsis: str = "…") -> str:
    """Cut `text` to at most `width` cells, marking the cut with an ellipsis."""
    text = str(text)
    if width <= 0:
        return ""
    if display_width(text) <= width:
        return text
    mark_width = display_width(ellipsis)
    if width <= mark_width:
        return ellipsis[:width] if mark_width == 1 else ""
    budget = width - mark_width
    out = []
    used = 0
    for ch in text:
        step = display_width(ch)
        if used + step > budget:
            break
        out.append(ch)
        used += step
    return "".join(out) + ellipsis


def pad(text: str, width: int, align: str = "left", fill: str = " ") -> str:
    """Pad or truncate `text` to exactly `width` cells."""
    text = truncate(text, width)
    gap = width - display_width(text)
    if gap <= 0:
        return text
    if align == "right":
        return fill * gap + text
    if align == "center":
        left = gap // 2
        return fill * left + text + fill * (gap - left)
    return text + fill * gap


def clamp01(value: float) -> float:
    """Coerce anything numeric into 0..1; non-numbers read as 0."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    if f != f:
        return 0.0
    return 0.0 if f < 0.0 else (1.0 if f > 1.0 else f)


def column(value: float, height: int) -> list[str]:
    """One spectrum column, top cell first.

    A partially filled cell picks the block glyph nearest its fraction, which
    is what gives the bars sub-cell movement instead of a jerky staircase.
    """
    if height < 1:
        raise ValueError("height must be >= 1")
    total = clamp01(value) * height
    cells = []
    for row in range(height):
        # Row 0 is the top, so it is the last cell to fill.
        filled = total - (height - 1 - row)
        level = 0 if filled <= 0 else (8 if filled >= 1 else int(round(filled * 8)))
        cells.append(BLOCKS[level])
    return cells


def spectrum_rows(values: Sequence[float], height: int,
                  peaks: Sequence[float] | None = None) -> list[str]:
    """Render a bar spectrum as `height` rows of block glyphs.

    `peaks` draws a falling marker above each bar wherever the bar itself has
    not already reached that cell.
    """
    if height < 1:
        raise ValueError("height must be >= 1")
    columns = [column(v, height) for v in values]
    if peaks is not None:
        for i, peak in enumerate(peaks):
            if i >= len(columns):
                break
            level = clamp01(peak) * height
            if level <= 0:
                continue
            # The cell the peak sits in, counted from the top.
            row = height - 1 - int(min(height - 1, max(0, int(level - 1e-9))))
            if columns[i][row] == " ":
                columns[i][row] = PEAK_GLYPH
    return ["".join(col[row] for col in columns) for row in range(height)]


def downsample(values: Sequence[float], count: int) -> list[float]:
    """Fold `values` down to `count` buckets, keeping the loudest of each.

    Used for the bar widget, which has room for a handful of columns rather
    than the console's full spectrum. Taking the maximum rather than the mean
    keeps a transient visible instead of averaging it away.
    """
    if count < 1:
        raise ValueError("count must be >= 1")
    values = list(values)
    if not values:
        return [0.0] * count
    out = []
    for i in range(count):
        start = i * len(values) // count
        end = max(start + 1, (i + 1) * len(values) // count)
        out.append(max(clamp01(v) for v in values[start:end]))
    return out


def meter_row(value: float, width: int, *, filled: str = "█", empty: str = "░") -> str:
    """A horizontal bar of `width` cells filled to `value`."""
    if width < 0:
        raise ValueError("width must be >= 0")
    count = int(round(clamp01(value) * width))
    return filled * count + empty * (width - count)


def shaded_row(value: float, width: int, *, empty: str = " ") -> str:
    """A horizontal bar with a soft leading edge, for signal-strength readouts."""
    if width < 0:
        raise ValueError("width must be >= 0")
    total = clamp01(value) * width
    out = []
    for i in range(width):
        step = total - i
        if step >= 1:
            out.append(SHADES[4])
        elif step <= 0:
            out.append(empty)
        else:
            out.append(SHADES[max(1, int(round(step * 4)))])
    return "".join(out)


def fmt_time(seconds) -> str:
    """`M:SS`, or `H:MM:SS` past an hour. Unknown or negative reads `--:--`."""
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return "--:--"
    if value != value or value in (float("inf"), float("-inf")) or value < 0:
        return "--:--"
    total = int(value)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return "%d:%02d:%02d" % (hours, minutes, secs)
    return "%d:%02d" % (minutes, secs)


def progress_bar(position, duration, width: int) -> str:
    """Transport bar with a distinct playhead cell."""
    if width < 3:
        raise ValueError("width must be >= 3")
    try:
        pos = max(0.0, float(position))
        dur = float(duration)
    except (TypeError, ValueError):
        pos, dur = 0.0, 0.0
    fraction = clamp01(pos / dur) if dur > 0 else 0.0
    head = int(round(fraction * (width - 1)))
    return "█" * head + "▌" + "░" * (width - head - 1)


def marquee(text: str, width: int, offset: int, separator: str = "   ·   ") -> str:
    """A window onto scrolling text.

    Short text is left alone and padded; long text wraps around through
    `separator` so the loop reads as continuous rather than snapping back.
    """
    text = str(text)
    if width <= 0:
        return ""
    if display_width(text) <= width:
        return pad(text, width)
    loop = text + separator
    chars = list(loop)
    start = int(offset) % len(chars)
    out = []
    used = 0
    i = start
    # Two laps is always enough to fill one window.
    for _ in range(len(chars) * 2):
        ch = chars[i % len(chars)]
        step = display_width(ch)
        if used + step > width:
            break
        out.append(ch)
        used += step
        i += 1
    return "".join(out) + " " * (width - used)


def dial(position: float, width: int, *, ticks: int = 4) -> str:
    """The tuning scale, with a pointer at `position` (0..1)."""
    if width < 5:
        raise ValueError("width must be >= 5")
    cells = ["═"] * width
    for t in range(1, ticks):
        idx = int(round(t * (width - 1) / ticks))
        cells[idx] = "╪"
    cells[0] = "╞"
    cells[-1] = "╡"
    cells[int(round(clamp01(position) * (width - 1)))] = "▼"
    return "".join(cells)


def band_switch(current: str, order: Sequence[str], labels: dict | None = None) -> str:
    """The band selector row; the selected band sits between half-blocks."""
    labels = labels or {}
    parts = []
    for name in order:
        label = str(labels.get(name, name)).upper()
        parts.append("▐%s▌" % label if name == current else " %s " % label)
    return " ".join(parts)


def signal_glyphs(strength: float, count: int = 5) -> str:
    """A stepped signal-strength readout, `▂▄▆█`-style."""
    if count < 1:
        raise ValueError("count must be >= 1")
    lit = int(round(clamp01(strength) * count))
    out = []
    for i in range(count):
        level = int(round((i + 1) / count * 8))
        out.append(BLOCKS[level] if i < lit else "·")
    return "".join(out)


def rule(width: int, *, left: str = BOX["lt"], right: str = BOX["rt"],
         fill: str = BOX["h"], label: str = "") -> str:
    """A horizontal divider, optionally with an inline label."""
    if width < 2:
        raise ValueError("width must be >= 2")
    inner = width - 2
    if not label:
        return left + fill * inner + right
    text = truncate(" %s " % label, inner)
    body = text + fill * (inner - display_width(text))
    return left + body + right


def box(lines: Iterable[str], width: int, *, title: str = "", status: str = "") -> list[str]:
    """Wrap `lines` in a box-drawing frame of exactly `width` cells.

    `title` sits in the top-left of the frame, `status` in the top-right — the
    nameplate and the on-air lamp of the receiver.
    """
    if width < 4:
        raise ValueError("width must be >= 4")
    inner = width - 2
    top_bits = []
    if title:
        top_bits.append(truncate(" %s " % title, inner))
    head = "".join(top_bits)
    if status:
        tag = truncate(" %s " % status, max(0, inner - display_width(head)))
        gap = inner - display_width(head) - display_width(tag)
        head = head + BOX["h"] * max(0, gap) + tag
    head = head + BOX["h"] * max(0, inner - display_width(head))
    out = [BOX["tl"] + head + BOX["tr"]]
    for line in lines:
        out.append(BOX["v"] + pad(line, inner) + BOX["v"])
    out.append(BOX["bl"] + BOX["h"] * inner + BOX["br"])
    return out
