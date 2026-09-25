from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable

from .models import ContractSpec, MultiplierRule, RatePeriod, ServiceRule, VolumeDiscountRule, VolumeTier


_TEXT_SUFFIXES = {".txt", ".md", ".json", ".html", ".xml", ".csv"}


def _extract_discount_section(text: str) -> str:
    """Return the most relevant Markdown/text section describing volume discounts.

    This intentionally uses generic headings/phrasing rather than hospital identifiers.
    If no dedicated section can be identified, the whole text is returned so explicit
    table headers can still be discovered.
    """
    lines = text.splitlines()
    starts: list[int] = []
    for i, line in enumerate(lines):
        low = line.strip().lower()
        if low.startswith("##") and (
            "cumulative volume discount" in low
            or low.endswith("discounts")
            or "volume discount" in low
        ):
            starts.append(i)

    if not starts:
        return text

    start = starts[0]
    end = len(lines)
    for j in range(start + 1, len(lines)):
        low = lines[j].strip().lower()
        if low.startswith("## ") and j > start:
            end = j
            break
    return "\n".join(lines[start:end])


def _scope_and_reset(section: str) -> tuple[str, str, bool]:
    low = section.lower()

    if re.search(r"\b(per|for each|for one)\s+(patient|member)\b", low) or "aggregated per patient" in low:
        scope = "patient_service"
        scope_explicit = True
    elif re.search(r"\b(per|for each)\s+invoice\b", low) or "aggregated per invoice" in low:
        scope = "invoice_service"
        scope_explicit = True
    elif (
        "aggregated across all patients" in low
        or "across all patients" in low
        or "whole term of this agreement" in low
        or "whole term of the agreement" in low
        or "across the agreement" in low
    ):
        scope = "contract_service"
        scope_explicit = True
    else:
        # Generic interpretation policy: if an explicit cumulative-Service rule does
        # not qualify the population by Patient or invoice, accumulate by Service for
        # the agreement. Preserve the uncertainty separately for human review.
        scope = "contract_service"
        scope_explicit = False

    reset_period = "calendar_year" if re.search(
        r"\b(calendar year|each year|per year|annually|annual reset)\b", low
    ) else "none"
    return scope, reset_period, scope_explicit


def _is_markdown_separator(line: str) -> bool:
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _parse_markdown_volume_table(section: str) -> dict[str, list[VolumeTier]]:
    """Parse explicit Markdown volume-discount tables generically.

    Expected columns contain Service, a cumulative/threshold column, and a discount
    percentage column. Service names and thresholds are read from the document; no
    hospital-specific names or rates are embedded here.
    """
    rows = [line.strip() for line in section.splitlines() if line.strip().startswith("|")]
    grouped: dict[str, list[VolumeTier]] = defaultdict(list)

    for i in range(len(rows) - 2):
        header = [c.strip().lower() for c in rows[i].strip("|").split("|")]
        if len(header) < 3:
            continue
        if "service" not in header[0]:
            continue
        if not any(token in header[1] for token in ("cumulative", "threshold", "utilisation", "utilization")):
            continue
        if "discount" not in header[2]:
            continue

        # Following row should be Markdown separator.
        if not _is_markdown_separator(rows[i + 1]):
            continue

        j = i + 2
        while j < len(rows):
            cells = [c.strip() for c in rows[j].strip("|").split("|")]
            if len(cells) < 3:
                break
            # Stop if another apparent header begins.
            if cells[0].lower() == "service":
                break

            service = cells[0]
            threshold_cell = cells[1]
            discount_cell = cells[2]

            threshold_matches = re.findall(r"\d+(?:\.\d+)?", threshold_cell.replace(",", ""))
            pct_matches = re.findall(r"\d+(?:\.\d+)?", discount_cell.replace(",", ""))
            if service and threshold_matches and pct_matches:
                threshold = float(threshold_matches[-1])
                pct = float(pct_matches[-1])
                multiplier = 1.0 - (pct / 100.0)
                grouped[service].append(
                    VolumeTier(
                        threshold_quantity=threshold,
                        multiplier=multiplier,
                        comparison="gt",
                    )
                )
            j += 1
        if grouped:
            break

    return grouped


