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
    QSystemTrayIcon, QMenu, QPlainTextEdit, QStackedWidget,
    QComboBox, QColorDialog
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
    OP_GET_FIRMWARE = 0x80
    OP_GET_MOUSE_INFO = 0x81
    OP_SET_MOUSE_INFO = 0x01
    OP_SET_REPORT_RATE = 0x20
    OP_SET_DPI_STAGE = 0x21
    OP_SET_RGB = 0x22
    OP_GET_CONFIG = 0x82
    OP_SET_RGB_COLOR = 0x23
    OP_GET_RGB_COLOR = 0xa3
    OP_SET_KEY_MATRIX = 0x24
    OP_GET_KEY_MATRIX = 0xa4
    OP_SET_DPI_CONFIG = 0x25
    OP_GET_DPI_CONFIG = 0xa5
    OP_SET_DPI_VAL = 0x26
    OP_GET_DPI_VAL = 0xa6
    OP_SET_DPI_COLOR = 0x27
    OP_GET_DPI_COLOR = 0xa7
    OP_SET_LIFT = 0x28
    OP_GET_LIFT = 0xa8
    OP_SET_SPECIAL = 0x2a
    OP_GET_SPECIAL = 0xaa
    OP_SET_SLEEP_TIME = 0x2b
    OP_GET_SLEEP_TIME = 0xab
    OP_SET_KEY_DEBOUNCE = 0x2c
    OP_GET_KEY_DEBOUNCE = 0xac

    RATE_MAP = {1000: 0x01, 500: 0x02, 250: 0x04, 125: 0x08}
    REV_RATE_MAP = {0x01: 1000, 0x02: 500, 0x04: 250, 0x08: 125}

    SLEEP_CODES = [
        (10, 0x01, "10S"),
        (30, 0x03, "30S"),
        (50, 0x05, "50S"),
        (60, 0x06, "1M"),
        (120, 0x0c, "2M"),
        (900, 0x5a, "15M"),
        (1800, 0xb4, "30M")
    ]

    DEBOUNCE_VALS = [1, 2, 4, 8, 15, 20, 30]

    KEY_BINDINGS = [
        ("Left Click", 0x02, 0x00, 0x00, 0xf0),
        ("Right Click", 0x02, 0x00, 0x00, 0xf1),
        ("Middle Click", 0x02, 0x00, 0x00, 0xf2),
        ("Forward", 0x02, 0x00, 0x00, 0xf4),
        ("Backward", 0x02, 0x00, 0x00, 0xf3),
        ("DPI Cycle", 0x0b, 0x00, 0x00, 0x03),
        ("DPI +", 0x0b, 0x00, 0x00, 0x02),
        ("DPI -", 0x0b, 0x00, 0x00, 0x01),
        ("Scroll Up", 0x02, 0x00, 0x00, 0xf5),
        ("Scroll Down", 0x02, 0x00, 0x00, 0xf6),
        ("Disabled", 0x00, 0x00, 0x00, 0x00),
    ]

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

    def _query(self, opcode, param1=0x00, retries=15):
        if not self.device:
            return None
        try:
            self.device.set_nonblocking(True)
            while self.device.read(64):
                pass
            self.device.set_nonblocking(False)

            pkt = bytes([0x00, opcode, 0x00, param1]) + bytes(61)
            self.device.send_feature_report(pkt)

            for _ in range(retries):
                r = self.device.read(64, timeout_ms=50)
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
            rgb_effect = cfg[3]
            rgb_brightness = cfg[4]
            rgb_speed = cfg[5]
            rgb_color = cfg[6]
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

            debounce = 4
            deb_pkt = self._query(self.OP_GET_KEY_DEBOUNCE)
            if deb_pkt:
                debounce = deb_pkt[1]

            sleep_code = 1
            slp_pkt = self._query(self.OP_GET_SLEEP_TIME)
            if slp_pkt:
                sleep_code = slp_pkt[1]

            stage_colors = []
            for s in range(6):
                cpkt = self._query(self.OP_GET_DPI_COLOR, param1=s)
                if cpkt and len(cpkt) >= 4:
                    stage_colors.append((cpkt[1], cpkt[2], cpkt[3]))
                else:
                    stage_colors.append((0, 255, 65))

            key_matrix = []
            km_pkt = self._query(self.OP_GET_KEY_MATRIX)
            if km_pkt and len(km_pkt) >= 25:
                for k in range(6):
                    chunk = km_pkt[1 + k*4 : 1 + (k+1)*4]
                    key_matrix.append((chunk[3], chunk[2], chunk[1], chunk[0]))

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
                'rgb_effect': rgb_effect,
                'rgb_brightness': rgb_brightness,
                'rgb_speed': rgb_speed,
                'rgb_color': rgb_color,
                'debounce': debounce,
                'sleep_code': sleep_code,
                'stage_colors': stage_colors,
                'key_matrix': key_matrix,
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

    def set_rgb(self, effect, brightness, speed, color):
        with self.lock:
            if not self.connect():
                return False
            buf = bytearray(65)
            buf[1] = self.OP_SET_RGB
            buf[2] = 0x00
            buf[3] = effect & 0xFF
            buf[4] = brightness & 0xFF
            buf[5] = speed & 0xFF
            buf[6] = color & 0xFF
            return self._send(buf)

    def set_dpi_color(self, stage_idx, r, g, b):
        with self.lock:
            if not self.connect():
                return False
            buf = bytearray(65)
            buf[1] = self.OP_SET_DPI_COLOR
            buf[2] = 0x00
            buf[3] = stage_idx & 0xFF
            buf[4] = r & 0xFF
            buf[5] = g & 0xFF
            buf[6] = b & 0xFF
            return self._send(buf)

    def set_key_debounce(self, ms):
        with self.lock:
            if not self.connect():
                return False
            buf = bytearray(65)
            buf[1] = self.OP_SET_KEY_DEBOUNCE
            buf[2] = 0x00
            buf[3] = 0x00
            buf[4] = ms & 0xFF
            return self._send(buf)

    def set_sleep_time(self, code):
        with self.lock:
            if not self.connect():
                return False
            buf = bytearray(65)
            buf[1] = self.OP_SET_SLEEP_TIME
            buf[2] = 0x00
            buf[3] = 0x00
            buf[4] = code & 0xFF
            return self._send(buf)

    def set_key_binding(self, key_idx, key_class, val1, val2, val3):
        with self.lock:
            if not self.connect():
                return False
            buf = bytearray(65)
            buf[1] = self.OP_SET_KEY_MATRIX
            buf[2] = 0x00
            buf[3] = key_idx & 0xFF
            buf[4] = val3 & 0xFF
            buf[5] = val2 & 0xFF
            buf[6] = val1 & 0xFF
            buf[7] = key_class & 0xFF
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

            time.sleep(1.2)

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


class NavTabButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.is_active = False
        font = QFont("Cascadia Mono", 8, QFont.Weight.Bold)
        font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        self.setFont(font)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(24)

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
            p.fillRect(0, 0, w, h, QColor(28, 28, 36))
            p.setPen(QPen(COLOR_TEXT, 1))
            p.drawRect(0, 0, w - 1, h - 1)
            p.setPen(COLOR_TEXT)
        else:
            p.fillRect(0, 0, w, h, QColor(14, 14, 18))
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
        font_t = QFont("Cascadia Mono", 8, QFont.Weight.Bold)
        font_t.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        self.title_lbl.setFont(font_t)
        self.title_lbl.setStyleSheet("color: #FFFFFF;")
        layout.addWidget(self.title_lbl, 1)

        self.status_btn = QPushButton("[ OFF ]", self)
        font_btn = QFont("Cascadia Mono", 8, QFont.Weight.Bold)
        font_btn.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        self.status_btn.setFont(font_btn)
        self.status_btn.setFixedSize(70, 20)
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


class ColorSwatchButton(QPushButton):
    color_chosen = pyqtSignal(QColor)

    def __init__(self, color=QColor(0, 255, 65), parent=None):
        super().__init__(parent)
        self.swatch_color = color
        self.setFixedSize(22, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self.pick_color)

    def set_color(self, color):
        self.swatch_color = color
        self.update()

    def pick_color(self):
        c = QColorDialog.getColor(self.swatch_color, self, "SELECT DPI LED COLOR")
        if c.isValid():
            self.swatch_color = c
            self.update()
            self.color_chosen.emit(c)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w = self.width()
        h = self.height()
        p.fillRect(0, 0, w, h, self.swatch_color)
        p.setPen(QPen(COLOR_BORDER, 1))
        p.drawRect(0, 0, w - 1, h - 1)
        p.end()


