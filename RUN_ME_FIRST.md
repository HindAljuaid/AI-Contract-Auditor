# Run Me First

## Start the app on macOS

Open Terminal and run:

```bash
cd ~/Downloads/AI-Contract-Auditor
chmod +x run_app.sh
./run_app.sh
```

The first run creates `.venv`, installs the pinned packages, and starts Streamlit.

## First check — Hospital 1 Validation

1. In the sidebar select **Provided hospital data**.
2. Select **Hospital 1**.
3. Open **H1 Validation**.
4. Click **Run validation**.

Expected development/calibration result:

```text
Perfect categories: 18/18
Mean precision: 1.000
Mean recall: 1.000
Mean F1: 1.000
```

No OpenAI API key is required for this validation.

## Run a normal audit

1. Select **Provided hospital data** or **Upload my own files**.
2. Select the hospital/data source.
3. Either:
   - use AI to analyze the contract, or
   - reuse a previously downloaded contract-rules JSON for the same source.
4. Open **Contract** and review services, rates, pricing rules, ambiguities, and unsupported clauses.
5. Check **I reviewed the contract rules**.
6. Return to **Workflow** and click **Run audit**.
7. Open **Results** to inspect findings, review cases, and invoice details.
8. Download **Contract rules (JSON)** and **Audit results (ZIP)** when needed.

## Reuse reviewed contract rules

The contract-rules upload is source-scoped. Select the hospital/data source first, then upload the matching JSON under the reuse-contract-rules control shown for that source.

This skips a new contract-extraction call.

Do not reuse one hospital's rule JSON for another hospital.

## Bundled mapping snapshots

For the bundled Hospitals 2–5, the app can reuse the reviewed service-mapping snapshot stored under `demo_outputs/`.

The snapshot is accepted only when:

- the current unique billing descriptions exactly match the snapshot; and
- every mapped service still exists in the active contract specification.

If validation fails, the app automatically returns to the normal local + optional AI mapping pipeline.

Custom/uploaded datasets always use the normal mapping pipeline.

## Final reproducibility baseline

The final reviewed bundled outputs are:

```text
H2 = 137 flagged
H3 =  98 flagged
H4 = 156 flagged
H5 = 177 flagged
Total = 568 flagged
```

Hospitals 2–5 are unlabeled, so these counts are system outputs rather than verified accuracy.

For the closest reproduction of the final baseline, use the saved/reviewed contract-rules JSON for the same hospital together with the bundled reviewed mapping snapshot.

## OpenAI API key

You can set the key before launching:

```bash
export OPENAI_API_KEY="your-api-key-here"
./run_app.sh
```

Never commit the API key to GitHub.

If the API has no credit or is temporarily unavailable:

- Hospital 1 Validation still works offline.
- Saved contract-rules JSON can still be reused.
- Local service matching can still run.
- If AI mapping was requested but unavailable, the app warns that uncertain cases remain for review; this degraded run can differ from the reviewed baseline.

## Before final submission

Run:

```bash
pytest -q
```

Then confirm:

- `submission/submission.csv` has 3,942 rows and 3,942 unique `invoice_id` values;
- the columns are exactly:
  `invoice_id, flagged, error_category, expected_total_cents, billed_total_cents, confidence`;
- `demo_outputs/hospital_2` through `hospital_5` contain the final reviewed service mappings and audit artifacts;
- no API key or local `.streamlit/secrets.toml` is committed.
