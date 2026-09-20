from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import pandas as pd

from .mapping import normalize_basis
from .models import ContractSpec, ServiceRule


ERROR_ORDER = [
    "unknown_service",
    "wrong_unit_basis",
    "unit_price_mismatch",
    "line_total_arithmetic",
    "invoice_total_mismatch",
    "malformed_service_date",
    "premium_incorrectly_applied",
    "service_date_after_invoice_date",
    "bundle_not_applied",
    "duplicate_invoice_id",
    "contract_number_mismatch",
    "service_date_out_of_window",
    "daily_cap_exceeded",
    "volume_discount_incorrectly_applied",
    "exclusion_window_violation",
    "cross_invoice_duplicate",
    "volume_discount_omitted",
    "premium_omitted",
]


def round_half_up(value: Any) -> int:
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def apply_multiplier(cents: int, multiplier: float | Decimal) -> int:
    return round_half_up(Decimal(cents) * Decimal(str(multiplier)))


def _parse_date(value) -> pd.Timestamp | pd.NaT:
    return pd.to_datetime(value, errors="coerce")


def _date_or_none(value: str | None) -> pd.Timestamp | None:
    if not value:
        return None
    ts = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(ts) else ts


def _condition(value: float, threshold: float, comparison: str) -> bool:
    return value >= threshold if comparison == "gte" else value > threshold


@dataclass
class PriceContext:
    base_rate: int
    bundle_rate: int | None
    facility_multiplier: float
    plan_multiplier: float
    threshold_multiplier: float
    threshold_expected: bool
    threshold_rule_exists: bool
    weekend_multiplier: float
    weekend_expected: bool
    weekend_rule_exists: bool
    volume_multiplier: float
    volume_rule_exists: bool


class ContractIndex:
    def __init__(self, spec: ContractSpec):
        self.spec = spec
        self.services = {s.service_name: s for s in spec.services}
        self.facility = {(r.service_name, r.key): r.multiplier for r in spec.facility_multipliers}
        self.plan = {(r.service_name, r.key.upper()): r.multiplier for r in spec.plan_multipliers}
        self.threshold = {r.service_name: r for r in spec.threshold_premiums}
        self.weekend = {r.service_name: r for r in spec.weekend_uplifts}
        self.volume = {r.service_name: r for r in spec.volume_discounts}
        self.bundles = spec.bundles
        self.exclusions = spec.exclusions

    def rate_for(self, service_name: str, service_date: pd.Timestamp | pd.NaT) -> tuple[int | None, float]:
        service = self.services.get(service_name)
        if service is None or not service.rates:
            return None, 0.0

        if pd.isna(service_date):
            if len(service.rates) == 1:
                r = service.rates[0]
                return r.rate_cents, min(0.75, r.confidence)
            return None, 0.0

        candidates = []
        for rate in service.rates:
            start = _date_or_none(rate.effective_from)
            end = _date_or_none(rate.effective_to)
            if (start is None or service_date >= start) and (end is None or service_date <= end):
                candidates.append(rate)

        if len(candidates) == 1:
            r = candidates[0]
            return r.rate_cents, r.confidence
        if len(candidates) > 1:
            # Pick the most recent effective-from rate if overlapping periods exist.
            candidates.sort(
                key=lambda r: _date_or_none(r.effective_from) or pd.Timestamp.min,
                reverse=True,
            )
            r = candidates[0]
            return r.rate_cents, min(r.confidence, 0.75)

        if len(service.rates) == 1:
            r = service.rates[0]
            return r.rate_cents, min(r.confidence, 0.60)
        return None, 0.0


def _effective_contract_window(spec: ContractSpec):
    return _date_or_none(spec.effective_from), _date_or_none(spec.effective_to)


