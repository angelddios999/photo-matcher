"""Apple Photos / Google Photos duplicate matcher module."""

import calendar
import shutil
import sqlite3
import subprocess
import time
from datetime import date, datetime, timezone
from pathlib import Path

from google_photos import TIMESTAMP_TOLERANCE_SECS

_PHOTOS_DB = Path.home() / "Pictures/Photos Library.photoslibrary/database/Photos.sqlite"
# Apple Core Data epoch starts at 2001-01-01 00:00:00 UTC
_APPLE_EPOCH_OFFSET = 978_307_200


def find_duplicates(google_index: dict, start_date: date, end_date: date) -> list[dict]:
    import osxphotos

    db = osxphotos.PhotosDB()
    photos = db.photos(
        from_date=datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc),
        to_date=datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc),
    )

    matches = []
    for photo in photos:
        google_matches = None
        for apple_ts in _apple_timestamps(photo):
            google_matches = _lookup_with_tolerance(google_index, apple_ts)
            if google_matches:
                break
        if google_matches:
            matches.append({
                "apple": {
                    "uuid": photo.uuid,
                    "filename": photo.original_filename,
                    "date": photo.date.isoformat() if photo.date else None,
                    "path": str(photo.path) if photo.path else None,
                    "is_video": not photo.isphoto,
                },
                "google": google_matches[0],
            })

    return matches


def _apple_timestamps(photo) -> list[int]:
    """Return candidate Unix timestamps to try when matching against Google.

    Google Photos uses two conventions depending on how the photo was uploaded:
      1. Local wall-clock time stored *as if* it were UTC (common for Apple transfers).
      2. Actual UTC timestamp (used for some photos).
    We return both so either convention gets matched.
    """
    if not photo.date:
        return []
    candidates: set[int] = set()
    # Convention 1: treat local wall-clock as UTC
    candidates.add(calendar.timegm(photo.date.timetuple()))
    # Convention 2: actual UTC (only valid when the datetime is timezone-aware)
    if photo.date.tzinfo is not None:
        candidates.add(int(photo.date.timestamp()))
    return list(candidates)


def _lookup_with_tolerance(index: dict, ts: int):
    for delta in range(0, TIMESTAMP_TOLERANCE_SECS + 1):
        for candidate in (ts + delta, ts - delta) if delta else (ts,):
            result = index.get(candidate)
            if result:
                return result
    return None


def delete_duplicates(matches: list[dict]) -> int:
    """Move matched Apple Photos to Recently Deleted via direct database update.

    Photos.app must be closed before calling this — the function will refuse to
    proceed if it detects Photos is running.
    """
    # Safety: ensure Photos.app is not open
    running = subprocess.run(["pgrep", "-x", "Photos"], capture_output=True, text=True)
    if running.stdout.strip():
        raise RuntimeError(
            "Photos.app is currently open. Close it first, then re-run with --delete."
        )

    if not _PHOTOS_DB.exists():
        raise RuntimeError(f"Photos database not found at {_PHOTOS_DB}")

    # Back up the database before modifying it
    backup = _PHOTOS_DB.with_suffix(".sqlite.bak")
    shutil.copy2(_PHOTOS_DB, backup)
    print(f"  Database backed up → {backup}")

    uuids = [m["apple"]["uuid"] for m in matches]
    apple_now = time.time() - _APPLE_EPOCH_OFFSET

    conn = sqlite3.connect(str(_PHOTOS_DB))
    try:
        # Photos.sqlite triggers call Core Data internal functions that only
        # exist when the framework is loaded. Register no-op stubs so the
        # triggers fire without error.
        conn.create_function("NSCoreDataTriggerUpdateAffectedObjectValue", -1, lambda *a: None)

        placeholders = ",".join("?" for _ in uuids)
        cur = conn.execute(
            f"""
            UPDATE ZASSET
               SET ZTRASHEDSTATE = 1, ZTRASHEDDATE = ?
             WHERE ZUUID IN ({placeholders})
               AND ZTRASHEDSTATE = 0
            """,
            [apple_now, *uuids],
        )
        count = cur.rowcount
        conn.commit()
    finally:
        conn.close()

    return count


def print_dry_run_report(matches: list[dict]) -> None:
    if not matches:
        print("\nNo duplicates found.")
        return

    photos = [m for m in matches if not m["apple"]["is_video"]]
    videos = [m for m in matches if m["apple"]["is_video"]]

    print(f"\n{'='*80}")
    print(f"DRY RUN REPORT — {len(matches)} duplicate(s) found")
    print(f"  Photos: {len(photos)}  |  Videos: {len(videos)}")
    print(f"{'='*80}")

    if photos:
        print(f"\n--- PHOTOS ({len(photos)}) ---")
        _print_matches(photos)

    if videos:
        print(f"\n--- VIDEOS ({len(videos)}) ---")
        _print_matches(videos)

    print(f"\n{'='*80}")
    print("No files were deleted (dry-run mode).")
    print(f"{'='*80}\n")


def _print_matches(matches: list[dict]) -> None:
    for i, m in enumerate(matches, 1):
        apple = m["apple"]
        google = m["google"]
        print(f"\n  [{i}] {apple['filename']}")
        print(f"      Date      : {apple['date']}")
        print(f"      Apple path: {apple['path'] or '(not on disk)'}")
        print(f"      Google ts : {google['creationTime']}")
