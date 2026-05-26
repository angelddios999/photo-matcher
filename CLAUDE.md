# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the tool (always use the project venv)
venv/bin/python main.py              # dry-run: find duplicates, no changes
venv/bin/python main.py --delete     # move Apple duplicates to Recently Deleted
venv/bin/python main.py --import     # copy Google-only items to to_import/

# Install dependency
venv/bin/pip install osxphotos
```

There are no tests, linter config, or build steps.

## Architecture

Three modules with a clear data flow:

```
google_photos.py  →  main.py  →  matcher.py
(parse JSON)         (orchestrate)  (match + act)
```

**`google_photos.py`** — reads `backups/*.json` (Google Takeout supplemental-metadata sidecars). Each parsed item carries `timestamp` (int Unix, from `photoTakenTime`), `mimeType`, `filename`, `creationTime`, and `file_path` (Path to the paired media file, or None). `build_index()` returns `{timestamp: [item]}` for O(1) lookup.

**`matcher.py`** — all matching, deletion, and import logic. Key internals:

- `_load_uuid_utc_map()` reads `ZDATECREATED` and `ZDURATION` directly from `Photos.sqlite` (`~/Pictures/Photos Library.photoslibrary/database/Photos.sqlite`) into a `{uuid: (utc_ts, duration)}` dict. This bypasses TCC/PhotoKit entirely.
- `_apple_timestamps(photo, direct_utc, duration)` generates all candidate Unix timestamps for one Apple photo to try against the Google index. It handles multiple conventions and edge cases — see below.
- `find_duplicates()` iterates Apple Photos (via `osxphotos.PhotosDB`), generates candidates per photo, and does exact-second lookups against the Google index.
- `delete_duplicates()` writes `ZTRASHEDSTATE=1` directly to `Photos.sqlite`. Registers a no-op stub for `NSCoreDataTriggerUpdateAffectedObjectValue` so Core Data triggers don't abort the write. Requires Photos.app to be closed.
- `find_google_only()` / `copy_to_import()` — import mode: takes the complement of `find_duplicates()` results, copies unmatched Google items to `to_import/`.

**`main.py`** — argument parsing (`--delete`, `--import` are mutually exclusive), year-range prompts, and mode dispatch.

## Timestamp matching complexity

This is the core of the codebase. `_apple_timestamps()` generates multiple candidates because Google and Apple use different conventions:

| Convention | Reason |
|---|---|
| `direct_utc` (from `ZDATECREATED`) | Google stored actual UTC |
| `local_as_utc` (wall-clock treated as UTC) | Google stored local time as if UTC (common for Apple Data & Privacy exports) |
| Each ± 3600 s | Apple Photos sometimes applies a DST correction the camera/Google did not |
| For videos: each candidate − (`duration` ± 5 s) | Apple stores end-of-recording; Google stores start-of-recording |

The query window is padded ±1 day so UTC/local-time year-boundary photos are not excluded.

## Key constraints

- **macOS only** — depends on `osxphotos`, Apple Photos SQLite schema, and file paths under `~/Pictures/`.
- **Photos.app must be closed** for `--delete` (enforced via `pgrep`). A `Photos.sqlite.bak` is written before any changes.
- **`backups/` is flat** — subdirectories are not scanned. Media files for `--import` must sit alongside their JSON sidecars; the media filename is derived by stripping `.supplemental-metadata[(<N>)].json` from the JSON filename.
- **Python 3.10+** required for `int | None` union syntax.