def enrich_volume_discounts_from_texts(spec: ContractSpec, texts: Iterable[str]) -> ContractSpec:
    """Supplement *missing* explicit cumulative volume discounts from contract text.

    The function is generic and conservative:
    - existing extracted volume rules are never overwritten;
    - only explicit tables with service/threshold/discount columns are parsed;
    - scope/reset semantics are derived from wording, not hospital identity;
    - ambiguous population wording is retained in ``ambiguities`` for review.
    """
    result = spec.model_copy(deep=True)
    existing = {r.service_name for r in result.volume_discounts}

    for text in texts:
        section = _extract_discount_section(text)
        grouped = _parse_markdown_volume_table(section)
        if not grouped:
            continue

        scope, reset_period, scope_explicit = _scope_and_reset(section)
        added: list[str] = []
        for service_name, tiers in grouped.items():
            if service_name in existing:
                continue
            tiers = sorted(tiers, key=lambda t: t.threshold_quantity)
            result.volume_discounts.append(
                VolumeDiscountRule(
                    service_name=service_name,
                    tiers=tiers,
                    scope=scope,
                    reset_period=reset_period,
                    notes=(
                        "Explicit cumulative volume-discount table parsed from contract text; "
                        "applies to subsequent instances based on prior cumulative utilisation."
                    ),
                )
            )
            existing.add(service_name)
            added.append(service_name)

        if added and not scope_explicit:
            note = (
                "Cumulative volume-discount population was not explicitly qualified by Patient "
                "or invoice; interpreted as contract-wide cumulative utilisation by Service."
            )
            already_recorded = any(
                ("cumulative" in item.lower() or "volume" in item.lower())
                and ("scope" in item.lower() or "patient" in item.lower() or "aggregation" in item.lower())
                for item in result.ambiguities
            )
            if not already_recorded:
                result.ambiguities.append(note)

        if added:
            interpretation = (
                f"Recovered {len(added)} explicit cumulative volume-discount rule(s) from "
                "the contract table using generic scope/reset parsing."
            )
            if interpretation not in result.interpretation_notes:
                result.interpretation_notes.append(interpretation)

    return result



