# OMAMPY

OMAMPY is a plugin for the Omarchy shell. It plays audio files from a local
directory. It applies an audio effect to these files. The effect makes the
sound like a radio broadcast of the 1980s. The plugin draws its display with
block characters.

OMAMPY does not use the network. It does not stream audio. It does not send
data to a remote system.

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

The display shows the measured level of the audio. The plugin measures the
audio after the effect. Each bar shows the level of one frequency band.

## Terminology

| Term | Definition |
|------|------------|
| The receiver | The mpv process. It plays and filters the audio. |
| The panel | The large display. It floats above the other windows. |
| The bar widget | The small display in the Omarchy bar. |
| A band | One position of the band selector. It sets the audio effect. |
| The noise bed | An audio file of hiss and crackle. The receiver mixes it with the music. |
| The intensity | A value from 0 to 1. It sets the level of the noise and the level changes. |

## Requirements

| Item | Function |
|------|----------|
| Omarchy 4 (Quattro), with `omarchy-shell` | Hosts the plugin. |
| `mpv` | Decodes, filters and plays the audio. |
| Python 3.11 or a later version | Runs the command-line program. |

Omarchy supplies mpv and Python. The Python code uses only the standard
library. Do not install Python packages.

## Installation

1. Add the plugin and enable it:

   ```bash
   omarchy plugin add https://github.com/asfarsadewa/omarchy-omampy.git --enable
   ```

   This is the command that the marketplace shows. The `--enable` option
   enables the plugin immediately.

   To read the code before the plugin runs, do not use the `--enable` option.
   The plugin then stays disabled. Enable it later with this command:

   ```bash
   omarchy plugin enable asfarsadewa.omampy right
   ```

2. Put audio files in the `~/Music` directory. To use a different directory,
   refer to "Configuration".

3. Do a check of the installation:

   ```bash
   ~/.config/omarchy/plugins/asfarsadewa.omampy/bin/omampy doctor
   ```

   The command shows the location of mpv, the audio directory and the socket.

4. Open the panel:

   ```bash
   omarchy-shell omampy panel
   ```

The bar widget shows at the right end of the bar.

## Removal

1. Disable the plugin:

   ```bash
   omarchy plugin disable asfarsadewa.omampy
   ```

2. Remove the plugin files:

   ```bash
   omarchy plugin remove asfarsadewa.omampy
   ```

3. To delete the data of the plugin, remove these directories:

   ```bash
   rm -rf ~/.config/omampy ~/.cache/omampy ~/.local/state/omampy
   ```

OMAMPY writes files only in these three directories. It does not change the
Omarchy configuration, the mpv configuration or the audio files.

## Operation

### The panel and the receiver

The panel and the receiver are independent. The receiver continues to
play after the panel closes.

NOTE: The panel floats above the other windows. A click outside the panel
goes to the window below it. The panel does not close after such a click.

NOTE: The panel takes the keyboard only after a click on the panel. Before
that click, the keyboard stays with the previous window. All of the primary
controls also operate with the mouse.

| Task | Action |
|------|--------|
| Open the panel | Click the bar widget, or run `omarchy-shell omampy panel` |
| Hide the panel | Push `q` or `esc`. The receiver continues to play. |
| Pause the audio | Push `space`, or click the bar widget with the right button. |
| Turn the receiver off | Push `o`, or run `omarchy-shell omampy stop` |
| Turn the receiver on | Push `o`, or open the panel. |

If the receiver is off when the panel opens, the panel turns the receiver
on and the audio starts. If the receiver is already on, the panel does not
change the audio.

The top line of the panel shows the state of the receiver: `◉ ON AIR`,
`▮▮ PAUSED`, `○ STANDBY` or `○ OFF AIR`.

### Controls with the mouse

| Action | Result |
|--------|--------|
| Click a band label | Selects that band. |
| Click the transport bar | Moves to that position in the audio file. |
| Click a line of the file list | Plays that file. |
| Drag the top edge of the panel | Moves the panel. |
| Turn the scroll wheel on the panel | Changes the volume. |

### Controls with the keyboard

Click the panel to use these keys.

