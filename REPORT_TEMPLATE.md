# Evaluation Report — Draft Structure

## Approach

I implemented a hybrid contract-auditing system. An LLM converts heterogeneous contract documents into a typed rule schema and can resolve only ambiguous text mappings among deterministic candidate services. All monetary calculations are performed by a deterministic Python rule engine using integer cents and explicit stepwise rounding.

The engine checks structural errors (line/invoice arithmetic, dates, contract number, duplicates), service identity and unit basis, time-dependent rates, facility/plan modifiers, threshold premiums, weekend uplifts, cumulative volume discounts, daily caps, bundles, and exclusion windows. Low-confidence or unsupported cases are placed in a review queue rather than forced into confident predictions.

## Hospital 1 development-set measurement

Insert `sample_outputs/hospital_1/hospital_1_category_evaluation.csv` or the H1 Validation table here. Report precision, recall, and F1 per error category, plus expected-total accuracy if calculated.

Clearly label Hospital 1 as development/calibration data rather than out-of-sample performance.

## Systematic error analysis

Group remaining errors by failure type, for example:

1. service-description ambiguity;
2. unsupported or ambiguous contract clauses;
3. duplicate source-record context;
4. rate-period or modifier interpretation.

Use one concrete example per failure type rather than listing every invoice.

## Uncertainty and coverage

Explain how mapping confidence, extraction confidence, unresolved lines, unsupported rules, and duplicate-record context affect the final confidence score and human-review queue.

Also distinguish source invoice-row counts from unique audited invoice IDs when duplicate IDs are present.

## What I would do with another week

- add contract-specific regression tests for every extracted special clause;
- statistically calibrate confidence using Hospital 1 without treating it as out-of-sample evidence;
- persist reviewer approval metadata and rule-version history;
- add richer amendment/version handling and clause provenance;
- expand contract-specific adapters for rules the generic schema marks unsupported;
- add automated evaluation of service mappings and expected totals;
- add end-to-end browser tests for the Streamlit workflow and exported artifacts.
