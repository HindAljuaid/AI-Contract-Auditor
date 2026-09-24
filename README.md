# AI Contract Auditor

A Streamlit application for the insurance-auditing technical exercise. It combines AI-assisted contract interpretation with deterministic invoice auditing.

## Live Demo

🚀 **Try the deployed application:** [AI Contract Auditor](https://ai-contract-auditor.streamlit.app)

The project deliberately separates **language interpretation** from **financial decisions**:

- OpenAI can extract heterogeneous contract documents into a typed `ContractSpec` and optionally help resolve ambiguous service descriptions.
- Python performs all monetary calculations, totals, rate-period checks, premiums, discounts, bundles, caps, exclusions, dates, duplicate handling, and final audit findings.
- Unresolved mappings remain visible as uncertainty and review cases rather than being forced into confident errors.
- Hospital 1 remains a frozen labelled-development benchmark for validating the deterministic logic.

## Final application workflow

The Streamlit UI has four tabs:

1. **Workflow** — analyze the contract and run the invoice audit.
2. **Contract** — review extracted services, rates, pricing rules, ambiguities, and unsupported clauses.
3. **Results** — inspect findings, review cases, invoice-level evidence, optional AI summaries, and downloads.
4. **H1 Validation** — run the frozen Hospital 1 benchmark offline.

The normal workflow is:

```text
Contract documents
      │
      ├── OpenAI structured extraction ──────┐
      │                                      │
      └── uploaded contract-rules JSON ──────┤
                                             ▼
                                   reviewed ContractSpec
                                             │
Invoices + line items                        │
      │                                      │
      └── local service mapping ─────────────┘
                    │
                    ├── optional AI help for unclear mappings
                    ▼
            deterministic Python audit
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
 contract rules JSON     audit results ZIP
                         ├── submission CSV
                         ├── review queue CSV
                         ├── service mapping CSV
                         └── line audit CSV
```

**Design principle:** AI interprets language and may summarize deterministic evidence; Python decides money and audit findings.

## Project layout

```text
insurance_auditor_app/
├── app.py
├── requirements.txt
├── run_app.sh
├── README.md
├── RUN_ME_FIRST.md
├── DECISION_LOG.md
├── REPORT_TEMPLATE.md
├── PROJECT_VALIDATION.txt
├── combine_submissions.py
├── prompts/
│   ├── contract_extraction_v1.md
│   └── mapping_resolution_v1.md
├── src/
│   ├── ai.py
│   ├── audit_engine.py
│   ├── cache_utils.py
│   ├── data_utils.py
│   ├── explain.py
│   ├── h1_benchmark.py
│   ├── hospital1_reference.py
│   ├── mapping.py
│   ├── models.py
│   └── offline_specs.py
├── tests/
│   ├── test_core.py
│   └── test_stage2.py
├── tools/
│   └── rebuild_offline_h2_spec.py
├── offline_specs/
│   └── hospital_2.json
└── exercise_data/
    └── insurance_auditing-main/
```

`offline_specs/` and `src/offline_specs.py` are retained as development/regression assets for Hospital 2. They are not exposed as special Hospital 2 buttons in the final UI.

## Run locally on macOS

Python 3.10+ is required.

```bash
cd insurance_auditor_app
chmod +x run_app.sh
./run_app.sh
```

The script creates `.venv`, installs the pinned dependencies, and starts Streamlit. The app normally opens at:

```text
http://localhost:8501
```

Manual setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

## OpenAI API key

You can provide an API key in any of these ways:

```bash
export OPENAI_API_KEY="your-api-key-here"
./run_app.sh
```

or:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

You can also paste the key into the password field in the sidebar for a local session.

The real `.streamlit/secrets.toml` file is ignored by Git. Never commit an API key.

If OpenAI is unavailable, Hospital 1 Validation still works fully offline. For auditing another hospital without repeating contract extraction, upload a previously downloaded **contract rules JSON** file under **Advanced settings → Reuse contract rules**.

## Recommended test sequence

### 1. Validate Hospital 1

1. In the sidebar choose **Provided hospital data**.
2. Select **Hospital 1**.
3. Open **H1 Validation**.
4. Click **Run validation**.

Expected labelled-development result:

```text
Perfect categories: 18/18
Mean precision: 1.000
Mean recall: 1.000
```

The validation is fully offline. The raw execution log is hidden by default and can be shown with **Show raw execution log**.

### 2. Analyze a contract and run an audit

1. Choose a hospital under **Provided hospital data**, or upload your own contract, invoice CSV, and line-item CSV.
2. Make sure **Use AI to read contract** is enabled.
3. Add an OpenAI API key in the sidebar.
4. In **Workflow**, click **Analyze contract**.
5. Open **Contract** and review services, rates, special pricing rules, ambiguities, and unsupported clauses.
6. Mark **I reviewed the contract rules**.
7. Return to **Workflow** and click **Run audit**.
8. Open **Results** to inspect findings, review cases, and invoice evidence.

### 3. Reuse reviewed contract rules

After a successful audit, download **Contract rules (JSON)** from the Results tab. In a later session, open **Advanced settings → Reuse contract rules** and upload that JSON file. This restores the typed contract rules without another contract-extraction call.

## Contract review

The Contract tab shows:

- contract number, currency, effective period, and service count;
- service names and unit bases;
- base and date-bounded rates;
- daily caps;
- source notes and rule confidence;
- threshold premiums and weekend/non-business-day uplifts;
- volume discounts;
- bundles;
- exclusion windows;
- interpretation notes;
- ambiguities and unsupported clauses.

The review checkbox is intentionally separate from extraction. It records that the user has inspected the current rules before treating the audit results as final.

## Service mapping

The mapping pipeline is conservative:

1. normalized exact matching;
2. local fuzzy/token matching;
3. stable billing-code propagation only where trusted mappings agree;
4. optional OpenAI candidate selection for unresolved/ambiguous descriptions;
5. unresolved when evidence remains insufficient.

An unresolved mapping is **not automatically treated as `unknown_service`**. Instead, it lowers mapping coverage/confidence and can place the invoice in the review queue. A likely truly unknown service is flagged only when the available evidence supports that conclusion.

This implements the exercise principle that a confidently wrong answer is worse than explicit uncertainty.

## Deterministic rules supported

The generic audit engine supports:

- contract-number mismatch;
- malformed service dates;
- service date after invoice date;
- service date outside the contract term;
- line-total arithmetic mismatch;
- invoice-total mismatch;
- duplicate invoice IDs;
- cross-invoice duplicate lines;
- unknown service;
- unit-basis mismatch;
- base rates and date-bounded rate periods/amendments;
- facility multipliers;
- plan-tier multipliers;
- threshold premiums;
- weekend/non-business-day uplifts;
- cumulative volume discounts;
- bundled rates;
- daily quantity caps;
- exclusion windows;
- generic unit-price mismatch.

If a clause cannot be represented safely, it belongs in `unsupported_rules` and lowers confidence instead of being silently ignored.

## Duplicate invoice IDs

The source invoice CSV can contain multiple physical records with the same `invoice_id`. The engine preserves the source-row context and, when the line ID encodes a source invoice row, attaches each line to the correct physical invoice record.

For a duplicated ID, the final submission still contains one row for that `invoice_id`. The latest physical source record is used as the canonical submission record, while all source records remain visible in **Results → Invoice details** and are shown separately rather than being summed together. Duplicate IDs always remain review-worthy.

Because of this, the **Invoices** count in Workflow can be larger than **Audited** in Results: Workflow counts source invoice rows, while Results contains one prediction per unique invoice ID.

## Results and explainability

The Results tab contains:

- audited, flagged, review, confidence, and mapping-coverage summaries;
- error-category counts;
- invoice-level results;
- a **Needs review** table;
- low-confidence service mappings when present;
- **Invoice details** with line-level billed vs expected evidence;
- separate source-record evidence for duplicate invoice IDs;
- a deterministic explanation generated directly from Python audit evidence;
- an optional AI plain-language summary that cannot recalculate or change the finding.

## Downloads

The final UI exposes two downloads:

### Contract rules (JSON)

`<hospital>_contract_rules.json`

This is the reviewed typed contract rule set and can be uploaded later under **Advanced settings → Reuse contract rules**.

### Audit results (ZIP)

`<hospital>_audit_results.zip` contains:

- `<hospital>_submission.csv` — final invoice-level predictions;
- `<hospital>_review_queue.csv` — invoices requiring additional review;
- `<hospital>_service_mapping.csv` — description-to-contract-service mapping evidence;
- `<hospital>_line_audit.csv` — line-level deterministic audit evidence.

The contract-rules JSON is intentionally downloaded separately instead of being duplicated inside the ZIP.

## Hospital 1 benchmark

The H1 validation runs `src/hospital1_reference.py`, the frozen labelled-development implementation. It reaches 18/18 perfect category detection on Hospital 1. This should be described as **development/calibration performance**, not as out-of-sample performance on Hospitals 2–5.

## Hospital 2 offline parser — development asset

`src/offline_specs.py` and `offline_specs/hospital_2.json` are retained for regression testing and reproducibility. The parser extracts explicit repeated Hospital 2 contract clauses, including services/rates, caps, non-Business-Day uplifts, threshold premiums, volume tiers, bundles, and exclusions.

Rebuild the development JSON with:

```bash
python tools/rebuild_offline_h2_spec.py
```

The final Streamlit UI does not expose a Hospital-2-specific offline starter button.

## Tests

Run:

```bash
pytest -q
```

The test suite covers core deterministic pricing/mapping behavior, the Hospital 2 parser, bundled rule-schema validity, and deterministic invoice explanations.

## Suggested exercise-submission workflow

1. Run and save the Hospital 1 validation result.
2. For each scored hospital, extract contract rules or load a previously reviewed contract-rules JSON file.
3. Verify rates, unit bases, amendments, premiums, discounts, bundles, caps, and exclusions against the source contract.
4. Record important interpretation choices in `DECISION_LOG.md`.
5. Run service mapping and deterministic auditing.
6. Review low-confidence mappings and invoices in **Needs review**.
7. Inspect invoice details for important or uncertain findings.
8. Download the contract rules JSON and audit-results ZIP for reproducibility.
9. Combine final Hospital 2–5 submission CSVs with `combine_submissions.py` when needed.
10. Complete the short report using `REPORT_TEMPLATE.md`.

## Privacy note

The bundled exercise data is synthetic. For real healthcare data, appropriate privacy, security, contractual, and regulatory controls would be required before sending any content to an external API.
