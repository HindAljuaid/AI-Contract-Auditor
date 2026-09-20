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
