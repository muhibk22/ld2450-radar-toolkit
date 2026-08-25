import os
import pandas as pd
import numpy as np
import argparse
from pathlib import Path

def slice_sessions(input_dir: str, output_dir: str, window_size: int = 20, step_size: int = 10):
    """
    Slices continuous dataset sessions into windowed training instances for LSTM.
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    csv_files = list(input_path.glob("*.csv"))
    if not csv_files:
        print(f"No CSV files found in {input_dir}")
        return

    # To avoid reading the index file if it's in the same dir
    csv_files = [f for f in csv_files if f.name != "dataset_index.csv"]

    total_windows_extracted = 0
    class_distribution = {}

    for file in csv_files:
        print(f"Processing {file.name}...")
        try:
            df = pd.read_csv(file)
            
            # Ensure required columns exist
            required_cols = ['x_mm', 'y_mm', 'speed_mms', 'action_label']
            if not all(col in df.columns for col in required_cols):
                print(f"  Skipping {file.name} - missing required columns.")
                continue
                
            num_rows = len(df)
            if num_rows < window_size:
                print(f"  Skipping {file.name} - too few rows ({num_rows} < {window_size}).")
                continue
                
            # Sliding window extraction
            for start_idx in range(0, num_rows - window_size + 1, step_size):
                window = df.iloc[start_idx : start_idx + window_size]
                
                # The "label" of the window is the label of the LAST frame in the window
                # (Since LSTM predicts based on the accumulated sequence)
                window_label_str = window['action_label'].iloc[-1]
                
                # Extract just the numeric prefix (e.g., "6" from "6: Fall onset")
                label_id = window_label_str.split(":")[0].strip()
                
                # Generate output filename
                out_filename = f"{file.stem}_win{start_idx}_class{label_id}.csv"
                out_filepath = output_path / out_filename
                
                # Save window (save only the features, or keep metadata if needed)
                # For training, we usually just need the physical metrics
                features_only = window[['x_mm', 'y_mm', 'speed_mms', 'distance_mm', 'angle_deg']]
                features_only.to_csv(out_filepath, index=False)
                
                # Track stats
                class_distribution[label_id] = class_distribution.get(label_id, 0) + 1
                total_windows_extracted += 1
                
        except Exception as e:
            print(f"  Error processing {file.name}: {e}")

    print("\n=== Extraction Complete ===")
    print(f"Total windows generated: {total_windows_extracted}")
    print("Class distribution:")
    for label, count in sorted(class_distribution.items()):
        print(f"  Class {label}: {count} windows")
    print(f"Output directory: {output_path.absolute()}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Slice continuous radar telemetry into training windows.")
    parser.add_argument("--input", type=str, default=".", help="Directory containing session CSVs")
    parser.add_argument("--output", type=str, default="sliced_windows", help="Directory to save sliced windows")
    parser.add_argument("--window", type=int, default=20, help="Number of frames per window (e.g., 20 frames = 2s at 10fps)")
    parser.add_argument("--step", type=int, default=10, help="Step size for sliding window (e.g., 10 frames = 1s overlap)")
    
    args = parser.parse_args()
    slice_sessions(args.input, args.output, args.window, args.step)
