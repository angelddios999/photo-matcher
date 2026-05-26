"""Apple Photos / Google Photos duplicate matcher module."""

import calendar
import shutil
import sqlite3
import subprocess
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


_PHOTOS_DB = Path.home() / "Pictures/Photos Library.photoslibrary/database/Photos.sqlite"
# Apple Core Data epoch starts at 2001-01-01 00:00:00 UTC
_APPLE_EPOCH_OFFSET = 978_307_200


def find_duplicates(google_index: dict, start_date: date, end_date: date) -> list[dict]:
    import osxphotos

    # Read the definitive UTC timestamp (ZDATECREATED) for every asset directly
    # from Photos.sqlite. This is more reliable than photo.date.timestamp() because
    # it doesn't depend on photo.date.tzinfo being set correctly (older cameras and
    # phones often don't embed timezone info in EXIF, so osxphotos may return a
    # naive datetime, causing photo.date.timestamp() to use the wrong timezone).
    uuid_utc = _load_uuid_utc_map()

    db = osxphotos.PhotosDB()
    # Pad by 1 day on each side so photos near the year boundary aren't excluded
    # when their UTC time crosses midnight (e.g. Dec 31 8 PM CST = Jan 1 2 AM UTC).
    photos = db.photos(
        from_date=datetime(start_date.year, 1, 1, tzinfo=timezone.utc) - timedelta(days=1),
        to_date=datetime(end_date.year, 12, 31, 23, 59, 59, tzinfo=timezone.utc) + timedelta(days=1),
    )

    matches = []
    for photo in photos:
        info = uuid_utc.get(photo.uuid)
        direct_utc, duration = info if info else (None, None)
        google_matches = None
        for apple_ts in _apple_timestamps(photo, direct_utc, duration):
            google_matches = _lookup(google_index, apple_ts)
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


def _load_uuid_utc_map() -> dict:
    """Read ZDATECREATED (UTC) and ZDURATION for every asset from Photos.sqlite.

    Returns {uuid: (utc_timestamp, duration_seconds)} where duration is None
    for photos and a float for videos.

    ZDATECREATED is an Apple Core Data timestamp (seconds since 2001-01-01 UTC),
    always stored in UTC regardless of the device timezone.
    """
    conn = sqlite3.connect(str(_PHOTOS_DB))
    try:
        cur = conn.execute(
            "SELECT ZUUID, ZDATECREATED, ZDURATION FROM ZASSET WHERE ZDATECREATED IS NOT NULL"
        )
        return {
            uuid: (int(ts + _APPLE_EPOCH_OFFSET), duration)
            for uuid, ts, duration in cur.fetchall()
        }
    finally:
        conn.close()


def _apple_timestamps(photo, direct_utc: int | None = None, duration: float | None = None) -> list[int]:
    """Return candidate Unix timestamps to try when matching against Google.

    Two base conventions are tried:

    A. direct_utc — ZDATECREATED read straight from Photos.sqlite, always UTC.
       Matches photos where Google stored the real UTC timestamp.

    B. local_as_utc — Apple's local wall-clock time treated as if it were UTC.
       Matches photos where Google stored the local time without a UTC offset
       (common for photos transferred via Apple Data & Privacy export).

    Each base candidate is also tried ±3600 s to catch cases where Apple Photos
    applied a DST correction that Google (using raw EXIF) did not.

    For videos, Apple stores the end of recording plus a metadata overhead of up
    to 3 seconds, while Google stores the start of recording. Each base candidate
    is therefore also tried with (duration + overhead) subtracted, where overhead
    is 0–3 seconds.
    """
    candidates: set[int] = set()

    if direct_utc is not None:
        candidates.add(direct_utc)
        candidates.add(direct_utc - 3600)
        candidates.add(direct_utc + 3600)

    if photo.date:
        local_as_utc = calendar.timegm(photo.date.timetuple())
        candidates.add(local_as_utc)
        candidates.add(local_as_utc - 3600)
        candidates.add(local_as_utc + 3600)

    # Videos: subtract duration + overhead (0-3 s) from every base candidate so
    # that Apple's "end-of-recording" timestamp maps back to Google's "start" time.
    if not photo.isphoto and duration:
        duration = round(duration)
        video_candidates: set[int] = set()
        for base in candidates:
            for overhead in range(-5, 6):  # -5 … +5 seconds
                video_candidates.add(base - duration - overhead)
        candidates |= video_candidates

    return list(candidates)


