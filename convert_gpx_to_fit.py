#!/usr/bin/env python3
"""
Convert .gpx files in a folder to .fit.gz files.

Embeds a full FIT *activity* layout (file_id, timer events, records, lap, session, activity)
as required for typical training platforms (see Garmin FIT encoding guidance for activity files).

Usage:
    python gpx_to_fit.py <input_folder> [output_folder]

    input_folder   : folder containing .gpx files
    output_folder  : where to write .fit.gz files (default: <input_folder>/fit_output)

Requires: pip install gpxpy fit-tool
"""

from __future__ import annotations

import argparse
import gzip
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import gpxpy
from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.activity_message import ActivityMessage
from fit_tool.profile.messages.event_message import EventMessage
from fit_tool.profile.messages.file_creator_message import FileCreatorMessage
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.lap_message import LapMessage
from fit_tool.profile.messages.record_message import RecordMessage
from fit_tool.profile.messages.session_message import SessionMessage
from fit_tool.profile.profile_type import (
    Activity,
    Event,
    EventType,
    FileType,
    LapTrigger,
    Manufacturer,
    Sport,
    SubSport,
)


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points in meters."""
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def _collect_points(gpx: gpxpy.gpx.GPX) -> list:
    points = []
    for track in gpx.tracks:
        for segment in track.segments:
            for p in segment.points:
                if p.latitude is None or p.longitude is None:
                    continue
                points.append(p)
    return points


def _timestamps_ms(points: list) -> list[int]:
    """Return per-point UTC timestamps in milliseconds; synthesize 1 Hz if missing."""
    if not points:
        return []
    has_any = any(p.time for p in points)
    if not has_any:
        base = int(datetime.now(timezone.utc).timestamp() * 1000)
        return [base + i * 1000 for i in range(len(points))]
    first = next(p.time for p in points if p.time)
    base = int(first.replace(tzinfo=timezone.utc).timestamp() * 1000)
    out = []
    last_ms = None
    for p in points:
        if p.time:
            last_ms = int(p.time.replace(tzinfo=timezone.utc).timestamp() * 1000)
            out.append(last_ms)
        else:
            last_ms = (last_ms or base) + 1000
            out.append(last_ms)
    return out


def gpx_to_fit_gz(gpx_path: Path, fit_gz_path: Path) -> None:
    with gpx_path.open("r", encoding="utf-8", errors="replace") as f:
        gpx = gpxpy.parse(f)

    points = _collect_points(gpx)
    if len(points) < 2:
        raise ValueError(f"need at least 2 valid track points: {gpx_path}")

    ts_ms = _timestamps_ms(points)
    start_ts = ts_ms[0]
    end_ts = ts_ms[-1]

    builder = FitFileBuilder(auto_define=True, min_string_size=50)

    fid = FileIdMessage()
    fid.type = FileType.ACTIVITY
    fid.manufacturer = Manufacturer.COROS.value
    fid.product = 0
    fid.time_created = start_ts
    fid.serial_number = 0
    builder.add(fid)

    creator = FileCreatorMessage()
    creator.software_version = 100
    builder.add(creator)

    ev_start = EventMessage()
    ev_start.event = Event.TIMER
    ev_start.event_type = EventType.START
    ev_start.timestamp = start_ts
    builder.add(ev_start)

    distance = 0.0
    prev = None
    records = []
    for i, p in enumerate(points):
        if prev is not None:
            distance += _haversine_m(prev.latitude, prev.longitude, p.latitude, p.longitude)
        rec = RecordMessage()
        rec.position_lat = p.latitude
        rec.position_long = p.longitude
        rec.distance = distance
        rec.timestamp = ts_ms[i]
        if p.elevation is not None:
            rec.altitude = p.elevation
        records.append(rec)
        prev = p

    builder.add_all(records)

    stop_ts = max(end_ts, start_ts + 1000)
    elapsed_sec = max((stop_ts - start_ts) / 1000.0, 1.0)
    total_distance = distance
    first, last = points[0], points[-1]

    ev_stop = EventMessage()
    ev_stop.event = Event.TIMER
    ev_stop.event_type = EventType.STOP
    ev_stop.timestamp = stop_ts
    builder.add(ev_stop)

    sport = Sport.RUNNING
    sub = SubSport.GENERIC

    lap = LapMessage()
    lap.message_index = 0
    lap.timestamp = stop_ts
    lap.start_time = start_ts
    lap.total_elapsed_time = elapsed_sec
    lap.total_timer_time = elapsed_sec
    lap.total_distance = total_distance
    lap.start_position_lat = first.latitude
    lap.start_position_long = first.longitude
    lap.end_position_lat = last.latitude
    lap.end_position_long = last.longitude
    lap.sport = sport
    lap.sub_sport = sub
    lap.lap_trigger = LapTrigger.SESSION_END
    builder.add(lap)

    sess = SessionMessage()
    sess.message_index = 0
    sess.timestamp = stop_ts
    sess.start_time = start_ts
    sess.first_lap_index = 0
    sess.num_laps = 1
    sess.sport = sport
    sess.sub_sport = sub
    sess.total_elapsed_time = elapsed_sec
    sess.total_timer_time = elapsed_sec
    sess.total_distance = total_distance
    sess.start_position_lat = first.latitude
    sess.start_position_long = first.longitude
    if elapsed_sec > 0:
        sess.avg_speed = total_distance / elapsed_sec
    builder.add(sess)

    act = ActivityMessage()
    act.timestamp = stop_ts
    act.total_timer_time = elapsed_sec
    act.num_sessions = 1
    act.type = Activity.MANUAL
    builder.add(act)

    fit_file = builder.build()
    raw = fit_file.to_bytes()
    fit_gz_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(fit_gz_path, "wb") as gz:
        gz.write(raw)


def convert_gpx_folder(input_dir: str | Path, output_dir: str | Path) -> None:
    input_dir = Path(input_dir).resolve()
    output_dir = Path(output_dir).resolve()

    if not input_dir.is_dir():
        raise ValueError(f"Not a directory: {input_dir}")

    gpx_files = sorted(input_dir.glob("*.gpx"))
    if not gpx_files:
        raise ValueError(f"No .gpx files in {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Found {len(gpx_files)} .gpx file(s) in {input_dir}")

    ok, failed = 0, 0
    for gpx_path in gpx_files:
        fit_gz_path = output_dir / (gpx_path.stem + ".fit.gz")
        try:
            gpx_to_fit_gz(gpx_path, fit_gz_path)
            print(f"OK  {gpx_path.name} -> {fit_gz_path.name}")
            ok += 1
        except Exception as e:
            print(f"ERR {gpx_path.name}: {e}")
            failed += 1

    print(
        f"Summary: converted {ok} of {len(gpx_files)} file(s)"
        + (f"; {failed} failed" if failed else "")
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert .gpx files to .fit.gz activity files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "input_dir",
        type=Path,
        help="Folder containing .gpx files to convert.",
    )
    parser.add_argument(
        "output_dir",
        type=Path,
        nargs="?",
        default=None,
        help="Folder to write .fit.gz files to (default: <input_dir>/fit_output).",
    )
    args = parser.parse_args()

    output_dir = args.output_dir or (args.input_dir / "fit_output")

    try:
        convert_gpx_folder(args.input_dir, output_dir)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()