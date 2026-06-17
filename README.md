# OnePlus Nord Buds Control for Linux

A native GTK4/Libadwaita application for Linux to control your OnePlus Nord Buds 3 Pro (and potentially other BBK ecosystem earbuds). This application communicates with the earbuds using their proprietary OPO BLE protocol to check battery levels and toggle Active Noise Cancellation (ANC) modes.

## Features

- **Native UI**: Built with GTK4 and Libadwaita for a seamless, modern Linux desktop experience.
- **Battery Monitoring**: Accurately tracks the battery level of your Left Earbud, Right Earbud, and Charging Case.
- **ANC Control**: Easily toggle between:
  - ANC On (Noise Cancellation)
  - Transparency Mode
  - ANC Off
- **Connection Handling**: Uses your existing classic Bluetooth pairing (via `bluetoothctl`) and establishes a BLE notification channel, allowing control without disrupting your audio playback.

## Prerequisites

Before running the application, make sure your earbuds are already paired and connected to your computer via standard Bluetooth settings.

You will also need the following system dependencies installed (names may vary depending on your distribution):

- `python3`
- `python3-venv`
- `libgirepository1.0-dev`
- `libcairo2-dev`
- `pkg-config`
- `gir1.2-gtk-4.0`
- `gir1.2-adw-1`

### Ubuntu/Debian Example:
```bash
sudo apt update
sudo apt install python3-venv libgirepository1.0-dev libcairo2-dev pkg-config gir1.2-gtk-4.0 gir1.2-adw-1
```

## Installation

1. Clone this repository:
```bash
git clone https://github.com/yourusername/nordbuds-linux.git
cd nordbuds-linux
```

2. Create a virtual environment:
```bash
python3 -m venv venv
```

3. Install the Python dependencies:
```bash
./venv/bin/pip install -r requirements.txt
```

4. Make the run script executable:
```bash
chmod +x run.sh
```

## Usage

Simply execute the `run.sh` script to launch the app:

```bash
./run.sh
```

### Notes & Troubleshooting

- **Duplicate Connections**: The app intentionally searches for your already-paired earbuds using `bluetoothctl` and connects to that MAC address. This prevents creating ghost/duplicate BLE devices in your system's Bluetooth menu.
- **No Battery / No RX**: If the app connects but fails to show battery data or toggle ANC, ensure that the official HeyMelody app on your smartphone is **not** actively connected to the earbuds at the same time. The earbuds can only handle one active BLE control session.
- **Logs**: If you encounter issues, check the `app.log` file generated in the project directory for debug information.

## Acknowledgements

Protocol reverse-engineering inspired by the OPO v1 BLE protocol analysis for OnePlus Buds.
