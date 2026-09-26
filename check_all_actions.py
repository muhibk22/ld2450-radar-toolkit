import csv
from pathlib import Path
from datetime import datetime
from collections import defaultdict

FOLDER = Path("data/raw_sessions")
MAX_GAP = 0.5  # seconds - gaps larger than this (pauses, dropouts) are ignored


def parse_ts(s):
    try:
        return float(s)
    except ValueError:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timestamp()


def format_hms(total_seconds):
    hours = int(total_seconds // 3600)
    minutes = (total_seconds % 3600) / 60
    if hours > 0:
        return f"{hours} hr {minutes:.1f} min"
    return f"{minutes:.1f} min"


def main():
    totals = defaultdict(float)      # action_label -> seconds
    per_volunteer = defaultdict(float)  # volunteer_id -> seconds
    files = sorted(f for f in FOLDER.glob("*.csv") if f.name != "dataset_index.csv")
    print(f"Found {len(files)} session files\n")

    for file in files:
        with open(file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            prev_ts = None
            for row in reader:
                ts = parse_ts(row["timestamp"])
                label = row.get("action_label", "UNKNOWN")
                volunteer = row.get("volunteer_id", "UNKNOWN")
                if prev_ts is not None:
                    dt = ts - prev_ts
                    if 0 < dt <= MAX_GAP:
                        totals[label] += dt
                        per_volunteer[volunteer] += dt
                prev_ts = ts

    print("Total duration per volunteer:")
    for vol, secs in sorted(per_volunteer.items(), key=lambda x: -x[1]):
        print(f"  {vol}: {secs:.1f} sec  ({format_hms(secs)})")

    print("\nTotal duration per action (all volunteers combined):")
    for label, secs in sorted(totals.items(), key=lambda x: -x[1]):
        print(f"  {label}: {secs:.1f} sec  ({format_hms(secs)})")

    grand_total = sum(totals.values())
    print(f"\nTOTAL (all actions, all volunteers): {grand_total:.1f} sec  ({format_hms(grand_total)})")


if __name__ == "__main__":
    main()