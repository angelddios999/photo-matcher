"""Apple Photos / Google Photos duplicate matcher module."""

from datetime import date, datetime, timezone


def find_duplicates(google_index: dict, start_date: date, end_date: date) -> list[dict]:
    import osxphotos

    db = osxphotos.PhotosDB()
    photos = db.photos(
        from_date=datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc),
        to_date=datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc),
    )

    matches = []
    for photo in photos:
        key = _make_apple_key(photo)
        if key is None:
            continue
        google_matches = google_index.get(key)
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


def _make_apple_key(photo):
    filename = photo.original_filename
    dt = photo.date
    if not filename or not dt:
        return None
    date_str = dt.date().isoformat()
    return (filename.lower(), date_str)


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
