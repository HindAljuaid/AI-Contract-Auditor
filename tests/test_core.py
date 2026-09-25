from decimal import Decimal

import pandas as pd

from src.audit_engine import apply_multiplier, audit_invoices
from src.mapping import normalize_basis, normalize_text
from src.models import ContractSpec, RatePeriod, ServiceRule


def test_half_up_multiplier():
    assert apply_multiplier(101, Decimal("1.5")) == 152


def test_normalization():
    assert normalize_text("Adv Card Recov Rm Occ /NG-1234") == "advanced cardiac recovery room occupancy"
    assert normalize_basis("per day") == "per_day_of_service"


def test_basic_price_mismatch():
    spec = ContractSpec(
        contract_number="C-1",
        effective_from="2026-01-01",
        effective_to="2026-12-31",
        rounding="half_up_cent",
        services=[
            ServiceRule(
                service_name="Example Service",
                unit_basis="per visit",
                rates=[RatePeriod(rate_cents=10000)],
            )
        ],
        extraction_confidence=1.0,
    )

    invoices = pd.DataFrame(
        [
            {
                "invoice_id": "INV-1",
                "hospital_id": "H",
                "contract_number": "C-1",
                "invoice_date": "2026-02-02",
                "patient_id": "P-1",
                "facility_code": "F-MAIN",
                "plan_tier": "GOLD",
                "admission_date": "2026-02-01",
                "discharge_date": "2026-02-03",
                "invoice_total_cents": 11000,
            }
        ]
    )
    lines = pd.DataFrame(
        [
            {
                "line_id": "L-1",
                "invoice_id": "INV-1",
                "line_no": 1,
                "service_date": "2026-02-02",
                "description": "Example Service",
                "quantity": 1,
                "unit_basis_as_billed": "per visit",
                "unit_price_cents": 11000,
                "line_total_cents": 11000,
            }
        ]
    )
    mapping = pd.DataFrame(
        [
            {
                "description": "Example Service",
                "service_name": "Example Service",
                "mapping_method": "exact",
                "mapping_confidence": 0.99,
                "top_score": 100.0,
                "score_gap": 100.0,
            }
        ]
    )

    predictions, line_audit = audit_invoices(invoices, lines, spec, mapping)
    assert predictions.iloc[0]["flagged"] == 1
    assert "unit_price_mismatch" in predictions.iloc[0]["error_category"]
    assert predictions.iloc[0]["expected_total_cents"] == 10000


def test_volume_discount_calendar_year_reset():
    from src.models import VolumeDiscountRule, VolumeTier

    spec = ContractSpec(
        contract_number="C-VOL",
        effective_from="2024-01-01",
        effective_to="2025-12-31",
        rounding="half_up_cent",
        services=[
            ServiceRule(
                service_name="Volume Service",
                unit_basis="per visit",
                rates=[RatePeriod(rate_cents=10000)],
            )
        ],
        volume_discounts=[
            VolumeDiscountRule(
                service_name="Volume Service",
                tiers=[VolumeTier(threshold_quantity=1, multiplier=0.5, comparison="gt")],
                scope="patient_service",
                reset_period="calendar_year",
            )
        ],
        extraction_confidence=1.0,
    )

    invoices = pd.DataFrame(
        [
            {
                "invoice_id": "INV-1", "hospital_id": "H", "contract_number": "C-VOL",
                "invoice_date": "2024-01-02", "patient_id": "P-1", "facility_code": "F",
                "plan_tier": "GOLD", "admission_date": "2024-01-01", "discharge_date": "2024-01-03",
                "invoice_total_cents": 20000,
            },
            {
                "invoice_id": "INV-2", "hospital_id": "H", "contract_number": "C-VOL",
                "invoice_date": "2024-01-03", "patient_id": "P-1", "facility_code": "F",
                "plan_tier": "GOLD", "admission_date": "2024-01-01", "discharge_date": "2024-01-04",
                "invoice_total_cents": 5000,
            },
            {
                "invoice_id": "INV-3", "hospital_id": "H", "contract_number": "C-VOL",
                "invoice_date": "2025-01-02", "patient_id": "P-1", "facility_code": "F",
                "plan_tier": "GOLD", "admission_date": "2025-01-01", "discharge_date": "2025-01-03",
                "invoice_total_cents": 10000,
            },
        ]
    )
    lines = pd.DataFrame(
        [
            {
                "line_id": "X-1", "invoice_id": "INV-1", "line_no": 1, "service_date": "2024-01-01",
                "description": "Volume Service", "quantity": 2, "unit_basis_as_billed": "per visit",
                "unit_price_cents": 10000, "line_total_cents": 20000,
            },
            {
                "line_id": "X-2", "invoice_id": "INV-2", "line_no": 1, "service_date": "2024-01-02",
                "description": "Volume Service", "quantity": 1, "unit_basis_as_billed": "per visit",
                "unit_price_cents": 5000, "line_total_cents": 5000,
            },
            {
                "line_id": "X-3", "invoice_id": "INV-3", "line_no": 1, "service_date": "2025-01-01",
                "description": "Volume Service", "quantity": 1, "unit_basis_as_billed": "per visit",
                "unit_price_cents": 10000, "line_total_cents": 10000,
            },
        ]
    )
    mapping = pd.DataFrame(
        [{
            "description": "Volume Service", "service_name": "Volume Service", "mapping_method": "exact",
            "mapping_confidence": 1.0, "top_score": 100.0, "score_gap": 100.0,
        }]
    )

    predictions, line_audit = audit_invoices(invoices, lines, spec, mapping)
    expected_rates = line_audit.sort_values("service_date_parsed")["expected_unit_rate_cents"].tolist()
    assert expected_rates == [10000, 5000, 10000]
    assert int(predictions["flagged"].sum()) == 0


