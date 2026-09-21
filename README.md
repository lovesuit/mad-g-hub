# MAD G Hub

Desktop settings tool for MAD G mice using the PixArt PAW3395 sensor. It talks to the mouse directly through HID reports using Python, PyQt6, and `hidapi`.

## Features

- Supports both wired USB (PID `0x100D`, `0x10C6`) and 2.4 GHz wireless dongle (PID `0x100F`, `0x1010`), switching automatically when connected.
- Shows battery percentage, charging state, current CPI, polling rate, and connection status.
- CPI adjustment from 200 to 12,000 in steps of 50, with a slider, +/-50 buttons, and presets for 400, 800, 1200, 1600, 2400, 3200, 6400, and 12,000.
- Polling rate selection for 125, 250, 500, and 1000 Hz with a cycle wave monitor.
- Lift-off distance switchable between 1.0 mm and 2.0 mm.
- Sensor toggles for Motion Sync, Angle Snapping, and Ripple Control.
- Collapsible log panel for hardware readouts and setting confirmations.
- Minimizes to the system tray.

## Requirements

- Windows 10 or 11 (64-bit)
- Python 3.10 or higher
- Supported MAD G mouse plugged in via cable or 2.4 GHz receiver

## Installation

Clone the repository and install the dependencies:

```bash
git clone https://github.com/lovesuit/mad-g-hub.git
cd mad-g-hub
pip install -r requirements.txt
```

## Usage

Run with a console window:
```bash
python app.py
```

Run in the background without a console window:
```bash
pythonw app.py
```

You can also double-click `start.bat`.

## License

This project is licensed under the [MIT License](LICENSE).
