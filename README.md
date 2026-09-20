# MAD G Hub

A fast, ultra-compact native desktop utility for **MAD G** gaming mice powered by the **PixArt PAW3395** optical sensor.

Built using Python, PyQt6, and direct USB/HID communication via `hidapi`.

---

## Features

- **Dual-Bus Support:** Automatic detection and hot-plugging between **Direct USB Cable** (`VID: 0x373B`, `PID: 0x100D` / `0x10C6`) and **2.4G Wireless Dongle** (`PID: 0x100F` / `0x1010`).
- **Real-Time Telemetry:** Battery percentage, charging status indicator, active CPI, polling rate, and connection health.
- **CPI / DPI Adjustment:**
  - Range: `200` to `12,000` CPI in precise `50` CPI steps.
  - Interactive calibrated segmented slider.
  - Quick-select presets: `400`, `800`, `1200`, `1600`, `2400`, `3200`, `6400`, `12000`.
  - Nudge buttons (`[-50]` / `[+50]`).
- **USB Polling Rate:**
  - Instant switching: `125 Hz`, `250 Hz`, `500 Hz`, `1000 Hz`.
  - Animated hardware clock cycle visualizer.
- **Lift-Off Distance (LOD):** Switchable between `1.0 mm` and `2.0 mm`.
- **Sensor DSP Pipeline:**
  - **Motion Sync:** SPI sensor-to-USB report clock synchronization.
  - **Angle Snapping:** Directional axis drift suppression and linear vector angle lock.
  - **Ripple Control:** High-frequency jitter smoothing at elevated CPI.
- **Collapsible Telemetry Drawer:** Embedded terminal logging hardware events, report rate handshakes, and diagnostic codes.
- **System Tray Integration:** Minimize to background tray, quick status tooltip, and graceful process management.

---

## Requirements

- **OS:** Windows 10 / 11 (64-bit)
- **Python:** 3.10 or higher
- Mouse connected via USB cable or 2.4G wireless adapter

---

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/<your-username>/mad-hub-native.git
   cd mad-hub-native
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

---

## Usage

### Run with Python
```bash
python app.py
```

### Run silently without console
```bash
pythonw app.py
```
Or double-click `start.bat`.

---

## License

This project is licensed under the [MIT License](LICENSE).
