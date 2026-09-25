# Final Reproducibility Outputs

These folders preserve the final reviewed application outputs for Hospitals 2–5 and the service-mapping snapshots used to make bundled reruns reproducible.

Live demo: https://ai-contract-auditor.streamlit.app

## Final outputs

| Hospital | Contract | Provider | Submission rows | Flagged | Review rows | Mapping rows | Contract services |
|---:|---|---|---:|---:|---:|---:|---:|
| 2 | INS-H2-2024-1183 | St. Auben Metropolitan Hospital Trust | 1,125 | 137 | 1,125 | 506 | 76 |
| 3 | INS-H3-2024-0562 | Rivermead General Hospital | 932 | 98 | 932 | 544 | 120 |
| 4 | INS-H4-2024-2049 | Calderwood University Teaching Hospital | 835 | 156 | 835 | 534 | 98 |
| 5 | INS-H5-2024-0731 | Pelham Health Network | 1,050 | 177 | 446 | 474 | 84 |
| **Total** |  |  | **3,942** | **568** |  |  |  |

Hospitals 2–5 are unlabeled challenge datasets. These counts are **system outputs, not verified ground truth**.

## Folder contents

Each hospital folder contains:

- `hospital_X_contract_rules.json` — reviewed structured contract rules used for the final run;
- `hospital_X_submission.csv` — final invoice-level predictions;
- `hospital_X_review_queue.csv` — invoices that require or benefit from manual review;
- `hospital_X_service_mapping.csv` — reviewed description-to-contract-service mapping snapshot;
- `hospital_X_line_audit.csv` — line-level deterministic audit evidence.

## Reproducibility behavior

For bundled data, `src/mapping_snapshots.py` reuses the reviewed mapping snapshot only when:

1. the current unique billing descriptions exactly match the snapshot; and
2. every mapped service still exists in the active `ContractSpec`.

If either check fails, the application falls back to the normal local + optional AI mapping pipeline. Uploaded/custom datasets do not use bundled snapshots.

The saved contract rules include the final generic deterministic enrichment behavior for explicit service/rate rows, cumulative volume-discount tables, and facility/plan multiplier tables.
