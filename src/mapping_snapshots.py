from __future__ import annotations

from pathlib import Path

import pandas as pd

from .models import ContractSpec


REQUIRED_MAPPING_COLUMNS = {
    "item_id",
    "description",
    "normalized_description",
    "service_name",
    "mapping_method",
    "mapping_confidence",
    "top_score",
    "score_gap",
}


def load_reviewed_mapping_snapshot(
    project_root: Path,
    source_key: str,
    lines: pd.DataFrame,
    spec: ContractSpec,
) -> pd.DataFrame | None:
    """Load a reviewed mapping snapshot only when it exactly fits the current data.

    The snapshot mechanism is generic: any bundled data source can provide a
    previously reviewed ``*_service_mapping.csv`` file.  A snapshot is reused
    only when it covers exactly the current unique billing descriptions and all
    mapped services still exist in the current contract specification.

    If any validation fails, return ``None`` so callers can safely fall back to
    the normal deterministic/AI mapping pipeline.
    """
    path = (
        Path(project_root)
        / "demo_outputs"
        / source_key
        / f"{source_key}_service_mapping.csv"
    )
    if not path.exists() or "description" not in lines.columns:
        return None

    try:
        mapping = pd.read_csv(path)
    except Exception:
        return None

    if not REQUIRED_MAPPING_COLUMNS.issubset(mapping.columns):
        return None

    current_descriptions = set(lines["description"].astype(str).drop_duplicates())
    snapshot_descriptions = set(mapping["description"].astype(str).drop_duplicates())
    if current_descriptions != snapshot_descriptions:
        return None

    contract_services = {service.service_name for service in spec.services}
    mapped_services = set(mapping["service_name"].dropna().astype(str))
    if not mapped_services.issubset(contract_services):
        return None

    # Preserve the exact reviewed decisions while tagging the in-memory frame so
    # the UI can explain why no new AI mapping call was required.
    mapping.attrs["mapping_source"] = "reviewed_snapshot"
    mapping.attrs["mapping_snapshot_path"] = str(path)
    return mapping
