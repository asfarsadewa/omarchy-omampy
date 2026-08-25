# OMAMPY

An Omarchy shell plugin that plays your local audio files through a 1980s
AM/shortwave receiver — band-limited, soft-clipped, drifting in and out, with
hiss and crackle riding underneath — and draws the whole radio in block glyphs.

```
┌ OMAMPY ──────────────────────────────── ◉ ON AIR ┐
│                    ▁▅▔ ▔                         │
│                   ▔██▁ ▆▔  ▔                     │
│                   ▃███▔█▅ ▔█                     │
│                  ▔████▅██▔██▁ ▔                  │
│                  ▄███████▇███▔▄                  │
│                  ██████████████                  │
│                  ██████████████                  │
│                                                  │
│BAND  MW  ▐SW▌  LW   FM                           │
│TUNE ╞═══════╪══▼═════╪════════╪═══════╡  9.75 MHz│
│SIG  ████████████▒···  VOL ██████████░░░░░░       │
│INT  ███████████░░░░░  70%                        │
│                                                  │
│▶ Visage — Fade To Grey                           │
│  1:23 ██████████████▌░░░░░░░░░░░░░░░░░░░░░░░ 3:40│
│                                                  │
│  01 Trio — Da Da Da                              │
│▶ 02 Visage — Fade To Grey                        │
│  03 Yello — Bostich                              │
└──────────────────────────────────────────────────┘
```

The spectrum is not decoration. Every bar is a real RMS measurement taken from
the audio after it has been through the radio, so what you see is what you
hear.

**Local files only.** OMAMPY has no network code of any kind — no streaming, no
lookups, no telemetry. It reads a directory of your own files and plays them.

## Requirements

- Omarchy with `omarchy-shell` (Quickshell)
- `mpv` — does all the decoding, filtering, and playback
- Python 3.11+ — **standard library only**, no pip install, no virtualenv

Both are already on a stock Omarchy machine.

## Install

```bash
omarchy plugin add https://github.com/asfarsadewa/omarchy-omampy.git
omarchy plugin enable asfarsadewa.omampy right
```

Point it at your music and turn it on:

```bash
~/.config/omarchy/plugins/asfarsadewa.omampy/bin/omampy doctor
omarchy-shell omampy show
```

The bar widget appears on the right of the bar. Click it to open the console,
right-click to play/pause, middle-click to skip, scroll to change volume.

## The bands

| Band | What it is | Passband | Character |
|------|-----------|----------|-----------|
| `MW` | Medium wave | 200–4500 Hz | The wide, warm broadcast sound. Mild drift, occasional crackle. |
| `SW` | Shortwave | 350–2800 Hz | Narrow, driven harder, deep fading, static all the way through. |
| `LW` | Long wave | 150–2000 Hz | Muffled and distant, with 50 Hz mains hum leaking in. |
| `FM` | Line in | — | No processing at all. Stereo, full bandwidth. Useful for A/B. |

`intensity` (0–1) scales the fading, the hiss, and the crackle together. At `0`
you get the band-limiting and saturation with none of the noise; at `1` the
station is barely holding on.

## Console keys

| Key | Does |
|-----|------|
| `space` | play / pause |
| `◂` `▸` | previous / next track |
| `⇧◂` `⇧▸` | seek 10s |
| `▴` `▾` | volume |
| `[` `]` | less / more static |
| `1`–`4` | pick a band directly |
| `tab` | next band |
| `s` / `r` | shuffle / repeat mode |
| `o` | receiver on/off |
| `q` or `esc` | close |

Clicking a row in the track list jumps to it.

## Configuration

`~/.config/omampy/config.json` — anything you leave out keeps its default:

```json
{
  "library": ["~/Music"],
  "recursive": true,
  "band": "sw",
  "intensity": 0.7,
  "seed": 1980,
  "volume": 60,
  "shuffle": false,
  "repeat": "all",
  "meter_bands": 14,
  "meter_height": 8,
  "mpv": "mpv"
}
```

`seed` pins the noise: the same seed always generates exactly the same hiss and
the same crackles, which makes an A/B comparison meaningful.

Changes you make from the console (band, intensity, volume, …) are written to
`~/.local/state/omampy/state.json` and take precedence, so `config.json` stays
as the settings you actually chose to write down.

## Command line

