"""Allocate recording names without reusing archived session identifiers."""
from pathlib import Path
import re


def next_session_path(raw_directory: Path, volunteer: str) -> Path:
    raw_directory = Path(raw_directory)
    archive_directory = raw_directory.parent.parent / "archived_data"
    pattern = re.compile(re.escape(volunteer) + r"_session(\d+)\.csv$", re.IGNORECASE)
    candidates = list(raw_directory.glob("*.csv"))
    if archive_directory.is_dir():
        candidates.extend(archive_directory.rglob("*_session*.csv"))
    highest = 0
    for path in candidates:
        match = pattern.fullmatch(path.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return raw_directory / f"{volunteer}_session{highest+1:02d}.csv"
