from __future__ import annotations

import io
from pathlib import Path
from typing import Iterable

import pandas as pd


REQUIRED_INVOICE_COLUMNS = {
    "invoice_id",
    "contract_number",
    "invoice_date",
    "patient_id",
    "facility_code",
    "plan_tier",
    "admission_date",
    "discharge_date",
    "invoice_total_cents",
}

REQUIRED_LINE_COLUMNS = {
    "line_id",
    "invoice_id",
    "line_no",
    "service_date",
    "description",
    "quantity",
    "unit_basis_as_billed",
    "unit_price_cents",
    "line_total_cents",
}


def validate_columns(df: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"{label} is missing required columns: {', '.join(missing)}")


def read_csv_any(source) -> pd.DataFrame:
    """Read a CSV from a path or Streamlit UploadedFile-like object."""
    if isinstance(source, (str, Path)):
        return pd.read_csv(source)
    if hasattr(source, "getvalue"):
        return pd.read_csv(io.BytesIO(source.getvalue()))
    return pd.read_csv(source)


def load_exercise_hospital(data_root: str | Path, hospital_number: int):
    root = Path(data_root)
    invoices = pd.read_csv(root / "invoices" / f"hospital_{hospital_number}_invoices.csv")
    lines = pd.read_csv(root / "invoices" / f"hospital_{hospital_number}_line_items.csv")
    validate_columns(invoices, REQUIRED_INVOICE_COLUMNS, "Invoice CSV")
    validate_columns(lines, REQUIRED_LINE_COLUMNS, "Line-item CSV")
    return invoices, lines


def exercise_contract_files(data_root: str | Path, hospital_number: int) -> list[Path]:
    folder = Path(data_root) / "contracts" / f"hospital_{hospital_number}"
    if not folder.exists():
        return []

    # Prefer human-readable source documents and avoid duplicate TXT copies when
    # Markdown is available. H2 also ships PDFs but the Markdown rendition is
    # sufficient for the bundled exercise demo; uploaded PDFs are supported by AI.
    md = sorted(folder.glob("*.md"))
    if md:
        return md
    txt = sorted(folder.glob("*.txt"))
    if txt:
        return txt
    return sorted(folder.glob("*.pdf"))


def contract_file_descriptor(file_obj) -> tuple[str, bytes]:
    if isinstance(file_obj, Path):
        return file_obj.name, file_obj.read_bytes()
    if isinstance(file_obj, str):
        path = Path(file_obj)
        return path.name, path.read_bytes()
    if hasattr(file_obj, "name") and hasattr(file_obj, "getvalue"):
        return file_obj.name, file_obj.getvalue()
    raise TypeError(f"Unsupported contract file object: {type(file_obj)!r}")


def safe_output_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in value).strip("_") or "audit"