def _lookup(index: dict, ts: int):
    return index.get(ts)


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


# ---------------------------------------------------------------------------
# Import mode — copy Google-only items to to_import/
# ---------------------------------------------------------------------------

_TO_IMPORT_DIR = Path(__file__).parent / "to_import"


def find_google_only(
    google_items: list[dict],
    matches: list[dict],
    start_date: date,
    end_date: date,
) -> list[dict]:
    """Return Google items in the date range that have no match in Apple Photos.

    Items without a corresponding media file in backups/ are silently skipped
    (the file_path field will be None if the file was not found).
    """
    matched_ts = {m["google"]["timestamp"] for m in matches}

    # Use the same ±1-day padded window as find_duplicates() so the filtering
    # is consistent with what was actually queried from Apple Photos.
    from_ts = (datetime(start_date.year, 1, 1, tzinfo=timezone.utc) - timedelta(days=1)).timestamp()
    to_ts = (datetime(end_date.year, 12, 31, 23, 59, 59, tzinfo=timezone.utc) + timedelta(days=1)).timestamp()

    result = []
    for item in google_items:
        ts = item.get("timestamp")
        if ts is None or not (from_ts <= ts <= to_ts):
            continue
        if ts in matched_ts:
            continue
        if item.get("file_path") is None:
            continue
        result.append(item)
    return result


def copy_to_import(items: list[dict]) -> int:
    """Copy unmatched Google items to the to_import/ folder.

    Multiple JSON sidecar entries can resolve to the same physical file (e.g.
    when Google renames many photos to the same date-based filename). Each
    unique source file is copied exactly once regardless of how many JSON
    entries point to it.

    Returns the number of files successfully copied.
    """
    _TO_IMPORT_DIR.mkdir(exist_ok=True)

    copied = 0
    seen_sources: set[Path] = set()   # deduplicate by source path
    seen_names: set[str] = set()      # avoid dest filename collisions

    for item in items:
        src = Path(item["file_path"]).resolve()

        # Skip if this physical file was already copied
        if src in seen_sources:
            continue
        seen_sources.add(src)

        dest_name = src.name

        # Resolve filename conflicts inside to_import/
        if dest_name in seen_names or (_TO_IMPORT_DIR / dest_name).exists():
            stem, suffix = src.stem, src.suffix
            i = 1
            while f"{stem}({i}){suffix}" in seen_names or (_TO_IMPORT_DIR / f"{stem}({i}){suffix}").exists():
                i += 1
            dest_name = f"{stem}({i}){suffix}"

        seen_names.add(dest_name)
        shutil.copy2(src, _TO_IMPORT_DIR / dest_name)
        copied += 1

    return copied


def print_import_report(items: list[dict]) -> None:
    if not items:
        print("\nNo new items to import — all Google Photos in this range are already in Apple Photos.")
        return

    photos = [i for i in items if i["mimeType"].startswith("image/")]
    videos = [i for i in items if i["mimeType"].startswith("video/")]

    print(f"\n{'='*80}")
    print(f"IMPORT REPORT — {len(items)} item(s) not found in Apple Photos")
    print(f"  Photos: {len(photos)}  |  Videos: {len(videos)}")
    print(f"{'='*80}")

    if photos:
        print(f"\n--- PHOTOS ({len(photos)}) ---")
        for i, item in enumerate(photos, 1):
            print(f"\n  [{i}] {item['filename']}")
            print(f"      Taken : {item['creationTime']}")
            print(f"      Source: {item['file_path']}")

    if videos:
        print(f"\n--- VIDEOS ({len(videos)}) ---")
        for i, item in enumerate(videos, 1):
            print(f"\n  [{i}] {item['filename']}")
            print(f"      Taken : {item['creationTime']}")
            print(f"      Source: {item['file_path']}")

    print(f"\n{'='*80}\n")
