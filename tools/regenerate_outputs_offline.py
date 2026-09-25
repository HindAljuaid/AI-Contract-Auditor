from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.audit_engine import audit_invoices
from src.contract_enrichment import (
    enrich_multiplier_tables_from_texts,
    enrich_volume_discounts_from_texts,
)
from src.data_utils import load_exercise_hospital
from src.models import ContractSpec

REQUIRED_SUBMISSION_COLUMNS = [
    "invoice_id",
    "flagged",
    "error_category",
    "expected_total_cents",
    "billed_total_cents",
    "confidence",
]


def _contract_texts(contract_dir: Path) -> list[str]:
    texts: list[str] = []
    for path in sorted(contract_dir.iterdir()):
        if path.suffix.lower() in {".md", ".txt"}:
            texts.append(path.read_text(encoding="utf-8", errors="replace"))
    return texts


def regenerate_hospital(root: Path, hospital: int) -> pd.DataFrame:
    data_root = root / "exercise_data" / "insurance_auditing-main"
    out_dir = root / "demo_outputs" / f"hospital_{hospital}"
    rules_path = out_dir / f"hospital_{hospital}_contract_rules.json"
    mapping_path = out_dir / f"hospital_{hospital}_service_mapping.csv"

    if not rules_path.exists():
        raise FileNotFoundError(f"Missing saved contract rules: {rules_path}")
    if not mapping_path.exists():
        raise FileNotFoundError(f"Missing saved service mapping: {mapping_path}")

    spec = ContractSpec.model_validate_json(rules_path.read_text(encoding="utf-8"))
    before = spec.model_dump(mode="json")

    texts = _contract_texts(data_root / "contracts" / f"hospital_{hospital}")
    spec = enrich_volume_discounts_from_texts(spec, texts)
    # This enrichment also reconciles missing explicit service/rate rows before
    # recovering facility/plan multiplier tables.
    spec = enrich_multiplier_tables_from_texts(spec, texts)

    # Rewrite only when deterministic enrichment changes the saved rule set.
    if spec.model_dump(mode="json") != before:
        rules_path.write_text(spec.model_dump_json(indent=2), encoding="utf-8")

    invoices, lines = load_exercise_hospital(data_root, hospital)
    mapping = pd.read_csv(mapping_path)
    predictions, line_audit = audit_invoices(invoices, lines, spec, mapping)

    submission = predictions[REQUIRED_SUBMISSION_COLUMNS].copy()
    review = predictions[
        predictions["review_required"] | predictions["confidence"].lt(0.75)
    ].sort_values(["confidence", "invoice_id"])

    submission.to_csv(out_dir / f"hospital_{hospital}_submission.csv", index=False)
    review.to_csv(out_dir / f"hospital_{hospital}_review_queue.csv", index=False)
    line_audit.to_csv(out_dir / f"hospital_{hospital}_line_audit.csv", index=False)
    # Mapping is a reviewed input to this offline rerun and is intentionally unchanged.

    print(
        f"Hospital {hospital}: {len(submission):,} invoices, "
        f"{int(submission['flagged'].sum()):,} flagged, "
        f"{len(spec.services)} services, "
        f"{len(spec.volume_discounts)} volume rule(s), "
        f"{len(spec.facility_multipliers)} facility multiplier rule(s), "
        f"{len(spec.plan_multipliers)} plan multiplier rule(s)"
    )
    return submission


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Regenerate bundled Hospital 2-5 audit outputs without OpenAI. "
            "Uses saved contract rules and reviewed service mappings, plus the "
            "same generic deterministic table enrichment used by the app."
        )
    )
    parser.add_argument(
        "--hospitals",
        nargs="+",
        type=int,
        default=[2, 3, 4, 5],
        choices=[2, 3, 4, 5],
    )
    args = parser.parse_args()

    frames: list[pd.DataFrame] = []
    for hospital in args.hospitals:
        frames.append(regenerate_hospital(ROOT, hospital))

    if set(args.hospitals) == {2, 3, 4, 5}:
        combined = pd.concat(frames, ignore_index=True)
        if combined["invoice_id"].duplicated().any():
            raise ValueError("Duplicate invoice IDs found across hospital submissions.")
        submission_dir = ROOT / "submission"
        submission_dir.mkdir(exist_ok=True)
        combined.to_csv(submission_dir / "submission.csv", index=False)
        print(
            f"Combined submission: {len(combined):,} rows, "
            f"{int(combined['flagged'].sum()):,} flagged"
        )


if __name__ == "__main__":
    main()
