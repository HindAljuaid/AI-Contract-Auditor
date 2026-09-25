# AI Contract Auditor

A Streamlit application for the insurance-auditing technical exercise. The project combines AI-assisted contract interpretation with deterministic invoice auditing.

## Live demo

**Application:** https://ai-contract-auditor.streamlit.app

The system deliberately separates **language interpretation** from **financial decisions**:

- OpenAI converts heterogeneous contract documents into a typed `ContractSpec` and can help resolve ambiguous service descriptions.
- Deterministic Python performs monetary calculations, rate-period checks, premiums, discounts, bundles, caps, exclusions, date rules, duplicate handling, and final audit findings.
- Generic local enrichment recovers explicit structured contract tables when the AI omits rows from long outputs.
- Unresolved mappings remain visible as uncertainty and review cases instead of being forced into confident errors.
- Hospital 1 is retained only as a labeled development/calibration benchmark.

## Final architecture

```text
Contract documents
        │
        ├── OpenAI structured extraction
        │
        └── reviewed contract-rules JSON
        │
        ▼
Typed ContractSpec
        │
        ├── generic explicit-table enrichment
        │      ├── missing service/rate rows
        │      ├── cumulative volume-discount tables
        │      └── facility / plan-tier multiplier tables
        │
        ▼
Reviewed contract rules
        │
Invoices + line items
        │
        ├── validated reviewed mapping snapshot
        │      └── bundled datasets only, when still compatible
        │
        └── otherwise local matching + optional AI candidate selection
        │
        ▼
Deterministic Python audit
        │
        ├── submission CSV
        ├── review queue CSV
        ├── service mapping CSV
        └── line audit CSV
```

**Design principle:** AI interprets language; deterministic code decides money and audit findings.

## Final challenge outputs

Hospitals 2–5 are unlabeled challenge datasets. The following are the **final system outputs**, not verified ground truth:

| Hospital | Predictions | Flagged |
|---|---:|---:|
| H2 | 1,125 | 137 |
| H3 | 932 | 98 |
| H4 | 835 | 156 |
| H5 | 1,050 | 177 |
| **Total** | **3,942** | **568** |

The combined `submission.csv` contains exactly **3,942 unique invoice IDs**.

## Hospital 1 development benchmark

Hospital 1 is the only labeled dataset and is used strictly for development/calibration.

Final development benchmark:

```text
Perfect categories: 18/18
True positives:      105
False positives:       0
False negatives:       0
Mean precision:     1.000
Mean recall:        1.000
Mean F1:            1.000
```

This result should not be described as out-of-sample performance on Hospitals 2–5.

## Robustness improvements

The final implementation includes three generic safeguards discovered during repeated fresh end-to-end runs.

### 1. Service/rate table enrichment

`src/contract_enrichment.py` can recover a service row that is explicitly present in a text/Markdown rate table but missing from the AI-generated `ContractSpec`.

This prevents one omitted table row from cascading into unresolved mappings and incorrect downstream rate checks.

### 2. Cumulative volume-discount enrichment

Explicit text/Markdown volume-discount tables can be recovered when structured AI extraction omits them.

`VolumeDiscountRule` also supports:

- `scope`: contract-service, patient-service, or invoice-service;
- `reset_period`: `none` or `calendar_year`.

The enrichment does not overwrite an already extracted rule.

### 3. Facility and plan-tier multiplier enrichment

Large explicit multiplier matrices can exceed practical structured-output limits. The local enrichment layer can reconstruct missing facility and plan-tier multiplier rules directly from explicit text/Markdown tables.

The parser is generic and does not branch on hospital IDs, provider names, service names, or fixed rates.

## Mapping reproducibility

Ambiguous descriptions can receive slightly different AI decisions across fresh runs. To make bundled examples reproducible, the app can reuse a reviewed `*_service_mapping.csv` snapshot from `demo_outputs/`.

A snapshot is used only when:

1. the current unique billing descriptions exactly match the snapshot; and
2. every mapped service still exists in the current `ContractSpec`.

If either validation fails, the app falls back to the normal local + optional AI mapping pipeline.

Uploaded/custom datasets do not use bundled mapping snapshots.

## Project layout

```text
AI-Contract-Auditor/
├── app.py
├── requirements.txt
├── run_app.sh
├── README.md
├── RUN_ME_FIRST.md
├── DECISION_LOG.md
├── PROJECT_VALIDATION.txt
├── combine_submissions.py
├── prompts/
│   ├── contract_extraction_v1.md
│   └── mapping_resolution_v1.md
├── src/
│   ├── ai.py
│   ├── audit_engine.py
│   ├── cache_utils.py
│   ├── contract_enrichment.py
│   ├── data_utils.py
│   ├── explain.py
│   ├── h1_benchmark.py
│   ├── hospital1_reference.py
│   ├── mapping.py
│   ├── mapping_snapshots.py
│   ├── models.py
│   └── offline_specs.py
├── tests/
│   ├── test_core.py
│   └── test_stage2.py
├── tools/
│   ├── rebuild_offline_h2_spec.py
│   └── regenerate_outputs_offline.py
├── offline_specs/
│   └── hospital_2.json
├── validation/
│   └── hospital_1/
│       ├── README.md
│       ├── hospital_1_validation_development.ipynb
│       └── hospital_1_validation_reference.py
├── sample_outputs/
│   └── hospital_1/
│       ├── hospital_1_category_evaluation.csv
│       ├── hospital_1_category_predictions.csv
│       └── hospital_1_line_mapping.csv
├── demo_outputs/
│   ├── README.md
│   ├── hospital_2/
│   ├── hospital_3/
│   ├── hospital_4/
│   └── hospital_5/
├── submission/
│   ├── submission.csv
│   └── AI_Contract_Auditor_Technical_Exercise_Writeup.pdf
└── exercise_data/
    └── insurance_auditing-main/
```

