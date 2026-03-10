# EMG Flappy Bird (COM6 @ 2000 baud)

A Flappy Bird clone controlled by EMG spikes from a serial device.

## Features
- Serial EMG control from `COM6` with `baudrate=2000`
- Auto-calibration on startup (baseline + dynamic threshold)
- Debounced trigger detection to avoid rapid accidental flaps
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

## EMG Input Format
The game accepts:
- plain numeric line: `123`
- text/CSV line where first numeric token is parseable.

## Tuning
If flaps trigger too easily or not enough, adjust constants in `main.py`:
- `THRESHOLD_MULTIPLIER`
- `MIN_THRESHOLD`
- `TRIGGER_DEBOUNCE_SEC`
- `SMOOTHING`

## Notes
- This project defaults to `COM6` and `2000` baud exactly as requested.
- If your board is on another serial port, change `EMG_PORT` in `main.py`.