The plugin's UI is a thin client over a CLI you can also use on its own:

```bash
omampy start | stop | toggle | next | prev | play [INDEX]
omampy band sw | --next | --prev      # switch bands
omampy intensity 0.8 | +0.1           # how rough the reception is
omampy volume 70 | +5
omampy seek -10 | 90 --absolute
omampy repeat one | --cycle
omampy shuffle on | off
omampy scan [DIR...]                  # rebuild the playlist
omampy status [--json | --ascii]      # --ascii draws the console in your terminal
omampy watch --hz 20                  # stream console frames as NDJSON
omampy chain --band sw [--af]         # print the libavfilter graph
omampy bed --band sw                  # generate the cached noise bed
omampy doctor                         # check mpv, the library, and the socket
```

`omampy status --ascii` in a terminal draws the same receiver, live spectrum
and all.

## Keybindings

The shell exposes an `omampy` IPC target, so you can bind whatever you like in
`~/.config/hypr/bindings.conf`:

```
bindd = SUPER, R, Radio, exec, omarchy-shell omampy panel
bindd = SUPER SHIFT, R, Radio play/pause, exec, omarchy-shell omampy toggle
bindd = , XF86AudioNext, Radio next, exec, omarchy-shell omampy next
```

## How it works

```
files ──▶ mpv ──▶ [ libavfilter graph ] ──▶ speakers
                        │
                        ├── downmix to mono @ 22.05 kHz
                        ├── high-shelf tilt, 6-pole passband
                        ├── tanh soft-clip (the transmitter running hot)
                        ├── slow tremolo (the signal wandering)
                        ├── mix the looping noise bed
                        ├── compress + limit
                        └── probe ──▶ 14 band-splits ──▶ astats
                                                          │
                          af-metadata/omampy ◀────────────┘
                                    │
                            omampy watch ──▶ NDJSON ──▶ the console
```

Three decisions worth knowing about:

**mpv does the audio, Python does the thinking.** Nothing here decodes or
resamples anything. The Python side builds one libavfilter graph, hands it to
mpv, and reads measurements back. That is why there are no dependencies.

**The metering rides the control socket.** The probe splits the finished audio
into bands and merges them *alongside* an untouched copy of the signal, so one
`astats` measures all of them at once and a final `pan` selects the real audio
back out. Because the measurement lands on the filter's own output frames, mpv
publishes it on `af-metadata/omampy` — the same socket that carries play and
pause. No fifo, no second process, and nothing that can stall the audio thread
if the console goes away.

**The static is synthesised in Python, not ffmpeg.** ffmpeg has no good way to
produce Poisson-distributed crackle, so the noise bed — band-limited hiss,
exponential crackle bursts, and mains hum on long wave — is generated in plain
Python, crossfaded so it loops without a seam, cached as a WAV, and mixed in by
`amovie`. It costs nothing at playback time and it is a thing a test can pin
down exactly.

**Everything you see is text.** The spectrum, the tuning scale, the meters, the
transport bar, the track list — all of it is rendered to strings by Python and
padded to an exact character width. The QML paints rows and colours them; it
does not compute a single bar height. That is what keeps the layout testable.

## Tests

```bash
./scripts/test
```

448 tests, standard library `unittest`, no audio device and no mpv required.
They cover every deterministic part: the band models, the filtergraph builder
(including the two-level ffmpeg escaping, verified against real ffmpeg), the
noise-bed synthesis and its determinism, the metering maths, every drawing
primitive down to the exact character, filename parsing, playlist ordering,
settings validation, the mpv IPC protocol against a scripted socket, and the
command line against an isolated environment.

## Development

Work on it in place by symlinking the checkout:

```bash
ln -sfn "$PWD" ~/.config/omarchy/plugins/asfarsadewa.omampy
omarchy-shell shell rescanPlugins
```

Saving a QML file reloads it. A QML file that fails to parse will not reload
from cache — restart with `omarchy-restart-shell` after fixing it. Load errors
show up in `journalctl --user -f | grep omampy`.

## Credits

The effect model — passbands, drive, fade depth, hiss level, crackle rate — is
carried over from [`make-radio-sound`](https://github.com/asfarsadewa), an
offline renderer that did the same thing to a file with numpy and scipy. This
plugin does it live, with no dependencies, and adds the metering, the bands,
and the receiver.

## License

MIT
