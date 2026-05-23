"""Photo Matcher — find duplicates between Google Photos and Apple Photos."""

import sys
from datetime import date

from google_photos import BACKUPS_DIR, parse_backups, build_index
from matcher import find_duplicates, print_dry_run_report


def _prompt_date(prompt: str) -> date:
    while True:
        try:
            return date.fromisoformat(input(prompt).strip())
        except ValueError:
            print("  Invalid date. Use YYYY-MM-DD format.")


def main():
    print("=== Photo Matcher (dry-run mode) ===\n")
    print(f"Reading metadata files from: {BACKUPS_DIR}/")

    items = parse_backups()
    if not items:
        print(
            f"No metadata files found in {BACKUPS_DIR}/.\n"
            "Place your Google Photos supplemental-metadata JSON files there and try again."
        )
        sys.exit(1)

    print(f"  {len(items)} media items parsed.")

    start_date = _prompt_date("Start date for matching (YYYY-MM-DD): ")
    end_date = _prompt_date("End date for matching   (YYYY-MM-DD): ")
    if end_date < start_date:
        print("End date must be on or after start date.")
        sys.exit(1)

    print("\nBuilding lookup index...")
    google_index = build_index(items)

    print(f"Querying Apple Photos library ({start_date} to {end_date})...")
    matches = find_duplicates(google_index, start_date, end_date)

    print_dry_run_report(matches)


if __name__ == "__main__":
    main()
