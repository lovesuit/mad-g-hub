import sys
import os
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPixmap, QAction, QFont, QColor
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu

from app import MouseController, TelemetryWorker, BatteryWidget, COLOR_ACCENT


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    ctl = MouseController()
    worker = TelemetryWorker(ctl)

    widget = BatteryWidget(worker)
    widget.move(20, 20)
    widget.show()

    worker.start()

    # Tray icon so the widget can be closed without a taskbar button
    tray = QSystemTrayIcon()
    icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
    if os.path.exists(icon_path):
        tray.setIcon(QIcon(icon_path))
    else:
        pm = QPixmap(16, 16)
        pm.fill(COLOR_ACCENT)
        tray.setIcon(QIcon(pm))
    tray.setToolTip("MAD G — Battery Widget")

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
