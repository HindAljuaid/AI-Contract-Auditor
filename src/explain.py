from __future__ import annotations

from typing import Any

import pandas as pd

from .models import ContractSpec


def _money(cents: Any, currency: str | None) -> str:
    if cents is None or pd.isna(cents):
        return "—"
    code = currency or "CUR"
    return f"{code} {int(cents) / 100:,.2f}"


def _safe_int(value):
    if value is None or pd.isna(value):
        return None
    return int(value)


def _safe_float(value, default: float = 0.0) -> float:
    if value is None or pd.isna(value):
        return default
    return float(value)


def _line_to_evidence(row: dict) -> dict:
    reasons = row.get("pricing_error_reasons", [])
    if not isinstance(reasons, list):
        reasons = []
    return {
        "line_id": row.get("line_id"),
        "source_invoice_row_no": _safe_int(row.get("invoice_row_no")),
        "line_source_row_no": _safe_int(row.get("line_source_row_no")),
        "source_context_method": row.get("source_context_method"),
        "service_date": str(row.get("service_date_raw", "")),
        "description": row.get("description"),
        "mapped_service": row.get("service_name"),
        "mapping_method": row.get("mapping_method"),
        "mapping_confidence": _safe_float(row.get("mapping_confidence")),
        "billed_basis": row.get("unit_basis_as_billed"),
        "contract_basis": row.get("contract_unit_basis"),
        "quantity": None if pd.isna(row.get("quantity")) else float(row.get("quantity")),
        "billed_unit_price_cents": _safe_int(row.get("unit_price_cents")),
        "expected_unit_rate_cents": _safe_int(row.get("expected_unit_rate_cents")),
        "billed_line_total_cents": _safe_int(row.get("line_total_cents")),
        "expected_line_total_cents": _safe_int(row.get("expected_line_total_cents")),
        "pricing_error_reasons": reasons,
        "wrong_unit_basis": bool(row.get("wrong_unit_basis", False)),
        "line_arithmetic_error": bool(row.get("line_arithmetic_error", False)),
    }


def _expected_record_total(lines: list[dict]) -> int:
    total = 0
    for line in lines:
        expected = line.get("expected_line_total_cents")
        billed = line.get("billed_line_total_cents")
        total += int(expected if expected is not None else (billed or 0))
    return total


def build_invoice_evidence(
    invoice_id: str,
    predictions: pd.DataFrame,
    line_audit: pd.DataFrame,
    spec: ContractSpec,
) -> dict:
    pred = predictions[predictions["invoice_id"].astype(str).eq(str(invoice_id))]
    if pred.empty:
        raise KeyError(f"Invoice not found: {invoice_id}")
    pred_row = pred.iloc[0]

    rows = line_audit[line_audit["invoice_id"].astype(str).eq(str(invoice_id))].copy()
    evidence_lines = [_line_to_evidence(row) for row in rows.to_dict(orient="records")]

    canonical_row_no = _safe_int(pred_row.get("canonical_invoice_row_no"))
    duplicate_record_count = int(pred_row.get("duplicate_record_count", 1) or 1)

    source_records: list[dict] = []
    if not rows.empty and "invoice_row_no" in rows.columns and rows["invoice_row_no"].notna().any():
        resolved = rows[rows["invoice_row_no"].notna()].copy()
        for row_no, group in resolved.groupby("invoice_row_no", sort=True):
            record_lines = [_line_to_evidence(row) for row in group.to_dict(orient="records")]
            first = group.iloc[0]
            source_records.append(
                {
                    "invoice_row_no": int(row_no),
                    "is_submission_record": canonical_row_no is not None and int(row_no) == canonical_row_no,
                    "patient_id": first.get("patient_id"),
                    "invoice_date": None if pd.isna(first.get("invoice_date_parsed")) else str(pd.Timestamp(first.get("invoice_date_parsed")).date()),
                    "contract_number": first.get("contract_number"),
                    "facility_code": first.get("facility_code"),
                    "plan_tier": first.get("plan_tier"),
                    "billed_total_cents": _safe_int(first.get("invoice_total_cents")),
                    "line_billed_sum_cents": sum((line.get("billed_line_total_cents") or 0) for line in record_lines),
                    "expected_total_cents": _expected_record_total(record_lines),
                    "lines": record_lines,
                }
            )

    unresolved = rows[rows["invoice_row_no"].isna()].copy() if "invoice_row_no" in rows.columns else rows.copy()
    if not unresolved.empty:
        record_lines = [_line_to_evidence(row) for row in unresolved.to_dict(orient="records")]
        source_records.append(
            {
                "invoice_row_no": None,
                "is_submission_record": False,
                "patient_id": None,
                "invoice_date": None,
                "contract_number": None,
                "facility_code": None,
                "plan_tier": None,
                "billed_total_cents": None,
                "line_billed_sum_cents": sum((line.get("billed_line_total_cents") or 0) for line in record_lines),
                "expected_total_cents": _expected_record_total(record_lines),
                "lines": record_lines,
                "context_note": "Source invoice record could not be resolved safely.",
            }
        )

    return {
        "invoice_id": str(invoice_id),
        "flagged": int(pred_row["flagged"]),
        "error_category": pred_row.get("error_category", ""),
        "expected_total_cents": int(pred_row["expected_total_cents"]),
        "billed_total_cents": int(pred_row["billed_total_cents"]),
        "confidence": float(pred_row["confidence"]),
        "coverage": float(pred_row.get("coverage", 0.0)),
        "review_required": bool(pred_row.get("review_required", False)),
        "duplicate_record_count": duplicate_record_count,
        "canonical_invoice_row_no": canonical_row_no,
        "source_context_complete": bool(pred_row.get("source_context_complete", True)),
        "currency": spec.currency,
        "contract_number": spec.contract_number,
        # Backwards-compatible flattened view, useful for downloads/AI summary.
        "lines": evidence_lines,
        # Preferred view for UI/explanations. Duplicate IDs are kept separate.
        "source_records": source_records,
    }


