// OMAMPY service — the shell's link to the receiver.
//
// Everything the UI shows is drawn by the Python CLI and arrives here as one
// JSON object per frame on a long-running `omampy watch`. Nothing in the QML
// layer computes a bar height or a text width; it paints rows and sends
// commands. That keeps the console honest about being made of characters, and
// keeps the parts worth testing out of QML.
import QtQuick
import Quickshell
import Quickshell.Io

Item {
  id: root

  // Injected by the shell when the plugin loads.
  property var shell: null
  property var manifest: null

  // ------------------------------------------------------------- location

  // The registry stamps the checkout path onto the manifest; resolving the
  // QML url is the fallback for a hand-dropped plugin directory.
  readonly property string pluginDir: {
    if (manifest && manifest.__sourceDir) return String(manifest.__sourceDir)
    var here = Qt.resolvedUrl(".").toString()
    if (here.indexOf("file://") === 0) here = here.substring(7)
    return here.replace(/\/$/, "").replace(/\/qml$/, "")
  }
  readonly property string cli: pluginDir + "/bin/omampy"
  readonly property string pluginId: (manifest && manifest.id) ? String(manifest.id) : "asfarsadewa.omampy"

  // ---------------------------------------------------------------- shape

  // Console dimensions, in character cells. The watcher draws to these, so
  // changing one restarts the stream rather than reflowing anything here.
  property int consoleWidth: 52
  property int spectrumHeight: 9
  property int playlistRows: 6

  // The console overlay raises this while it is on screen. A closed console
  // only needs enough frames to keep the bar widget's meter alive.
  property bool consoleOpen: false
  readonly property int frameRate: consoleOpen ? 20 : 6

  // ---------------------------------------------------------------- state

  property var frame: ({})
  property var status: ({})

  readonly property string playerState: status.state ? String(status.state) : "stopped"
  readonly property bool onAir: playerState === "playing"
  readonly property bool live: status.running === true
  readonly property string trackTitle: status.title ? String(status.title) : ""
  readonly property string trackArtist: status.artist ? String(status.artist) : ""
  readonly property string trackDisplay: status.display ? String(status.display) : ""
  readonly property string bandLabel: status.bandLabel ? String(status.bandLabel) : ""
  readonly property string statusTag: frame.statusTag ? String(frame.statusTag) : ""
  readonly property string mini: frame.mini ? String(frame.mini) : ""
  readonly property var rows: frame.rows ? frame.rows : []
  readonly property var bandTargets: frame.bandTargets ? frame.bandTargets : []
  readonly property var transportTarget: frame.transportTarget ? frame.transportTarget : ({})
  readonly property real trackDuration: status.duration ? Number(status.duration) : 0
  readonly property string topRule: frame.top ? String(frame.top) : ""
  readonly property string bottomRule: frame.bottom ? String(frame.bottom) : ""
  readonly property string tooltip: frame.lines ? frame.lines.join("\n") : ""

  // -------------------------------------------------------------- actions

  // Every command is fire-and-forget: the watcher reports the result a frame
  // later, so there is nothing to wait for and nothing to keep in sync.
  function run(args) {
    if (!cli) return
    Quickshell.execDetached([cli].concat(args))
  }

  function start() { run(["start"]) }
  function stop() { run(["stop"]) }
  function toggle() { run(["toggle"]) }
  function next() { run(["next"]) }
  function previous() { run(["prev"]) }
  function playIndex(index) { run(["play", String(Math.max(0, index))]) }
  function seek(seconds) { run(["seek", String(seconds)]) }
  function seekTo(seconds) { run(["seek", String(Math.max(0, seconds)), "--absolute"]) }
  function nudgeVolume(step) { run(["volume", (step >= 0 ? "+" : "") + String(step)]) }
  function setBand(name) { run(["band", String(name)]) }
  function stepBand(direction) { run(["band", direction >= 0 ? "--next" : "--prev"]) }
  function nudgeIntensity(step) { run(["intensity", (step >= 0 ? "+" : "") + String(step)]) }
  function cycleRepeat() { run(["repeat", "--cycle"]) }
  function toggleShuffle() { run(["shuffle"]) }
  function rescan() { run(["scan"]) }

  // Starting the receiver on the first summon means the plugin costs nothing
  // until someone actually opens it.
  function openConsole() {
    if (!live) start()
    if (shell && typeof shell.summon === "function") shell.summon(pluginId, "{}")
  }

  function closeConsole() {
    if (shell && typeof shell.hide === "function") shell.hide(pluginId)
  }

  function toggleConsole() {
    if (consoleOpen) closeConsole()
    else openConsole()
  }

  // ------------------------------------------------------------- watching

  function ingest(line) {
    var text = String(line || "").trim()
    if (text === "") return
    var parsed
    try {
      parsed = JSON.parse(text)
    } catch (e) {
      return
    }
    if (!parsed || typeof parsed !== "object") return
    root.frame = parsed
    root.status = parsed.status || ({})
  }

  function restartWatcher() {
    watcher.running = false
    reviveTimer.restart()
  }

  onFrameRateChanged: root.restartWatcher()
  onConsoleWidthChanged: root.restartWatcher()
  onSpectrumHeightChanged: root.restartWatcher()
  onPlaylistRowsChanged: root.restartWatcher()

  Process {
    id: watcher
    running: root.cli !== ""
    command: [root.cli, "watch",
              "--hz", String(root.frameRate),
              "--width", String(root.consoleWidth),
              "--height", String(root.spectrumHeight),
              "--rows", String(root.playlistRows)]
    stdout: SplitParser {
      onRead: function (line) { root.ingest(line) }
    }
    // The watcher only exits if the CLI is missing or was killed; either way
    // a slow retry keeps the bar widget from spinning on a broken checkout.
    onExited: reviveTimer.restart()
  }

  Timer {
    id: reviveTimer
    interval: 1200
    onTriggered: if (!watcher.running) watcher.running = true
  }

  // Lets keybinds and scripts drive the radio:
  //   omarchy-shell omampy toggle
  //   omarchy-shell omampy band sw
  IpcHandler {
    target: "omampy"

    function toggle(): void { root.toggle() }
    function next(): void { root.next() }
    function prev(): void { root.previous() }
    function start(): void { root.start() }
    function stop(): void { root.stop() }
    function band(name: string): void { root.setBand(name) }
    function intensity(step: string): void { root.run(["intensity", step]) }
    function volume(step: string): void { root.run(["volume", step]) }
    function show(): void { root.openConsole() }
    function hide(): void { root.closeConsole() }
    function panel(): void { root.toggleConsole() }
    function state(): string { return JSON.stringify(root.status) }
  }
}
