# EMG Flappy Bird (COM6 @ 2000 baud)

A Flappy Bird clone controlled by EMG spikes from a serial device.

## Features
- Serial EMG control from `COM6` with `baudrate=2000`
- 12-channel frame support (uses channel 1 / first value)
- Startup calibration menu (calibrates first, then waits for manual start)
- Hysteresis trigger logic to prevent repeated flaps from one sustained flex
- Dedicated side telemetry panel with live EMG graph (`0-2500` range)
- Keyboard fallback (`SPACE`) for testing without EMG
- Restart with `R`

## Requirements
- Python 3.10+
- An EMG board streaming values over serial

## Setup
```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run
```bash
python main.py
```

## Controls
- Menu: wait for calibration, then press `ENTER` to start
- In game: flex EMG or press `SPACE` to flap
- Game over: press `R` to restart
- Right panel: live CH1 signal graph + threshold/release lines

## EMG Input Format
The game accepts:
- plain numeric line: `123`
- text/CSV line where first numeric token is parseable.

## Tuning
If flaps trigger too easily or not enough, adjust constants in `main.py`:
- `THRESHOLD_MULTIPLIER`
- `MIN_THRESHOLD`
- `HYSTERESIS_RELEASE_RATIO`
- `MIN_HYSTERESIS_GAP`
- `TRIGGER_DEBOUNCE_SEC`
- `SMOOTHING`
- `GRAPH_MAX` (default `2500.0`)

## Notes
- This project defaults to `COM6` and `2000` baud exactly as requested.
- If your board is on another serial port, change `EMG_PORT` in `main.py`.
