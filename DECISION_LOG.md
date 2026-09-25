# Decision Log

## 1. LLM role is intentionally constrained

The OpenAI model is used for contract extraction and ambiguous text-to-service resolution. It does not calculate invoice totals. Monetary calculations, date checks, thresholds, bundles, discounts, caps, and invoice aggregation are deterministic Python.

Reason: a hallucinated rate can affect many invoices. Uncertain interpretations are surfaced for review instead of silently applied.

## 2. Hospital 1 is development/calibration only

The labeled Hospital 1 set validates the deterministic architecture and service-resolution strategy. A frozen Hospital 1 reference implementation is kept separate from the generic auditor.

The 18/18 category result is reported only as development/calibration performance, not as out-of-sample performance.

## 3. Generic engine prioritizes honest coverage over forced answers

When a description is unresolved, a rate period is ambiguous, or a rule is unsupported, the engine lowers confidence and marks the invoice for review.

For expected-total estimation, unresolved lines conservatively retain their billed line amount rather than inventing a contract price.

## 4. Service mapping does not use billed price

The local matcher uses normalized wording. The optional AI mapper chooses only among lexical candidate services and is instructed not to use billed price, unit basis, or invoice outcome to infer service identity.

## 5. Duplicate invoice IDs preserve physical source records

Duplicate invoice IDs are directly flagged. Source invoice rows are numbered, and line IDs that encode a source row are used to attach lines to the correct physical invoice record. Safe invoice-ID fallback is used only when the ID is unique.

The final submission remains one row per `invoice_id`. When an ID has multiple physical source records, the latest physical record is used as the canonical submission record. Duplicate source records remain separate evidence and are never summed together.

## 6. Contract amendments are date-bounded

The contract schema supports multiple rate periods for one service. Amendments override base rates only from their stated effective date.

## 7. Explicit tables are recovered deterministically when safe

Repeated fresh extraction tests showed that long structured outputs can occasionally omit explicit table rows even when the model understands the contract.

To reduce that failure mode, `src/contract_enrichment.py` performs conservative local recovery from explicit text/Markdown tables for:

- missing service/rate rows;
- cumulative volume-discount tables;
- facility multiplier matrices;
- plan-tier multiplier matrices.

The enrichment is generic. It does not branch on hospital ID, provider name, contract number, fixed service names, or fixed rates.

Existing extracted rules are not overwritten merely because a table is also present.

## 8. Volume-discount scope and reset behavior are explicit

`VolumeDiscountRule` includes both `scope` and `reset_period`.

Supported reset behavior is currently:

- `none`
- `calendar_year`

A reset is applied only when the contract states it. If population wording is ambiguous, the ambiguity remains visible instead of inventing a narrower scope.

## 9. Reviewed mapping snapshots are a reproducibility control

Fresh AI mapping can vary on ambiguous abbreviations even when the contract rules and financial engine are unchanged.

For bundled datasets, the app may reuse the reviewed `*_service_mapping.csv` snapshot from `demo_outputs/`, but only when:

1. the current unique billing descriptions exactly match the snapshot; and
2. all mapped services still exist in the current `ContractSpec`.

If either condition fails, the app uses the normal local + optional AI mapping pipeline.

Custom/uploaded datasets do not inherit bundled snapshots.

## 10. Unsupported clauses remain visible

A generic schema cannot guarantee complete representation of every bespoke clause. Clauses that still cannot be represented safely are retained in `unsupported_rules`, lower confidence, and remain visible for human review.

A stale unsupported-rule message is removed only when the corresponding explicit table has actually been recovered by deterministic enrichment.

## 11. API failures should be actionable

Raw OpenAI tracebacks are not shown for quota, authentication, rate-limit, or network failures. The UI presents concise messages.

Hospital 1 Validation remains offline. Previously downloaded contract-rules JSON files can be reused without repeating extraction.

If AI mapping is unavailable, the app can continue with local matching but clearly warns that uncertain cases remain for review.

## 12. Hospital 2 offline parser is a regression asset, not a production shortcut

Hospital 2 retains a deterministic source-grounded parser because its repeated prose clauses follow a stable drafting pattern.

The parser and bundled JSON are retained for regression testing and reproducibility, but the final UI does not expose a Hospital-2-specific offline starter button.

## 13. Unresolved mapping is not automatically an error

For unlabeled challenge hospitals, failure to resolve an abbreviation is uncertainty, not proof that the hospital billed an unknown service.

The engine distinguishes unresolved mapping from a likely `unknown_service`. Unresolved mappings reduce coverage/confidence and enter the human-review queue.

## 14. Explanations are downstream of deterministic evidence

Invoice details and deterministic explanations are generated directly from Python audit evidence.

Optional AI prose receives only that evidence and cannot change amounts, mappings, contract terms, or findings.

## 15. Downloads separate reusable rules from audit outputs

The Results tab exposes:

- a contract-rules JSON file for later reuse;
- an audit-results ZIP containing submission rows, review queue, service mapping, and line-level audit evidence.

The contract-rules JSON is intentionally not duplicated inside the audit ZIP.

## 16. Final Hospitals 2–5 outputs are frozen reproducibility artifacts

The final challenge output contains 3,942 unique invoice IDs and 568 flagged invoices:

- H2: 137
- H3: 98
- H4: 156
- H5: 177

Because Hospitals 2–5 are unlabeled, these counts are not presented as accuracy measurements or ground truth. They are the final system outputs selected after the generic robustness improvements and are preserved with their reviewed mapping snapshots for reproducibility.
