# photo-matcher

A command-line tool for reconciling **Google Photos** and **Apple Photos** libraries. It can:

- **Dry-run** — find duplicates (photos/videos present in both) without making any changes
- **Delete** — remove Apple Photos duplicates that already exist in Google Photos
- **Import** — copy Google Photos that are missing from Apple Photos into a local folder for manual import

> **macOS only.** The tool reads and writes Apple's `Photos.sqlite` database directly, bypassing all PhotoKit/TCC authorization requirements.

---

## Requirements

| Requirement | Details |
|---|---|
| **OS** | macOS (any recent version) |
| **Python** | 3.10 or newer |
| **Package** | `osxphotos` |
| **Permissions** | Full Disk Access for Terminal (System Settings → Privacy & Security → Full Disk Access) |

---

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/angelddios999/photo-matcher.git
cd photo-matcher

# 2. Create a virtual environment and install the dependency
python3 -m venv venv
venv/bin/pip install osxphotos

# 3. Place your Google Photos supplemental-metadata JSON files in backups/
#    (For --import mode, also place the actual media files there alongside the JSONs)
```

### Preparing the `backups/` folder

Export your Google Photos library using **Google Takeout** or **Apple Data and Privacy**. Each media file comes with a JSON sidecar named:

```
<filename>.supplemental-metadata.json
<filename>.supplemental-metadata(<N>).json   ← when Google uses numbered sidecars
```

Place all JSON files (and, for `--import` mode, the actual media files) flat in the `backups/` folder. Subdirectories are not scanned.

---

## Usage

```bash
venv/bin/python main.py              # dry-run: show duplicates, change nothing
venv/bin/python main.py --delete     # delete duplicates from Apple Photos
venv/bin/python main.py --import     # copy Google-only items to to_import/
```

All modes prompt for a year range:

```
From year: 2007
To year  : 2012
```

`--delete` and `--import` are mutually exclusive.

---

## Modes

### Dry-run (default)

Finds all photos and videos present in both Google Photos (`backups/`) and Apple Photos, and prints a report. Nothing is modified.

```
=== Photo Matcher (dry-run mode) ===

DRY RUN REPORT — 62 duplicate(s) found
  Photos: 58  |  Videos: 4
...
No files were deleted (dry-run mode).
```

### `--delete`

Same matching as dry-run, then moves all matched Apple Photos to **Recently Deleted** (they remain recoverable for 30 days).

**Photos.app must be closed** before confirming. The tool will refuse to proceed if it detects Photos is running.

A backup of `Photos.sqlite` is saved as `Photos.sqlite.bak` before any changes are made.

```
WARNING: This will move 62 photo(s) to Recently Deleted in Apple Photos.
         Make sure Photos.app is CLOSED before confirming.
Type 'yes' to confirm: yes

62/62 photo(s) moved to Recently Deleted.
```

### `--import`

Finds Google Photos items in the requested year range that are **not** present in Apple Photos, and copies their media files to a `to_import/` folder. You can then drag that folder into Apple Photos to import them.

Requires the actual media files to be present in `backups/` alongside their JSON sidecars (Google Takeout pairing — the media filename is derived by stripping `.supplemental-metadata[(<N>)].json` from the JSON filename).

```
=== Photo Matcher (IMPORT mode) ===

IMPORT REPORT — 14 item(s) not found in Apple Photos
  Photos: 11  |  Videos: 3
...
14/14 file(s) copied to /path/to/photo-matcher/to_import/
```

---

## How matching works

Matching is purely timestamp-based — filenames are ignored because Google renames files during export (e.g. `DSC00056.JPG` → `2024-02-25.jpg`).

### Timestamp sources

| Source | How it's used |
|---|---|
| **Google** `photoTakenTime` | The reference timestamp from the JSON sidecar |
| **Apple** `ZDATECREATED` | Read directly from `Photos.sqlite`; always stored in UTC |
| **Apple** local wall-clock | `photo.date` local time treated as if it were UTC |

### Why two Apple conventions?

Google Photos stores `photoTakenTime` using two different conventions depending on how the photo was originally uploaded:

1. **Local-as-UTC** — The camera's local wall-clock time recorded as if it were UTC (common for photos transferred via Apple Data and Privacy export).
2. **Actual UTC** — The real UTC timestamp (used by some cameras and upload paths).

The matcher tries both interpretations for every Apple photo, so either convention is detected.

### DST correction (±1 hour)

Apple Photos sometimes applies a Daylight Saving Time correction on import that the original camera (and Google) did not apply — most visible for photos taken on DST change days. The matcher also tries each base candidate ±3 600 seconds to catch these cases.

### Video matching

Apple stores a video's timestamp as:

```
recording_start  +  duration  +  metadata_overhead (≈ 0–5 s)
```

Google stores `recording_start`. For videos, the matcher subtracts `duration ± 5 seconds` from every Apple timestamp candidate to align with Google's reference point. Duration is read from the `ZDURATION` column in `Photos.sqlite`.

### Year-boundary padding

The Apple Photos query is padded by ±1 day so that photos taken near the end of December or beginning of January are not excluded when their UTC time crosses the year boundary (e.g. Dec 31 8 PM CST = Jan 1 2 AM UTC).

---

## Project structure

```
photo-matcher/
├── main.py            # Entry point; argument parsing and mode orchestration
├── google_photos.py   # Parses supplemental-metadata JSON files; builds timestamp index
├── matcher.py         # Core matching, deletion, import logic
├── backups/           # Place Google Photos JSON sidecars (and media files for --import) here
├── to_import/         # Created by --import mode; contains files ready to drag into Photos
└── venv/              # Python virtual environment
```

### `google_photos.py`

| Symbol | Description |
|---|---|
| `BACKUPS_DIR` | Path to the `backups/` folder |
| `parse_backups()` | Glob all `*.json` files in `backups/` and return parsed items |
| `build_index(items)` | Build a `{unix_timestamp: [item, ...]}` dict for O(1) lookup |

Each parsed item contains: `filename`, `mimeType`, `creationTime`, `timestamp` (int), `file_path` (Path or None).

### `matcher.py`

| Function | Description |
|---|---|
| `find_duplicates(index, start, end)` | Return list of `{apple, google}` match dicts for the given year range |
| `delete_duplicates(matches)` | Set `ZTRASHEDSTATE=1` in `Photos.sqlite` for each matched Apple UUID |
| `find_google_only(items, matches, start, end)` | Return Google items in range with no Apple match and a media file present |
| `copy_to_import(items)` | Copy unmatched items to `to_import/`; returns count copied |
| `print_dry_run_report(matches)` | Pretty-print the duplicate report |
| `print_import_report(items)` | Pretty-print the import report |

---

## Notes and caveats

- **`Photos.app` must be closed** when running `--delete`. The tool checks for this and will refuse to proceed if Photos is open.
- **Database backup** — `--delete` saves `Photos.sqlite.bak` before writing. If something goes wrong, close Photos, replace `Photos.sqlite` with the backup, and reopen.
- **Recently Deleted** — `--delete` moves photos to Recently Deleted (not permanently deleted). They can be recovered from Photos for up to 30 days.
- **False positives** — The ±1 hour DST window and ±5 second video overhead window slightly increase the chance of a false positive match. Review the dry-run report before deleting.
- **iCloud libraries** — The tool has only been tested with a local Photos library. iCloud-synced libraries may behave differently.
