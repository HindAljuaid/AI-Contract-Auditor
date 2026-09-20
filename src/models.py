from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class RatePeriod(BaseModel):
    rate_cents: int = Field(ge=0)
    effective_from: str | None = None
    effective_to: str | None = None
    source_note: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ServiceRule(BaseModel):
    service_name: str
    unit_basis: str
    rates: list[RatePeriod]
    aliases: list[str] = []
    daily_cap: float | None = Field(default=None, ge=0)
    daily_cap_unit: str | None = None
    notes: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class MultiplierRule(BaseModel):
    service_name: str
    key: str
    multiplier: float = Field(gt=0)


class ThresholdPremiumRule(BaseModel):
    service_name: str
    threshold_quantity: float = Field(ge=0)
    multiplier: float = Field(gt=0)
    comparison: Literal["gt", "gte"] = "gt"
    scope: Literal["patient_service_day", "service_day", "invoice_service"] = "patient_service_day"
    notes: str = ""


class WeekendUpliftRule(BaseModel):
    service_name: str
    multiplier: float = Field(gt=0)
    weekdays: list[int] = [5, 6]
    notes: str = ""


class VolumeTier(BaseModel):
    threshold_quantity: float = Field(ge=0)
    multiplier: float = Field(gt=0)
    comparison: Literal["gt", "gte"] = "gt"


class VolumeDiscountRule(BaseModel):
    service_name: str
    tiers: list[VolumeTier]
    scope: Literal["contract_service", "patient_service", "invoice_service"] = "contract_service"
    notes: str = ""


class BundleRule(BaseModel):
    service_a: str
    service_b: str
    rate_a_cents: int = Field(ge=0)
    rate_b_cents: int = Field(ge=0)
    same_patient: bool = True
    same_service_date: bool = True
    notes: str = ""


class ExclusionRule(BaseModel):
    trigger_service: str
    excluded_service: str
    window_days: int = Field(ge=0)
    direction: Literal["either", "after", "before"] = "either"
    notes: str = ""


class ContractSpec(BaseModel):
    contract_number: str | None = None
    provider_name: str | None = None
    payer_name: str | None = None
    currency: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    rounding: Literal["half_up_cent", "half_even_cent", "unknown"] = "unknown"

    services: list[ServiceRule]
    facility_multipliers: list[MultiplierRule] = []
    plan_multipliers: list[MultiplierRule] = []
    threshold_premiums: list[ThresholdPremiumRule] = []
    weekend_uplifts: list[WeekendUpliftRule] = []
    volume_discounts: list[VolumeDiscountRule] = []
    bundles: list[BundleRule] = []
    exclusions: list[ExclusionRule] = []

    adjustment_order: list[str] = [
        "bundle",
        "facility_multiplier",
        "plan_multiplier",
        "threshold_premium",
        "weekend_uplift",
        "volume_discount",
    ]

    interpretation_notes: list[str] = []
    ambiguities: list[str] = []
    unsupported_rules: list[str] = []
    extraction_confidence: float = Field(default=0.85, ge=0.0, le=1.0)


class MappingItem(BaseModel):
    item_id: int
    selected_service: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class MappingBatch(BaseModel):
    mappings: list[MappingItem]
