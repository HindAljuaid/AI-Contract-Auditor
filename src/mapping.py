from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

import pandas as pd
from rapidfuzz import fuzz, process

from .ai import AIServiceError, resolve_ambiguous_mappings
from .models import ContractSpec


ABBREVIATIONS = {
    "adv": "advanced",
    "amb": "ambulatory",
    "asst": "assisted",
    "compr": "comprehensive",
    "cont": "continuous",
    "emer": "emergency",
    "emerg": "emergency",
    "ext": "extended",
    "foc": "focused",
    "intens": "intensive",
    "interm": "intermittent",
    "inpt": "inpatient",
    "outpt": "outpatient",
    "postop": "postoperative",
    "preop": "preoperative",
    "rtn": "routine",
    "spec": "specialist",
    "std": "standard",
    "supp": "support",
    "svc": "service",
    "transf": "transfusion",
    "transp": "transport",
    "recov": "recovery",
    "occ": "occupancy",
    "wnd": "wound",
    "rm": "room",
    "prog": "programme",
    "sess": "session",
    "physio": "physiotherapy",
    "rehab": "rehabilitation",
    "nutr": "nutritional",
    "frac": "fraction",
    "rad": "radiotherapy",
    "radiother": "radiotherapy",
    "immun": "immunologic",
    "neuro": "neurological",
    "ophth": "ophthalmic",
    "ortho": "orthopaedic",
    "pulm": "pulmonary",
    "ger": "geriatric",
    "urol": "urologic",
    "musk": "musculoskeletal",
    "msk": "musculoskeletal",
    "derm": "dermatologic",
    "card": "cardiac",
    "infect": "infectious",
    "psych": "psychiatric",
    "endo": "endocrine",
    "gi": "gastrointestinal",
    "ent": "otolaryngologic",
    "cs": "case conference",
    "pnl": "panel",
    "anly": "analysis",
    "diag": "diagnostic",
    "img": "imaging",
    "haem": "haematology",
    "metab": "metabolic",
    "nurs": "nursing",
    "biop": "biopsy",
    "vent": "ventilation",
    "disp": "dispensing",
    "admin": "administration",
    "consult": "consultation",
    "conf": "conference",
    "proc": "procedure",
    "spcm": "specimen",
    "monit": "monitoring",
    "inf": "infusion",
    "endosc": "endoscopic",
    "lab": "laboratory",
    "pall": "palliative",
    "isol": "isolation",
    "hep": "hepatic",
    "ren": "renal",
    "uro": "urologic",
    "gastro": "gastrointestinal",
    "elect": "elective",
    "electiv": "elective",
    "paed": "paediatric",
    "paedi": "paediatric",
    "peds": "paediatric",
    "onc": "oncology",
    "vasc": "vascular",
    "hm": "home",
    "vst": "visit",
    "plng": "planning",
    "dial": "dialysis",
    "crit": "critical",
}

CODE_RE = re.compile(r"(/NG-\d+)$", re.I)


def extract_service_code(text: object) -> str | None:
    if pd.isna(text):
        return None
    m = CODE_RE.search(str(text).strip())
    return m.group(1).upper() if m else None