def _line_markdown(line: dict, currency: str | None) -> list[str]:
    reasons = list(line.get("pricing_error_reasons") or [])
    if line.get("wrong_unit_basis"):
        reasons.append("wrong_unit_basis")
    if line.get("line_arithmetic_error"):
        reasons.append("line_total_arithmetic")
    reason_text = ", ".join(dict.fromkeys(reasons)) if reasons else "no pricing discrepancy"
    return [
        "",
        f"**{line.get('line_id') or 'Line'} — {line.get('description') or '—'}**",
        f"- Mapped service: {line.get('mapped_service') or 'UNRESOLVED'}",
        f"- Mapping: {line.get('mapping_method') or '—'} ({line.get('mapping_confidence', 0):.1%})",
        f"- Unit basis: billed `{line.get('billed_basis') or '—'}` vs contract `{line.get('contract_basis') or '—'}`",
        f"- Quantity: {line.get('quantity') if line.get('quantity') is not None else '—'}",
        f"- Unit rate: billed {_money(line.get('billed_unit_price_cents'), currency)} vs expected {_money(line.get('expected_unit_rate_cents'), currency)}",
        f"- Line total: billed {_money(line.get('billed_line_total_cents'), currency)} vs expected {_money(line.get('expected_line_total_cents'), currency)}",
        f"- Finding: **{reason_text}**",
    ]


def deterministic_explanation_markdown(evidence: dict) -> str:
    currency = evidence.get("currency")
    categories = evidence.get("error_category") or "none"
    duplicate_count = int(evidence.get("duplicate_record_count", 1) or 1)
    canonical_row_no = evidence.get("canonical_invoice_row_no")

    billed_label = "Submission billed total" if duplicate_count > 1 else "Billed total"
    expected_label = "Submission expected total" if duplicate_count > 1 else "Expected total"

    parts = [
        f"### Invoice `{evidence['invoice_id']}`",
        "",
        f"- **Status:** {'Flagged' if evidence['flagged'] else 'Clean'}",
        f"- **Detected category/categories:** `{categories}`",
        f"- **{billed_label}:** {_money(evidence['billed_total_cents'], currency)}",
        f"- **{expected_label}:** {_money(evidence['expected_total_cents'], currency)}",
        f"- **Confidence:** {evidence['confidence']:.1%}",
        f"- **Mapped coverage:** {evidence['coverage']:.1%}",
        f"- **Human review required:** {'Yes' if evidence['review_required'] else 'No'}",
    ]

    if duplicate_count > 1:
        parts.extend(
            [
                "",
                f"> ⚠ This invoice ID occurs in **{duplicate_count} source invoice records**. "
                f"The submission totals use the latest source record"
                + (f" (row {canonical_row_no})" if canonical_row_no is not None else "")
                + ". The source records are shown separately below; they are not summed together for the submission total.",
            ]
        )

    records = evidence.get("source_records") or []
    if records:
        for i, record in enumerate(records, start=1):
            row_no = record.get("invoice_row_no")
            label = f"Source record {i}"
            if row_no is not None:
                label += f" — row {row_no}"
            if record.get("is_submission_record"):
                label += " (submission record)"

            parts.extend(
                [
                    "",
                    f"#### {label}",
                    f"- Header billed total: {_money(record.get('billed_total_cents'), currency)}",
                    f"- Reconstructed expected total: {_money(record.get('expected_total_cents'), currency)}",
                ]
            )
            if record.get("patient_id"):
                parts.append(f"- Patient: `{record.get('patient_id')}`")
            if record.get("invoice_date"):
                parts.append(f"- Invoice date: `{record.get('invoice_date')}`")
            if record.get("context_note"):
                parts.append(f"- Note: {record.get('context_note')}")

            parts.append("")
            parts.append("##### Line-by-line evidence")
            for line in record.get("lines", []):
                parts.extend(_line_markdown(line, currency))
    else:
        parts.extend(["", "#### Line-by-line evidence"])
        for line in evidence.get("lines", []):
            parts.extend(_line_markdown(line, currency))

    parts.extend(
        [
            "",
            "> This explanation is generated from deterministic audit evidence. The language model is not used to calculate prices or decide the finding.",
        ]
    )
    return "\n".join(parts)
