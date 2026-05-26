"""Google Photos supplemental-metadata parser module."""

import json
import mimetypes
import re
from datetime import datetime, timezone
from pathlib import Path

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

    # Derive the media file path from the JSON filename.
    # Google Takeout pairs each media file with a sidecar JSON whose name is:
    #   <media_filename>.supplemental-metadata[(<N>)].json
    # Stripping that suffix gives the actual media filename.
    media_name = re.sub(r"\.supplemental-metadata(\(\d+\))?\.json$", "", json_path.name)
    media_mime, _ = mimetypes.guess_type(media_name)
    media_path = json_path.parent / media_name
    if (
        media_mime
        and (media_mime.startswith("image/") or media_mime.startswith("video/"))
        and media_path.exists()
    ):
        file_path = media_path
    else:
        file_path = None

    return {
        "filename": title,
        "mimeType": mime,
        "creationTime": creation_time,
        "timestamp": ts,
        "file_path": file_path,
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
