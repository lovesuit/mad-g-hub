import sys
import os
import hid
import time
import math
import threading
from datetime import datetime
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import (
    QIcon, QFont, QColor, QPainter, QPen,
    QPixmap, QAction, QFontMetrics
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QFrame,
    QSystemTrayIcon, QMenu, QPlainTextEdit
)

COLOR_BG = QColor(0, 0, 0)
COLOR_DOTS = QColor(40, 40, 46)
COLOR_PANEL = QColor(14, 14, 16)
COLOR_SURFACE = QColor(20, 20, 24)
COLOR_BORDER = QColor(46, 46, 52)
COLOR_ACCENT = QColor(0, 38, 255)
COLOR_GREEN = QColor(0, 255, 65)
COLOR_RED = QColor(255, 30, 30)
COLOR_TEXT = QColor(255, 255, 255)
COLOR_TEXT_MUTED = QColor(165, 165, 172)


class MouseController:
    OP_GET_CONFIG = 0x82
    OP_GET_DPI_CONFIG = 0xa5
    OP_GET_DPI_VAL = 0xa6
    OP_GET_LIFT = 0xa8
    OP_GET_SPECIAL = 0xaa

    OP_SET_REPORT_RATE = 0x21
    OP_SET_DPI_STAGE = 0x22
    OP_SET_DPI_CONFIG = 0x25
    OP_SET_DPI_VAL = 0x26
    OP_SET_LIFT = 0x28
    OP_SET_SPECIAL = 0x2a

    RATE_MAP = {1000: 0x01, 500: 0x02, 250: 0x04, 125: 0x08}
    REV_RATE_MAP = {0x01: 1000, 0x02: 500, 0x04: 250, 0x08: 125}

    WIRED_PIDS = {0x100d, 0x10c6}
    DONGLE_PIDS = {0x100f, 0x1010}
    SUPPORTED_PIDS = WIRED_PIDS | DONGLE_PIDS

    def __init__(self):
        self.device = None
        self.current_pid = None
        self.is_wired = False
        self.lock = threading.RLock()

    def connect(self):
        with self.lock:
            devs = [
                d for d in hid.enumerate(0x373b)
                if d['usage_page'] == 65296 and d['product_id'] in self.SUPPORTED_PIDS
            ]
            if not devs:
                if self.device:
                    try:
                        self.device.close()
                    except Exception:
                        pass
                    self.device = None
                    self.current_pid = None
                return False

            wired = [d for d in devs if d['product_id'] in self.WIRED_PIDS]
            dongle = [d for d in devs if d['product_id'] in self.DONGLE_PIDS]
            chosen = (wired + dongle)[0]

            if self.device and self.current_pid == chosen['product_id']:
                return True

            if self.device:
                try:
                    self.device.close()
                except Exception:
                    pass
                self.device = None

            try:
                h = hid.device()
                h.open_path(chosen['path'])
                self.device = h
                self.current_pid = chosen['product_id']
                self.is_wired = chosen['product_id'] in self.WIRED_PIDS
                return True
            except Exception:
                self.device = None
                self.current_pid = None
                return False

    def close(self):
        with self.lock:
            if self.device:
                try:
                    self.device.close()
                except Exception:
                    pass
                self.device = None
                self.current_pid = None

    def _query(self, opcode, retries=15):
        if not self.device:
            return None
        try:
            self.device.set_nonblocking(True)
            while self.device.read(64):
                pass
            self.device.set_nonblocking(False)

            pkt = bytes([0x00, opcode]) + bytes(63)
            self.device.send_feature_report(pkt)

            for _ in range(retries):
                r = self.device.read(64, timeout_ms=100)
                if not r:
                    break
                if r[0] == opcode:
                    return list(bytes(r))
            return None
        except Exception:
            self.close()
            return None

    def _send(self, buf65):
        if not self.device:
            return False
        try:
            self.device.set_nonblocking(True)
            while self.device.read(64):
                pass
            self.device.set_nonblocking(False)
            self.device.send_feature_report(bytes(buf65))
            time.sleep(0.035)
            return True
        except Exception:
            self.close()
            return False

    def get_full_state(self):
        with self.lock:
            if not self.connect():
                return None

            cfg = self._query(self.OP_GET_CONFIG)
            if not cfg:
                return None

            rate_code = cfg[1]
            stage_idx = cfg[2]
            raw_bat = cfg[8]
            battery_pct = raw_bat & 0x7F
            is_charging = bool(raw_bat & 0x80)
            polling_rate = self.REV_RATE_MAP.get(rate_code, 1000)

            dpi_val = 800
            dpi_pkt = self._query(self.OP_GET_DPI_VAL)
            if dpi_pkt:
                dpi_val = dpi_pkt[1] | (dpi_pkt[2] << 8)

            lod = 1
            lod_pkt = self._query(self.OP_GET_LIFT)
            if lod_pkt:
                lod = lod_pkt[1]

            motion_sync = False
            angle_snapping = False
            ripple = False
            opt_pkt = self._query(self.OP_GET_SPECIAL)
            if opt_pkt:
                b = opt_pkt[1]
                motion_sync = bool(b & 0x01)
                angle_snapping = bool(b & 0x02)
                ripple = bool(b & 0x04)

            return {
                'battery': battery_pct,
                'charging': is_charging,
                'dpi': dpi_val,
                'stage': stage_idx,
                'polling_rate': polling_rate,
                'lod': lod,
                'motion_sync': motion_sync,
                'angle_snapping': angle_snapping,
                'ripple': ripple,
                'is_wired': self.is_wired,
                'pid': self.current_pid
            }

    def set_dpi(self, stage_idx, dpi_val):
        with self.lock:
            if not self.connect():
                return False
            buf = bytearray(65)
            buf[1] = self.OP_SET_DPI_VAL
            buf[2] = 0x00
            buf[3] = stage_idx
            buf[4] = dpi_val & 0xFF
            buf[5] = (dpi_val >> 8) & 0xFF
            return self._send(buf)

    def set_polling_rate(self, hz):
        with self.lock:
            if not self.connect():
                return False
            code = self.RATE_MAP.get(hz, 0x01)
            buf = bytearray(65)
            buf[1] = self.OP_SET_REPORT_RATE
            buf[2] = 0x00
            buf[3] = 0x00
            buf[4] = code
            return self._send(buf)

    def set_lod(self, mm):
        with self.lock:
            if not self.connect():
                return False
            buf = bytearray(65)
            buf[1] = self.OP_SET_LIFT
            buf[2] = 0x00
            buf[3] = 0x00
            buf[4] = mm
            return self._send(buf)

    def set_special_options(self, motion_sync, angle_snapping, ripple):
        with self.lock:
            if not self.connect():
                return False
            mask = 0
            if motion_sync:
                mask |= 0x01
            if angle_snapping:
                mask |= 0x02
            if ripple:
                mask |= 0x04
            buf = bytearray(65)
            buf[1] = self.OP_SET_SPECIAL
            buf[2] = 0x00
            buf[3] = 0x00
            buf[4] = mask
            return self._send(buf)