def _prepare_invoices(invoices: pd.DataFrame) -> tuple[pd.DataFrame, set[str]]:
    """Prepare invoice headers and assign a stable 1-based source-row key.

    The exercise line IDs encode the source invoice row (for example,
    ``H2-L00104-03`` belongs to invoice source row 104).  Keeping that key is
    essential when ``invoice_id`` itself is duplicated.
    """
    inv = invoices.copy().reset_index(drop=True)
    inv["invoice_row_no"] = pd.Series(range(1, len(inv) + 1), dtype="Int64")
    inv["invoice_date_parsed"] = pd.to_datetime(inv["invoice_date"], errors="coerce")
    inv["admission_date_parsed"] = pd.to_datetime(inv["admission_date"], errors="coerce")
    inv["discharge_date_parsed"] = pd.to_datetime(inv["discharge_date"], errors="coerce")
    duplicate_ids = set(inv.loc[inv["invoice_id"].duplicated(keep=False), "invoice_id"].astype(str))
    inv["duplicate_record_count"] = inv.groupby("invoice_id")["invoice_id"].transform("size")
    return inv, duplicate_ids


def _prepare_lines(lines: pd.DataFrame) -> pd.DataFrame:
    out = lines.copy().reset_index(drop=True)
    out["service_date_raw"] = out["service_date"].astype("string")
    out["service_date_parsed"] = pd.to_datetime(out["service_date"], errors="coerce")
    out["quantity"] = pd.to_numeric(out["quantity"], errors="coerce")
    out["unit_price_cents"] = pd.to_numeric(out["unit_price_cents"], errors="coerce")
    out["line_total_cents"] = pd.to_numeric(out["line_total_cents"], errors="coerce")

    # For the supplied exercise files, the middle numeric component of line_id
    # is the 1-based invoice source row: H2-L00104-03 -> 104.  Custom uploads
    # may not follow this convention, so unresolved rows fall back safely later.
    out["line_source_row_no"] = pd.to_numeric(
        out["line_id"].astype("string").str.extract(r"(?:^|-)L(\d+)-", expand=False),
        errors="coerce",
    ).astype("Int64")
    return out


def _attach_invoice_context(
    lines: pd.DataFrame,
    invoices: pd.DataFrame,
    duplicate_ids: set[str],
) -> pd.DataFrame:
    """Attach the correct physical invoice header to each line.

    Source-row matching is preferred because duplicate invoice IDs are not a
    valid join key.  If a custom upload does not encode source rows in line_id,
    only *unique* invoice IDs are used as a fallback.  Duplicate IDs without a
    resolvable source row are deliberately left without header context rather
    than being attached to an arbitrary first record.
    """
    out = lines.copy()
    context_cols = [
        "invoice_row_no",
        "invoice_id",
        "contract_number",
        "invoice_date_parsed",
        "patient_id",
        "facility_code",
        "plan_tier",
        "admission_date_parsed",
        "discharge_date_parsed",
        "invoice_total_cents",
        "duplicate_record_count",
    ]
    ctx = invoices[context_cols].rename(columns={"invoice_id": "context_invoice_id"})

    out = out.merge(
        ctx,
        left_on="line_source_row_no",
        right_on="invoice_row_no",
        how="left",
        validate="many_to_one",
    )

    source_match = (
        out["context_invoice_id"].notna()
        & out["context_invoice_id"].astype(str).eq(out["invoice_id"].astype(str))
    )

    # Reject a numeric source-row match if it points to a different invoice ID.
    context_payload = [
        "invoice_row_no",
        "contract_number",
        "invoice_date_parsed",
        "patient_id",
        "facility_code",
        "plan_tier",
        "admission_date_parsed",
        "discharge_date_parsed",
        "invoice_total_cents",
        "duplicate_record_count",
    ]
    bad_source = ~source_match
    out.loc[bad_source, context_payload] = pd.NA

    # Safe fallback for custom files: invoice_id is usable only when it occurs
    # exactly once in the header table.
    unique_ctx = invoices[~invoices["invoice_id"].astype(str).isin(duplicate_ids)][context_cols].copy()
    unique_ctx = unique_ctx.rename(
        columns={c: f"{c}_fallback" for c in context_cols if c != "invoice_id"}
    )
    out = out.merge(unique_ctx, on="invoice_id", how="left", validate="many_to_one")

    fallback_available = out["invoice_row_no"].isna() & out["invoice_row_no_fallback"].notna()
    for col in context_payload:
        fallback_col = f"{col}_fallback"
        out.loc[fallback_available, col] = out.loc[fallback_available, fallback_col]

    out["source_context_method"] = "unresolved"
    out.loc[source_match, "source_context_method"] = "source_row"
    out.loc[fallback_available, "source_context_method"] = "unique_invoice_id"
    unresolved_duplicate = (
        out["invoice_row_no"].isna()
        & out["invoice_id"].astype(str).isin(duplicate_ids)
    )
    out.loc[unresolved_duplicate, "source_context_method"] = "unresolved_duplicate"
    out["source_context_resolved"] = out["invoice_row_no"].notna()

    # Use the physical source row as the invoice-scoped key.  This prevents
    # threshold/volume calculations from mixing two records that share an ID.
    out["invoice_record_key"] = out["invoice_row_no"].map(
        lambda x: f"row:{int(x)}" if not pd.isna(x) else None
    )
    unresolved_key = out["invoice_record_key"].isna()
    out.loc[unresolved_key, "invoice_record_key"] = (
        "ambiguous:" + out.loc[unresolved_key, "invoice_id"].astype(str)
    )

    drop_cols = [
        "context_invoice_id",
        *[f"{c}_fallback" for c in context_cols if c != "invoice_id"],
    ]
    return out.drop(columns=[c for c in drop_cols if c in out.columns])