| Key | Result |
|-----|--------|
| `space` | Starts or pauses the audio. |
| `◂` `▸` | Selects the previous or the next file. |
| `⇧◂` `⇧▸` | Moves 10 seconds back or forward. |
| `▴` `▾` | Changes the volume. |
| `[` `]` | Decreases or increases the intensity. |
| `1` to `4` | Selects the MW, SW, LW or FM band. |
| `tab` | Selects the next band. |
| `s` | Turns the random order on or off. |
| `r` | Changes the repeat mode. |
| `o` | Turns the receiver on or off. |
| `q` or `esc` | Hides the panel. |

### Controls of the bar widget

| Action | Result |
|--------|--------|
| Click with the left button | Shows or hides the panel. |
| Click with the right button | Starts or pauses the audio. |
| Click with the middle button | Selects the next file. |
| Turn the scroll wheel | Changes the volume. |

## The bands

| Band | Name | Passband | Effect |
|------|------|----------|--------|
| `MW` | Medium wave | 200 Hz to 4500 Hz | Small level changes. Few crackles. |
| `SW` | Shortwave | 350 Hz to 2800 Hz | Large level changes. More crackles. More distortion. |
| `LW` | Long wave | 150 Hz to 2000 Hz | Adds a 50 Hz hum. |
| `FM` | Line in | Full bandwidth | No effect. The audio does not change. The output is stereo. |

The MW, SW and LW bands give a mono output at 22050 Hz. These bands apply a
passband filter, a soft-clip distortion, a slow level change, a noise bed and
an automatic gain control.

The intensity value sets the level of the noise and the level changes. At an
intensity of 0, the receiver applies the passband filter and the distortion,
but it adds no noise. At an intensity of 1, the noise is at its maximum.

Use the FM band to hear the audio without an effect.

## Configuration

The configuration file is `~/.config/omampy/config.json`. The plugin does not
create this file. Make the file to change a default value. The plugin uses the
default value for each field that the file does not contain.

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

| Field | Type | Function |
|-------|------|----------|
| `library` | List of directories | The directories that contain the audio files. |
| `recursive` | `true` or `false` | Includes the subdirectories in the search. |
| `band` | `mw`, `sw`, `lw` or `fm` | The band at the start. |
| `intensity` | 0 to 1 | The level of the noise and the level changes. |
| `seed` | Integer | The seed of the noise bed. The same seed gives the same noise. |
| `volume` | 0 to 130 | The volume at the start. |
| `shuffle` | `true` or `false` | Puts the files in a random order. |
| `repeat` | `off`, `one` or `all` | The repeat mode. |
| `meter_bands` | 4 to 32 | The quantity of bars in the display. |
| `meter_height` | 3 to 24 | The height of the display in characters. |
| `mpv` | Command name or path | The mpv program to use. |

The plugin writes the changes from the panel to
`~/.local/state/omampy/state.json`. The values in this file have a higher
priority than the values in `config.json`.

## The command-line program

The panel sends its commands to a command-line program. The program is at
`bin/omampy` in the plugin directory. The program also operates directly
from a terminal.

| Command | Function |
|---------|----------|
| `omampy start` | Turns the receiver on. |
| `omampy stop` | Turns the receiver off. |
| `omampy toggle` | Starts or pauses the audio. |
| `omampy next` / `omampy prev` | Selects the next or the previous file. |
| `omampy play [INDEX]` | Plays the file at this position in the list. |
| `omampy seek SECONDS [--absolute]` | Moves in the audio file. |
| `omampy band NAME` | Selects a band. Use `--next` or `--prev` to move one position. |
| `omampy intensity VALUE` | Sets the intensity. A value with a sign is relative. |
| `omampy volume VALUE` | Sets the volume. A value with a sign is relative. |
| `omampy repeat MODE` | Sets the repeat mode. Use `--cycle` to select the next mode. |
| `omampy shuffle on\|off` | Turns the random order on or off. |
| `omampy scan [DIR...]` | Makes the file list again. |
| `omampy status [--json\|--ascii]` | Shows the state of the receiver. |
| `omampy watch [--hz N]` | Sends the display data as one JSON object for each frame. |
| `omampy chain [--band NAME]` | Shows the libavfilter graph. |
| `omampy bed [--band NAME]` | Makes the noise bed file. |
| `omampy doctor` | Does a check of mpv, the audio directory and the socket. |

