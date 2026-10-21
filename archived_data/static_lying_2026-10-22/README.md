# Archived static lying recordings

Archived on 22 October 2026 from the radar tracker active dataset.
raw_sessions/ contains 264 recordings already excluded by the reviewed training selection; dataset_windows/ contains their 14,364 cached derived slices.

raw_sessions/dataset_index.csv indexes the archived recordings once each. metadata/dataset_index.before.csv preserves the complete original active index, including duplicates. metadata/index_reconciliation.csv identifies entries reconstructed from CSV metadata and last recorded timestamps. The move manifest records original and archived paths and SHA-256 checksums for every moved file.

To review these recordings in Dataset Visualization Studio, explicitly select raw_sessions/ inside this archive. Project-wide scans skip archived_data/.

Model weights are unchanged. The active legacy sliced cache remains an older partial collection; it has not been regenerated. Prefer the current raw-session training pipeline.