def _mapping_dict(mapping: pd.DataFrame) -> pd.DataFrame:
    keep = [
        "description",
        "service_name",
        "mapping_method",
        "mapping_confidence",
        "top_score",
        "score_gap",
    ]
    existing = [c for c in keep if c in mapping.columns]
    return mapping[existing].drop_duplicates("description")


def _bundle_overrides(df: pd.DataFrame, index: ContractIndex) -> dict[int, int]:
    overrides: dict[int, int] = {}
    valid = df[df["service_name"].notna() & df["patient_id"].notna() & df["service_date_parsed"].notna()]
    if valid.empty:
        return overrides

    for rule in index.bundles:
        for _, group in valid.groupby(["patient_id", "service_date_parsed"], dropna=False):
            names = set(group["service_name"].dropna())
            if rule.service_a in names and rule.service_b in names:
                for row_idx in group.index[group["service_name"].eq(rule.service_a)]:
                    overrides[int(row_idx)] = rule.rate_a_cents
                for row_idx in group.index[group["service_name"].eq(rule.service_b)]:
                    overrides[int(row_idx)] = rule.rate_b_cents
    return overrides


def _threshold_context(df: pd.DataFrame, index: ContractIndex) -> dict[int, tuple[float, bool, bool]]:
    result: dict[int, tuple[float, bool, bool]] = {}
    if not index.threshold:
        return result

    group_qty = (
        df.groupby(["patient_id", "service_date_parsed", "service_name"], dropna=False)["quantity"]
        .sum(min_count=1)
        .to_dict()
    )

    invoice_qty = df.groupby(["invoice_record_key", "service_name"], dropna=False)["quantity"].sum(min_count=1).to_dict()
    service_day_qty = df.groupby(["service_date_parsed", "service_name"], dropna=False)["quantity"].sum(min_count=1).to_dict()

    for idx_row, row in df.iterrows():
        rule = index.threshold.get(row["service_name"])
        if rule is None:
            continue

        if rule.scope == "patient_service_day":
            qty = group_qty.get((row["patient_id"], row["service_date_parsed"], row["service_name"]), 0) or 0
        elif rule.scope == "service_day":
            qty = service_day_qty.get((row["service_date_parsed"], row["service_name"]), 0) or 0
        else:
            qty = invoice_qty.get((row["invoice_record_key"], row["service_name"]), 0) or 0

        expected = _condition(float(qty), rule.threshold_quantity, rule.comparison)
        result[int(idx_row)] = (rule.multiplier if expected else 1.0, expected, True)
    return result


def _weekend_context(df: pd.DataFrame, index: ContractIndex) -> dict[int, tuple[float, bool, bool]]:
    result: dict[int, tuple[float, bool, bool]] = {}
    for idx_row, row in df.iterrows():
        rule = index.weekend.get(row["service_name"])
        if rule is None:
            continue
        date = row["service_date_parsed"]
        expected = (not pd.isna(date)) and int(date.dayofweek) in set(rule.weekdays)
        result[int(idx_row)] = (rule.multiplier if expected else 1.0, expected, True)
    return result


