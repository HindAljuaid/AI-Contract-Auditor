from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.offline_specs import build_hospital_2_spec


source = (
    ROOT
    / "exercise_data"
    / "insurance_auditing-main"
    / "contracts"
    / "hospital_2"
    / "master_services_agreement.md"
)
out = ROOT / "offline_specs" / "hospital_2.json"
out.parent.mkdir(parents=True, exist_ok=True)
spec = build_hospital_2_spec(source)
out.write_text(spec.model_dump_json(indent=2), encoding="utf-8")
print(f"Wrote {out}")
print(f"Services: {len(spec.services)}")
