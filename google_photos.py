"""Google Photos supplemental-metadata parser module."""

import json
import mimetypes
from datetime import datetime, timezone
from pathlib import Path

TIMESTAMP_TOLERANCE_SECS = 60

BACKUPS_DIR = Path(__file__).parent / "backups"

mimetypes.add_type("image/heic", ".heic")
mimetypes.add_type("image/heif", ".heif")


def parse_backups() -> list[dict]:
    """Parse all supplemental-metadata JSON files found directly in backups/."""
    json_files = sorted(BACKUPS_DIR.glob("*.json"))
    if not json_files:
        return []

    items = []
    for json_path in json_files:
        item = _parse_sidecar(json_path)
        if item:
            items.append(item)
    return items


def _parse_sidecar(json_path: Path):
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    title = data.get("title", "").strip()
    if not title:
        return None

    # Prefer photoTakenTime, fall back to creationTime
    taken = data.get("photoTakenTime") or data.get("creationTime")
    if not taken:
        return None

    try:
        ts = int(taken["timestamp"])
        creation_time = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except (KeyError, ValueError, OSError):
        return None

    mime, _ = mimetypes.guess_type(title)
    if not mime:
        return None

    return {
        "filename": title,
        "mimeType": mime,
        "creationTime": creation_time,
        "timestamp": ts,
    }


def build_index(items: list[dict]) -> dict:
    """Index items by Unix timestamp (photoTakenTime) for fast lookup."""
    index = {}
    for item in items:
        ts = item.get("timestamp")
        if ts is None:
            continue
        index.setdefault(ts, []).append(item)
    return index
