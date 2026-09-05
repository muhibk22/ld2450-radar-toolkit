import csv
from pathlib import Path

folder = Path("data/raw_sessions")
total_seconds = 0

for file in folder.glob("*.csv"):
    if file.name == "dataset_index.csv":
        continue
    with open(file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        timestamps = [float(row["timestamp"]) for row in reader if row.get("timestamp")]
    if timestamps:
        duration = max(timestamps) - min(timestamps)
        total_seconds += duration
        print(f"{file.name}: {duration:.1f} sec")

print(f"\nTOTAL: {total_seconds:.1f} seconds ({total_seconds/60:.1f} minutes)")