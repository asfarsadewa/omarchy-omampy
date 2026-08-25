// OMAMPY console — the receiver, drawn in block glyphs.
//
// The whole face of the radio arrives from the service as rows of characters
// that are already padded to a fixed width. This file's only jobs are to put
// them on screen in a monospace font, colour each row by what it is, and turn
// clicks and keys into commands.
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Ui

Item {
  id: root

  property var shell: null
  property var manifest: null
  // Handed over by the shell loader when the plugin also declares a service.
  property var service: null

  property bool opened: false

  // Shares the [menu] surface tokens, so a theme that styles the Omarchy
  // menu styles the radio too. The background is forced fully opaque: unlike
  // a popup that flashes past, this panel sits over whatever you are working
  // in, and even slight translucency makes block glyphs hard to read against
  // a page of terminal text showing through them.
  readonly property color background: Util.alpha(Color.menu.background, 1.0)
  readonly property color foreground: Color.menu.text
  readonly property color accent: Color.accent
  readonly property color dim: Color.muted
  readonly property color selected: Color.menu.selectedText

  readonly property string fontFamily: Style.font.menuFamily
  readonly property int fontSize: Style.font.subtitle
  readonly property int pad: Style.spacing.panelPadding

  // Rows are stacked at exactly one character cell apart. Qt's natural line
  // height includes the font's leading, and that gap is enough to break the
  // box-drawing frame into disconnected dashes — the borders have to touch
  // for the receiver to read as one object.
  readonly property int cellHeight: Math.max(1, Math.round(cell.ascent + cell.descent))
  // One character cell wide. The Python side reports click targets in cells,
  // so this is all the arithmetic the UI needs to place them.
  readonly property real cellWidth: cell.advanceWidth("0")

  FontMetrics {
    id: cell
    font.family: root.fontFamily
    font.pixelSize: root.fontSize
  }

  readonly property var rows: service ? service.rows : []

  // Where the card sits. Centred until it is dragged, then wherever it was
  // left — a panel you keep open is a panel you want out of your way.
  property real cardX: 0
  property real cardY: 0
  property bool placed: false
  property real dragOriginX: 0
  property real dragOriginY: 0

  function colorFor(kind) {
    switch (kind) {
    case "spectrum": return root.accent
    case "band": return root.foreground
    case "dial": return root.dim
    case "meter": return root.dim
    case "now": return root.foreground
    case "transport": return root.dim
    default: return root.foreground
    }
  }

  function open(payloadJson) {
    root.opened = true
    if (root.service) root.service.consoleOpen = true
    Qt.callLater(function () { keys.forceActiveFocus() })
  }

  function close() {
    root.opened = false
    if (root.service) root.service.consoleOpen = false
  }

  function dismiss() {
    root.close()
    if (root.shell && typeof root.shell.hide === "function")
      root.shell.hide((root.manifest && root.manifest.id) || "asfarsadewa.omampy")
  }

  function beginDrag() {
    root.dragOriginX = keys.x
    root.dragOriginY = keys.y
    root.placed = true
  }

  // `activeTranslation` is measured from where the drag started, so the new
  // position is always origin plus translation — accumulating it instead
  // would move the card at several times the speed of the pointer.
  function dragTo(translation) {
    var maxX = Math.max(0, window.width - keys.width)
    var maxY = Math.max(0, window.height - keys.height)
    root.cardX = Math.max(0, Math.min(maxX, root.dragOriginX + translation.x))
    root.cardY = Math.max(0, Math.min(maxY, root.dragOriginY + translation.y))
  }

  function act(key) {
    if (!root.service) return false
    switch (key) {
    case "toggle": root.service.toggle(); return true
    case "next": root.service.next(); return true
    case "prev": root.service.previous(); return true
    case "louder": root.service.nudgeVolume(5); return true
    case "quieter": root.service.nudgeVolume(-5); return true
    case "more": root.service.nudgeIntensity(0.1); return true
    case "less": root.service.nudgeIntensity(-0.1); return true
    case "bandUp": root.service.stepBand(1); return true
    case "bandDown": root.service.stepBand(-1); return true
    case "forward": root.service.seek(10); return true
    case "back": root.service.seek(-10); return true
    case "shuffle": root.service.toggleShuffle(); return true
    case "repeat": root.service.cycleRepeat(); return true
    case "rescan": root.service.rescan(); return true
    case "power": root.service.live ? root.service.stop() : root.service.start(); return true
    }
    return false
  }

  // A radio is something you leave on while you work, so this is a floating
  // panel rather than a modal overlay. The surface covers the screen so the
  // card can be dragged anywhere on it, but:
  //
  //   * the input mask is only the card, so every click outside it goes
  //     straight through to whatever window is underneath;
  //   * keyboard focus is on demand, so your terminal keeps the keyboard
  //     until you actually click the radio;
  //   * there is no scrim and no click-anywhere-to-dismiss, which is what
  //     made it vanish the moment you went back to what you were doing.
  //
  // It still sits on the overlay layer, so it stays in front of everything.
  PanelWindow {
    id: window
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "omampy-console"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.OnDemand
    exclusionMode: ExclusionMode.Ignore
    mask: Region { item: keys }

    FocusScope {
      id: keys
      x: root.placed ? root.cardX : Math.round((window.width - width) / 2)
      y: root.placed ? root.cardY : Math.round((window.height - height) / 2)
      width: card.width
      height: card.height
      focus: root.opened

      Keys.onPressed: function (event) {
        switch (event.key) {
        case Qt.Key_Escape:
        case Qt.Key_Q:
          root.dismiss(); event.accepted = true; return
        case Qt.Key_Space:
        case Qt.Key_Return:
        case Qt.Key_Enter:
          event.accepted = root.act("toggle"); return
        case Qt.Key_Right:
          event.accepted = root.act(event.modifiers & Qt.ShiftModifier ? "forward" : "next"); return
        case Qt.Key_Left:
          event.accepted = root.act(event.modifiers & Qt.ShiftModifier ? "back" : "prev"); return
        case Qt.Key_Up:
          event.accepted = root.act("louder"); return
        case Qt.Key_Down:
          event.accepted = root.act("quieter"); return
        case Qt.Key_BracketRight:
          event.accepted = root.act("more"); return
        case Qt.Key_BracketLeft:
          event.accepted = root.act("less"); return
        case Qt.Key_Tab:
          event.accepted = root.act("bandUp"); return
        }

        // Number keys pick a band straight off the switch.
        if (event.key >= Qt.Key_1 && event.key <= Qt.Key_4) {
          var bands = ["mw", "sw", "lw", "fm"]
          if (root.service) root.service.setBand(bands[event.key - Qt.Key_1])
          event.accepted = true
          return
        }

        var letters = { "s": "shuffle", "r": "repeat", "n": "next", "p": "prev",
                        "o": "power", "l": "rescan" }
        var action = letters[String(event.text || "").toLowerCase()]
        if (action) event.accepted = root.act(action)
      }

      Rectangle {
        id: card
        width: column.width + root.pad * 2
        height: column.height + root.pad * 2
        color: root.background
        radius: Style.cornerRadius

        MouseArea {
          anchors.fill: parent
          acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
          onWheel: function (wheel) {
            root.act(wheel.angleDelta.y > 0 ? "louder" : "quieter")
          }
          // Clicking the panel is also how it takes the keyboard, since the
          // compositor only hands focus over on demand.
          onPressed: keys.forceActiveFocus()
        }


        Column {
          id: column
          x: root.pad
          y: root.pad
          spacing: 0

          Text {
            id: topRule
            text: root.service ? root.service.topRule : ""
            textFormat: Text.PlainText
            font.family: root.fontFamily
            font.pixelSize: root.fontSize
            color: root.accent
            height: root.cellHeight
            verticalAlignment: Text.AlignVCenter
          }

          // The model is the row *count*, not the row array. A new frame
          // arrives twenty times a second and each one is a fresh array, so
          // binding to it directly would destroy and rebuild every delegate —
          // and every MouseArea in them — at 20 Hz. The cursor flickered and
          // a press and its release landed on different objects, so nothing
          // could be clicked. Bound to the count, the delegates persist and
          // only their text changes.
          Repeater {
            model: root.rows.length

            delegate: Item {
              id: rowItem
              required property int index
              readonly property var row: root.rows[index] || ({})

              width: line.implicitWidth
              height: root.cellHeight

              Text {
                id: line
                anchors.fill: parent
                verticalAlignment: Text.AlignVCenter
                // Plain text, always. These rows carry file names and tags,
                // and QML's default AutoText sniffs a string for markup and
                // will load remote resources out of a crafted one.
                text: "│" + (rowItem.row.text || "") + "│"
                textFormat: Text.PlainText
                font.family: root.fontFamily
                font.pixelSize: root.fontSize
                color: rowItem.row.kind === "track" && rowItem.row.current
                  ? root.selected
                  : root.colorFor(rowItem.row.kind)
              }

              // A track row is a jump: the index it carries is its playlist
              // position.
              MouseArea {
                anchors.fill: parent
                enabled: rowItem.row.kind === "track"
                cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: if (root.service) root.service.playIndex(rowItem.row.index)
              }

              // The band switch is a real switch — each label is its own
              // target, placed from the cell offsets Python measured.
              Repeater {
                model: rowItem.row.kind === "band" && root.service
                  ? root.service.bandTargets.length : 0

                delegate: MouseArea {
                  required property int index
                  readonly property var hit: root.service.bandTargets[index]
                    || ({ start: 0, width: 0, band: "" })
                  x: hit.start * root.cellWidth
                  width: Math.max(root.cellWidth, hit.width * root.cellWidth)
                  height: rowItem.height
                  cursorShape: Qt.PointingHandCursor
                  onClicked: if (root.service && hit.band) root.service.setBand(hit.band)
                }
              }

              // Clicking along the transport bar seeks to that point.
              MouseArea {
                id: scrub
                readonly property var target: root.service ? root.service.transportTarget : ({})
                enabled: rowItem.row.kind === "transport" && target.width > 0
                visible: enabled
                x: (target.start || 0) * root.cellWidth
                width: Math.max(1, (target.width || 0) * root.cellWidth)
                height: rowItem.height
                cursorShape: Qt.PointingHandCursor
                onClicked: function (mouse) {
                  if (!root.service) return
                  var duration = root.service.trackDuration
                  if (duration <= 0) return
                  root.service.seekTo(Math.max(0, mouse.x / scrub.width) * duration)
                }
              }
            }
          }

          Text {
            text: root.service ? root.service.bottomRule : ""
            textFormat: Text.PlainText
            font.family: root.fontFamily
            font.pixelSize: root.fontSize
            color: root.accent
            height: root.cellHeight
            verticalAlignment: Text.AlignVCenter
          }

          Item { width: 1; height: Style.spacing.sm }

          // Bound to the frame's own width rather than the column's, which
          // would otherwise depend on this label and elide it to nothing.
          Text {
            // Sized to the frame: each line fits the 52-cell console width,
            // so the caption never wraps out from under the receiver.
            // The last line spells out the difference between hiding the
            // panel and switching the radio off. "q close" on its own reads
            // like a stop button, and then a receiver you thought you had
            // closed carries on playing with nothing on screen to stop it.
            text: "click a band, the bar or a track · drag · scroll=vol"
                + "\nspace play · ◂▸ track · ▴▾ volume · [ ] static"
                + "\n1-4 band · s shuffle · r repeat · o radio on/off"
                + "\nq hides this panel — the radio keeps playing"
            textFormat: Text.PlainText
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            color: root.dim
            width: topRule.implicitWidth
            wrapMode: Text.WordWrap
            lineHeight: 1.3
          }
        }

        // Drag by the nameplate, the way a window is dragged by its title
        // bar. A drag handler across the whole card would sit over every row
        // and fight them for the cursor shape.
        Item {
          width: card.width
          height: root.pad + root.cellHeight

          DragHandler {
            target: null
            cursorShape: Qt.SizeAllCursor
            onActiveChanged: if (active) root.beginDrag()
            onTranslationChanged: if (active) root.dragTo(activeTranslation)
          }
        }
      }
    }
  }
}