def _volume_context(df: pd.DataFrame, index: ContractIndex) -> dict[int, tuple[float, bool]]:
    result: dict[int, tuple[float, bool]] = {}
    if not index.volume:
        return result

    ordered = df.sort_values(["service_date_parsed", "line_id"], na_position="last")
    accum_contract: dict[str, float] = {}
    accum_patient: dict[tuple[str, str], float] = {}
    accum_invoice: dict[tuple[str, str], float] = {}

    for idx_row, row in ordered.iterrows():
        service = row["service_name"]
        rule = index.volume.get(service)
        if rule is None:
            continue

        if rule.scope == "patient_service":
            key = (str(row["patient_id"]), service)
            prior = accum_patient.get(key, 0.0)
        elif rule.scope == "invoice_service":
            key = (str(row["invoice_record_key"]), service)
            prior = accum_invoice.get(key, 0.0)
        else:
            key = service
            prior = accum_contract.get(key, 0.0)

        chosen = 1.0
        for tier in sorted(rule.tiers, key=lambda x: x.threshold_quantity, reverse=True):
            if _condition(prior, tier.threshold_quantity, tier.comparison):
                chosen = tier.multiplier
                break

        result[int(idx_row)] = (chosen, True)
        qty = float(row["quantity"] or 0.0) if not pd.isna(row["quantity"]) else 0.0
        if rule.scope == "patient_service":
            accum_patient[key] = prior + qty
        elif rule.scope == "invoice_service":
            accum_invoice[key] = prior + qty
        else:
            accum_contract[key] = prior + qty
    return result


def _rate_with_overrides(ctx: PriceContext, order: list[str], overrides: dict[str, Any] | None = None) -> int:
    overrides = overrides or {}
    rate = overrides.get("base_rate", ctx.base_rate)
    bundle = overrides.get("bundle_rate", ctx.bundle_rate)
    if bundle is not None:
        rate = bundle

    for step in order:
        key = step.lower().strip()
        if key == "bundle":
            continue
        if key in {"facility", "facility_multiplier"}:
            rate = apply_multiplier(rate, overrides.get("facility_multiplier", ctx.facility_multiplier))
        elif key in {"plan", "plan_tier", "plan_multiplier", "plan_tier_multiplier"}:
            rate = apply_multiplier(rate, overrides.get("plan_multiplier", ctx.plan_multiplier))
        elif key in {"premium", "threshold_premium"}:
            rate = apply_multiplier(rate, overrides.get("threshold_multiplier", ctx.threshold_multiplier))
        elif key in {"weekend", "weekend_uplift", "non_business_day_uplift"}:
            rate = apply_multiplier(rate, overrides.get("weekend_multiplier", ctx.weekend_multiplier))
        elif key in {"volume", "volume_discount", "cumulative_volume_discount", "discount"}:
            rate = apply_multiplier(rate, overrides.get("volume_multiplier", ctx.volume_multiplier))

    return int(rate)


def _daily_cap_ids(df: pd.DataFrame, contract: ContractIndex) -> set[str]:
    result: set[str] = set()
    daily_caps = {s.service_name: s.daily_cap for s in contract.spec.services if s.daily_cap is not None}
    if not daily_caps:
        return result

    grouped = (
        df[df["service_name"].isin(daily_caps)]
        .groupby(["patient_id", "service_date_parsed", "service_name"], dropna=False)["quantity"]
        .sum(min_count=1)
        .reset_index()
    )
    for row in grouped.itertuples(index=False):
        cap = daily_caps.get(row.service_name)
        if cap is None or pd.isna(row.quantity):
            continue
        if float(row.quantity) > float(cap):
            ids = df[
                df["patient_id"].eq(row.patient_id)
                & df["service_date_parsed"].eq(row.service_date_parsed)
                & df["service_name"].eq(row.service_name)
            ]["invoice_id"].astype(str)
            result.update(ids)
    return result


