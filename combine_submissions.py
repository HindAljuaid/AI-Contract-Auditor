from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd

REQUIRED = [
    "invoice_id",
    "flagged",
    "error_category",
    "expected_total_cents",
    "billed_total_cents",
    "confidence",
]


def main():
    parser = argparse.ArgumentParser(description="Combine per-hospital audit CSVs into submission.csv")
    parser.add_argument("files", nargs="+", help="CSV files exported from the app")
    parser.add_argument("-o", "--output", default="submission.csv")
    args = parser.parse_args()

    frames = []
    for file in args.files:
        df = pd.read_csv(file)
        missing = [c for c in REQUIRED if c not in df.columns]
        if missing:
            raise ValueError(f"{file} is missing: {missing}")
        frames.append(df[REQUIRED])

    result = pd.concat(frames, ignore_index=True)
    if result["invoice_id"].duplicated().any():
        dup = result.loc[result["invoice_id"].duplicated(keep=False), "invoice_id"].unique().tolist()
        raise ValueError(f"Duplicate invoice IDs across input files: {dup[:10]}")

    result.to_csv(args.output, index=False)
    print(f"Wrote {len(result):,} rows to {Path(args.output).resolve()}")


if __name__ == "__main__":
    main()
