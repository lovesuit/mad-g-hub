import sys
import os
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor, QAction, QFont
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu

from app import MouseController, TelemetryWorker, BatteryWidget


def make_battery_icon(pct: int, charging: bool) -> QIcon:
    """Draw a 16x16 battery icon reflecting the current charge level."""
    size = 16
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)

    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    if charging:
        color = QColor(0, 255, 65)       # green
    elif pct >= 50:
        color = QColor(0, 255, 65)       # green
    elif pct >= 20:
        color = QColor(255, 215, 0)      # yellow
    else:
        color = QColor(255, 30, 30)      # red

    # Battery body: x=2, y=3, w=11, h=12
    bx, by, bw, bh = 2, 3, 11, 12

    # Nub on top
    p.fillRect(5, 1, 5, 2, color)

    # Outline
    p.setPen(QPen(color, 1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(bx, by, bw - 1, bh - 1)

    # Fill bar (grows from bottom)
    fill_h = max(1, int((bh - 3) * pct / 100))
    fill_y = by + (bh - 2) - fill_h
    p.fillRect(bx + 2, fill_y, bw - 5, fill_h, color)

    # Lightning bolt for charging
    if charging:
        p.setPen(QPen(QColor(255, 255, 255), 1))
        bolt = [(7, 4), (5, 9), (7, 9), (5, 14)]
        for i in range(len(bolt) - 1):
            p.drawLine(bolt[i][0], bolt[i][1], bolt[i + 1][0], bolt[i + 1][1])

    p.end()
    return QIcon(pm)


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    ctl = MouseController()
    worker = TelemetryWorker(ctl)

    widget = BatteryWidget(worker)
    widget.move(20, 20)
    widget.show()

    worker.start()

    tray = QSystemTrayIcon()
    tray.setIcon(make_battery_icon(0, False))
    tray.setToolTip("MAD G — Battery Widget")

    def on_state(state):
        pct = state.get('battery', 0)
        charging = state.get('charging', False)
        tray.setIcon(make_battery_icon(pct, charging))
        chg = " ⚡" if charging else ""
        tray.setToolTip(f"MAD G — {pct}%{chg}")

    worker.state_updated.connect(on_state)

    menu = QMenu()
    menu.setStyleSheet("""
        QMenu {
            background-color: #0E0E10;
            color: #FFFFFF;
            border: 1px solid #303036;
            padding: 4px;
            font-family: 'Cascadia Mono', monospace;
            font-size: 11px;
        }
        QMenu::item:selected {
            background-color: #0026FF;
            color: #FFFFFF;
        }
    """)

    quit_act = QAction("Quit Widget", None)
    quit_act.triggered.connect(lambda: _quit(worker, ctl, app))
    menu.addAction(quit_act)

    tray.setContextMenu(menu)
    tray.show()

    sys.exit(app.exec())


def _quit(worker, ctl, app):
    worker.stop()
    worker.wait(1000)
    ctl.close()
    app.quit()


if __name__ == "__main__":
    main()