def test_generic_volume_enrichment_extracts_scope_and_reset_without_hospital_logic():
    from src.contract_enrichment import enrich_volume_discounts_from_texts

    spec = ContractSpec(
        contract_number="GENERIC",
        services=[
            ServiceRule(
                service_name="Example Service",
                unit_basis="per visit",
                rates=[RatePeriod(rate_cents=10000)],
            )
        ],
    )
    contract_text = """
## Cumulative Volume Discounts
For each Patient, cumulative utilisation is measured separately in each calendar year.

| Service | Cumulative utilisation exceeds | Discount on subsequent instances |
|---|---|---|
| Example Service | 10 | 15% |
| Example Service | 20 | 30% |
"""
    enriched = enrich_volume_discounts_from_texts(spec, [contract_text])
    assert len(enriched.volume_discounts) == 1
    rule = enriched.volume_discounts[0]
    assert rule.service_name == "Example Service"
    assert rule.scope == "patient_service"
    assert rule.reset_period == "calendar_year"
    assert [t.threshold_quantity for t in rule.tiers] == [10.0, 20.0]
    assert [round(t.multiplier, 2) for t in rule.tiers] == [0.85, 0.70]


def test_reviewed_mapping_snapshot_reuses_exact_bundled_mapping():
    from pathlib import Path

    from src.data_utils import load_exercise_hospital
    from src.mapping_snapshots import load_reviewed_mapping_snapshot
    from src.models import ContractSpec

    root = Path(__file__).resolve().parents[1]
    data_root = root / "exercise_data" / "insurance_auditing-main"
    _, lines = load_exercise_hospital(data_root, 4)
    spec = ContractSpec.model_validate_json(
        (root / "demo_outputs" / "hospital_4" / "hospital_4_contract_rules.json").read_text(
            encoding="utf-8"
        )
    )

    mapping = load_reviewed_mapping_snapshot(root, "hospital_4", lines, spec)
    assert mapping is not None
    assert mapping.attrs.get("mapping_source") == "reviewed_snapshot"
    assert set(mapping["description"].astype(str)) == set(lines["description"].astype(str))


def test_reviewed_mapping_snapshot_rejects_changed_dataset():
    from pathlib import Path

    from src.data_utils import load_exercise_hospital
    from src.mapping_snapshots import load_reviewed_mapping_snapshot
    from src.models import ContractSpec

    root = Path(__file__).resolve().parents[1]
    data_root = root / "exercise_data" / "insurance_auditing-main"
    _, lines = load_exercise_hospital(data_root, 4)
    spec = ContractSpec.model_validate_json(
        (root / "demo_outputs" / "hospital_4" / "hospital_4_contract_rules.json").read_text(
            encoding="utf-8"
        )
    )

    changed = lines.copy()
    changed.loc[changed.index[0], "description"] = "brand new unmatched service description"
    mapping = load_reviewed_mapping_snapshot(root, "hospital_4", changed, spec)
    assert mapping is None


