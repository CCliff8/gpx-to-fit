# GPX to FIT Converter

A Python script to batch convert `.gpx` activity files into `.fit.gz` format, compatible with training platforms such as Strava, Coros and Garmin Connect.

---

## What it does

Takes a folder of `.gpx` files and converts each one into a structured `.fit.gz` activity file, embedding GPS track points, distance, elevation, and all required FIT activity metadata (lap, session, events).

---

## Requirements

- Python 3.9+
- Install dependencies:

```bash
pip install gpxpy fit-tool
```

---

## How to run

```bash
python3 /your/path/convert_gpx_to_fit.py "input_folder" "output_folder"
```

- `input_folder` — folder containing your `.gpx` files
- `output_folder` — where the converted `.fit.gz` files will be saved

## Notes

- Both paths must be wrapped in quotes if they contain spaces.
- Files with fewer than 2 valid track points are skipped.
- If GPX points have no timestamps, they are synthesized automatically at 1 Hz. This is needed because the .fit.gz format requires timestamps on every point.
