# Decision Log

## 1. LLM role is intentionally constrained

The OpenAI model is used for contract extraction and ambiguous text-to-service resolution. It does not calculate invoice totals. Monetary calculations, date checks, thresholds, bundles, discounts, caps, and invoice aggregation are deterministic Python.

Reason: a single hallucinated rate can contaminate many invoices. Uncertain interpretations are surfaced for review instead of silently applied.

## 2. Hospital 1 is development/calibration only

The labelled Hospital 1 set validates the deterministic architecture and service-resolution strategy. A frozen Hospital 1 reference implementation is kept separate from the generic auditor. The 18/18 result is therefore reported only as labelled-development performance.

## 3. Generic engine prioritizes honest coverage over forced answers

When a description is unresolved, a contract rate period is ambiguous, or a rule is unsupported, the engine lowers confidence and marks the invoice for review. For expected-total estimation, unresolved lines conservatively retain their billed line amount rather than inventing a contract price.

## 4. Service mapping does not use billed price

The local matcher uses normalized wording. The optional AI mapper chooses only among lexical candidate services and is explicitly instructed not to use billed price, unit basis, or invoice outcome to infer identity.

## 5. Duplicate invoice IDs preserve physical source records

Duplicate invoice IDs are directly flagged. Source invoice rows are numbered, and line IDs that encode a source row are used to attach lines to the correct physical invoice record. Safe invoice-ID fallback is used only when the ID is unique.

The final submission remains one row per `invoice_id`. When an ID has multiple physical source records, the latest physical record is used as the canonical submission record, while all duplicate source records remain available as separate evidence and are never summed together for the submission total. Duplicate IDs always require review.

This replaces the earlier generic behavior that could merge duplicate-record context.

## 6. Contract amendments

The contract schema supports multiple date-bounded rate periods for a service. Amendments override base rates only from their stated effective date.

## 7. Unsupported clauses

A generic schema cannot guarantee complete representation of every bespoke contract clause. The extraction prompt requires such clauses to be listed in `unsupported_rules`; the app lowers confidence and exposes them for review.

## 8. API failures should be actionable, not technical

Raw OpenAI tracebacks are not shown for quota, authentication, rate-limit, or network failures. The UI surfaces concise messages. Hospital 1 Validation remains offline, and previously downloaded contract-rules JSON files can be uploaded to reuse a reviewed rule set without repeating extraction.

## 9. Hospital 2 offline parser is a regression asset, not a final UI shortcut

Hospital 2 retains a deterministic source-grounded parser because its repeated prose clauses follow a stable drafting pattern. It extracts only explicitly stated rates, caps, premiums, non-Business-Day uplifts, cumulative discounts, bundles, and exclusions.

The parser and bundled JSON are retained for tests and reproducibility, but the final UI does not expose a Hospital-2-specific offline starter button.

## 10. Unresolved mapping is not automatically an error

For scored/unlabelled hospitals, failure to resolve an abbreviation is uncertainty, not proof that the hospital billed an unknown service. The engine distinguishes unresolved mapping from a likely `unknown_service`; unresolved mappings reduce coverage/confidence and enter the human review queue.

## 11. Explanations are downstream of deterministic evidence

Invoice details and the deterministic explanation are generated directly from Python audit evidence. Optional AI prose receives only that evidence and cannot change amounts, mappings, contract terms, or findings.

## 12. Downloads separate reusable rules from audit outputs

The Results tab exposes two artifacts:

- a contract-rules JSON file for reuse in later sessions;
- an audit-results ZIP containing submission rows, review queue, service mapping, and line-level audit evidence.

The contract-rules JSON is intentionally not duplicated inside the audit ZIP.