def normalize_text(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).lower().strip()
    text = re.sub(r"/ng-\d+", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    words = [ABBREVIATIONS.get(w, w) for w in text.split()]
    return " ".join(words)


def normalize_basis(value: object) -> str:
    if pd.isna(value):
        return ""
    text = re.sub(r"[^a-z0-9]+", "_", str(value).lower().strip()).strip("_")
    aliases = {
        "day": "per_day_of_service",
        "days": "per_day_of_service",
        "per_day": "per_day_of_service",
        "per_day_service": "per_day_of_service",
        "night": "per_night_of_occupancy",
        "nights": "per_night_of_occupancy",
        "per_night": "per_night_of_occupancy",
        "item": "per_item_supplied",
        "each": "per_item_supplied",
        "per_item": "per_item_supplied",
        "unit": "per_unit_dispensed",
        "per_unit": "per_unit_dispensed",
        "procedure": "per_procedure",
        "visit": "per_visit",
        "hour": "per_hour",
        "hr": "per_hour",
        "test": "per_test",
        "session": "per_session",
        "fraction": "per_fraction",
    }
    return aliases.get(text, text)


@dataclass
class Candidate:
    service_name: str
    score: float


def service_alias_table(spec: ContractSpec) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for service in spec.services:
        values = [service.service_name, *service.aliases]
        for value in values:
            norm = normalize_text(value)
            if norm:
                aliases[norm] = service.service_name
    return aliases


def _candidate_list(description: str, aliases: dict[str, str], limit: int = 5) -> list[Candidate]:
    if not description or not aliases:
        return []

    # Candidate strings are normalized aliases. Collapse duplicate services by
    # keeping their best alias score.
    raw = process.extract(
        description,
        list(aliases.keys()),
        scorer=fuzz.WRatio,
        limit=min(max(limit * 4, 12), len(aliases)),
    )
    best: dict[str, float] = {}
    for alias, score, _ in raw:
        service = aliases[alias]
        token_score = fuzz.token_set_ratio(description, alias)
        blended = 0.55 * float(score) + 0.45 * float(token_score)
        best[service] = max(best.get(service, 0.0), blended)

    ranked = sorted(best.items(), key=lambda x: x[1], reverse=True)[:limit]
    return [Candidate(service_name=s, score=sc) for s, sc in ranked]


def _initial_mapping(unique_descriptions: list[str], spec: ContractSpec) -> pd.DataFrame:
    aliases = service_alias_table(spec)
    rows = []

    for idx, original in enumerate(unique_descriptions):
        norm = normalize_text(original)
        candidates = _candidate_list(norm, aliases, limit=5)

        exact_service = aliases.get(norm)
        if exact_service:
            rows.append(
                {
                    "item_id": idx,
                    "description": original,
                    "normalized_description": norm,
                    "service_name": exact_service,
                    "mapping_method": "exact",
                    "mapping_confidence": 0.995,
                    "top_score": 100.0,
                    "score_gap": 100.0,
                    "candidates": candidates,
                }
            )
            continue

        if not candidates:
            rows.append(
                {
                    "item_id": idx,
                    "description": original,
                    "normalized_description": norm,
                    "service_name": None,
                    "mapping_method": "unmapped",
                    "mapping_confidence": 0.20,
                    "top_score": 0.0,
                    "score_gap": 0.0,
                    "candidates": [],
                }
            )
            continue

        top = candidates[0]
        second = candidates[1].score if len(candidates) > 1 else 0.0
        gap = top.score - second

        if top.score >= 95 and gap >= 6:
            conf, method, selected = 0.96, "fuzzy_high", top.service_name
        elif top.score >= 89 and gap >= 10:
            conf, method, selected = 0.89, "fuzzy_medium", top.service_name
        else:
            conf, method, selected = 0.52, "review", None

        rows.append(
            {
                "item_id": idx,
                "description": original,
                "normalized_description": norm,
                "service_name": selected,
                "mapping_method": method,
                "mapping_confidence": conf,
                "top_score": round(top.score, 3),
                "score_gap": round(gap, 3),
                "candidates": candidates,
            }
        )

    return pd.DataFrame(rows)


def _propagate_stable_codes(lines: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
    """Use repeated billing codes only when high-confidence rows agree on one service."""
    if "description" not in lines.columns or mapping.empty:
        return mapping

    desc_to_row = mapping.set_index("description")
    tmp = lines[["description"]].drop_duplicates().copy()
    tmp["service_code"] = tmp["description"].map(extract_service_code)
    tmp = tmp.join(desc_to_row[["service_name", "mapping_confidence"]], on="description")

    trusted = tmp[
        tmp["service_code"].notna()
        & tmp["service_name"].notna()
        & tmp["mapping_confidence"].ge(0.88)
    ]
    if trusted.empty:
        return mapping

    stable: dict[str, str] = {}
    for code, grp in trusted.groupby("service_code"):
        services = grp["service_name"].dropna().unique().tolist()
        if len(services) == 1:
            stable[code] = services[0]

    if not stable:
        return mapping

    out = mapping.copy()
    code_by_desc = {
        d: extract_service_code(d) for d in out["description"].tolist()
    }
    for idx, row in out.iterrows():
        if row["service_name"] is not None and row["mapping_confidence"] >= 0.88:
            continue
        code = code_by_desc.get(row["description"])
        if code in stable:
            out.at[idx, "service_name"] = stable[code]
            out.at[idx, "mapping_method"] = "stable_code"
            out.at[idx, "mapping_confidence"] = 0.93
    return out


def map_descriptions(
    lines: pd.DataFrame,
    spec: ContractSpec,
    *,
    api_key: str | None = None,
    model: str = "gpt-5.6-terra",
    use_ai_for_ambiguous: bool = True,
    ai_batch_size: int = 40,
    max_ai_items: int = 240,
) -> pd.DataFrame:
    """Map each unique billing description to a contracted service."""
    unique_descriptions = (
        lines["description"].astype(str).drop_duplicates().tolist()
    )
    mapping = _initial_mapping(unique_descriptions, spec)
    mapping = _propagate_stable_codes(lines, mapping)

    if not use_ai_for_ambiguous or not api_key:
        return mapping.drop(columns=["candidates"])

    review = mapping[
        mapping["service_name"].isna()
        | mapping["mapping_confidence"].lt(0.80)
    ].copy()

    # Spend API calls where they have the most impact: frequent billing
    # descriptions first. Remaining ambiguous descriptions stay unresolved and
    # therefore lower invoice confidence instead of being guessed.
    desc_counts = lines["description"].astype(str).value_counts()
    review["frequency"] = review["description"].map(desc_counts).fillna(0)
    review = review.sort_values(["frequency", "top_score"], ascending=[False, False])
    if max_ai_items > 0:
        review = review.head(max_ai_items)

    if review.empty:
        return mapping.drop(columns=["candidates"])

    service_names = {s.service_name for s in spec.services}

    for start in range(0, len(review), ai_batch_size):
        chunk = review.iloc[start : start + ai_batch_size]
        payload = []
        for row in chunk.itertuples(index=False):
            payload.append(
                {
                    "item_id": int(row.item_id),
                    "description": row.description,
                    "candidates": [
                        {
                            "service_name": c.service_name,
                            "local_similarity_score": round(c.score, 2),
                        }
                        for c in row.candidates
                    ],
                }
            )

        try:
            decisions = resolve_ambiguous_mappings(
                payload,
                api_key=api_key,
                model=model,
            )
        except AIServiceError as exc:
            # The deterministic/local mapping is still useful when the API is
            # unavailable. Leave ambiguous rows unresolved instead of failing
            # the entire audit.
            mapping.attrs["ai_warning"] = str(exc)
            break

        by_id = {m.item_id: m for m in decisions.mappings}
        for idx, row in mapping.iterrows():
            decision = by_id.get(int(row["item_id"]))
            if decision is None:
                continue
            selected = decision.selected_service
            if selected is not None and selected not in service_names:
                continue
            if selected is not None and decision.confidence >= 0.70:
                mapping.at[idx, "service_name"] = selected
                mapping.at[idx, "mapping_method"] = "ai_candidate_selection"
                mapping.at[idx, "mapping_confidence"] = min(0.95, float(decision.confidence))
            elif selected is None:
                mapping.at[idx, "mapping_method"] = "ai_unresolved"
                mapping.at[idx, "mapping_confidence"] = min(
                    float(mapping.at[idx, "mapping_confidence"]), 0.55
                )

    return mapping.drop(columns=["candidates"])