def _exclusion_ids(df: pd.DataFrame, contract: ContractIndex) -> set[str]:
    result: set[str] = set()
    source = df[df["patient_id"].notna() & df["service_date_parsed"].notna() & df["service_name"].notna()]
    if source.empty:
        return result

    for rule in contract.exclusions:
        triggers = source[source["service_name"].eq(rule.trigger_service)]
        excluded = source[source["service_name"].eq(rule.excluded_service)]
        if triggers.empty or excluded.empty:
            continue

        by_patient = {pid: grp for pid, grp in triggers.groupby("patient_id")}
        for row in excluded.itertuples():
            candidates = by_patient.get(row.patient_id)
            if candidates is None:
                continue
            deltas = (row.service_date_parsed - candidates["service_date_parsed"]).dt.days
            if rule.direction == "after":
                hit = deltas.between(0, rule.window_days).any()
            elif rule.direction == "before":
                hit = deltas.between(-rule.window_days, 0).any()
            else:
                hit = deltas.abs().le(rule.window_days).any()
            if hit:
                result.add(str(row.invoice_id))
    return result


def _cross_invoice_duplicate_ids(df: pd.DataFrame) -> set[str]:
    keys = [
        "patient_id",
        "service_date_raw",
        "description",
        "quantity",
        "unit_basis_as_billed",
        "unit_price_cents",
        "line_total_cents",
    ]
    dup_count = df.groupby(keys, dropna=False)["invoice_id"].transform("nunique")
    return set(df.loc[dup_count.gt(1), "invoice_id"].astype(str))