class ConsoleFrame(QFrame):
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

        self.rgb_effect = 0
        self.rgb_brightness = 0x7f
        self.rgb_speed = 3
        self.rgb_color = 1
        self.debounce_ms = 4
        self.sleep_code = 1
        self.stage_colors = [(0, 255, 65)] * 6

        self.init_window()
        self.init_ui()
        self.init_tray()

        self.worker = TelemetryWorker(self.ctl)
        self.worker.state_updated.connect(self.on_state_updated)
        self.worker.connection_changed.connect(self.on_connection_changed)
        self.worker.start()

    def init_window(self):
        self.setWindowTitle("MAD G Hub")
        self.setMinimumSize(540, 390)
        self.resize(550, 410)

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
            QComboBox {
                background-color: #141418;
                color: #FFFFFF;
                border: 1px solid #303036;
                padding: 3px 6px;
                font-family: 'Cascadia Mono', monospace;
                font-size: 10px;
                font-weight: bold;
            }
            QComboBox::drop-down {
                border: none;
                width: 16px;
            }
            QComboBox QAbstractItemView {
                background-color: #0E0E10;
                color: #FFFFFF;
                selection-background-color: #0026FF;
                selection-color: #FFFFFF;
                border: 1px solid #303036;
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

        # Header Frame
        header_frame = QFrame(self)
        header_frame.setFixedHeight(38)
        header_frame.setStyleSheet("background-color: #0E0E10; border: 1px solid #303036;")
        h_layout = QHBoxLayout(header_frame)
        h_layout.setContentsMargins(8, 4, 8, 4)
        h_layout.setSpacing(8)

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

        # Nav Tabs
        self.nav_btns = []
        self.tab_names = ["SENSOR", "LIGHTING", "HARDWARE", "KEYS"]
        for idx, tname in enumerate(self.tab_names):
            tbtn = NavTabButton(tname, header_frame)
            tbtn.clicked.connect(lambda ch, i=idx: self.switch_tab(i))
            self.nav_btns.append(tbtn)
            h_layout.addWidget(tbtn)

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

        # Tab Stacked Widget
        self.stack = QStackedWidget(self)
        self.build_sensor_tab()
        self.build_lighting_tab()
        self.build_hardware_tab()
        self.build_keys_tab()
        root_layout.addWidget(self.stack, 1)

        self.switch_tab(0)

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
        """)
        c_layout.addWidget(self.log_edit)
        root_layout.addWidget(self.console_container)

        self.log_cli("device ready: paw3395 (compx/holtek)")

    def switch_tab(self, index):
        self.stack.setCurrentIndex(index)
        for i, b in enumerate(self.nav_btns):
            b.setActive(i == index)

    def build_sensor_tab(self):
        page = QWidget()
        grid_layout = QHBoxLayout(page)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setSpacing(6)

        # Left Column: CPI & LOD
        left_card = CardFrame("// CPI", parent=page)
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(8, 16, 8, 8)
        left_layout.setSpacing(6)

        cpi_row = QHBoxLayout()
        self.cpi_num_lbl = QLabel(f"{self.current_dpi}", page)
        font_cpi = QFont("Impact", 28)
        font_cpi.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        self.cpi_num_lbl.setFont(font_cpi)
        self.cpi_num_lbl.setStyleSheet("color: #FFFFFF; margin: 0; padding: 0;")

        cpi_sub = QLabel("CPI", page)
        font_sub = QFont("Cascadia Mono", 8, QFont.Weight.Bold)
        font_sub.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        cpi_sub.setFont(font_sub)
        cpi_sub.setStyleSheet("color: #FFFFFF; background-color: #0026FF; padding: 1px 4px;")

        cpi_row.addWidget(self.cpi_num_lbl)
        cpi_row.addWidget(cpi_sub, 0, Qt.AlignmentFlag.AlignVCenter)
        cpi_row.addStretch()

        btn_minus = QPushButton("[-50]", page)
        btn_plus = QPushButton("[+50]", page)
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

        rate_card = CardFrame("// USB CLOCK", parent=page)
        rate_layout = QVBoxLayout(rate_card)
        rate_layout.setContentsMargins(8, 14, 8, 6)
        rate_layout.setSpacing(4)

        self.rate_info_lbl = QLabel(f"CYCLE: 1.0ms // {self.current_rate} Hz", page)
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

        dsp_card = CardFrame("// DSP SETTINGS", parent=page)
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
        self.stack.addWidget(page)

    def build_lighting_tab(self):
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Left: Mouse RGB Engine
        rgb_card = CardFrame("// RGB ENGINE", parent=page)
        rgb_vbox = QVBoxLayout(rgb_card)
        rgb_vbox.setContentsMargins(8, 16, 8, 8)
        rgb_vbox.setSpacing(6)

        lbl_mode = QLabel("// EFFECT MODE:", page)
        lbl_mode.setFont(QFont("Cascadia Mono", 8, QFont.Weight.Bold))
        lbl_mode.setStyleSheet("color: #A5A5AC;")
        rgb_vbox.addWidget(lbl_mode)

        self.effect_btns = {}
        effects = [("OFF", 0), ("STATIC", 1), ("BREATHE", 2), ("NEON", 3), ("CLICK", 4)]
        effect_row = QHBoxLayout()
        effect_row.setSpacing(4)
        for name, code in effects:
            btn = PlaqueButton(name, rgb_card)
            btn.clicked.connect(lambda ch, c=code: self.apply_rgb_effect(c))
            self.effect_btns[code] = btn
            effect_row.addWidget(btn)
        rgb_vbox.addLayout(effect_row)

        lbl_bright = QLabel("// BRIGHTNESS:", page)
        lbl_bright.setFont(QFont("Cascadia Mono", 8, QFont.Weight.Bold))
        lbl_bright.setStyleSheet("color: #A5A5AC;")
        rgb_vbox.addWidget(lbl_bright)

        self.bright_btns = {}
        bright_levels = [("10%", 0x10), ("25%", 0x3f), ("50%", 0x7f), ("75%", 0xbf), ("100%", 0xff)]
        bright_row = QHBoxLayout()
        bright_row.setSpacing(4)
        for name, val in bright_levels:
            btn = PlaqueButton(name, rgb_card)
            btn.clicked.connect(lambda ch, v=val: self.apply_rgb_brightness(v))
            self.bright_btns[val] = btn
            bright_row.addWidget(btn)
        rgb_vbox.addLayout(bright_row)

        lbl_speed = QLabel("// SPEED:", page)
        lbl_speed.setFont(QFont("Cascadia Mono", 8, QFont.Weight.Bold))
        lbl_speed.setStyleSheet("color: #A5A5AC;")
        rgb_vbox.addWidget(lbl_speed)

        self.speed_btns = {}
        speed_row = QHBoxLayout()
        speed_row.setSpacing(4)
        for s in [1, 2, 3, 4, 5]:
            btn = PlaqueButton(f"SPD {s}", rgb_card)
            btn.clicked.connect(lambda ch, sp=s: self.apply_rgb_speed(sp))
            self.speed_btns[s] = btn
            speed_row.addWidget(btn)
        rgb_vbox.addLayout(speed_row)

        lbl_pal = QLabel("// COLOR PALETTE:", page)
        lbl_pal.setFont(QFont("Cascadia Mono", 8, QFont.Weight.Bold))
        lbl_pal.setStyleSheet("color: #A5A5AC;")
        rgb_vbox.addWidget(lbl_pal)

        palette_row = QHBoxLayout()
        palette_row.setSpacing(4)
        colors = [
            QColor(255, 0, 0), QColor(255, 122, 0), QColor(226, 236, 52),
            QColor(0, 255, 65), QColor(0, 240, 255), QColor(0, 38, 255),
            QColor(140, 86, 241), QColor(255, 255, 255)
        ]
        for c_idx, clr in enumerate(colors):
            c_btn = QPushButton(page)
            c_btn.setFixedSize(22, 22)
            c_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            c_btn.setStyleSheet(f"background-color: {clr.name()}; border: 1px solid #303036;")
            c_btn.clicked.connect(lambda ch, ci=c_idx+1: self.apply_rgb_color(ci))
            palette_row.addWidget(c_btn)
        rgb_vbox.addLayout(palette_row)

        layout.addWidget(rgb_card, 1)

        # Right: DPI Stage LED Colors
        dpi_led_card = CardFrame("// DPI STAGE LED", parent=page)
        dpi_vbox = QVBoxLayout(dpi_led_card)
        dpi_vbox.setContentsMargins(8, 16, 8, 8)
        dpi_vbox.setSpacing(6)

        info_lbl = QLabel("// INDIVIDUAL STAGE INDICATOR COLORS", page)
        info_lbl.setFont(QFont("Cascadia Mono", 7))
        info_lbl.setStyleSheet("color: #A5A5AC;")
        dpi_vbox.addWidget(info_lbl)

        self.stage_swatches = []
        stages_grid = QGridLayout()
        stages_grid.setSpacing(6)

        stage_default_cpi = [400, 800, 1600, 2400, 3200, 6400]
        for s in range(6):
            lbl_s = QLabel(f"STAGE {s+1} [{stage_default_cpi[s]}]", page)
            lbl_s.setFont(QFont("Cascadia Mono", 8, QFont.Weight.Bold))
            lbl_s.setStyleSheet("color: #FFFFFF;")

            swatch = ColorSwatchButton(QColor(0, 255, 65), page)
            swatch.color_chosen.connect(lambda clr, st=s: self.apply_stage_color(st, clr))
            self.stage_swatches.append(swatch)

            stages_grid.addWidget(lbl_s, s, 0)
            stages_grid.addWidget(swatch, s, 1)

        dpi_vbox.addLayout(stages_grid)
        dpi_vbox.addStretch()
        layout.addWidget(dpi_led_card, 1)

        self.stack.addWidget(page)

    def build_hardware_tab(self):
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Left Column: Debounce & Sleep Timer
        left_vbox = QVBoxLayout()
        left_vbox.setSpacing(6)

        deb_card = CardFrame("// KEY DEBOUNCE", parent=page)
        deb_layout = QVBoxLayout(deb_card)
        deb_layout.setContentsMargins(8, 16, 8, 8)
        deb_layout.setSpacing(6)

        deb_info = QLabel("// SWITCH FILTER DELAY (ANTI-CHATTER)", page)
        deb_info.setFont(QFont("Cascadia Mono", 7))
        deb_info.setStyleSheet("color: #A5A5AC;")
        deb_layout.addWidget(deb_info)

        self.deb_btns = {}
        deb_row = QHBoxLayout()
        deb_row.setSpacing(3)
        for d in self.ctl.DEBOUNCE_VALS:
            btn = PlaqueButton(f"{d}MS", deb_card)
            btn.clicked.connect(lambda ch, ms=d: self.apply_debounce(ms))
            self.deb_btns[d] = btn
            deb_row.addWidget(btn)
        deb_layout.addLayout(deb_row)
        left_vbox.addWidget(deb_card)

        sleep_card = CardFrame("// SLEEP TIMEOUT", parent=page)
        slp_layout = QVBoxLayout(sleep_card)
        slp_layout.setContentsMargins(8, 16, 8, 8)
        slp_layout.setSpacing(6)

        slp_info = QLabel("// MOTIONLESS AUTO-STANDBY TIMER", page)
        slp_info.setFont(QFont("Cascadia Mono", 7))
        slp_info.setStyleSheet("color: #A5A5AC;")
        slp_layout.addWidget(slp_info)

        self.slp_btns = {}
        slp_row = QHBoxLayout()
        slp_row.setSpacing(3)
        for sec, code, label in self.ctl.SLEEP_CODES:
            btn = PlaqueButton(label, sleep_card)
            btn.clicked.connect(lambda ch, cd=code, sc=sec: self.apply_sleep_time(cd, sc))
            self.slp_btns[code] = btn
            slp_row.addWidget(btn)
        slp_layout.addLayout(slp_row)
        left_vbox.addWidget(sleep_card)

        layout.addLayout(left_vbox, 1)

        # Right Column: System & Hardware Telemetry
        hw_card = CardFrame("// CONTROLLER INFO", parent=page)
        hw_layout = QVBoxLayout(hw_card)
        hw_layout.setContentsMargins(8, 16, 8, 8)
        hw_layout.setSpacing(8)

        self.hw_sensor_lbl = QLabel("SENSOR: PIXART PAW3395 (26000 CPI)", page)
        self.hw_sensor_lbl.setFont(QFont("Cascadia Mono", 8, QFont.Weight.Bold))
        self.hw_sensor_lbl.setStyleSheet("color: #FFFFFF;")

        self.hw_mcu_lbl = QLabel("MCU: COMPX / HOLTEK HIGH-SPEED USB", page)
        self.hw_mcu_lbl.setFont(QFont("Cascadia Mono", 8))
        self.hw_mcu_lbl.setStyleSheet("color: #A5A5AC;")

        self.hw_mode_lbl = QLabel("LINK: 2.4G WIRELESS DONGLE", page)
        self.hw_mode_lbl.setFont(QFont("Cascadia Mono", 8))
        self.hw_mode_lbl.setStyleSheet("color: #00FF41;")

        self.hw_pid_lbl = QLabel("DEVICE ID: VID 0x373B // PID 0x100F", page)
        self.hw_pid_lbl.setFont(QFont("Cascadia Mono", 8))
        self.hw_pid_lbl.setStyleSheet("color: #A5A5AC;")

        hw_layout.addWidget(self.hw_sensor_lbl)
        hw_layout.addWidget(self.hw_mcu_lbl)
        hw_layout.addWidget(self.hw_mode_lbl)
        hw_layout.addWidget(self.hw_pid_lbl)
        hw_layout.addStretch()

        layout.addWidget(hw_card, 1)
        self.stack.addWidget(page)

    def build_keys_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        key_card = CardFrame("// KEY MATRIX REBINDING", parent=page)
        k_layout = QVBoxLayout(key_card)
        k_layout.setContentsMargins(8, 16, 8, 8)
        k_layout.setSpacing(6)

        info_lbl = QLabel("// REMAP 6 PHYSICAL SWITCHES VIA HARDWARE EEPROM", page)
        info_lbl.setFont(QFont("Cascadia Mono", 7))
        info_lbl.setStyleSheet("color: #A5A5AC;")
        k_layout.addWidget(info_lbl)

        self.key_combos = []
        buttons_names = [
            "BUTTON 1 [LEFT CLICK]",
            "BUTTON 2 [RIGHT CLICK]",
            "BUTTON 3 [MIDDLE CLICK]",
            "BUTTON 4 [SIDE FORWARD]",
            "BUTTON 5 [SIDE BACKWARD]",
            "BUTTON 6 [DPI CYCLE]"
        ]

        grid = QGridLayout()
        grid.setSpacing(6)

        for idx, bname in enumerate(buttons_names):
            lbl = QLabel(bname, page)
            lbl.setFont(QFont("Cascadia Mono", 8, QFont.Weight.Bold))
            lbl.setStyleSheet("color: #FFFFFF;")

            cb = QComboBox(page)
            for title, kcls, v1, v2, v3 in self.ctl.KEY_BINDINGS:
                cb.addItem(title, (kcls, v1, v2, v3))
            cb.setCurrentIndex(idx if idx < len(self.ctl.KEY_BINDINGS) else 0)
            cb.currentIndexChanged.connect(lambda c_idx, k=idx: self.on_key_bound(k, c_idx))
            self.key_combos.append(cb)

            row = idx // 2
            col = (idx % 2) * 2
            grid.addWidget(lbl, row, col)
            grid.addWidget(cb, row, col + 1)

        k_layout.addLayout(grid)
        k_layout.addStretch()
        layout.addWidget(key_card)

        self.stack.addWidget(page)

    def toggle_console(self):
        self.is_log_expanded = not self.is_log_expanded
        self.console_container.setVisible(self.is_log_expanded)
        if self.is_log_expanded:
            self.btn_toggle_log.setText("[ - TELEMETRY ]")
            self.resize(self.width(), self.height() + 146)
        else:
            self.btn_toggle_log.setText("[ + TELEMETRY ]")
            self.resize(self.width(), max(390, self.height() - 146))

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

        # Update RGB
        self.rgb_effect = state['rgb_effect']
        self.rgb_brightness = state['rgb_brightness']
        self.rgb_speed = state['rgb_speed']
        self.rgb_color = state['rgb_color']
        self.update_rgb_buttons()

        # Update Debounce & Sleep
        self.debounce_ms = state['debounce']
        for ms, b in self.deb_btns.items():
            b.setActive(ms == self.debounce_ms)

        self.sleep_code = state['sleep_code']
        for code, b in self.slp_btns.items():
            b.setActive(code == self.sleep_code)

        # Update Stage colors
        if 'stage_colors' in state and len(state['stage_colors']) == 6:
            self.stage_colors = state['stage_colors']
            for s, clr_tuple in enumerate(self.stage_colors):
                self.stage_swatches[s].set_color(QColor(*clr_tuple))

        # Hardware labels
        bus_str = "USB DIRECT" if self.is_wired else "2.4G WIRELESS DONGLE"
        self.hw_mode_lbl.setText(f"LINK: {bus_str}")
        self.hw_pid_lbl.setText(f"DEVICE ID: VID 0x373B // PID 0x{self.current_pid:04X}")

        bus_name = "USB" if self.is_wired else "2.4G"
        self.tray.setToolTip(f"MAD G ({bus_name})\nBattery: {self.current_battery}% | {self.current_dpi} CPI")

    def update_rgb_buttons(self):
        for eff, b in self.effect_btns.items():
            b.setActive(eff == self.rgb_effect)
        for br, b in self.bright_btns.items():
            b.setActive(br == self.rgb_brightness)
        for sp, b in self.speed_btns.items():
            b.setActive(sp == self.rgb_speed)

    def on_connection_changed(self, connected, pid, wired):
        self.is_connected = connected
        self.is_wired = wired
        self.current_pid = pid

        if connected:
            self.status_badge.setText("● CONNECTED")
            self.status_badge.setStyleSheet("color: #00FF41; background-color: #141418; border: 1px solid #303036; padding: 2px 6px;")
            bus_type = "direct usb" if wired else "2.4g wireless"
            self.log_cli(f"connected: {bus_type} (pid=0x{pid:04x})", "[*]")
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

    def apply_rgb_effect(self, code):
        self.rgb_effect = code
        self.update_rgb_buttons()
        self.log_cli(f"rgb effect set: {code}")
        QTimer.singleShot(10, lambda: self.ctl.set_rgb(self.rgb_effect, self.rgb_brightness, self.rgb_speed, self.rgb_color))

    def apply_rgb_brightness(self, val):
        self.rgb_brightness = val
        self.update_rgb_buttons()
        self.log_cli(f"rgb brightness set: 0x{val:02x}")
        QTimer.singleShot(10, lambda: self.ctl.set_rgb(self.rgb_effect, self.rgb_brightness, self.rgb_speed, self.rgb_color))

    def apply_rgb_speed(self, val):
        self.rgb_speed = val
        self.update_rgb_buttons()
        self.log_cli(f"rgb speed set: {val}")
        QTimer.singleShot(10, lambda: self.ctl.set_rgb(self.rgb_effect, self.rgb_brightness, self.rgb_speed, self.rgb_color))

    def apply_rgb_color(self, idx):
        self.rgb_color = idx
        self.log_cli(f"rgb color preset set: {idx}")
        QTimer.singleShot(10, lambda: self.ctl.set_rgb(self.rgb_effect, self.rgb_brightness, self.rgb_speed, self.rgb_color))

    def apply_stage_color(self, stage, color):
        r, g, b = color.red(), color.green(), color.blue()
        self.log_cli(f"dpi stage {stage+1} color set: rgb({r},{g},{b})")
        QTimer.singleShot(10, lambda: self.ctl.set_dpi_color(stage, r, g, b))

    def apply_debounce(self, ms):
        self.debounce_ms = ms
        for d, b in self.deb_btns.items():
            b.setActive(d == ms)
        self.log_cli(f"key debounce delay set: {ms}ms")
        QTimer.singleShot(10, lambda: self.ctl.set_key_debounce(ms))

    def apply_sleep_time(self, code, sec):
        self.sleep_code = code
        for c, b in self.slp_btns.items():
            b.setActive(c == code)
        self.log_cli(f"motionless sleep timeout set: {sec}s")
        QTimer.singleShot(10, lambda: self.ctl.set_sleep_time(code))

    def on_key_bound(self, key_idx, combo_idx):
        data = self.key_combos[key_idx].itemData(combo_idx)
        if data:
            kcls, v1, v2, v3 = data
            self.log_cli(f"button {key_idx+1} remapped to class=0x{kcls:02x}")
            QTimer.singleShot(10, lambda: self.ctl.set_key_binding(key_idx, kcls, v1, v2, v3))

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
