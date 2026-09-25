# Hospital 1 Validation Evidence

This folder preserves the original Hospital 1 development/validation implementation separately from the normal application submission workflow.

Hospital 1 is the labeled development dataset, so it is used only to measure the deterministic audit logic against known ground truth.

## Validation result

- Perfect categories: **18/18**
- Mean precision: **1.000**
- Mean recall: **1.000**
- Mean F1: **1.000**
- Total true positives: **105**
- Total false positives: **0**
- Total false negatives: **0**

## Files

- `hospital_1_validation_development.ipynb` — original development notebook with the printed validation output.
- `hospital_1_validation_reference.py` — standalone frozen validator.
- `../../sample_outputs/hospital_1/hospital_1_category_evaluation.csv` — per-category precision, recall, F1, TP, FP, and FN.
- `../../sample_outputs/hospital_1/hospital_1_category_predictions.csv` — predicted error categories for each Hospital 1 invoice.
- `../../sample_outputs/hospital_1/hospital_1_line_mapping.csv` — line-level mapping evidence used by the validator.

The Streamlit app executes the frozen reference logic through `src/hospital1_reference.py` and writes temporary results under `.cache/`; `.cache/` is intentionally ignored by Git.

## Reproduce locally

From the repository root:

```bash
python validation/hospital_1/hospital_1_validation_reference.py \
  --data-dir exercise_data/insurance_auditing-main \
  --output-dir sample_outputs/hospital_1
```

This regenerates the three versioned Hospital 1 evidence CSVs.

## Why this is separate from challenge outputs

Hospitals 2–5 are unlabeled challenge datasets and their outputs live under `demo_outputs/` and `submission/`. Hospital 1 is labeled development/calibration evidence, so it is kept separate to avoid presenting it as out-of-sample performance.