The `--ascii` option of the `status` command draws the panel in the terminal.
The display shows the measured levels of the audio.

The exit codes are 0 for success, 2 for an incorrect command, and 3 when the
receiver is not available.

## Keyboard shortcuts in Hyprland

The plugin supplies an IPC target with the name `omampy`. Add the necessary
shortcuts to `~/.config/hypr/bindings.conf`:

```
bindd = SUPER, R, Radio, exec, omarchy-shell omampy panel
bindd = SUPER SHIFT, R, Radio play or pause, exec, omarchy-shell omampy toggle
bindd = , XF86AudioNext, Radio next file, exec, omarchy-shell omampy next
```

The IPC target accepts these methods: `panel`, `show`, `hide`, `toggle`,
`next`, `prev`, `start`, `stop`, `band`, `intensity`, `volume` and `state`.

The IPC methods do not print a result. To see error messages, use the
command-line program.

## Technical description

```
files ──▶ mpv ──▶ [ libavfilter graph ] ──▶ audio output
                        │
                        ├── mono downmix at 22050 Hz
                        ├── high-shelf filter, 6-pole passband
                        ├── tanh soft-clip distortion
                        ├── slow tremolo
                        ├── mix of the noise bed
                        ├── compressor and limiter
                        └── probe ──▶ 14 band filters ──▶ astats
                                                            │
                          af-metadata/omampy ◀──────────────┘
                                    │
                            omampy watch ──▶ JSON ──▶ the panel
```

### The audio processing

The Python code does not decode, resample or filter audio. It makes one
libavfilter graph as a text string. It gives this string to mpv. mpv does all
of the audio work. This is the reason that the plugin has no dependencies.

### The measurement method

The graph divides the output audio into 14 frequency bands. It merges these
bands with an unchanged copy of the audio into one frame. One `astats` filter
measures all of the channels at the same time. A `pan` filter then selects the
unchanged channels for the output.

The measurement is on the output frames of the filter. Therefore mpv makes it
available on the `af-metadata/omampy` property. The plugin reads this property
on the socket that also carries the play and pause commands.

An alternative method is a fifo. The plugin does not use a fifo, because mpv
stops the audio if no program reads the fifo.

### The noise bed

ffmpeg cannot make crackle with a Poisson distribution. Therefore the Python
code makes the noise bed. The noise bed contains band-limited hiss, crackle
pulses of an exponential shape, and a mains hum for the long wave band.

The Python code applies a crossfade to the end of the file. The file thus
loops without a click. The plugin writes the file to the cache directory. The
`amovie` filter loops the file during playback.

The same seed always gives the same noise bed.

### The display text

The Python code draws the display. It sets each line to an exact quantity of
characters. The QML code shows the lines and applies a color to each line. The
QML code does not calculate the height of a bar.

The Python code also reports the character positions of the band labels and
the transport bar. The QML code multiplies these positions by the width of one
character. The click areas are thus a function of the drawn text, and a test
can do a check of them.

## Tests

Run the tests:

```bash
./scripts/test
```

The tests use the `unittest` module of the Python standard library. The tests
do not need mpv, an audio device or a network connection. There are 497 tests.

The tests examine these items:

- the band data
- the libavfilter graph, and the two-level escape sequences of ffmpeg
- the noise bed, and its repeatability for a given seed
- the calculation of the levels
- each drawing function, character by character
- the analysis of file names
- the sequence of the file list
- the validation of the configuration
- the mpv IPC protocol, against a test socket
- the command-line program, in a temporary directory

## Development

To make changes, make a symbolic link to the local copy:

```bash
ln -sfn "$PWD" ~/.config/omarchy/plugins/asfarsadewa.omampy
omarchy-shell shell rescanPlugins
```

The shell loads a QML file again after a save. If a QML file has a syntax
error, the shell keeps the previous version in its cache. Correct the error,
then run `omarchy-restart-shell`.

To see the errors of the plugin:

```bash
journalctl --user -f | grep omampy
```

## Credits

The values of the audio effect come from
[`make-radio-sound`](https://github.com/asfarsadewa/make-radio-sound). That
program applies the same effect to a file with numpy and scipy. OMAMPY applies
the effect during playback, without these packages. OMAMPY adds the
measurement, the bands and the display.

## License

MIT. Refer to the `LICENSE` file.
