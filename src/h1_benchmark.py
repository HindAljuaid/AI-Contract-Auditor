from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd


def run_h1_reference(project_root: str | Path) -> tuple[pd.DataFrame, str]:
    root = Path(project_root)
    script = root / "src" / "hospital1_reference.py"
    data_dir = root / "exercise_data" / "insurance_auditing-main"
    out_dir = root / ".cache" / "h1_reference"
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        str(script),
        "--data-dir",
        str(data_dir),
        "--output-dir",
        str(out_dir),
    ]
    completed = subprocess.run(
        cmd,
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Hospital 1 reference run failed.\n\n"
            + completed.stdout
            + "\n"
            + completed.stderr
        )

    evaluation = pd.read_csv(out_dir / "hospital_1_category_evaluation.csv")
    return evaluation, completed.stdout
