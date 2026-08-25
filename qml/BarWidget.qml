// OMAMPY bar widget — a working VU meter in the width of a few characters.
//
// The block glyphs come straight from the service's frame, so the little
// meter in the bar is driven by the same measurement as the full console.
import QtQuick
import Quickshell
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "asfarsadewa.omampy"

  readonly property var service: bar && bar.shell && typeof bar.shell.serviceFor === "function"
    ? bar.shell.serviceFor("asfarsadewa.omampy")
    : null

  readonly property bool live: service ? service.live : false
  readonly property bool onAir: service ? service.onAir : false
  readonly property string meter: service ? service.mini : ""
  readonly property string label: service ? service.trackDisplay : ""
  readonly property string band: service ? service.bandLabel : ""

  // Off air the widget collapses to its power glyph rather than holding open
  // a slot of empty meter.
  readonly property real maxLabelWidth: Style.space(160)

  implicitWidth: row.implicitWidth + Style.space(12)
  implicitHeight: barSize

  Row {
    id: row
    anchors.centerIn: parent
    spacing: Style.space(6)

    // The receiver itself, in the bar's icon font. The glyph never changes:
    // it is how the widget is recognised among the others. State is in the
    // colour, and in the meter and title beside it, which are hidden when
    // the receiver is off.
    Text {
      anchors.verticalCenter: parent.verticalCenter
      // U+F0439 nf-md-radio, embedded directly: it is above the BMP, and a
      // \u escape takes only four hex digits.
      text: "󰐹"
      color: root.onAir
        ? root.bar.barForeground
        : Qt.darker(root.bar.barForeground, root.live ? 1.35 : 2.0)
      font.family: root.bar.fontFamily
      font.pixelSize: Style.bar.iconFont
      Behavior on color {
        enabled: !root.bar || root.bar.foregroundAnimationEnabled
        ColorAnimation { duration: 160 }
      }
    }

    Text {
      anchors.verticalCenter: parent.verticalCenter
      // Only while the audio plays. A paused meter decays to blank
      // characters, which held its width open as an empty gap.
      visible: root.onAir && root.meter !== ""
      text: root.meter
      color: root.bar.barForeground
      font.family: root.bar.fontFamily
      font.pixelSize: Style.font.body
    }

    Text {
      anchors.verticalCenter: parent.verticalCenter
      visible: root.live && root.band !== "" && !root.bar.vertical
      text: root.band
      color: Qt.darker(root.bar.barForeground, 1.4)
      font.family: root.bar.fontFamily
      font.pixelSize: Style.font.caption
    }

    Item {
      id: clip
      anchors.verticalCenter: parent.verticalCenter
      visible: root.live && root.label !== "" && !root.bar.vertical
      width: Math.min(root.maxLabelWidth, title.implicitWidth)
      height: title.implicitHeight
      clip: true

      Text {
        id: title
        text: root.label
        color: root.bar.barForeground
        font.family: root.bar.fontFamily
        font.pixelSize: Style.font.body

        readonly property bool needsScroll: implicitWidth > clip.width

        NumberAnimation on x {
          running: title.needsScroll && clip.visible
          loops: Animation.Infinite
          duration: Math.max(6000, title.implicitWidth * 25)
          from: clip.width
          to: -title.implicitWidth
          easing.type: Easing.Linear
        }
      }
    }
  }

  MouseArea {
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton

    onClicked: function (mouse) {
      if (!root.service) return
      if (mouse.button === Qt.MiddleButton) root.service.next()
      else if (mouse.button === Qt.RightButton) root.service.toggle()
      else root.service.toggleConsole()
    }

    onWheel: function (wheel) {
      if (!root.service) return
      root.service.nudgeVolume(wheel.angleDelta.y > 0 ? 5 : -5)
    }

    onEntered: if (root.bar) root.bar.showTooltip(root, root.live
      ? (root.label || "OMAMPY") + (root.band ? "  ·  " + root.band : "")
      : "OMAMPY — off air (click to open)")
    onExited: if (root.bar) root.bar.hideTooltip(root)
  }
}
