from pathlib import Path

import pandas as pd

from src.cache_utils import load_contract_spec
from src.explain import build_invoice_evidence, deterministic_explanation_markdown
from src.offline_specs import build_hospital_2_spec


ROOT = Path(__file__).resolve().parents[1]


def test_h2_offline_parser_counts():
    source = (
        ROOT
        / "exercise_data"
        / "insurance_auditing-main"
        / "contracts"
        / "hospital_2"
        / "master_services_agreement.md"
    )
    spec = build_hospital_2_spec(source)
    assert len(spec.services) == 76
    assert len(spec.weekend_uplifts) == 8
    assert len(spec.threshold_premiums) == 9
    assert len(spec.volume_discounts) == 8
    assert len(spec.bundles) == 3
    assert len(spec.exclusions) == 6


def test_bundled_h2_json_is_valid():
    spec = load_contract_spec(ROOT / "offline_specs" / "hospital_2.json")
    assert spec.contract_number == "INS-H2-2024-1183"
    assert spec.currency == "GBP"
    assert len(spec.services) == 76


def test_deterministic_explanation_uses_evidence():
    spec = load_contract_spec(ROOT / "offline_specs" / "hospital_2.json")
    predictions = pd.DataFrame(
        [
            {
                "invoice_id": "INV-X",
                "flagged": 1,
                "error_category": "unit_price_mismatch",
                "expected_total_cents": 10000,
                "billed_total_cents": 12000,
                "confidence": 0.9,
                "coverage": 1.0,
                "review_required": False,
            }
        ]
    )
    line_audit = pd.DataFrame(
        [
            {
                "invoice_id": "INV-X",
                "line_id": "L1",
                "service_date_raw": "2025-01-01",
                "description": "Test service",
                "service_name": spec.services[0].service_name,
                "mapping_method": "exact",
                "mapping_confidence": 0.99,
                "unit_basis_as_billed": spec.services[0].unit_basis,
                "contract_unit_basis": spec.services[0].unit_basis,
                "quantity": 1,
                "unit_price_cents": 12000,
                "expected_unit_rate_cents": 10000,
                "line_total_cents": 12000,
                "expected_line_total_cents": 10000,
                "pricing_error_reasons": ["unit_price_mismatch"],
                "wrong_unit_basis": False,
                "line_arithmetic_error": False,
            }
        ]
    )
    evidence = build_invoice_evidence("INV-X", predictions, line_audit, spec)
    text = deterministic_explanation_markdown(evidence)
    assert "unit_price_mismatch" in text
    assert "GBP 120.00" in text
    assert "GBP 100.00" in text
