from __future__ import annotations

import re
from pathlib import Path

from .models import (
    BundleRule,
    ContractSpec,
    ExclusionRule,
    RatePeriod,
    ServiceRule,
    ThresholdPremiumRule,
    VolumeDiscountRule,
    VolumeTier,
    WeekendUpliftRule,
)


def _cents(amount: str) -> int:
    return int(round(float(amount.replace(",", "")) * 100))


def _basis(value: str) -> str:
    value = value.strip().lower()
    mapping = {
        "per day of service": "per_day_of_service",
        "per night of occupancy": "per_night_of_occupancy",
        "per item supplied": "per_item_supplied",
        "per unit dispensed": "per_unit_dispensed",
        "per procedure": "per_procedure",
        "per visit": "per_visit",
        "per hour": "per_hour",
        "per hour, per item": "per_hour_per_item",
        "per test": "per_test",
    }
    return mapping.get(value, re.sub(r"[^a-z0-9]+", "_", value).strip("_"))


def build_hospital_2_spec(contract_md: Path) -> ContractSpec:
    """Deterministically parse H2's prose contract.

    This is intentionally source-grounded: it only extracts clauses that match
    explicit, repeated contract language. It is a fallback/starter rule pack,
    not an attempt to infer unstated terms.
    """
    text = Path(contract_md).read_text(encoding="utf-8")

    contract_number = re.search(r"\*\*Contract number:\*\*\s*(.+)", text).group(1).strip()
    provider = re.search(r"\*\*Provider:\*\*\s*(.+)", text).group(1).strip()
    payer = re.search(r"\*\*Payer:\*\*\s*(.+)", text).group(1).strip()

    clause_re = re.compile(
        r"(?ms)^(\d+\.\d+)\s+In respect of (.*?)(?=^\d+\.\d+\s+In respect of |^## |\Z)"
    )
    rate_re = re.compile(
        r"^(.*?), the Provider shall invoice the Payer at the rate of GBP ([\d,]+\.\d{2}) (per .*?)\.",
        re.I | re.S,
    )

    services = []
    service_by_name = {}
    threshold_premiums = []
    weekend_uplifts = []
    volume_discounts = []
    bundle_rules = []
    exclusions = []
    seen_bundle_pairs = set()

    for clause_no, body in clause_re.findall(text):
        rate_match = rate_re.search(body)
        if not rate_match:
            continue
        service_name, amount, basis_text = rate_match.groups()
        service_name = service_name.strip()
        unit_basis = _basis(basis_text)

        cap = None
        cap_unit = None
        cap_match = re.search(
            r"shall not bill more than [^(]+\((\d+)\)\s+([^\.]+?) of this Service for a Patient on a single Service Day",
            body,
            re.I,
        )
        if cap_match:
            cap = float(cap_match.group(1))
            cap_unit = cap_match.group(2).strip()

        service = ServiceRule(
            service_name=service_name,
            unit_basis=unit_basis,
            rates=[
                RatePeriod(
                    rate_cents=_cents(amount),
                    effective_from="2024-01-01",
                    effective_to="2025-12-31",
                    source_note=f"Hospital 2 clause {clause_no}",
                    confidence=0.99,
                )
            ],
            aliases=[],
            daily_cap=cap,
            daily_cap_unit=cap_unit,
            notes=f"Offline source-grounded parse of clause {clause_no}.",
            confidence=0.98,
        )
        services.append(service)
        service_by_name[service_name] = service

        weekend = re.search(
            r"does not fall on a Business Day, the rate applicable to it shall be increased by .*?\((\d+)%\)",
            body,
            re.I,
        )
        if weekend:
            weekend_uplifts.append(
                WeekendUpliftRule(
                    service_name=service_name,
                    multiplier=1 + int(weekend.group(1)) / 100,
                    weekdays=[5, 6],
                    notes=f"Clause {clause_no}: non-Business-Day uplift.",
                )
            )

        threshold = re.search(
            r"aggregate quantity of this Service delivered to a Patient on a single Service Day exceeds .*?\((\d+)\)\s+[^,]+, the rate applicable to that Service Day shall be increased by .*?\((\d+)%\)",
            body,
            re.I,
        )
        if threshold:
            threshold_premiums.append(
                ThresholdPremiumRule(
                    service_name=service_name,
                    threshold_quantity=float(threshold.group(1)),
                    multiplier=1 + int(threshold.group(2)) / 100,
                    comparison="gt",
                    scope="patient_service_day",
                    notes=f"Clause {clause_no}: patient Service Day threshold premium.",
                )
            )

        volume_matches = re.findall(
            r"cumulative utilisation of this Service exceeds .*?\((\d+)\)\s+[^,]+,.*?a discount of .*?\((\d+)%\)",
            body,
            re.I,
        )
        if volume_matches:
            volume_discounts.append(
                VolumeDiscountRule(
                    service_name=service_name,
                    tiers=[
                        VolumeTier(
                            threshold_quantity=float(threshold_value),
                            multiplier=1 - int(discount_pct) / 100,
                            comparison="gt",
                        )
                        for threshold_value, discount_pct in volume_matches
                    ],
                    scope="contract_service",
                    notes=f"Clause {clause_no}: cumulative utilisation across all patients.",
                )
            )

        bundle = re.search(
            r"Where this Service and (.*?) are both delivered to the same Patient on the same Service Day, the two shall be billed as a bundle, this Service at GBP ([\d,]+\.\d{2}) (per .*?) and .*? at GBP ([\d,]+\.\d{2}) (per .*?), in substitution for their standalone rates",
            body,
            re.I,
        )
        if bundle:
            other_service, rate_a, _basis_a, rate_b, _basis_b = bundle.groups()
            other_service = other_service.strip()
            pair = tuple(sorted((service_name, other_service)))
            if pair not in seen_bundle_pairs:
                seen_bundle_pairs.add(pair)
                bundle_rules.append(
                    BundleRule(
                        service_a=service_name,
                        service_b=other_service,
                        rate_a_cents=_cents(rate_a),
                        rate_b_cents=_cents(rate_b),
                        same_patient=True,
                        same_service_date=True,
                        notes=f"Clause {clause_no}: substituted bundle rates.",
                    )
                )

        exclusion = re.search(
            r"This Service is not billable where (.*?) has been delivered to the same Patient within [^(]+\((\d+)\) days of the Service Date",
            body,
            re.I,
        )
        if exclusion:
            trigger, days = exclusion.groups()
            exclusions.append(
                ExclusionRule(
                    trigger_service=trigger.strip(),
                    excluded_service=service_name,
                    window_days=int(days),
                    direction="either",
                    notes=f"Clause {clause_no}; Article 3.6 measures the exclusion window in either direction.",
                )
            )

    unsupported = []
    if len(services) < 70:
        unsupported.append(
            "Offline parser extracted fewer H2 services than expected; use AI extraction or manual review before submission."
        )

    return ContractSpec(
        contract_number=contract_number,
        provider_name=provider,
        payer_name=payer,
        currency="GBP",
        effective_from="2024-01-01",
        effective_to="2025-12-31",
        rounding="half_up_cent",
        services=services,
        facility_multipliers=[],
        plan_multipliers=[],
        threshold_premiums=threshold_premiums,
        weekend_uplifts=weekend_uplifts,
        volume_discounts=volume_discounts,
        bundles=bundle_rules,
        exclusions=exclusions,
        adjustment_order=[
            "bundle",
            "facility_multiplier",
            "plan_multiplier",
            "threshold_premium",
            "weekend_uplift",
            "volume_discount",
        ],
        interpretation_notes=[
            "Offline fallback parsed only explicit repeated H2 clause patterns from the bundled source contract.",
            "Article 1.3 states no facility differential and rates apply irrespective of plan tier.",
            "Article 3.1 requires half-up rounding after each adjustment step.",
            "Article 3.5 defines cumulative utilisation as prior quantity in Service Date / line-id order.",
            "This starter rule pack should be reviewed in the Contract rules tab before final submission.",
        ],
        ambiguities=[],
        unsupported_rules=unsupported,
        extraction_confidence=0.94,
    )


def build_offline_exercise_spec(exercise_root: Path, hospital_number: int) -> ContractSpec | None:
    if int(hospital_number) == 2:
        return build_hospital_2_spec(
            Path(exercise_root) / "contracts" / "hospital_2" / "master_services_agreement.md"
        )
    return None
