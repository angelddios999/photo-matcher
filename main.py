"""Photo Matcher — find duplicates between Google Photos and Apple Photos."""

import argparse
import sys
from datetime import date

from google_photos import BACKUPS_DIR, parse_backups, build_index
from matcher import find_duplicates, print_dry_run_report, delete_duplicates


def _prompt_year(prompt: str) -> int:
    while True:
        raw = input(prompt).strip()
        if raw.isdigit() and len(raw) == 4:
            return int(raw)
        print("  Invalid year. Use a 4-digit year like 2007.")


def main():
    parser = argparse.ArgumentParser(description="Match and optionally delete Google Photos duplicates from Apple Photos.")
    parser.add_argument("--delete", action="store_true", help="Delete matched duplicates from Apple Photos (moves to Recently Deleted).")
    args = parser.parse_args()

    mode = "DELETE mode" if args.delete else "dry-run mode"
    print(f"=== Photo Matcher ({mode}) ===\n")
    print(f"Reading metadata files from: {BACKUPS_DIR}/")

    items = parse_backups()
    if not items:
        print(
            f"No metadata files found in {BACKUPS_DIR}/.\n"
            "Place your Google Photos supplemental-metadata JSON files there and try again."
        )
        sys.exit(1)

    print(f"  {len(items)} media items parsed.")

    from_year = _prompt_year("From year: ")
    to_year   = _prompt_year("To year  : ")
    if to_year < from_year:
        print("To year must be on or after From year.")
        sys.exit(1)

    start_date = date(from_year, 1, 1)
    end_date   = date(to_year, 12, 31)

    print("\nBuilding lookup index...")
    google_index = build_index(items)

    print(f"Querying Apple Photos library ({start_date} to {end_date})...")
    matches = find_duplicates(google_index, start_date, end_date)

    print_dry_run_report(matches)

    if args.delete and matches:
        print(f"WARNING: This will move {len(matches)} photo(s) to Recently Deleted in Apple Photos.")
        print("         Make sure Photos.app is CLOSED before confirming.")
        confirm = input("Type 'yes' to confirm: ").strip().lower()
        if confirm == "yes":
            print()
            deleted = delete_duplicates(matches)
            print(f"\n{deleted}/{len(matches)} photo(s) moved to Recently Deleted.")
        else:
            print("Deletion cancelled.")


if __name__ == "__main__":
    main()