def audit_invoices(
    invoices: pd.DataFrame,
    lines: pd.DataFrame,
    spec: ContractSpec,
    mapping: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Deterministic invoice audit. Returns invoice-level predictions and a line-level
    evidence table. AI is not used here.
    """
    contract = ContractIndex(spec)
    inv, duplicate_ids = _prepare_invoices(invoices)
    ln = _prepare_lines(lines)

    map_df = _mapping_dict(mapping)
    ln = ln.merge(map_df, on="description", how="left", validate="many_to_one")
    ln["mapping_confidence"] = pd.to_numeric(ln["mapping_confidence"], errors="coerce").fillna(0.15)

    # Attach physical invoice-row context before applying any patient/date/header
    # dependent rule.  This is critical for duplicated invoice IDs.
    ln = _attach_invoice_context(ln, inv, duplicate_ids)

    # Deterministic structural flags.
    ln["line_arithmetic_error"] = (
        (ln["quantity"] * ln["unit_price_cents"]).round().ne(ln["line_total_cents"])
    )
    raw_date = ln["service_date_raw"].fillna("").str.strip()
    ln["malformed_service_date"] = raw_date.ne("") & ln["service_date_parsed"].isna()
    ln["service_date_after_invoice_date"] = (
        ln["service_date_parsed"].notna()
        & ln["invoice_date_parsed"].notna()
        & ln["service_date_parsed"].gt(ln["invoice_date_parsed"])
    )

    contract_start, contract_end = _effective_contract_window(spec)
    within = pd.Series(True, index=ln.index)
    if contract_start is not None:
        within &= ln["service_date_parsed"].ge(contract_start) | ln["service_date_parsed"].isna()
    if contract_end is not None:
        within &= ln["service_date_parsed"].le(contract_end) | ln["service_date_parsed"].isna()
    ln["within_contract_period"] = within
    ln["service_date_out_of_window"] = ln["service_date_parsed"].notna() & ~within

    # Distinguish a likely truly unknown/non-contracted service from an unresolved
    # mapping. An ambiguous text match is uncertainty, not evidence of an error.
    # This is essential for unlabeled hospitals: confidently flagging every
    # unresolved abbreviation as unknown_service would violate the exercise's
    # uncertainty principle.
    top_score_source = ln["top_score"] if "top_score" in ln.columns else pd.Series(0.0, index=ln.index)
    top_score = pd.to_numeric(top_score_source, errors="coerce").fillna(0.0)
    ln["mapping_unresolved"] = ln["service_name"].isna() & top_score.ge(60.0)
    ln["unknown_service"] = ln["service_name"].isna() & top_score.lt(60.0)

    # Contract rate and basis.
    base_rates = []
    rate_conf = []
    service_basis = []
    service_conf = []
    for row in ln.itertuples():
        service = contract.services.get(row.service_name) if row.service_name else None
        if service is None:
            base_rates.append(None)
            rate_conf.append(0.0)
            service_basis.append(None)
            service_conf.append(0.0)
            continue
        rate, conf = contract.rate_for(row.service_name, row.service_date_parsed)
        base_rates.append(rate)
        rate_conf.append(conf)
        service_basis.append(service.unit_basis)
        service_conf.append(service.confidence)

    ln["base_rate_cents"] = base_rates
    ln["rate_confidence"] = rate_conf
    ln["contract_unit_basis"] = service_basis
    ln["service_rule_confidence"] = service_conf
    ln["normalized_billed_basis"] = ln["unit_basis_as_billed"].map(normalize_basis)
    ln["normalized_contract_basis"] = ln["contract_unit_basis"].map(normalize_basis)
    ln["wrong_unit_basis"] = (
        ln["service_name"].notna()
        & ln["normalized_billed_basis"].ne("")
        & ln["normalized_contract_basis"].ne("")
        & ln["normalized_billed_basis"].ne(ln["normalized_contract_basis"])
    )

    bundle_overrides = _bundle_overrides(ln, contract)
    threshold_ctx = _threshold_context(ln, contract)
    weekend_ctx = _weekend_context(ln, contract)
    volume_ctx = _volume_context(ln, contract)

    expected_rates = []
    error_reasons: list[list[str]] = []
    pricing_confidences = []

    for idx_row, row in ln.iterrows():
        reasons: list[str] = []
        if row["unknown_service"] or pd.isna(row["base_rate_cents"]):
            expected_rates.append(None)
            error_reasons.append(reasons)
            pricing_confidences.append(0.20)
            continue

        service = str(row["service_name"])
        base = int(row["base_rate_cents"])
        bundle_rate = bundle_overrides.get(int(idx_row))
        facility_mult = float(contract.facility.get((service, str(row["facility_code"])), 1.0))
        plan_mult = float(contract.plan.get((service, str(row["plan_tier"]).upper()), 1.0))
        threshold_mult, threshold_expected, threshold_exists = threshold_ctx.get(int(idx_row), (1.0, False, False))
        weekend_mult, weekend_expected, weekend_exists = weekend_ctx.get(int(idx_row), (1.0, False, False))
        volume_mult, volume_exists = volume_ctx.get(int(idx_row), (1.0, False))

        ctx = PriceContext(
            base_rate=base,
            bundle_rate=bundle_rate,
            facility_multiplier=facility_mult,
            plan_multiplier=plan_mult,
            threshold_multiplier=float(threshold_mult),
            threshold_expected=bool(threshold_expected),
            threshold_rule_exists=bool(threshold_exists),
            weekend_multiplier=float(weekend_mult),
            weekend_expected=bool(weekend_expected),
            weekend_rule_exists=bool(weekend_exists),
            volume_multiplier=float(volume_mult),
            volume_rule_exists=bool(volume_exists),
        )

        expected = _rate_with_overrides(ctx, spec.adjustment_order)
        expected_rates.append(expected)

        billed = int(row["unit_price_cents"]) if not pd.isna(row["unit_price_cents"]) else None
        if billed is not None and billed != expected:
            no_bundle = _rate_with_overrides(ctx, spec.adjustment_order, {"bundle_rate": None})
            no_threshold = _rate_with_overrides(ctx, spec.adjustment_order, {"threshold_multiplier": 1.0})
            no_weekend = _rate_with_overrides(ctx, spec.adjustment_order, {"weekend_multiplier": 1.0})
            no_volume = _rate_with_overrides(ctx, spec.adjustment_order, {"volume_multiplier": 1.0})

            if bundle_rate is not None and billed == no_bundle:
                reasons.append("bundle_not_applied")
            elif threshold_exists and threshold_expected and billed == no_threshold:
                reasons.append("premium_omitted")
            elif weekend_exists and weekend_expected and billed == no_weekend:
                reasons.append("premium_omitted")
            elif volume_exists and float(volume_mult) < 1.0 and billed == no_volume:
                reasons.append("volume_discount_omitted")
            else:
                # Detect a premium that appears to have been applied when it should not.
                if threshold_exists and not threshold_expected:
                    rule = contract.threshold[service]
                    forced = _rate_with_overrides(
                        ctx,
                        spec.adjustment_order,
                        {"threshold_multiplier": float(rule.multiplier)},
                    )
                    if billed == forced:
                        reasons.append("premium_incorrectly_applied")
                if not reasons and volume_exists and float(volume_mult) == 1.0:
                    rule = contract.volume[service]
                    for tier in rule.tiers:
                        forced = _rate_with_overrides(
                            ctx,
                            spec.adjustment_order,
                            {"volume_multiplier": float(tier.multiplier)},
                        )
                        if billed == forced:
                            reasons.append("volume_discount_incorrectly_applied")
                            break
                if not reasons:
                    reasons.append("unit_price_mismatch")

        error_reasons.append(reasons)
        pricing_confidences.append(
            min(
                float(row["mapping_confidence"]),
                float(row["rate_confidence"] or 0.0),
                float(row["service_rule_confidence"] or 0.0),
            )
        )

    ln["expected_unit_rate_cents"] = expected_rates
    ln["pricing_error_reasons"] = error_reasons
    ln["pricing_confidence"] = pricing_confidences
    ln["expected_line_total_cents"] = [
        round_half_up(rate * qty)
        if rate is not None and not pd.isna(rate) and not pd.isna(qty)
        else None
        for rate, qty in zip(ln["expected_unit_rate_cents"], ln["quantity"])
    ]

    daily_cap_ids = _daily_cap_ids(ln, contract)
    exclusion_ids = _exclusion_ids(ln, contract)
    cross_duplicate_ids = _cross_invoice_duplicate_ids(ln)

    # Invoice-level arithmetic is computed by physical source record, not merely
    # invoice_id.  That keeps duplicate IDs from contaminating each other's totals.
    line_billed_sum_by_record = ln.groupby("invoice_record_key")["line_total_cents"].sum(min_count=1).to_dict()

    category_sets: dict[str, set[str]] = {c: set() for c in ERROR_ORDER}
    category_sets["duplicate_invoice_id"] = set(duplicate_ids)
    category_sets["daily_cap_exceeded"] = daily_cap_ids
    category_sets["exclusion_window_violation"] = exclusion_ids
    category_sets["cross_invoice_duplicate"] = cross_duplicate_ids

    category_sets["unknown_service"] = set(ln.loc[ln["unknown_service"], "invoice_id"].astype(str))
    category_sets["wrong_unit_basis"] = set(ln.loc[ln["wrong_unit_basis"], "invoice_id"].astype(str))
    category_sets["line_total_arithmetic"] = set(ln.loc[ln["line_arithmetic_error"], "invoice_id"].astype(str))
    category_sets["malformed_service_date"] = set(ln.loc[ln["malformed_service_date"], "invoice_id"].astype(str))
    category_sets["service_date_after_invoice_date"] = set(ln.loc[ln["service_date_after_invoice_date"], "invoice_id"].astype(str))
    category_sets["service_date_out_of_window"] = set(ln.loc[ln["service_date_out_of_window"], "invoice_id"].astype(str))

    for idx_row, row in ln.iterrows():
        inv_id = str(row["invoice_id"])
        for reason in row["pricing_error_reasons"]:
            if reason in category_sets:
                category_sets[reason].add(inv_id)

    # Contract number mismatch and invoice-total mismatch.
    if spec.contract_number:
        category_sets["contract_number_mismatch"] = set(
            inv.loc[
                inv["contract_number"].astype(str).str.strip().ne(str(spec.contract_number).strip()),
                "invoice_id",
            ].astype(str)
        )

    for row in inv.itertuples(index=False):
        inv_id = str(row.invoice_id)
        record_key = f"row:{int(row.invoice_row_no)}"
        billed_sum = line_billed_sum_by_record.get(record_key)
        if billed_sum is not None and not pd.isna(billed_sum):
            if int(billed_sum) != int(row.invoice_total_cents):
                category_sets["invoice_total_mismatch"].add(inv_id)

    # Build one row per distinct invoice_id because the challenge submission is
    # keyed by invoice_id.  When the ID is duplicated, the latest physical source
    # row is used as the canonical submission record.  This matches the labeled H1
    # development convention while all source records remain available in line_audit
    # for transparent review.
    rows = []
    for inv_id, grp in inv.groupby("invoice_id", sort=False):
        inv_id = str(inv_id)
        grp = grp.sort_values("invoice_row_no")
        header = grp.iloc[-1]
        canonical_row_no = int(header["invoice_row_no"])
        duplicate_record_count = int(len(grp))

        errors = [c for c in ERROR_ORDER if inv_id in category_sets.get(c, set())]

        canonical_lines = ln[
            ln["invoice_id"].astype(str).eq(inv_id)
            & ln["invoice_row_no"].eq(canonical_row_no)
        ].copy()

        source_context_complete = not canonical_lines.empty
        if canonical_lines.empty:
            # If a custom file has duplicate IDs but no source-row information,
            # there is no defensible way to assign lines to one physical header.
            # Keep the canonical billed total as a conservative placeholder and
            # force human review rather than merging both records.
            total_lines = 0
            mapped = 0
            coverage = 0.0
            expected = int(header.invoice_total_cents)
            mapping_conf = 0.20
            pricing_conf = 0.20
        else:
            total_lines = int(len(canonical_lines))
            mapped = int(canonical_lines["service_name"].count())
            coverage = mapped / total_lines if total_lines else 0.0

            expected = 0
            for line in canonical_lines.itertuples(index=False):
                if line.expected_line_total_cents is None or pd.isna(line.expected_line_total_cents):
                    expected += int(line.line_total_cents) if not pd.isna(line.line_total_cents) else 0
                else:
                    expected += int(line.expected_line_total_cents)

            mapping_conf = float(canonical_lines["mapping_confidence"].min()) if total_lines else 0.20
            pricing_conf = float(canonical_lines["pricing_confidence"].min()) if total_lines else mapping_conf

        contract_conf = float(spec.extraction_confidence)

        deterministic_only = all(
            e in {
                "line_total_arithmetic",
                "invoice_total_mismatch",
                "malformed_service_date",
                "service_date_after_invoice_date",
                "duplicate_invoice_id",
                "contract_number_mismatch",
                "service_date_out_of_window",
                "cross_invoice_duplicate",
            }
            for e in errors
        ) and bool(errors)

        if deterministic_only and duplicate_record_count == 1:
            confidence = 0.97
        else:
            confidence = 0.20 + 0.35 * coverage + 0.25 * mapping_conf + 0.15 * pricing_conf + 0.05 * contract_conf
            if duplicate_record_count > 1:
                confidence -= 0.12
            if not source_context_complete:
                confidence -= 0.15
            if spec.unsupported_rules:
                confidence -= min(0.15, 0.03 * len(spec.unsupported_rules))
            if spec.ambiguities:
                confidence -= min(0.10, 0.02 * len(spec.ambiguities))
            confidence = max(0.10, min(0.99, confidence))

        review_required = (
            coverage < 1.0
            or confidence < 0.75
            or bool(spec.unsupported_rules)
            or duplicate_record_count > 1
            or not source_context_complete
        )

        rows.append(
            {
                "invoice_id": inv_id,
                "flagged": int(bool(errors)),
                "error_category": "|".join(errors),
                "expected_total_cents": int(expected),
                "billed_total_cents": int(header.invoice_total_cents),
                "confidence": round(confidence, 3),
                "coverage": round(coverage, 3),
                "review_required": bool(review_required),
                "duplicate_record_count": duplicate_record_count,
                "canonical_invoice_row_no": canonical_row_no,
                "source_context_complete": bool(source_context_complete),
            }
        )

    predictions = pd.DataFrame(rows)
    return predictions, ln