_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def _parse_english_date(value: str) -> str | None:
    """Parse a written English date such as ``1 January 2025`` to ISO form."""
    match = re.search(
        r"\b(\d{1,2})\s+("
        + "|".join(_MONTHS)
        + r")\s+(\d{4})\b",
        value,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    day = int(match.group(1))
    month = _MONTHS[match.group(2).lower()]
    year = int(match.group(3))
    return f"{year:04d}-{month:02d}-{day:02d}"


def _previous_iso_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        from datetime import date, timedelta

        year, month, day = (int(part) for part in value.split("-"))
        return (date(year, month, day) - timedelta(days=1)).isoformat()
    except Exception:
        return None


def _parse_money_cents(value: str) -> int | None:
    """Parse an explicit money cell to whole cents."""
    cleaned = value.strip()
    if not cleaned or cleaned in {"—", "-", "–", "n/a", "N/A"}:
        return None
    if "%" in cleaned:
        return None

    cleaned = re.sub(r"\b(?:GBP|USD|EUR|SAR)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("£", "").replace("$", "").replace("€", "").replace(",", "").strip()
    match = re.fullmatch(r"(-?\d+(?:\.\d{1,2})?)", cleaned)
    if not match:
        return None

    amount = float(match.group(1))
    if amount < 0:
        return None
    return int(round(amount * 100))


def _parse_daily_cap(value: str) -> tuple[float | None, str | None]:
    cleaned = value.strip()
    if not cleaned or cleaned.lower() in {"—", "-", "–", "none", "n/a"}:
        return None, None

    match = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(.*?)\s*$", cleaned)
    if not match:
        return None, None

    quantity = float(match.group(1))
    unit = match.group(2).strip() or None
    return quantity, unit


def _service_table_effective_from(context: str, contract_start: str | None) -> str | None:
    """Infer a later start date only when nearby wording states one explicitly."""
    low = context.lower()
    patterns = (
        r"(?:effective|takes effect)\s+(?:from|on)\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
        r"(?:on or after|from)\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
        r"become billable.*?(?:on or after|from)\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})",
    )
    for pattern in patterns:
        match = re.search(pattern, low, flags=re.IGNORECASE | re.DOTALL)
        if match:
            parsed = _parse_english_date(match.group(1))
            if parsed:
                return parsed
    return contract_start


def _rate_periods_from_table_row(
    header: list[str],
    cells: list[str],
    context: str,
    spec: ContractSpec,
) -> list[RatePeriod]:
    """Build rate periods from explicit rate columns in a service table."""
    lower_header = [h.strip().lower() for h in header]
    rate_indexes = [
        i
        for i, name in enumerate(lower_header)
        if "rate" in name and "unit" not in name and "bundled" not in name
    ]
    if not rate_indexes:
        return []

    periods: list[RatePeriod] = []

    if len(rate_indexes) == 1:
        idx = rate_indexes[0]
        cents = _parse_money_cents(cells[idx])
        if cents is None:
            return []
        start = _service_table_effective_from(context, spec.effective_from)
        periods.append(
            RatePeriod(
                rate_cents=cents,
                effective_from=start,
                effective_to=spec.effective_to,
                source_note="Explicit service-rate table recovered from contract text",
                confidence=1.0,
            )
        )
        return periods

    for idx in rate_indexes:
        cents = _parse_money_cents(cells[idx])
        if cents is None:
            continue
        label = header[idx]
        start = spec.effective_from
        end = spec.effective_to

        from_match = re.search(r"\bfrom\s+(.+)$", label, flags=re.IGNORECASE)
        to_match = re.search(r"\bto\s+(.+)$", label, flags=re.IGNORECASE)

        if from_match:
            parsed = _parse_english_date(from_match.group(1))
            if parsed:
                start = parsed
        if to_match:
            parsed = _parse_english_date(to_match.group(1))
            if parsed:
                end = parsed

        periods.append(
            RatePeriod(
                rate_cents=cents,
                effective_from=start,
                effective_to=end,
                source_note="Explicit multi-period service-rate table recovered from contract text",
                confidence=1.0,
            )
        )

    starts = sorted(
        [p.effective_from for p in periods if p.effective_from and p.effective_from != spec.effective_from]
    )
    if starts:
        first_later = starts[0]
        prior_end = _previous_iso_date(first_later)
        if prior_end:
            for period in periods:
                if period.effective_from == spec.effective_from and period.effective_to == spec.effective_to:
                    period.effective_to = prior_end

    return periods


def _parse_explicit_service_rate_tables(text: str, spec: ContractSpec) -> list[ServiceRule]:
    """Parse explicit Markdown service/rate tables conservatively.

    Accepted tables must contain a Service column, a Unit basis column and at
    least one Rate column. Premium, discount, bundle, multiplier and exclusion
    tables therefore do not qualify.
    """
    lines = text.splitlines()
    recovered: list[ServiceRule] = []

    i = 0
    while i < len(lines) - 2:
        row = lines[i].strip()
        if not row.startswith("|"):
            i += 1
            continue

        header = [c.strip() for c in row.strip("|").split("|")]
        lower_header = [c.lower() for c in header]
        if not header or "service" not in lower_header[0]:
            i += 1
            continue
        if not _is_markdown_separator(lines[i + 1].strip()):
            i += 1
            continue

        unit_indexes = [idx for idx, name in enumerate(lower_header) if "unit basis" in name]
        rate_indexes = [
            idx
            for idx, name in enumerate(lower_header)
            if "rate" in name and "unit" not in name and "bundled" not in name
        ]
        if len(unit_indexes) != 1 or not rate_indexes:
            i += 1
            continue

        if any("service b" in name or "service a" in name for name in lower_header):
            i += 1
            continue

        unit_idx = unit_indexes[0]
        cap_idx = next(
            (idx for idx, name in enumerate(lower_header) if "daily cap" in name or "maximum units" in name),
            None,
        )
        context = _table_context(lines, i, lookback=12)

        j = i + 2
        while j < len(lines):
            data_row = lines[j].strip()
            if not data_row.startswith("|"):
                break
            if _is_markdown_separator(data_row):
                j += 1
                continue

            cells = [c.strip() for c in data_row.strip("|").split("|")]
            if len(cells) != len(header):
                break

            service_name = cells[0].strip()
            unit_basis = cells[unit_idx].strip()
            if not service_name or not unit_basis or service_name.lower() == "service":
                break

            rate_periods = _rate_periods_from_table_row(header, cells, context, spec)
            if not rate_periods:
                j += 1
                continue

            daily_cap = None
            daily_cap_unit = None
            if cap_idx is not None:
                daily_cap, daily_cap_unit = _parse_daily_cap(cells[cap_idx])

            recovered.append(
                ServiceRule(
                    service_name=service_name,
                    unit_basis=unit_basis,
                    rates=rate_periods,
                    aliases=[],
                    daily_cap=daily_cap,
                    daily_cap_unit=daily_cap_unit,
                    notes="Recovered from an explicit service-rate table in the contract.",
                    confidence=1.0,
                )
            )
            j += 1

        i = max(j, i + 1)

    return recovered


def enrich_service_tables_from_texts(spec: ContractSpec, texts: Iterable[str]) -> ContractSpec:
    """Recover service rows omitted by structured AI extraction.

    Existing services are never overwritten. A service is added only when an
    explicit Markdown table provides its name, unit basis and rate.
    """
    result = spec.model_copy(deep=True)
    existing = {service.service_name for service in result.services}
    added_names: list[str] = []

    for text in texts:
        for service in _parse_explicit_service_rate_tables(text, result):
            if service.service_name in existing:
                continue
            result.services.append(service)
            existing.add(service.service_name)
            added_names.append(service.service_name)

    if added_names:
        interpretation = (
            f"Recovered {len(added_names)} missing service-rate row(s) from explicit "
            "contract tables using deterministic table parsing."
        )
        if interpretation not in result.interpretation_notes:
            result.interpretation_notes.append(interpretation)

    return result

def _table_context(lines: list[str], header_index: int, lookback: int = 8) -> str:
    start = max(0, header_index - lookback)
    return "\n".join(lines[start:header_index]).lower()


def _classify_multiplier_table(header: list[str], context: str) -> str | None:
    """Classify an explicit service multiplier table as facility or plan-tier.

    Classification uses table headings/context and generic column-name patterns only;
    it never relies on hospital/provider identity or specific service names.
    """
    keys = [h.strip() for h in header[1:] if h.strip()]
    low_context = context.lower()
    low_keys = [k.lower() for k in keys]

    # Check plan/tier wording first because a plan-table description may mention
    # that it is applied after the facility multiplier.
    if "plan-tier multiplier" in low_context or "plan tier multiplier" in low_context or "plan multipliers" in low_context:
        return "plan"
    if "facility multiplier" in low_context or "facility multipliers" in low_context:
        return "facility"

    # Generic fallback when column labels themselves carry the semantics.
    if any("facility" in k for k in low_keys):
        return "facility"
    if any("tier" in k or "plan" in k for k in low_keys):
        return "plan"

    return None


def _parse_explicit_multiplier_tables(text: str) -> dict[str, list[MultiplierRule]]:
    """Parse explicit Markdown service-by-key multiplier tables.

    A table is accepted only when:
    - the first column is a Service column;
    - following cells are numeric positive multipliers;
    - nearby text or generic column naming identifies it as a facility or plan table.

    This deliberately avoids parsing arbitrary numeric tables.
    """
    lines = text.splitlines()
    parsed: dict[str, list[MultiplierRule]] = {"facility": [], "plan": []}

    i = 0
    while i < len(lines) - 2:
        line = lines[i].strip()
        if not line.startswith("|"):
            i += 1
            continue

        header = [c.strip() for c in line.strip("|").split("|")]
        if len(header) < 3 or "service" not in header[0].lower():
            i += 1
            continue
        if not _is_markdown_separator(lines[i + 1].strip()):
            i += 1
            continue

        kind = _classify_multiplier_table(header, _table_context(lines, i))
        if kind is None:
            i += 1
            continue

        keys = header[1:]
        j = i + 2
        table_rules: list[MultiplierRule] = []
        while j < len(lines):
            row = lines[j].strip()
            if not row.startswith("|"):
                break
            if _is_markdown_separator(row):
                j += 1
                continue

            cells = [c.strip() for c in row.strip("|").split("|")]
            if len(cells) != len(header):
                break
            if cells[0].lower() == "service":
                break

            service_name = cells[0]
            if not service_name:
                break

            values: list[float] = []
            valid = True
            for cell in cells[1:]:
                cleaned = cell.replace(",", "").strip()
                try:
                    value = float(cleaned)
                except ValueError:
                    valid = False
                    break
                if value <= 0:
                    valid = False
                    break
                values.append(value)

            if not valid:
                break

            for key, value in zip(keys, values):
                table_rules.append(
                    MultiplierRule(
                        service_name=service_name,
                        key=key,
                        multiplier=value,
                    )
                )
            j += 1

        if table_rules:
            parsed[kind].extend(table_rules)
            i = j
        else:
            i += 1

    return parsed


def _remove_resolved_multiplier_unsupported_rules(
    unsupported_rules: list[str],
    recovered_facility: bool,
    recovered_plan: bool,
) -> list[str]:
    """Remove only stale 'table not expanded' notes that enrichment has resolved."""
    cleaned: list[str] = []
    for item in unsupported_rules:
        low = item.lower()
        mentions_facility = "facility" in low and "multiplier" in low
        mentions_plan = ("plan" in low or "tier" in low) and "multiplier" in low
        omission_wording = any(
            phrase in low
            for phrase in (
                "not expanded",
                "have not been expanded",
                "not fully expanded",
                "not represented",
                "not fully represented",
                "not fully encoded",
                "omitted",
                "missing from",
            )
        )

        resolved = omission_wording and (
            (mentions_facility and mentions_plan and recovered_facility and recovered_plan)
            or (mentions_facility and not mentions_plan and recovered_facility)
            or (mentions_plan and not mentions_facility and recovered_plan)
        )
        if not resolved:
            cleaned.append(item)
    return cleaned


def enrich_multiplier_tables_from_texts(spec: ContractSpec, texts: Iterable[str]) -> ContractSpec:
    """Recover missing explicit facility/plan multiplier tables from contract text.

    This is a generic deterministic fallback for large tables that a structured LLM
    response may intentionally summarize instead of expanding. Existing model-extracted
    rules always win: the function only adds missing ``(service_name, key)`` pairs.
    """
    text_list = list(texts)

    # Recover explicit service-rate rows first. If a service was omitted by the
    # structured model, downstream service mapping should still see it.
    result = enrich_service_tables_from_texts(spec, text_list)
    service_names = {service.service_name for service in result.services}

    existing_facility = {(r.service_name, r.key) for r in result.facility_multipliers}
    existing_plan = {(r.service_name, r.key.upper()) for r in result.plan_multipliers}

    added_facility = 0
    added_plan = 0

    for text in text_list:
        parsed = _parse_explicit_multiplier_tables(text)

        for rule in parsed["facility"]:
            # Use the extracted service catalogue as a safety boundary. If the model did
            # not recognize the service itself, do not silently introduce a new service.
            if rule.service_name not in service_names:
                continue
            pair = (rule.service_name, rule.key)
            if pair in existing_facility:
                continue
            result.facility_multipliers.append(rule)
            existing_facility.add(pair)
            added_facility += 1

        for rule in parsed["plan"]:
            if rule.service_name not in service_names:
                continue
            pair = (rule.service_name, rule.key.upper())
            if pair in existing_plan:
                continue
            result.plan_multipliers.append(rule)
            existing_plan.add(pair)
            added_plan += 1

    recovered_facility = added_facility > 0
    recovered_plan = added_plan > 0

    if recovered_facility or recovered_plan:
        result.unsupported_rules = _remove_resolved_multiplier_unsupported_rules(
            result.unsupported_rules,
            recovered_facility=recovered_facility,
            recovered_plan=recovered_plan,
        )

        parts: list[str] = []
        if recovered_facility:
            parts.append(f"{added_facility} facility multiplier rule(s)")
        if recovered_plan:
            parts.append(f"{added_plan} plan-tier multiplier rule(s)")
        interpretation = (
            "Recovered " + " and ".join(parts) +
            " from explicit contract multiplier tables using deterministic table parsing."
        )
        if interpretation not in result.interpretation_notes:
            result.interpretation_notes.append(interpretation)

    return result


def text_sources_from_descriptors(descriptors: Iterable[tuple[str, bytes]]) -> list[str]:
    texts: list[str] = []
    for name, data in descriptors:
        suffix = __import__("pathlib").Path(name).suffix.lower()
        if suffix in _TEXT_SUFFIXES:
            texts.append(data.decode("utf-8", errors="replace"))
    return texts