class TelemetryWorker(QThread):
    state_updated = pyqtSignal(dict)
    connection_changed = pyqtSignal(bool, int, bool)

    def __init__(self, ctl):
        super().__init__()
        self.ctl = ctl
        self.running = True
        self.last_connected = None
        self.last_pid = None

    def run(self):
        while self.running:
            state = self.ctl.get_full_state()
            if state:
                connected = True
                pid = state['pid']
                wired = state['is_wired']
                self.state_updated.emit(state)
            else:
                connected = False
                pid = 0
                wired = False

            if connected != self.last_connected or pid != self.last_pid:
                self.connection_changed.emit(connected, pid, wired)
                self.last_connected = connected
                self.last_pid = pid

            time.sleep(1.0)

    def stop(self):
        self.running = False


class BackgroundWidget(QWidget):
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w = self.width()
        h = self.height()

        p.fillRect(0, 0, w, h, COLOR_BG)
        p.setPen(COLOR_DOTS)
        for x in range(5, w, 10):
            for y in range(5, h, 10):
                p.drawPoint(x, y)
        p.end()


class CardFrame(QFrame):
    def __init__(self, title="", parent=None):
        super().__init__(parent)
        self.title = title
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w = self.width()
        h = self.height()

        p.fillRect(0, 0, w, h, COLOR_PANEL)
        p.setPen(QPen(COLOR_BORDER, 1))
        p.drawRect(0, 0, w - 1, h - 1)

        if self.title:
            font = QFont("Cascadia Mono", 8, QFont.Weight.Bold)
            font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
            p.setFont(font)

            title_text = f" {self.title} "
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(title_text)

            p.fillRect(8, 0, tw + 4, 1, COLOR_PANEL)
            p.setPen(COLOR_TEXT)
            p.drawText(10, 10, title_text)

            p.setPen(COLOR_BORDER)
            p.drawText(2, 10, "+")
            p.drawText(w - 8, 10, "+")

        p.end()


class PlaqueButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.is_active = False
        font = QFont("Cascadia Mono", 8, QFont.Weight.Bold)
        font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        self.setFont(font)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(22)

    def setActive(self, active):
        self.is_active = active
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w = self.width()
        h = self.height()

        if self.is_active:
            p.fillRect(0, 0, w, h, COLOR_ACCENT)
            p.setPen(QPen(COLOR_TEXT, 1))
            p.drawRect(0, 0, w - 1, h - 1)
            p.setPen(COLOR_TEXT)
        elif self.underMouse():
            p.fillRect(0, 0, w, h, QColor(32, 32, 40))
            p.setPen(QPen(COLOR_TEXT, 1))
            p.drawRect(0, 0, w - 1, h - 1)
            p.setPen(COLOR_TEXT)
        else:
            p.fillRect(0, 0, w, h, COLOR_SURFACE)
            p.setPen(QPen(COLOR_BORDER, 1))
            p.drawRect(0, 0, w - 1, h - 1)
            p.setPen(COLOR_TEXT_MUTED)

        p.setFont(self.font())
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())
        p.end()


class SegmentedCpiSlider(QWidget):
    cpi_changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.min_cpi = 200
        self.max_cpi = 12000
        self.current_cpi = 800
        self.total_segments = 20
        self.setFixedHeight(16)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_cpi(self, val):
        self.current_cpi = max(self.min_cpi, min(self.max_cpi, val))
        self.update()

    def calc_active_segments(self, val):
        norm = max(0.0, min(1.0, (val - self.min_cpi) / (self.max_cpi - self.min_cpi)))
        ratio = math.pow(norm, 0.48)
        return max(2, min(self.total_segments, int(round(ratio * self.total_segments))))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.handle_pos(event.pos().x())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.handle_pos(event.pos().x())

    def handle_pos(self, x):
        ratio = max(0.0, min(1.0, float(x) / float(self.width())))
        norm = math.pow(ratio, 1.0 / 0.48)
        raw_val = self.min_cpi + norm * (self.max_cpi - self.min_cpi)
        val = int(round(raw_val / 50.0)) * 50
        self.current_cpi = max(self.min_cpi, min(self.max_cpi, val))
        self.update()
        self.cpi_changed.emit(self.current_cpi)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w = self.width()
        h = self.height()

        active_segs = self.calc_active_segments(self.current_cpi)
        seg_gap = 2
        seg_w = max(4, (w - (self.total_segments - 1) * seg_gap) // self.total_segments)

        for i in range(self.total_segments):
            sx = i * (seg_w + seg_gap)
            if i < active_segs:
                if i == active_segs - 1:
                    p.fillRect(sx, 2, seg_w, h - 4, COLOR_TEXT)
                    p.setPen(COLOR_TEXT)
                else:
                    p.fillRect(sx, 2, seg_w, h - 4, COLOR_ACCENT)
                    p.setPen(QColor(80, 120, 255))
                p.drawRect(sx, 2, seg_w - 1, h - 5)
            else:
                p.fillRect(sx, 2, seg_w, h - 4, QColor(18, 18, 22))
                p.setPen(COLOR_BORDER)
                p.drawRect(sx, 2, seg_w - 1, h - 5)
        p.end()


class PulseWaveWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rate = 1000
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(40)
        self.phase = 0

    def set_rate(self, rate):
        self.rate = rate
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w = self.width()
        h = self.height()

        p.fillRect(0, 0, w, h, QColor(10, 10, 12))
        p.setPen(QPen(COLOR_BORDER, 1))
        p.drawRect(0, 0, w - 1, h - 1)

        step_w = {1000: 7, 500: 14, 250: 28, 125: 56}.get(self.rate, 7)
        self.phase = (self.phase + 1) % (step_w * 2)

        y_high = 4
        y_low = h - 5

        p.setPen(QPen(COLOR_ACCENT, 2))
        x = -step_w * 2 + self.phase
        high = True
        while x < w + step_w * 2:
            next_x = x + step_w
            y = y_high if high else y_low
            p.drawLine(x, y, next_x, y)
            p.drawLine(next_x, y_high, next_x, y_low)
            x = next_x
            high = not high
        p.end()


class ToggleRow(QFrame):
    toggled = pyqtSignal(bool)

    def __init__(self, title, tooltip_text="", parent=None):
        super().__init__(parent)
        self.checked = False
        self.setStyleSheet("QFrame { background: transparent; border: none; }")
        self.setToolTip(tooltip_text)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(6)

        self.title_lbl = QLabel(title, self)
        font_t = QFont("Cascadia Mono", 9, QFont.Weight.Bold)
        font_t.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        self.title_lbl.setFont(font_t)
        self.title_lbl.setStyleSheet("color: #FFFFFF;")
        layout.addWidget(self.title_lbl, 1)

        self.status_btn = QPushButton("[ OFF ]", self)
        font_btn = QFont("Cascadia Mono", 9, QFont.Weight.Bold)
        font_btn.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        self.status_btn.setFont(font_btn)
        self.status_btn.setFixedSize(80, 22)
        self.status_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.status_btn.clicked.connect(self.on_clicked)
        layout.addWidget(self.status_btn, 0)

        self.refresh_ui()

    def setChecked(self, state):
        self.checked = state
        self.refresh_ui()

    def on_clicked(self):
        self.checked = not self.checked
        self.refresh_ui()
        self.toggled.emit(self.checked)

    def refresh_ui(self):
        if self.checked:
            self.status_btn.setText("[ ON ]")
            self.status_btn.setStyleSheet("background: transparent; color: #00FF41; border: none; text-align: right;")
        else:
            self.status_btn.setText("[ OFF ]")
            self.status_btn.setStyleSheet("background: transparent; color: #FF1E1E; border: none; text-align: right;")


class ConsoleFrame(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w = self.width()
        h = self.height()

        p.fillRect(0, 0, w, h, COLOR_PANEL)
        p.setPen(QPen(COLOR_BORDER, 1))
        p.drawRect(0, 0, w - 1, h - 1)
        p.end()



class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ctl = MouseController()

        self.current_dpi = 800
        self.current_rate = 1000
        self.current_lod = 2
        self.current_stage = 0
        self.current_battery = 99
        self.is_charging = True
        self.is_connected = False
        self.is_wired = False
        self.current_pid = 0x100D

        self.motion_sync = True
        self.angle_snapping = False
        self.ripple = False
        self.is_log_expanded = False

        self.init_window()
        self.init_ui()
        self.init_tray()

        self.worker = TelemetryWorker(self.ctl)
        self.worker.state_updated.connect(self.on_state_updated)
        self.worker.connection_changed.connect(self.on_connection_changed)
        self.worker.start()

    def init_window(self):
        self.setWindowTitle("MAD G Hub")
        self.setMinimumSize(490, 360)
        self.resize(510, 380)

        self.setStyleSheet("""
            QMainWindow {
                background-color: #000000;
            }
            QWidget {
                color: #FFFFFF;
                font-family: 'Segoe UI', -apple-system, sans-serif;
            }
            QToolTip {
                background-color: #101014;
                color: #FFFFFF;
                border: 1px solid #0026FF;
                padding: 4px 6px;
                font-family: 'Cascadia Mono', monospace;
                font-size: 10px;
            }
            QScrollBar:vertical {
                background: #000000;
                width: 5px;
            }
            QScrollBar::handle:vertical {
                background: #0026FF;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
        """)

    def init_ui(self):
        central = BackgroundWidget(self)
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(6)

        header_frame = QFrame(self)
        header_frame.setFixedHeight(36)
        header_frame.setStyleSheet("background-color: #0E0E10; border: 1px solid #303036;")
        h_layout = QHBoxLayout(header_frame)
        h_layout.setContentsMargins(8, 4, 8, 4)

        face_badge = QLabel("[X_X]", self)
        font_b = QFont("Cascadia Mono", 9, QFont.Weight.Bold)
        font_b.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        face_badge.setFont(font_b)
        face_badge.setStyleSheet("color: #FFFFFF; background-color: #0026FF; padding: 1px 5px;")

        title_lbl = QLabel("MAD G", self)
        font_t = QFont("Impact", 13)
        font_t.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        title_lbl.setFont(font_t)
        title_lbl.setStyleSheet("color: #FFFFFF; letter-spacing: 0.5px;")

        h_layout.addWidget(face_badge)
        h_layout.addWidget(title_lbl)
        h_layout.addStretch()

        self.status_badge = QLabel("● CONNECTED", self)
        self.status_badge.setFont(QFont("Cascadia Mono", 8, QFont.Weight.Bold))
        self.status_badge.setStyleSheet("color: #00FF41; background-color: #141418; border: 1px solid #303036; padding: 2px 6px;")

        self.bat_lbl = QLabel("[ 99% ⚡ ]", self)
        self.bat_lbl.setFont(QFont("Cascadia Mono", 8, QFont.Weight.Bold))
        self.bat_lbl.setStyleSheet("color: #A5A5AC;")

        h_layout.addWidget(self.status_badge)
        h_layout.addWidget(self.bat_lbl)
        root_layout.addWidget(header_frame)

        grid_layout = QHBoxLayout()
        grid_layout.setSpacing(6)

        # Left Column: CPI & LOD
        left_card = CardFrame("// CPI", parent=self)
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(8, 16, 8, 8)
        left_layout.setSpacing(6)

        cpi_row = QHBoxLayout()
        self.cpi_num_lbl = QLabel(f"{self.current_dpi}", self)
        font_cpi = QFont("Impact", 28)
        font_cpi.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        self.cpi_num_lbl.setFont(font_cpi)
        self.cpi_num_lbl.setStyleSheet("color: #FFFFFF; margin: 0; padding: 0;")

        cpi_sub = QLabel("CPI", self)
        font_sub = QFont("Cascadia Mono", 8, QFont.Weight.Bold)
        font_sub.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        cpi_sub.setFont(font_sub)
        cpi_sub.setStyleSheet("color: #FFFFFF; background-color: #0026FF; padding: 1px 4px;")

        cpi_row.addWidget(self.cpi_num_lbl)
        cpi_row.addWidget(cpi_sub, 0, Qt.AlignmentFlag.AlignVCenter)
        cpi_row.addStretch()

        btn_minus = QPushButton("[-50]", self)
        btn_plus = QPushButton("[+50]", self)
        for b in (btn_minus, btn_plus):
            b.setFixedSize(40, 20)
            b.setFont(QFont("Cascadia Mono", 7, QFont.Weight.Bold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet("background-color: #141418; color: #FFFFFF; border: 1px solid #303036;")
        btn_minus.clicked.connect(lambda: self.nudge_dpi(-50))
        btn_plus.clicked.connect(lambda: self.nudge_dpi(50))
        cpi_row.addWidget(btn_minus)
        cpi_row.addWidget(btn_plus)
        left_layout.addLayout(cpi_row)

        self.seg_cpi = SegmentedCpiSlider(left_card)
        self.seg_cpi.set_cpi(self.current_dpi)
        self.seg_cpi.cpi_changed.connect(self.apply_dpi)
        left_layout.addWidget(self.seg_cpi)

        presets_grid = QGridLayout()
        presets_grid.setSpacing(4)
        self.preset_btns = {}
        preset_vals = [400, 800, 1200, 1600, 2400, 3200, 6400, 12000]
        for idx, p_val in enumerate(preset_vals):
            btn = PlaqueButton(str(p_val), left_card)
            btn.clicked.connect(lambda ch, v=p_val: self.apply_dpi(v))
            self.preset_btns[p_val] = btn
            r = idx // 4
            c = idx % 4
            presets_grid.addWidget(btn, r, c)
        left_layout.addLayout(presets_grid)
        self.update_preset_buttons(self.current_dpi)

        lod_row = QHBoxLayout()
        lod_row.setSpacing(4)
        lod_lbl = QLabel("// LOD:", left_card)
        font_l = QFont("Cascadia Mono", 8, QFont.Weight.Bold)
        font_l.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        lod_lbl.setFont(font_l)
        lod_lbl.setStyleSheet("color: #A5A5AC;")
        lod_row.addWidget(lod_lbl)

        self.btn_lod_1 = PlaqueButton("1.0 MM", left_card)
        self.btn_lod_2 = PlaqueButton("2.0 MM", left_card)
        self.btn_lod_1.clicked.connect(lambda: self.apply_lod(1))
        self.btn_lod_2.clicked.connect(lambda: self.apply_lod(2))
        lod_row.addWidget(self.btn_lod_1)
        lod_row.addWidget(self.btn_lod_2)
        left_layout.addLayout(lod_row)

        grid_layout.addWidget(left_card, 1)

        # Right Column: Polling Rate & DSP Options
        right_vbox = QVBoxLayout()
        right_vbox.setSpacing(6)

        rate_card = CardFrame("// USB CLOCK", parent=self)
        rate_layout = QVBoxLayout(rate_card)
        rate_layout.setContentsMargins(8, 14, 8, 6)
        rate_layout.setSpacing(4)

        self.rate_info_lbl = QLabel(f"CYCLE: 1.0ms // {self.current_rate} Hz", self)
        self.rate_info_lbl.setFont(QFont("Cascadia Mono", 7))
        self.rate_info_lbl.setStyleSheet("color: #A5A5AC;")
        rate_layout.addWidget(self.rate_info_lbl)

        self.pixel_canvas = PulseWaveWidget(rate_card)
        self.pixel_canvas.setFixedHeight(26)
        rate_layout.addWidget(self.pixel_canvas)

        rate_btn_row = QHBoxLayout()
        rate_btn_row.setSpacing(3)
        self.rate_btns = {}
        for r_hz in [125, 250, 500, 1000]:
            btn = PlaqueButton(f"{r_hz}", rate_card)
            btn.clicked.connect(lambda ch, r=r_hz: self.apply_polling_rate(r))
            self.rate_btns[r_hz] = btn
            rate_btn_row.addWidget(btn)
        rate_layout.addLayout(rate_btn_row)
        self.update_rate_buttons(self.current_rate)
        right_vbox.addWidget(rate_card)

        dsp_card = CardFrame("// DSP SETTINGS", parent=self)
        dsp_layout = QVBoxLayout(dsp_card)
        dsp_layout.setContentsMargins(8, 14, 8, 6)
        dsp_layout.setSpacing(3)

        self.sw_motion = ToggleRow(
            "MOTION SYNC",
            "Realtime sensor-to-USB report clock synchronization",
            dsp_card
        )
        self.sw_snap = ToggleRow(
            "ANGLE SNAPPING",
            "Directional drift suppression and angle lock",
            dsp_card
        )
        self.sw_ripple = ToggleRow(
            "RIPPLE CONTROL",
            "Jitter smoothing at high CPI",
            dsp_card
        )

        self.sw_motion.toggled.connect(self.on_flags_changed)
        self.sw_snap.toggled.connect(self.on_flags_changed)
        self.sw_ripple.toggled.connect(self.on_flags_changed)

        dsp_layout.addWidget(self.sw_motion)
        dsp_layout.addWidget(self.sw_snap)
        dsp_layout.addWidget(self.sw_ripple)
        right_vbox.addWidget(dsp_card)

        grid_layout.addLayout(right_vbox, 1)
        root_layout.addLayout(grid_layout)

        # Bottom Drawer: Telemetry / Logs
        drawer_frame = QFrame(self)
        drawer_frame.setFixedHeight(24)
        drawer_frame.setStyleSheet("background-color: #0E0E10; border: 1px solid #303036;")
        d_layout = QHBoxLayout(drawer_frame)
        d_layout.setContentsMargins(6, 0, 6, 0)

        self.ticker_lbl = QLabel("ready", self)
        self.ticker_lbl.setFont(QFont("Cascadia Mono", 7))
        self.ticker_lbl.setStyleSheet("color: #A5A5AC;")
        d_layout.addWidget(self.ticker_lbl, 1)

        self.btn_toggle_log = QPushButton("[ + TELEMETRY ]", self)
        font_tog = QFont("Cascadia Mono", 7, QFont.Weight.Bold)
        font_tog.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        self.btn_toggle_log.setFont(font_tog)
        self.btn_toggle_log.setFixedSize(94, 18)
        self.btn_toggle_log.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_log.setStyleSheet("""
            QPushButton {
                background-color: #141418;
                color: #FFFFFF;
                border: 1px solid #303036;
            }
            QPushButton:hover {
                border-color: #0026FF;
                color: #0026FF;
            }
        """)
        self.btn_toggle_log.clicked.connect(self.toggle_console)
        d_layout.addWidget(self.btn_toggle_log, 0)
        root_layout.addWidget(drawer_frame)

        self.console_container = ConsoleFrame(self)
        self.console_container.setFixedHeight(140)
        self.console_container.setVisible(False)
        c_layout = QVBoxLayout(self.console_container)
        c_layout.setContentsMargins(6, 6, 6, 6)

        self.log_edit = QPlainTextEdit(self.console_container)
        self.log_edit.setReadOnly(True)
        self.log_edit.setFont(QFont("Cascadia Mono", 7))
        self.log_edit.setStyleSheet("""
            QPlainTextEdit {
                background-color: #090A0D;
                color: #C5C8D0;
                border: 1px solid #1E1E24;
                padding: 4px;
                selection-background-color: #0026FF;
                selection-color: #FFFFFF;
            }
            QScrollBar:vertical {
                background: #090A0D;
                width: 6px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #282830;
                min-height: 16px;
            }
            QScrollBar::handle:vertical:hover {
                background: #0026FF;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar:horizontal {
                background: #090A0D;
                height: 6px;
                margin: 0px;
            }
            QScrollBar::handle:horizontal {
                background: #282830;
                min-width: 16px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #0026FF;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
        """)
        c_layout.addWidget(self.log_edit)
        root_layout.addWidget(self.console_container)

        self.log_cli("device ready: paw3395")

    def toggle_console(self):
        self.is_log_expanded = not self.is_log_expanded
        self.console_container.setVisible(self.is_log_expanded)
        if self.is_log_expanded:
            self.btn_toggle_log.setText("[ - TELEMETRY ]")
            self.resize(self.width(), self.height() + 146)
        else:
            self.btn_toggle_log.setText("[ + TELEMETRY ]")
            self.resize(self.width(), max(360, self.height() - 146))

    def log_cli(self, text, prefix="[+]"):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {prefix} {text}"
        self.log_edit.appendPlainText(line)
        self.ticker_lbl.setText(line)
        self.log_edit.verticalScrollBar().setValue(
            self.log_edit.verticalScrollBar().maximum()
        )

    def on_state_updated(self, state):
        self.is_connected = True
        self.is_wired = state['is_wired']
        self.current_pid = state['pid']
        self.current_battery = state['battery']
        self.is_charging = state['charging']
        self.current_stage = state['stage']

        chg_str = " ⚡" if self.is_charging else ""
        self.bat_lbl.setText(f"[ {self.current_battery}%{chg_str} ]")

        if abs(state['dpi'] - self.current_dpi) >= 50:
            self.current_dpi = state['dpi']
            self.seg_cpi.set_cpi(state['dpi'])
            self.cpi_num_lbl.setText(f"{state['dpi']}")
            self.update_preset_buttons(state['dpi'])

        if state['polling_rate'] != self.current_rate:
            self.current_rate = state['polling_rate']
            self.pixel_canvas.set_rate(state['polling_rate'])
            self.update_rate_buttons(state['polling_rate'])
            ms = 1000.0 / self.current_rate
            self.rate_info_lbl.setText(f"CYCLE: {ms:0.1f}ms // {self.current_rate} Hz")

        self.current_lod = state['lod']
        self.btn_lod_1.setActive(self.current_lod == 1)
        self.btn_lod_2.setActive(self.current_lod == 2)

        self.sw_motion.blockSignals(True)
        self.sw_snap.blockSignals(True)
        self.sw_ripple.blockSignals(True)
        self.sw_motion.setChecked(state['motion_sync'])
        self.sw_snap.setChecked(state['angle_snapping'])
        self.sw_ripple.setChecked(state['ripple'])
        self.sw_motion.blockSignals(False)
        self.sw_snap.blockSignals(False)
        self.sw_ripple.blockSignals(False)

        bus_name = "USB" if self.is_wired else "2.4G"
        self.tray.setToolTip(f"MAD G ({bus_name})\nBattery: {self.current_battery}% | {self.current_dpi} CPI")

    def on_connection_changed(self, connected, pid, wired):
        self.is_connected = connected
        self.is_wired = wired
        self.current_pid = pid

        if connected:
            self.status_badge.setText("● CONNECTED")
            self.status_badge.setStyleSheet("color: #00FF41; background-color: #141418; border: 1px solid #303036; padding: 2px 6px;")
            if wired:
                self.log_cli(f"connected: direct usb (pid=0x{pid:04x})", "[*]")
            else:
                self.log_cli(f"connected: 2.4g wireless (pid=0x{pid:04x})", "[*]")
        else:
            self.status_badge.setText("○ DISCONNECTED")
            self.status_badge.setStyleSheet("color: #FF1E1E; background-color: #141418; border: 1px solid #303036; padding: 2px 6px;")
            self.log_cli("disconnected", "[!]")

    def nudge_dpi(self, delta):
        val = max(200, min(12000, self.current_dpi + delta))
        self.apply_dpi(val)

    def apply_dpi(self, val):
        self.current_dpi = val
        self.seg_cpi.set_cpi(val)
        self.cpi_num_lbl.setText(f"{val}")
        self.update_preset_buttons(val)

        self.log_cli(f"cpi set to {val} (stage={self.current_stage})")
        QTimer.singleShot(10, lambda: self._exec_set_dpi(val))

    def _exec_set_dpi(self, val):
        ok = self.ctl.set_dpi(self.current_stage, val)
        if ok:
            self.log_cli(f"cpi confirmed: {val}", "[OK]")
        else:
            self.log_cli("cpi write error", "[ERR]")

    def update_preset_buttons(self, val):
        for p_val, btn in self.preset_btns.items():
            btn.setActive(p_val == val)

    def apply_polling_rate(self, hz):
        self.current_rate = hz
        self.update_rate_buttons(hz)
        self.pixel_canvas.set_rate(hz)
        ms = 1000.0 / hz
        self.rate_info_lbl.setText(f"CYCLE: {ms:0.1f}ms // {hz} Hz")
        self.log_cli(f"polling rate set to {hz} Hz")
        QTimer.singleShot(10, lambda: self.ctl.set_polling_rate(hz))

    def update_rate_buttons(self, hz):
        for r_hz, btn in self.rate_btns.items():
            btn.setActive(r_hz == hz)

    def apply_lod(self, mm):
        self.current_lod = mm
        self.btn_lod_1.setActive(mm == 1)
        self.btn_lod_2.setActive(mm == 2)
        self.log_cli(f"lod set to {mm} mm")
        QTimer.singleShot(10, lambda: self.ctl.set_lod(mm))

    def on_flags_changed(self):
        ms = self.sw_motion.checked
        snap = self.sw_snap.checked
        rip = self.sw_ripple.checked
        self.log_cli(f"dsp updated: motion_sync={ms}, angle_snap={snap}, ripple={rip}")
        QTimer.singleShot(10, lambda: self.ctl.set_special_options(ms, snap, rip))

    def init_tray(self):
        self.tray = QSystemTrayIcon(self)
        icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
        if os.path.exists(icon_path):
            self.tray.setIcon(QIcon(icon_path))
        else:
            pm = QPixmap(16, 16)
            pm.fill(COLOR_ACCENT)
            self.tray.setIcon(QIcon(pm))

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

        title_act = QAction("MAD G Hub", self)
        title_act.setEnabled(False)
        menu.addAction(title_act)
        menu.addSeparator()

        show_act = QAction("Open Window", self)
        show_act.triggered.connect(self.show_normal)
        menu.addAction(show_act)

        hide_act = QAction("Minimize to Tray", self)
        hide_act.triggered.connect(self.hide)
        menu.addAction(hide_act)
        menu.addSeparator()

        quit_act = QAction("Quit", self)
        quit_act.triggered.connect(self.quit_app)
        menu.addAction(quit_act)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.show()

    def show_normal(self):
        self.show()
        self.activateWindow()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.show_normal()

    def closeEvent(self, event):
        self.worker.stop()
        self.worker.wait(1000)
        self.ctl.close()
        event.accept()

    def quit_app(self):
        self.worker.stop()
        self.worker.wait(1000)
        self.ctl.close()
        QApplication.quit()


if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        win = MainWindow()
        win.show()
        sys.exit(app.exec())
    except Exception as e:
        import traceback
        with open(os.path.join(os.path.dirname(__file__), "hub_error.log"), "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
