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
  // menu styles the radio too.
  readonly property color background: Color.menu.background
  readonly property color foreground: Color.menu.text
  readonly property color scrim: Color.menu.scrim
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

  FontMetrics {
    id: cell
    font.family: root.fontFamily
    font.pixelSize: root.fontSize
  }

  readonly property var rows: service ? service.rows : []

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

  PanelWindow {
    id: window
    visible: root.opened
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"
    WlrLayershell.namespace: "omampy-console"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    exclusionMode: ExclusionMode.Ignore

    Rectangle {
      anchors.fill: parent
      color: root.scrim
    }

    MouseArea {
      anchors.fill: parent
      onClicked: root.dismiss()
    }

    FocusScope {
      id: keys
      anchors.centerIn: parent
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

        // Swallow clicks so they do not reach the dismiss layer underneath.
        MouseArea {
          anchors.fill: parent
          acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
          onWheel: function (wheel) {
            root.act(wheel.angleDelta.y > 0 ? "louder" : "quieter")
          }
        }

        Column {
          id: column
          x: root.pad
          y: root.pad
          spacing: 0

          Text {
            id: topRule
            text: root.service ? root.service.topRule : ""
            font.family: root.fontFamily
            font.pixelSize: root.fontSize
            color: root.accent
            height: root.cellHeight
            verticalAlignment: Text.AlignVCenter
          }

          Repeater {
            model: root.rows

            delegate: Item {
              required property var modelData
              required property int index

              width: line.implicitWidth
              height: root.cellHeight

              Text {
                id: line
                anchors.fill: parent
                verticalAlignment: Text.AlignVCenter
                text: "│" + (modelData.text || "") + "│"
                font.family: root.fontFamily
                font.pixelSize: root.fontSize
                color: modelData.kind === "track" && modelData.current
                  ? root.selected
                  : root.colorFor(modelData.kind)
              }

              // Track rows are the only clickable ones; the number a row
              // carries is the playlist position, so a click is a jump.
              MouseArea {
                anchors.fill: parent
                enabled: modelData.kind === "track"
                cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: if (root.service) root.service.playIndex(modelData.index)
              }
            }
          }

          Text {
            text: root.service ? root.service.bottomRule : ""
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
            text: "space play · ◂▸ track · ⇧◂▸ seek · ▴▾ volume · [ ] static\n1-4 band · tab next band · s shuffle · r repeat · o power · q close"
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            color: root.dim
            width: topRule.implicitWidth
            wrapMode: Text.WordWrap
            lineHeight: 1.3
          }
        }
      }
    }
  }
}
