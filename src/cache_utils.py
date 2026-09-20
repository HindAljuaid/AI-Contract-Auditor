from __future__ import annotations

import re
from pathlib import Path

from .models import ContractSpec


def safe_key(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(value).strip()).strip("_")
    return value.lower() or "contract"


def contract_cache_path(project_root: Path, key: str) -> Path:
    path = Path(project_root) / ".cache" / "contracts" / f"{safe_key(key)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def save_contract_spec(project_root: Path, key: str, spec: ContractSpec) -> Path:
    path = contract_cache_path(project_root, key)
    path.write_text(spec.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_contract_spec(path: Path) -> ContractSpec:
    return ContractSpec.model_validate_json(Path(path).read_text(encoding="utf-8"))


def load_cached_contract_spec(project_root: Path, key: str) -> ContractSpec | None:
    path = contract_cache_path(project_root, key)
    if not path.exists():
        return None
    return load_contract_spec(path)