## Run locally on macOS

Python 3.10+ is required.

```bash
cd AI-Contract-Auditor
chmod +x run_app.sh
./run_app.sh
```

The script creates `.venv`, installs the pinned dependencies, and starts Streamlit.

Manual setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

## OpenAI API key

You can provide the API key as an environment variable:

```bash
export OPENAI_API_KEY="your-api-key-here"
./run_app.sh
```

or use a local Streamlit secret:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

You can also paste a key into the app for the current local session.

Never commit a real API key.

If OpenAI is unavailable or the API balance is exhausted:

- Hospital 1 Validation remains fully offline.
- A previously downloaded contract-rules JSON can be reused without another extraction call.
- The mapping stage can fall back to local matching, but the app warns when AI mapping was unavailable because this can change coverage and final findings.

## Run an audit

1. Select **Provided hospital data** or upload your own files.
2. Select the hospital/data source.
3. Either analyze the contract with AI or reuse a previously saved contract-rules JSON for that same source.
4. Review the extracted services, rates, pricing rules, ambiguities, and unsupported clauses.
5. Mark **I reviewed the contract rules**.
6. Click **Run audit**.
7. Open **Results** to inspect findings, review cases, mapping evidence, and line-level details.
8. Download the contract-rules JSON and audit-results ZIP.

For bundled hospitals with a compatible reviewed mapping snapshot, the validated snapshot is reused automatically. Otherwise the normal mapping pipeline runs.

## Service mapping

The normal mapping pipeline is conservative:

1. normalized exact matching;
2. local fuzzy/token matching;
3. stable billing-code propagation where trusted mappings agree;
4. optional OpenAI candidate selection for unresolved/ambiguous descriptions;
5. unresolved when evidence remains insufficient.

The optional AI mapper chooses only among candidate contract services. Billed price is not used to infer service identity.

An unresolved mapping is **not automatically treated as `unknown_service`**. It lowers coverage/confidence and can place the invoice in the review queue.

## Deterministic audit rules

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
- base and date-bounded rates/amendments;
- facility multipliers;
- plan-tier multipliers;
- threshold premiums;
- weekend/non-business-day uplifts;
- cumulative volume discounts;
- bundled rates;
- daily quantity caps;
- exclusion windows;
- generic unit-price mismatch.

Rules that cannot be represented safely remain in `unsupported_rules` and lower confidence rather than being silently invented.

## Duplicate invoice IDs

The source data can contain multiple physical rows with the same `invoice_id`.

The engine preserves source-row context and uses line identifiers to attach lines to the correct physical invoice record when possible. The final submission still contains one row per unique `invoice_id`; the latest physical record is used as the canonical submission record while duplicate source records remain available as evidence and are never summed together.

## Downloads

### Contract rules JSON

`<hospital>_contract_rules.json`

This is the typed rule set and can be reused for the same data source in a later session.

### Audit results ZIP

`<hospital>_audit_results.zip` contains:

- `<hospital>_submission.csv`
- `<hospital>_review_queue.csv`
- `<hospital>_service_mapping.csv`
- `<hospital>_line_audit.csv`

The contract-rules JSON is downloaded separately.

## Reproducibility assets

`demo_outputs/` contains the final Hospitals 2–5 audit artifacts, including the reviewed mapping snapshots used for reproducible bundled runs.

The final mapping snapshots correspond to:

```text
H2 = 137 flagged
H3 =  98 flagged
H4 = 156 flagged
H5 = 177 flagged
Total = 568 flagged
```

These are challenge-system outputs, not labeled accuracy measurements.

`validation/hospital_1/` preserves the frozen Hospital 1 validation implementation and development notebook. The static benchmark CSV evidence is kept under `sample_outputs/hospital_1/` so it is versioned without depending on generated cache folders.

`offline_specs/` and `src/offline_specs.py` remain development/regression assets for the Hospital 2 repeated-prose parser; they are not special-case UI shortcuts.

## Tests

Run:

```bash
pytest -q
```

The test suite covers deterministic pricing and mapping behavior, rule-schema validity, contract enrichment, reviewed mapping snapshots, the Hospital 2 regression parser, and deterministic explanations.

## Privacy note

The bundled exercise data is synthetic. Real healthcare data would require appropriate privacy, security, contractual, and regulatory controls before any content is sent to an external API.