def test_generic_service_table_enrichment_recovers_missing_row():
    from src.contract_enrichment import enrich_service_tables_from_texts

    spec = ContractSpec(
        contract_number="GENERIC-SERVICE-TABLE",
        effective_from="2024-01-01",
        effective_to="2025-12-31",
        services=[
            ServiceRule(
                service_name="Existing Service",
                unit_basis="per visit",
                rates=[RatePeriod(rate_cents=10000)],
            )
        ],
    )
    contract_text = """
## Rate Schedule

| Service | Unit basis | Rate | Daily cap |
|---|---|---:|---:|
| Existing Service | per visit | GBP 100.00 | |
| Newly Listed Service | per test | GBP 285.00 | 4 tests |
"""

    enriched = enrich_service_tables_from_texts(spec, [contract_text])
    by_name = {service.service_name: service for service in enriched.services}

    assert set(by_name) == {"Existing Service", "Newly Listed Service"}
    recovered = by_name["Newly Listed Service"]
    assert recovered.unit_basis == "per test"
    assert recovered.rates[0].rate_cents == 28500
    assert recovered.daily_cap == 4
    assert recovered.daily_cap_unit == "tests"


def test_generic_multiplier_enrichment_recovers_explicit_tables():
    from src.contract_enrichment import enrich_multiplier_tables_from_texts

    spec = ContractSpec(
        contract_number="GENERIC-MULTIPLIERS",
        services=[
            ServiceRule(
                service_name="Example Service",
                unit_basis="per visit",
                rates=[RatePeriod(rate_cents=10000)],
            )
        ],
        unsupported_rules=[
            "Facility multiplier matrix and plan-tier multiplier matrix are not fully encoded."
        ],
    )
    contract_text = """
## Facility multipliers

| Service | F-A | F-B |
|---|---:|---:|
| Example Service | 1.00 | 1.10 |

## Plan-tier multipliers

| Service | BASIC | GOLD |
|---|---:|---:|
| Example Service | 1.00 | 0.90 |
"""

    enriched = enrich_multiplier_tables_from_texts(spec, [contract_text])

    facility = {(r.service_name, r.key): r.multiplier for r in enriched.facility_multipliers}
    plan = {(r.service_name, r.key): r.multiplier for r in enriched.plan_multipliers}
    assert facility == {
        ("Example Service", "F-A"): 1.0,
        ("Example Service", "F-B"): 1.1,
    }
    assert plan == {
        ("Example Service", "BASIC"): 1.0,
        ("Example Service", "GOLD"): 0.9,
    }
    assert not enriched.unsupported_rules


def test_final_submission_matches_demo_outputs():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    required = [
        "invoice_id",
        "flagged",
        "error_category",
        "expected_total_cents",
        "billed_total_cents",
        "confidence",
    ]

    frames = []
    expected_flagged = {2: 137, 3: 98, 4: 156, 5: 177}
    for hospital in (2, 3, 4, 5):
        path = (
            root
            / "demo_outputs"
            / f"hospital_{hospital}"
            / f"hospital_{hospital}_submission.csv"
        )
        frame = pd.read_csv(path)
        assert list(frame.columns) == required
        assert int(frame["flagged"].sum()) == expected_flagged[hospital]
        frames.append(frame)

    combined = pd.concat(frames, ignore_index=True)
    assert len(combined) == 3942
    assert combined["invoice_id"].nunique() == 3942
    assert int(combined["flagged"].sum()) == 568

    final = pd.read_csv(root / "submission" / "submission.csv")
    assert list(final.columns) == required

    combined = combined.sort_values("invoice_id").reset_index(drop=True)
    final = final.sort_values("invoice_id").reset_index(drop=True)
    pd.testing.assert_frame_equal(final, combined, check_dtype=False, check_exact=False, rtol=0, atol=1e-12)


def test_all_final_bundled_mapping_snapshots_validate():
    from pathlib import Path

    from src.data_utils import load_exercise_hospital
    from src.mapping_snapshots import load_reviewed_mapping_snapshot

    root = Path(__file__).resolve().parents[1]
    data_root = root / "exercise_data" / "insurance_auditing-main"

    for hospital in (2, 3, 4, 5):
        _, lines = load_exercise_hospital(data_root, hospital)
        rules_path = (
            root
            / "demo_outputs"
            / f"hospital_{hospital}"
            / f"hospital_{hospital}_contract_rules.json"
        )
        spec = ContractSpec.model_validate_json(rules_path.read_text(encoding="utf-8"))
        mapping = load_reviewed_mapping_snapshot(
            root, f"hospital_{hospital}", lines, spec
        )
        assert mapping is not None
        assert mapping.attrs.get("mapping_source") == "reviewed_snapshot"
