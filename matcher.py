"""Apple Photos / Google Photos duplicate matcher module."""

import calendar
from datetime import date, datetime, timezone

from google_photos import TIMESTAMP_TOLERANCE_SECS


def find_duplicates(google_index: dict, start_date: date, end_date: date) -> list[dict]:
    import osxphotos

    db = osxphotos.PhotosDB()
    photos = db.photos(
        from_date=datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc),
        to_date=datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc),
    )

    matches = []
    for photo in photos:
        apple_ts = _apple_timestamp(photo)
        if apple_ts is None:
            continue
        google_matches = _lookup_with_tolerance(google_index, apple_ts)
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


def _apple_timestamp(photo) -> int | None:
    if not photo.date:
        return None
    # Google stored wall-clock time as UTC, so we match by treating
    # Apple's local wall-clock time as UTC too (no offset applied).
    return calendar.timegm(photo.date.timetuple())


def _lookup_with_tolerance(index: dict, ts: int):
    for delta in range(0, TIMESTAMP_TOLERANCE_SECS + 1):
        for candidate in (ts + delta, ts - delta) if delta else (ts,):
            result = index.get(candidate)
            if result:
                return result
    return None


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
