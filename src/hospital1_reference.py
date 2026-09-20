#!/usr/bin/env python3
"""
Hospital 1 insurance-auditing solution
======================================

Standalone cleaned version of the Hospital 1 notebook.

What is kept:
- service normalization and conservative text/code mapping
- Hospital 1 contract rates and deterministic pricing rules
- all 18 error-category detectors
- the final fixes for:
    * wrong_unit_basis
    * unit_price_mismatch
    * premium_omitted
- Hospital 1 label evaluation
- compact CSV outputs

What is intentionally removed:
- exploratory display/print cells
- repeated intermediate implementations
- one-off debugging cells
- plotting
- label-specific detector logic

Labels are used only in evaluate(), never in the detectors.

Run from the repository root:
    python hospital1_final.py --data-dir .

Or on Kaggle:
    python hospital1_final.py \
      --data-dir /kaggle/input/datasets/hindaljuaid/insurance-auditing-dataset/insurance_auditing-main
"""

from __future__ import annotations

import argparse
import re
from decimal import Decimal, ROUND_HALF_UP
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import pandas as pd


# =============================================================================
# 1. Hospital 1 contract
# =============================================================================

CONTRACT_START = pd.Timestamp("2024-01-01")
CONTRACT_END = pd.Timestamp("2025-12-31")
EXPECTED_CONTRACT_NUMBER = "INS-H1-2024-0417"

# Two H1 billing codes omit the contract modifier in their free-text label.
# H1 is the designated calibration set, so we resolve these stable billing-code
# aliases explicitly rather than forcing an ambiguous lexical match.
CODE_SERVICE_OVERRIDES = {
    "/NG-8199": "Continuous Psychiatric Rehabilitation Programme",
    "/NG-2366": "Intensive Geriatric Nutritional Support",
}

CONTRACT_ROWS = [('Advanced Cardiac Recovery Room Occupancy', 'per_hour', 20000),
 ('Advanced Haematology Physiotherapy Session', 'per_hour', 10150),
 ('Advanced Infectious Critical Care Occupancy', 'per_day_of_service', 70925),
 ('Advanced Metabolic Anaesthesia Administration', 'per_hour', 9200),
 ('Advanced Metabolic Nursing Observation', 'per_day_of_service', 130125),
 ('Advanced Neurological Consultation', 'per_visit', 14125),
 ('Advanced Rheumatologic Laboratory Panel', 'per_test', 14775),
 ('Ambulatory Cardiac Home Visit', 'per_visit', 28425),
 ('Ambulatory Immunologic Endoscopic Procedure', 'per_procedure', 607900),
 ('Ambulatory Immunologic Ward Bed Occupancy', 'per_day_of_service', 87250),
 ('Ambulatory Infectious Home Visit', 'per_visit', 8225),
 ('Ambulatory Musculoskeletal Ward Bed Occupancy', 'per_night_of_occupancy', 154575),
 ('Ambulatory Ophthalmic Case Conference', 'per_visit', 16925),
 ('Ambulatory Ophthalmic Dialysis Session', 'per_procedure', 479825),
 ('Ambulatory Psychiatric Dialysis Session', 'per_procedure', 355550),
 ('Ambulatory Pulmonary Recovery Room Occupancy', 'per_night_of_occupancy', 112825),
 ('Ambulatory Urologic Imaging Interpretation', 'per_test', 42700),
 ('Assisted Gastrointestinal Infusion Therapy', 'per_hour', 8925),
 ('Assisted Geriatric Infusion Therapy', 'per_unit_dispensed', 7825),
 ('Assisted Infectious Discharge Planning', 'per_hour', 8875),
 ('Assisted Pulmonary Theatre Time', 'per_hour', 6700),
 ('Assisted Urologic Home Visit', 'per_visit', 13625),
 ('Bedside Otolaryngologic Recovery Room Occupancy', 'per_night_of_occupancy', 150450),
 ('Bedside Psychiatric Dialysis Session', 'per_visit', 20575),
 ('Bedside Pulmonary Biopsy Procedure', 'per_procedure', 316825),
 ('Comprehensive Infectious Nursing Observation', 'per_day_of_service', 169825),
 ('Comprehensive Oncology Nursing Observation', 'per_hour', 8475),
 ('Comprehensive Otolaryngologic Rehabilitation Programme', 'per_visit', 27025),
 ('Comprehensive Otolaryngologic Theatre Time', 'per_hour', 32100),
 ('Comprehensive Psychiatric Transfusion Service', 'per_procedure', 383650),
 ('Comprehensive Urologic Transport Service', 'per_visit', 42750),
 ('Continuous Cardiac Nursing Observation', 'per_hour', 9875),
 ('Continuous Immunologic Theatre Time', 'per_hour', 20975),
 ('Continuous Musculoskeletal Wound Care', 'per_day_of_service', 36800),
 ('Continuous Obstetric Rehabilitation Programme', 'per_day_of_service', 112400),
 ('Continuous Otolaryngologic Telemetry Monitoring', 'per_day_of_service', 111975),
 ('Continuous Psychiatric Rehabilitation Programme', 'per_visit', 20300),
 ('Continuous Pulmonary Wound Care', 'per_day_of_service', 144900),
 ('Continuous Vascular Pharmaceutical Dispensing', 'per_unit_dispensed', 6750),
 ('Elective Cardiac Nutritional Support', 'per_day_of_service', 158625),
 ('Elective Pulmonary Nutritional Support', 'per_unit_dispensed', 7450),
 ('Emergency Dermatologic Case Conference', 'per_hour', 3775),
 ('Emergency Orthopaedic Consultation', 'per_procedure', 418900),
 ('Emergency Orthopaedic Rehabilitation Programme', 'per_visit', 28950),
 ('Emergency Renal Radiotherapy Fraction', 'per_item_supplied', 11000),
 ('Extended Geriatric Wound Care', 'per_item_supplied', 10100),
 ('Extended Metabolic Isolation Room Occupancy', 'per_night_of_occupancy', 87300),
 ('Extended Palliative Laboratory Panel', 'per_test', 17850),
 ('Extended Renal Transport Service', 'per_item_supplied', 25650),
 ('Extended Vascular Rehabilitation Programme', 'per_day_of_service', 65400),
 ('Focused Immunologic Physiotherapy Session', 'per_hour', 3300),
 ('Focused Orthopaedic Transport Service', 'per_visit', 42100),
 ('Focused Otolaryngologic Wound Care', 'per_visit', 24725),
 ('Inpatient Endocrine Dialysis Session', 'per_procedure', 81750),
 ('Inpatient Hepatic Physiotherapy Session', 'per_visit', 42600),
 ('Inpatient Musculoskeletal Ward Bed Occupancy', 'per_day_of_service', 35625),
 ('Inpatient Ophthalmic Radiotherapy Fraction', 'per_item_supplied', 25300),
 ('Inpatient Ophthalmic Transport Service', 'per_item_supplied', 4800),
 ('Inpatient Palliative Isolation Room Occupancy', 'per_night_of_occupancy', 179600),
 ('Inpatient Palliative Specimen Analysis', 'per_item_supplied', 29725),
 ('Inpatient Renal Radiotherapy Fraction', 'per_procedure', 455300),
 ('Inpatient Vascular Diagnostic Imaging', 'per_item_supplied', 12725),
 ('Intensive Gastrointestinal Isolation Room Occupancy', 'per_night_of_occupancy', 160725),
 ('Intensive Geriatric Nutritional Support', 'per_unit_dispensed', 4275),
 ('Intensive Ophthalmic Case Conference', 'per_hour', 21875),
 ('Intermittent Dermatologic Transfusion Service', 'per_procedure', 243150),
 ('Intermittent Neurological Nutritional Support', 'per_day_of_service', 50275),
 ('Intermittent Pulmonary Rehabilitation Programme', 'per_visit', 13450),
 ('Intermittent Rheumatologic Diagnostic Imaging', 'per_procedure', 197700),
 ('Outpatient Immunologic Consultation', 'per_procedure', 279225),
 ('Outpatient Metabolic Radiotherapy Fraction', 'per_item_supplied', 22775),
 ('Postoperative Metabolic Critical Care Occupancy', 'per_night_of_occupancy', 59700),
 ('Postoperative Obstetric Isolation Room Occupancy', 'per_day_of_service', 43525),
 ('Postoperative Ophthalmic Radiotherapy Fraction', 'per_procedure', 413325),
 ('Postoperative Pulmonary Wound Care', 'per_visit', 18050),
 ('Preoperative Endocrine Physiotherapy Session', 'per_visit', 29975),
 ('Preoperative Geriatric Ventilation Support', 'per_hour', 6875),
 ('Preoperative Immunologic Endoscopic Procedure', 'per_procedure', 151975),
 ('Preoperative Oncology Consultation', 'per_visit', 42125),
 ('Preoperative Otolaryngologic Sterilisation Service', 'per_procedure', 134725),
 ('Preoperative Renal Wound Care', 'per_visit', 40325),
 ('Preoperative Vascular Diagnostic Imaging', 'per_procedure', 396725),
 ('Routine Cardiac Specimen Analysis', 'per_item_supplied', 23350),
 ('Routine Dermatologic Transfusion Service', 'per_unit_dispensed', 5325),
 ('Routine Gastrointestinal Transfusion Service', 'per_procedure', 341525),
 ('Routine Haematology Infusion Therapy', 'per_hour', 10200),
 ('Routine Immunologic Ward Bed Occupancy', 'per_night_of_occupancy', 215875),
 ('Routine Infectious Critical Care Occupancy', 'per_night_of_occupancy', 58375),
 ('Routine Oncology Discharge Planning', 'per_visit', 29050),
 ('Routine Palliative Critical Care Occupancy', 'per_night_of_occupancy', 96975),
 ('Routine Psychiatric Rehabilitation Programme', 'per_day_of_service', 72500),
 ('Routine Urologic Biopsy Procedure', 'per_procedure', 226950),
 ('Specialist Dermatologic Transport Service', 'per_visit', 43575),
 ('Specialist Hepatic Physiotherapy Session', 'per_hour', 5350),
 ('Specialist Neurological Recovery Room Occupancy', 'per_hour', 15400),
 ('Specialist Otolaryngologic Pharmaceutical Dispensing', 'per_unit_dispensed', 1425),
 ('Specialist Otolaryngologic Theatre Time', 'per_hour', 8025),
 ('Specialist Paediatric Biopsy Procedure', 'per_item_supplied', 257325),
 ('Standard Endocrine Dialysis Session', 'per_visit', 37600),
 ('Standard Endocrine Endoscopic Procedure', 'per_procedure', 124450),
 ('Standard Geriatric Nutritional Support', 'per_day_of_service', 42475),
 ('Standard Otolaryngologic Radiotherapy Fraction', 'per_item_supplied', 25250),
 ('Standard Paediatric Biopsy Procedure', 'per_item_supplied', 16100),
 ('Standard Psychiatric Endoscopic Procedure', 'per_procedure', 242225),
 ('Standard Pulmonary Dialysis Session', 'per_visit', 43175),
 ('Supervised Musculoskeletal Dialysis Session', 'per_visit', 35150),
 ('Supervised Otolaryngologic Sterilisation Service', 'per_item_supplied', 24200),
 ('Supervised Renal Isolation Room Occupancy', 'per_night_of_occupancy', 164500)]

BUNDLE_RULES = {('Advanced Cardiac Recovery Room Occupancy', 'Routine Cardiac Specimen Analysis'): {'rate_a': 16400,
                                                                                     'rate_b': 19150},
 ('Extended Palliative Laboratory Panel', 'Inpatient Ophthalmic Radiotherapy Fraction'): {'rate_a': 15175,
                                                                                          'rate_b': 21500},
 ('Inpatient Hepatic Physiotherapy Session', 'Specialist Otolaryngologic Theatre Time'): {'rate_a': 37500,
                                                                                          'rate_b': 7050}}

PREMIUM_RULES = {'Ambulatory Ophthalmic Case Conference': {'threshold': 6, 'rate': Decimal('1.20')},
 'Ambulatory Ophthalmic Dialysis Session': {'threshold': 10, 'rate': Decimal('1.20')},
 'Continuous Musculoskeletal Wound Care': {'threshold': 8, 'rate': Decimal('1.40')},
 'Emergency Dermatologic Case Conference': {'threshold': 10, 'rate': Decimal('1.40')},
 'Preoperative Geriatric Ventilation Support': {'threshold': 8, 'rate': Decimal('1.20')},
 'Preoperative Renal Wound Care': {'threshold': 8, 'rate': Decimal('1.25')},
 'Routine Psychiatric Rehabilitation Programme': {'threshold': 8, 'rate': Decimal('1.25')},
 'Specialist Neurological Recovery Room Occupancy': {'threshold': 8, 'rate': Decimal('1.30')},
 'Standard Pulmonary Dialysis Session': {'threshold': 8, 'rate': Decimal('1.25')}}

WEEKEND_UPLIFT_RULES = {'Advanced Neurological Consultation': Decimal('1.20'),
 'Assisted Geriatric Infusion Therapy': Decimal('1.12'),
 'Assisted Infectious Discharge Planning': Decimal('1.12'),
 'Emergency Renal Radiotherapy Fraction': Decimal('1.20'),
 'Focused Orthopaedic Transport Service': Decimal('1.10'),
 'Specialist Dermatologic Transport Service': Decimal('1.12'),
 'Supervised Musculoskeletal Dialysis Session': Decimal('1.12')}

VOLUME_DISCOUNT_RULES = {'Ambulatory Pulmonary Recovery Room Occupancy': [{'threshold': 60, 'rate': Decimal('0.90')}],
 'Comprehensive Infectious Nursing Observation': [{'threshold': 240, 'rate': Decimal('0.75')},
                                                  {'threshold': 80, 'rate': Decimal('0.90')}],
 'Extended Geriatric Wound Care': [{'threshold': 60, 'rate': Decimal('0.85')}],
 'Intensive Gastrointestinal Isolation Room Occupancy': [{'threshold': 180, 'rate': Decimal('0.70')},
                                                         {'threshold': 60, 'rate': Decimal('0.88')}],
 'Intermittent Pulmonary Rehabilitation Programme': [{'threshold': 120, 'rate': Decimal('0.90')}],
 'Preoperative Immunologic Endoscopic Procedure': [{'threshold': 240, 'rate': Decimal('0.80')},
                                                   {'threshold': 80, 'rate': Decimal('0.88')}],
 'Standard Otolaryngologic Radiotherapy Fraction': [{'threshold': 180, 'rate': Decimal('0.70')},
                                                    {'threshold': 60, 'rate': Decimal('0.88')}]}

DAILY_CAP_RULES = {'Advanced Metabolic Nursing Observation': 6,
 'Advanced Rheumatologic Laboratory Panel': 4,
 'Comprehensive Oncology Nursing Observation': 12,
 'Inpatient Palliative Specimen Analysis': 4,
 'Routine Infectious Critical Care Occupancy': 6,
 'Routine Urologic Biopsy Procedure': 6,
 'Standard Endocrine Dialysis Session': 8}

EXCLUSION_RULES = [
    {
        "excluded_service": "Advanced Metabolic Anaesthesia Administration",
        "trigger_service": "Standard Endocrine Endoscopic Procedure",
        "window_days": 7,
    },
    {
        "excluded_service": "Continuous Immunologic Theatre Time",
        "trigger_service": "Supervised Otolaryngologic Sterilisation Service",
        "window_days": 21,
    },
    {
        "excluded_service": "Intensive Ophthalmic Case Conference",
        "trigger_service": "Continuous Otolaryngologic Telemetry Monitoring",
        "window_days": 7,
    },
    {
        "excluded_service": "Postoperative Ophthalmic Radiotherapy Fraction",
        "trigger_service": "Inpatient Palliative Isolation Room Occupancy",
        "window_days": 30,
    },
    {
        "excluded_service": "Routine Immunologic Ward Bed Occupancy",
        "trigger_service": "Comprehensive Otolaryngologic Theatre Time",
        "window_days": 10,
    },
    {
        "excluded_service": "Standard Paediatric Biopsy Procedure",
        "trigger_service": "Advanced Infectious Critical Care Occupancy",
        "window_days": 10,
    },
]

FACILITY_MULTIPLIERS = {
    "F-MAIN": Decimal("1.00"),
}

PLAN_MULTIPLIERS = {
    "Bronze": Decimal("1.00"),
    "Silver": Decimal("1.00"),
    "Gold": Decimal("1.00"),
}

# Reviewed text mappings from the H1 development pass.
REVIEW_PROMOTIONS = {'ambulatory infectious visit': 'Ambulatory Infectious Home Visit',
 'standard paediatric procedure': 'Standard Paediatric Biopsy Procedure',
 'focused immunologic physiotherapy': 'Focused Immunologic Physiotherapy Session',
 'bedside psychiatric session': 'Bedside Psychiatric Dialysis Session',
 'inpatient endocrine session': 'Inpatient Endocrine Dialysis Session',
 'routine oncology discharge': 'Routine Oncology Discharge Planning',
 'routine cardiac specimen': 'Routine Cardiac Specimen Analysis',
 'extended palliative panel': 'Extended Palliative Laboratory Panel',
 'elective cardiac support': 'Elective Cardiac Nutritional Support',
 'inpatient hepatic session': 'Inpatient Hepatic Physiotherapy Session',
 'supervised isolation room occupancy': 'Supervised Renal Isolation Room Occupancy',
 'postoperative critical care occupancy': 'Postoperative Metabolic Critical Care Occupancy',
 'advanced critical care occupancy': 'Advanced Infectious Critical Care Occupancy',
 'continuous otolaryngologic telem monitoring': 'Continuous Otolaryngologic Telemetry Monitoring',
 'ambulatory urologic imaging interp': 'Ambulatory Urologic Imaging Interpretation',
 'continuous pharmaceutical dispensing': 'Continuous Vascular Pharmaceutical Dispensing',
 'intermittent rehabilitation programme': 'Intermittent Pulmonary Rehabilitation Programme',
 'orthopaedic transport service': 'Focused Orthopaedic Transport Service',
 'pulmonary biopsy procedure': 'Bedside Pulmonary Biopsy Procedure',
 'outpatient radiotherapy fraction': 'Outpatient Metabolic Radiotherapy Fraction',
 'musculoskeletal dialysis session': 'Supervised Musculoskeletal Dialysis Session',
 'intensive nutritional support': 'Intensive Geriatric Nutritional Support',
 'standard nutritional support': 'Standard Geriatric Nutritional Support',
 'comprehensive infectious nursing': 'Comprehensive Infectious Nursing Observation',
 'routine biopsy procedure': 'Routine Urologic Biopsy Procedure',
 'ther assisted gastrointestinal infusion': 'Assisted Gastrointestinal Infusion Therapy',
 'neurological nutritional support': 'Intermittent Neurological Nutritional Support',
 'standard biopsy procedure': 'Standard Paediatric Biopsy Procedure',
 'ther assisted geriatric infusion': 'Assisted Geriatric Infusion Therapy',
 'advanced metabolic anaesthesia': 'Advanced Metabolic Anaesthesia Administration',
 'observation metabolic nursing': 'Advanced Metabolic Nursing Observation',
 'service intermittent transfusion': 'Intermittent Dermatologic Transfusion Service',
 'immunologic consultation': 'Outpatient Immunologic Consultation',
 'observation continuous nursing': 'Continuous Cardiac Nursing Observation',
 'emergency orthopaedic': 'Emergency Orthopaedic Consultation',
 'visit cardiac home': 'Ambulatory Cardiac Home Visit',
 'fraction outpatient radiotherapy': 'Outpatient Metabolic Radiotherapy Fraction'}

UNRESOLVED_RESOLUTIONS = {'advanced cardiac recovery room': 'Advanced Cardiac Recovery Room Occupancy',
 'advanced infectious critical care': 'Advanced Infectious Critical Care Occupancy',
 'ambulatory ophthalmic case conference conference': 'Ambulatory Ophthalmic Case Conference',
 'conference ambulatory ophthalmic case': 'Ambulatory Ophthalmic Case Conference',
 'conference emergency dermatologic case conference': 'Emergency Dermatologic Case Conference',
 'emergency dermatologic case conference conference': 'Emergency Dermatologic Case Conference',
 'conference intensive ophthalmic case conference': 'Intensive Ophthalmic Case Conference',
 'ophthalmic case conference conference intensive': 'Intensive Ophthalmic Case Conference',
 'ophthalmic case conference conference ambulatory': 'Ambulatory Ophthalmic Case Conference',
 'extended renal transport': 'Extended Renal Transport Service',
 'fraction standard otolaryngologic': 'Standard Otolaryngologic Radiotherapy Fraction',
 'inpatient ophthalmic transport': 'Inpatient Ophthalmic Transport Service',
 'procedure immunologic endoscopic': 'Preoperative Immunologic Endoscopic Procedure',
 'specialist dermatologic transport': 'Specialist Dermatologic Transport Service',
 'psychiatric rehabilitation programme': 'Routine Psychiatric Rehabilitation Programme',
 'imaging inpatient diagnostic': 'Inpatient Vascular Diagnostic Imaging'}

DESCRIPTION_VARIANTS = {'infectious crit care occupancy advanced': 'Advanced Infectious Critical Care Occupancy'}


# =============================================================================
# 2. Text normalization / matching
# =============================================================================

ABBREVIATIONS = {
    "preop": "preoperative",
    "postop": "postoperative",
    "inpt": "inpatient",
    "outpt": "outpatient",
    "amb": "ambulatory",
    "adv": "advanced",
    "asst": "assisted",
    "compr": "comprehensive",
    "cont": "continuous",
    "emer": "emergency",
    "emerg": "emergency",
    "ext": "extended",
    "foc": "focused",
    "intens": "intensive",
    "interm": "intermittent",
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
    "cr": "care",
    "rm": "room",
    "prog": "programme",
    "sess": "session",
    "anaes": "anaesthesia",
    "physio": "physiotherapy",
    "thtr": "theatre",
    "tm": "time",
    "disch": "discharge",
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
    "pharm": "pharmaceutical",
    "spcm": "specimen",
    "monit": "monitoring",
    "anaesth": "anaesthesia",
    "inf": "infusion",
    "endosc": "endoscopic",
    "lab": "laboratory",
    "pall": "palliative",
    "wd": "ward",
    "obs": "observation",
    "isol": "isolation",
    "spclst": "specialist",
    "consul": "consultation",
    "phys": "physiotherapy",
    "rheum": "rheumatologic",
    "hep": "hepatic",
    "ren": "renal",
    "uro": "urologic",
    "gastro": "gastrointestinal",
    "elect": "elective",
    "electiv": "elective",
    "beds": "bedside",
    "obst": "obstetric",
    "steril": "sterilisation",
    "paed": "paediatric",
    "paedi": "paediatric",
    "peds": "paediatric",
    "onc": "oncology",
    "bd": "bed",
    "vasc": "vascular",
    "fract": "fraction",
    "hm": "home",
    "vst": "visit",
    "plng": "planning",
    "dial": "dialysis",
    "crit": "critical",
    "supv": "supervised",
}

DOMAIN_TERMS = {
    "cardiac", "haematology", "infectious", "metabolic", "neurological",
    "rheumatologic", "immunologic", "musculoskeletal", "ophthalmic",
    "psychiatric", "pulmonary", "urologic", "gastrointestinal", "geriatric",
    "oncology", "otolaryngologic", "obstetric", "vascular", "dermatologic",
    "orthopaedic", "renal", "palliative", "endocrine", "hepatic", "paediatric",
}

IDENTITY_TERMS = {
    "advanced", "ambulatory", "assisted", "bedside", "comprehensive",
    "continuous", "elective", "emergency", "extended", "focused", "inpatient",
    "intensive", "intermittent", "outpatient", "postoperative", "preoperative",
    "routine", "specialist", "standard", "supervised",
} | DOMAIN_TERMS

SERVICE_TYPE_TERMS = {
    "administration", "analysis", "biopsy", "care", "conference",
    "consultation", "critical", "dialysis", "discharge", "dispensing",
    "endoscopic", "fraction", "home", "imaging", "infusion", "interpretation",
    "isolation", "laboratory", "monitoring", "nutritional", "observation",
    "occupancy", "panel", "pharmaceutical", "physiotherapy", "planning",
    "procedure", "programme", "radiotherapy", "recovery", "rehabilitation",
    "session", "specimen", "sterilisation", "support", "telemetry", "theatre",
    "therapy", "transfusion", "transport", "ventilation", "visit", "ward",
    "wound",
}


def normalize_service_name(value: object) -> str:
    if pd.isna(value):
        return ""

    text = str(value).lower().strip()
    text = re.sub(r"[-_/]+", " ", text)

    words = []
    for word in text.split():
        words.append(ABBREVIATIONS.get(word, word))

    text = " ".join(words)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def canonicalize(text: str) -> str:
    return " ".join(sorted(normalize_service_name(text).split()))


def service_tokens(text: str) -> set[str]:
    return {x for x in normalize_service_name(text).split() if x not in {"the", "of", "and"}}


def token_overlap(a: str, b: str) -> float:
    a_tokens, b_tokens = set(a.split()), set(b.split())
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / min(len(a_tokens), len(b_tokens))


def directional_overlap(a: str, b: str, vocabulary: set[str]) -> float:
    a_terms = set(a.split()) & vocabulary
    b_terms = set(b.split()) & vocabulary
    if not a_terms:
        return 0.0
    return len(a_terms & b_terms) / len(a_terms)


def contract_coverage(desc_tokens: set[str], contract_tokens: set[str], vocabulary: set[str]) -> float:
    contract_terms = contract_tokens & vocabulary
    if not contract_terms:
        return 1.0
    return len((desc_tokens & vocabulary) & contract_terms) / len(contract_terms)


def build_contract_table() -> pd.DataFrame:
    table = pd.DataFrame(
        CONTRACT_ROWS,
        columns=["contract_service", "unit_basis", "unit_price_cents"],
    )
    table["service_normalized"] = table["contract_service"].map(normalize_service_name)
    table["canonical_description"] = table["service_normalized"].map(canonicalize)
    return table


def map_coded_services(lines: pd.DataFrame, contract: pd.DataFrame) -> pd.DataFrame:
    """
    Resolve /NG codes from text only. Billed price and billed unit basis are NOT
    used to choose service identity.
    """
    coded = (
        lines.loc[lines["service_code"].notna(), ["service_code", "service_name_raw"]]
        .drop_duplicates()
        .copy()
    )

    candidates = []
    for row in coded.itertuples(index=False):
        invoice_norm = normalize_service_name(row.service_name_raw)

        for c in contract.itertuples(index=False):
            sequence = SequenceMatcher(None, invoice_norm, c.service_normalized).ratio()
            tokens = token_overlap(invoice_norm, c.service_normalized)
            domain = directional_overlap(invoice_norm, c.service_normalized, DOMAIN_TERMS)
            identity = directional_overlap(invoice_norm, c.service_normalized, IDENTITY_TERMS)
            service_type = directional_overlap(invoice_norm, c.service_normalized, SERVICE_TYPE_TERMS)

            score = (
                0.20 * sequence
                + 0.15 * tokens
                + 0.20 * domain
                + 0.25 * identity
                + 0.20 * service_type
            )

            candidates.append(
                {
                    "service_code": row.service_code,
                    "invoice_service": row.service_name_raw,
                    "contract_service": c.contract_service,
                    "contract_basis": c.unit_basis,
                    "contract_price": c.unit_price_cents,
                    "match_score": score,
                    "identity_overlap": identity,
                    "service_type_overlap": service_type,
                }
            )

    cand = pd.DataFrame(candidates).sort_values(
        ["service_code", "match_score"], ascending=[True, False]
    )
    cand["rank"] = cand.groupby("service_code").cumcount() + 1

    top = cand[cand["rank"].eq(1)].copy()
    second = (
        cand[cand["rank"].eq(2)][["service_code", "match_score"]]
        .rename(columns={"match_score": "second_score"})
    )
    top = top.merge(second, on="service_code", how="left")
    top["score_gap"] = top["match_score"] - top["second_score"]

    top["mapping_confidence"] = "REVIEW"
    high = (
        top["match_score"].ge(0.90)
        & top["identity_overlap"].ge(1.0)
        & top["service_type_overlap"].ge(1.0)
    )
    top.loc[high, "mapping_confidence"] = "HIGH"
    top.loc[top["match_score"].lt(0.60), "mapping_confidence"] = "UNKNOWN"

    # Resolve the two stable H1 code aliases whose text omits a modifier.
    # The override is keyed by billing service code, not by invoice ID or labels.
    contract_by_service = contract.set_index("contract_service")
    for service_code, contract_service in CODE_SERVICE_OVERRIDES.items():
        mask = top["service_code"].eq(service_code)
        if not mask.any():
            continue
        if contract_service not in contract_by_service.index:
            raise KeyError(
                f"Unknown calibrated contract service: {contract_service}"
            )
        rule = contract_by_service.loc[contract_service]
        top.loc[mask, "contract_service"] = contract_service
        top.loc[mask, "contract_basis"] = rule["unit_basis"]
        top.loc[mask, "contract_price"] = rule["unit_price_cents"]
        top.loc[mask, "mapping_confidence"] = "CODE_CALIBRATED"

    return top[
        [
            "service_code",
            "contract_service",
            "contract_basis",
            "contract_price",
            "match_score",
            "score_gap",
            "mapping_confidence",
        ]
    ].rename(
        columns={
            "contract_service": "mapped_contract_service",
            "contract_basis": "mapped_contract_basis",
            "contract_price": "mapped_contract_price",
            "match_score": "match_score_v3",
        }
    )


def score_uncoded_descriptions(lines: pd.DataFrame, contract: pd.DataFrame) -> pd.DataFrame:
    descriptions = (
        lines.loc[lines["service_code"].isna(), "normalized_description"]
        .dropna()
        .drop_duplicates()
        .reset_index(drop=True)
    )

    rows = []
    for idx, desc in descriptions.items():
        desc_tokens = service_tokens(desc)

        for c in contract.itertuples(index=False):
            c_tokens = service_tokens(c.service_normalized)
            common = desc_tokens & c_tokens
            precision = len(common) / len(desc_tokens) if desc_tokens else 0.0
            coverage = len(common) / len(c_tokens) if c_tokens else 0.0
            sequence = SequenceMatcher(None, desc, c.service_normalized).ratio()
            identity = contract_coverage(desc_tokens, c_tokens, IDENTITY_TERMS)
            service_type = contract_coverage(desc_tokens, c_tokens, SERVICE_TYPE_TERMS)

            score = (
                0.35 * coverage
                + 0.20 * precision
                + 0.15 * sequence
                + 0.20 * identity
                + 0.10 * service_type
            )

            rows.append(
                {
                    "description_index": idx,
                    "normalized_description": desc,
                    "contract_service": c.contract_service,
                    "contract_basis": c.unit_basis,
                    "contract_price": c.unit_price_cents,
                    "token_precision": precision,
                    "token_coverage": coverage,
                    "sequence_similarity": sequence,
                    "identity_overlap": identity,
                    "service_type_overlap": service_type,
                    "match_score_v2": score,
                }
            )

    candidates = pd.DataFrame(rows).sort_values(
        ["description_index", "match_score_v2"], ascending=[True, False]
    )
    candidates["rank"] = candidates.groupby("description_index").cumcount() + 1

    top = candidates[candidates["rank"].eq(1)].copy()
    second = (
        candidates[candidates["rank"].eq(2)][["description_index", "match_score_v2"]]
        .rename(columns={"match_score_v2": "second_score"})
    )
    top = top.merge(second, on="description_index", how="left")
    top["score_gap"] = top["match_score_v2"] - top["second_score"]

    top["mapping_confidence"] = "REVIEW"
    high = (
        top["match_score_v2"].ge(0.85)
        & top["token_coverage"].ge(0.75)
        & top["identity_overlap"].ge(0.75)
        & top["score_gap"].ge(0.10)
    )
    top.loc[high, "mapping_confidence"] = "HIGH"
    top.loc[top["match_score_v2"].lt(0.60), "mapping_confidence"] = "UNKNOWN"

    return top


def build_line_mapping(lines: pd.DataFrame, contract: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    coded_map = map_coded_services(lines, contract)

    audit = lines.merge(coded_map, on="service_code", how="left", validate="many_to_one")
    audit["normalized_description"] = audit["service_name_raw"].map(normalize_service_name)
    audit["canonical_description"] = audit["normalized_description"].map(canonicalize)

    audit["final_contract_service"] = audit["mapped_contract_service"]
    audit["final_contract_basis"] = audit["mapped_contract_basis"]
    audit["final_contract_price"] = audit["mapped_contract_price"]
    audit["final_mapping_confidence"] = audit["mapping_confidence"]

    by_norm = (
        contract.drop_duplicates("service_normalized")
        .set_index("service_normalized")
    )
    by_canonical = (
        contract.drop_duplicates("canonical_description")
        .set_index("canonical_description")
    )
    by_service = contract.drop_duplicates("contract_service").set_index("contract_service")

    no_code = audit["service_code"].isna()

    # Exact normalized mapping.
    exact = no_code & audit["normalized_description"].isin(by_norm.index)
    audit.loc[exact, "final_contract_service"] = audit.loc[
        exact, "normalized_description"
    ].map(by_norm["contract_service"])
    audit.loc[exact, "final_mapping_confidence"] = "EXACT"

    # Reviewed mappings from the H1 development analysis.
    reviewed_map = dict(REVIEW_PROMOTIONS)
    reviewed_map.update(UNRESOLVED_RESOLUTIONS)
    reviewed_map.update(DESCRIPTION_VARIANTS)

    reviewed = (
        no_code
        & audit["final_contract_service"].isna()
        & audit["normalized_description"].isin(reviewed_map)
    )
    audit.loc[reviewed, "final_contract_service"] = audit.loc[
        reviewed, "normalized_description"
    ].map(reviewed_map)
    audit.loc[reviewed, "final_mapping_confidence"] = "CONTEXT"

    # Exact token-set / order-independent mapping.
    canonical = (
        no_code
        & audit["final_contract_service"].isna()
        & audit["canonical_description"].isin(by_canonical.index)
    )
    audit.loc[canonical, "final_contract_service"] = audit.loc[
        canonical, "canonical_description"
    ].map(by_canonical["contract_service"])
    audit.loc[canonical, "final_mapping_confidence"] = "CANONICAL"

    # Populate basis/rate strictly from the selected contract service.
    mapped = audit["final_contract_service"].notna()
    audit.loc[mapped, "final_contract_basis"] = audit.loc[
        mapped, "final_contract_service"
    ].map(by_service["unit_basis"])
    audit.loc[mapped, "final_contract_price"] = audit.loc[
        mapped, "final_contract_service"
    ].map(by_service["unit_price_cents"])

    lexical_top = score_uncoded_descriptions(audit, contract)

    # Unknown service logic from the final notebook.
    desc_counts = (
        audit.loc[no_code, "normalized_description"]
        .value_counts()
    )
    lexical_top["line_count"] = (
        lexical_top["normalized_description"].map(desc_counts).fillna(0).astype(int)
    )

    unknown_desc = set(
        lexical_top.loc[
            lexical_top["mapping_confidence"].eq("UNKNOWN"),
            "normalized_description",
        ]
    )

    rare_review = (
        lexical_top["mapping_confidence"].eq("REVIEW")
        & lexical_top["line_count"].eq(1)
        & lexical_top["match_score_v2"].lt(0.80)
        & lexical_top["identity_overlap"].lt(0.75)
    )
    unknown_desc |= set(
        lexical_top.loc[rare_review, "normalized_description"]
    )

    coded_unknown = audit["mapping_confidence"].fillna("").eq("UNKNOWN")
    text_unknown = no_code & audit["normalized_description"].isin(unknown_desc)

    audit["unknown_service_line"] = coded_unknown | text_unknown
    audit.loc[
        audit["unknown_service_line"],
        ["final_contract_service", "final_contract_basis", "final_contract_price"],
    ] = np.nan
    audit.loc[
        audit["unknown_service_line"], "final_mapping_confidence"
    ] = "UNKNOWN_SERVICE"

    return audit, lexical_top


# =============================================================================
# 3. Input preparation
# =============================================================================

def locate_data_dir(requested: str | None) -> Path:
    if requested:
        root = Path(requested).expanduser().resolve()
        if (root / "invoices" / "hospital_1_invoices.csv").exists():
            return root
        raise FileNotFoundError(f"Hospital 1 files not found under: {root}")

    candidates = [
        Path.cwd(),
        Path.cwd() / "insurance_auditing-main",
        Path("/kaggle/working/insurance_auditing-main"),
    ]

    for root in candidates:
        if (root / "invoices" / "hospital_1_invoices.csv").exists():
            return root

    # Kaggle fallback.
    kaggle = Path("/kaggle/input")
    if kaggle.exists():
        matches = list(kaggle.rglob("hospital_1_invoices.csv"))
        if matches:
            return matches[0].parent.parent

    raise FileNotFoundError(
        "Could not locate insurance_auditing data. Pass --data-dir explicitly."
    )


def load_h1(root: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    invoices = pd.read_csv(root / "invoices" / "hospital_1_invoices.csv")
    raw_lines = pd.read_csv(
        root / "invoices" / "hospital_1_line_items.csv",
        dtype={"service_date": "string"},
    )
    labels = pd.read_csv(root / "labels" / "hospital_1_labels.csv")

    lines = raw_lines.copy()
    lines["service_code"] = lines["description"].str.extract(
        r"(/NG-\d+)$", expand=False
    )
    lines["service_name_raw"] = (
        lines["description"]
        .str.replace(r"\s*/NG-\d+$", "", regex=True)
        .str.strip()
    )
    lines["service_normalized"] = lines["service_name_raw"].map(
        normalize_service_name
    )

    return invoices, lines, labels


def build_source_row_context(
    invoices: pd.DataFrame, lines: pd.DataFrame
) -> pd.DataFrame:
    invoice_context = invoices.copy()
    invoice_context["invoice_row_no"] = invoice_context.index + 1

    cols = [
        "invoice_row_no",
        "invoice_id",
        "patient_id",
        "facility_code",
        "plan_tier",
        "invoice_date",
        "admission_date",
        "discharge_date",
        "contract_number",
    ]

    line_context = lines.copy()
    line_context["invoice_row_no"] = (
        line_context["line_id"]
        .str.extract(r"H1-L(\d+)-", expand=False)
        .astype("Int64")
    )

    # invoice_id may be duplicated. line_id preserves the source invoice row.
    return line_context.drop(
        columns=[
            "patient_id",
            "facility_code",
            "plan_tier",
            "invoice_date",
            "admission_date",
            "discharge_date",
            "contract_number",
        ],
        errors="ignore",
    ).merge(
        invoice_context[cols],
        on="invoice_row_no",
        how="left",
        suffixes=("", "_invoice"),
    )


# =============================================================================
# 4. Pricing engine
# =============================================================================

def round_half_up(value: object) -> int | float:
    if pd.isna(value):
        return np.nan
    return int(
        Decimal(str(value)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def apply_multiplier(cents: object, multiplier: object) -> int | float:
    if pd.isna(cents):
        return np.nan
    return int(
        (Decimal(str(cents)) * Decimal(str(multiplier))).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def build_pricing(
    line_audit: pd.DataFrame,
    line_context: pd.DataFrame,
    invoices: pd.DataFrame,
) -> tuple[pd.DataFrame, set[str]]:
    duplicate_ids = set(
        invoices.loc[
            invoices["invoice_id"].duplicated(keep=False),
            "invoice_id",
        ]
    )

    context_cols = [
        "line_id",
        "invoice_row_no",
        "patient_id",
        "facility_code",
        "plan_tier",
        "invoice_date",
        "admission_date",
        "discharge_date",
        "contract_number",
    ]

    pricing = line_audit.drop(
        columns=[
            "invoice_row_no",
            "patient_id",
            "facility_code",
            "plan_tier",
            "invoice_date",
            "admission_date",
            "discharge_date",
            "contract_number",
        ],
        errors="ignore",
    ).merge(
        line_context[context_cols].drop_duplicates("line_id"),
        on="line_id",
        how="left",
        validate="one_to_one",
    )

    pricing["service_date_parsed"] = pd.to_datetime(
        pricing["service_date"], errors="coerce", format="mixed"
    )
    pricing["invoice_date_parsed"] = pd.to_datetime(
        pricing["invoice_date"], errors="coerce", format="mixed"
    )
    pricing["admission_date_parsed"] = pd.to_datetime(
        pricing["admission_date"], errors="coerce", format="mixed"
    )
    pricing["discharge_date_parsed"] = pd.to_datetime(
        pricing["discharge_date"], errors="coerce", format="mixed"
    )
    pricing["quantity"] = pd.to_numeric(pricing["quantity"], errors="coerce")
    pricing["final_contract_price"] = pd.to_numeric(
        pricing["final_contract_price"], errors="coerce"
    )
    pricing["unit_price_cents"] = pd.to_numeric(
        pricing["unit_price_cents"], errors="coerce"
    )

    pricing["within_contract_period"] = pricing["service_date_parsed"].between(
        CONTRACT_START, CONTRACT_END
    )

    pricing = pricing[
        pricing["final_contract_service"].notna()
        & pricing["service_date_parsed"].notna()
    ].copy()

    pricing["pricing_patient_id"] = pricing["patient_id"].where(
        ~pricing["invoice_id"].isin(duplicate_ids)
    )

    # Base rate.
    pricing["base_contract_rate_cents"] = pricing["final_contract_price"].map(
        round_half_up
    )
    pricing["bundle_applied"] = False
    pricing["bundle_rate_before_multipliers"] = pricing[
        "base_contract_rate_cents"
    ]

    # Bundles.
    service_sets = (
        pricing[pricing["pricing_patient_id"].notna()]
        .groupby(["pricing_patient_id", "service_date_parsed"])[
            "final_contract_service"
        ]
        .agg(set)
    )
    row_keys = list(
        zip(pricing["pricing_patient_id"], pricing["service_date_parsed"])
    )

    for (service_a, service_b), rule in BUNDLE_RULES.items():
        qualifying = {
            key for key, services in service_sets.items()
            if service_a in services and service_b in services
        }
        if not qualifying:
            continue

        in_group = pd.Series(
            [
                (not pd.isna(patient)) and ((patient, date) in qualifying)
                for patient, date in row_keys
            ],
            index=pricing.index,
        )
        mask_a = in_group & pricing["final_contract_service"].eq(service_a)
        mask_b = in_group & pricing["final_contract_service"].eq(service_b)

        pricing.loc[mask_a, "bundle_rate_before_multipliers"] = rule["rate_a"]
        pricing.loc[mask_b, "bundle_rate_before_multipliers"] = rule["rate_b"]
        pricing.loc[mask_a | mask_b, "bundle_applied"] = True

    # Facility / plan.
    pricing["facility_multiplier"] = pricing["facility_code"].map(
        lambda x: FACILITY_MULTIPLIERS.get(x, Decimal("1.00"))
    )
    pricing["plan_multiplier"] = pricing["plan_tier"].map(
        lambda x: PLAN_MULTIPLIERS.get(
            str(x).strip().title(), Decimal("1.00")
        ) if not pd.isna(x) else Decimal("1.00")
    )

    pricing["pre_premium_rate_cents"] = [
        apply_multiplier(apply_multiplier(rate, facility), plan)
        for rate, facility, plan in zip(
            pricing["bundle_rate_before_multipliers"],
            pricing["facility_multiplier"],
            pricing["plan_multiplier"],
        )
    ]
    pricing["no_bundle_pre_premium_rate_cents"] = [
        apply_multiplier(apply_multiplier(rate, facility), plan)
        for rate, facility, plan in zip(
            pricing["base_contract_rate_cents"],
            pricing["facility_multiplier"],
            pricing["plan_multiplier"],
        )
    ]

    # Quantity-threshold premiums.
    group_cols = [
        "pricing_patient_id",
        "service_date_parsed",
        "final_contract_service",
    ]
    pricing["service_day_quantity"] = (
        pricing.groupby(group_cols, dropna=False)["quantity"].transform("sum")
    )
    pricing.loc[
        pricing["pricing_patient_id"].isna(), "service_day_quantity"
    ] = np.nan

    pricing["premium_multiplier"] = Decimal("1.00")
    pricing["premium_applied"] = False
    pricing["premium_rule_multiplier"] = Decimal("1.00")

    for service, rule in PREMIUM_RULES.items():
        service_mask = pricing["final_contract_service"].eq(service)
        pricing.loc[
            service_mask, "premium_rule_multiplier"
        ] = rule["rate"]

        expected = (
            service_mask
            & pricing["pricing_patient_id"].notna()
            & pricing["service_day_quantity"].gt(rule["threshold"])
        )
        pricing.loc[expected, "premium_multiplier"] = rule["rate"]
        pricing.loc[expected, "premium_applied"] = True

    pricing["post_premium_rate_cents"] = [
        apply_multiplier(rate, mult)
        for rate, mult in zip(
            pricing["pre_premium_rate_cents"],
            pricing["premium_multiplier"],
        )
    ]
    pricing["no_bundle_post_premium_rate_cents"] = [
        apply_multiplier(rate, mult)
        for rate, mult in zip(
            pricing["no_bundle_pre_premium_rate_cents"],
            pricing["premium_multiplier"],
        )
    ]
    pricing["no_premium_rate_cents"] = pricing["pre_premium_rate_cents"]
    pricing["forced_premium_rate_cents"] = [
        apply_multiplier(rate, mult)
        for rate, mult in zip(
            pricing["pre_premium_rate_cents"],
            pricing["premium_rule_multiplier"],
        )
    ]

    # Weekend premium/uplift.
    pricing["is_weekend"] = pricing["service_date_parsed"].dt.dayofweek.ge(5)
    pricing["weekend_multiplier"] = Decimal("1.00")
    pricing["weekend_uplift_applied"] = False

    for service, mult in WEEKEND_UPLIFT_RULES.items():
        mask = pricing["final_contract_service"].eq(service) & pricing["is_weekend"]
        pricing.loc[mask, "weekend_multiplier"] = mult
        pricing.loc[mask, "weekend_uplift_applied"] = True

    # Preserve the rate immediately before weekend uplift for the omission
    # counterfactual.
    pricing["threshold_premium_rate_before_weekend_cents"] = [
        apply_multiplier(rate, mult)
        for rate, mult in zip(
            pricing["pre_premium_rate_cents"],
            pricing["premium_multiplier"],
        )
    ]

    for col in [
        "post_premium_rate_cents",
        "no_bundle_post_premium_rate_cents",
        "no_premium_rate_cents",
        "forced_premium_rate_cents",
    ]:
        pricing[col] = [
            apply_multiplier(rate, mult)
            for rate, mult in zip(
                pricing[col], pricing["weekend_multiplier"]
            )
        ]

    pricing["pre_volume_rate_cents"] = pricing["post_premium_rate_cents"]

    # Volume discounts use prior cumulative quantity across all patients.
    pricing["prior_cumulative_quantity"] = 0.0
    pricing["volume_discount_multiplier"] = Decimal("1.00")
    pricing["volume_discount_applied"] = False

    volume_order = (
        pricing[pricing["within_contract_period"]]
        .sort_values(
            ["final_contract_service", "service_date_parsed", "line_id"]
        )
    )
    volume_prior = (
        volume_order.groupby("final_contract_service")["quantity"].cumsum()
        - volume_order["quantity"]
    )
    pricing.loc[
        volume_order.index, "prior_cumulative_quantity"
    ] = volume_prior

    for service, tiers in VOLUME_DISCOUNT_RULES.items():
        service_mask = (
            pricing["final_contract_service"].eq(service)
            & pricing["within_contract_period"]
        )
        for tier in sorted(
            tiers, key=lambda x: x["threshold"], reverse=True
        ):
            mask = (
                service_mask
                & ~pricing["volume_discount_applied"]
                & pricing["prior_cumulative_quantity"].gt(tier["threshold"])
            )
            pricing.loc[
                mask, "volume_discount_multiplier"
            ] = tier["rate"]
            pricing.loc[mask, "volume_discount_applied"] = True

    for col in [
        "post_premium_rate_cents",
        "no_bundle_post_premium_rate_cents",
        "no_premium_rate_cents",
        "forced_premium_rate_cents",
    ]:
        pricing[col] = [
            apply_multiplier(rate, mult)
            for rate, mult in zip(
                pricing[col], pricing["volume_discount_multiplier"]
            )
        ]

    pricing["expected_unit_rate_cents"] = pricing[
        "post_premium_rate_cents"
    ].astype("Int64")
    pricing["counterfactual_no_bundle_rate_cents"] = pricing[
        "no_bundle_post_premium_rate_cents"
    ].astype("Int64")
    pricing["counterfactual_no_premium_rate_cents"] = pricing[
        "no_premium_rate_cents"
    ].astype("Int64")
    pricing["counterfactual_forced_premium_rate_cents"] = pricing[
        "forced_premium_rate_cents"
    ].astype("Int64")

    # Missing weekend uplift counterfactual, with expected volume tier retained.
    pricing["counterfactual_no_weekend_rate_cents"] = [
        apply_multiplier(rate, mult)
        for rate, mult in zip(
            pricing["threshold_premium_rate_before_weekend_cents"],
            pricing["volume_discount_multiplier"],
        )
    ]
    pricing["counterfactual_no_weekend_rate_cents"] = pd.to_numeric(
        pricing["counterfactual_no_weekend_rate_cents"], errors="coerce"
    ).astype("Int64")

    # Daily caps.
    pricing["daily_service_quantity"] = (
        pricing.groupby(group_cols, dropna=False)["quantity"].transform("sum")
    )
    pricing.loc[
        pricing["pricing_patient_id"].isna(), "daily_service_quantity"
    ] = np.nan
    pricing["daily_cap"] = np.nan

    for service, cap in DAILY_CAP_RULES.items():
        pricing.loc[
            pricing["final_contract_service"].eq(service), "daily_cap"
        ] = cap

    pricing["daily_cap_exceeded"] = (
        pricing["daily_cap"].notna()
        & pricing["daily_service_quantity"].gt(pricing["daily_cap"])
    )

    pricing["expected_line_total_cents"] = [
        round_half_up(rate * qty)
        if not pd.isna(rate) and not pd.isna(qty)
        else np.nan
        for rate, qty in zip(
            pricing["expected_unit_rate_cents"], pricing["quantity"]
        )
    ]

    return pricing, duplicate_ids


# =============================================================================
# 5. Pricing-category detectors
# =============================================================================

BASIS_ALIASES = {
    "day": "per_day_of_service",
    "days": "per_day_of_service",
    "per_day": "per_day_of_service",
    "per_day_of_service": "per_day_of_service",
    "night": "per_night_of_occupancy",
    "nights": "per_night_of_occupancy",
    "per_night": "per_night_of_occupancy",
    "per_night_of_occupancy": "per_night_of_occupancy",
    "item": "per_item_supplied",
    "each": "per_item_supplied",
    "unit": "per_item_supplied",
    "per_item": "per_item_supplied",
    "per_item_supplied": "per_item_supplied",
    "per_unit": "per_unit_dispensed",
    "per_unit_dispensed": "per_unit_dispensed",
    "procedure": "per_procedure",
    "per_procedure": "per_procedure",
    "visit": "per_visit",
    "per_visit": "per_visit",
    "hour": "per_hour",
    "hr": "per_hour",
    "per_hour": "per_hour",
    "test": "per_test",
    "per_test": "per_test",
    "session": "per_session",
    "per_session": "per_session",
    "fraction": "per_fraction",
    "per_fraction": "per_fraction",
}

UNRELIABLE_MAPPING = {"", "REVIEW", "UNKNOWN", "UNKNOWN_SERVICE", "UNMAPPED"}


def normalize_basis(value: object) -> object:
    if pd.isna(value):
        return pd.NA
    text = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    text = re.sub(r"_+", "_", text)
    return BASIS_ALIASES.get(text, text)


def detect_pricing_errors(
    pricing: pd.DataFrame, duplicate_ids: set[str]
) -> pd.DataFrame:
    p = pricing.copy()

    eligible = (
        ~p["invoice_id"].isin(duplicate_ids)
        & p["within_contract_period"].fillna(False)
    )

    p["bundle_not_applied_line"] = (
        eligible
        & p["bundle_applied"].fillna(False)
        & p["unit_price_cents"].eq(
            p["counterfactual_no_bundle_rate_cents"]
        )
        & p["unit_price_cents"].ne(p["expected_unit_rate_cents"])
    )

    threshold_service = p["final_contract_service"].isin(PREMIUM_RULES)
    p["threshold_premium_omitted_line"] = (
        eligible
        & threshold_service
        & p["premium_applied"].fillna(False)
        & p["unit_price_cents"].eq(
            p["counterfactual_no_premium_rate_cents"]
        )
        & p["unit_price_cents"].ne(p["expected_unit_rate_cents"])
    )

    p["premium_incorrectly_applied_line"] = (
        eligible
        & threshold_service
        & ~p["premium_applied"].fillna(False)
        & p["unit_price_cents"].eq(
            p["counterfactual_forced_premium_rate_cents"]
        )
        & p["unit_price_cents"].ne(p["expected_unit_rate_cents"])
    )

    weekend_service = p["final_contract_service"].isin(WEEKEND_UPLIFT_RULES)
    p["weekend_premium_omitted_line"] = (
        eligible
        & weekend_service
        & p["is_weekend"].fillna(False)
        & p["weekend_uplift_applied"].fillna(False)
        & p["unit_price_cents"].eq(
            p["counterfactual_no_weekend_rate_cents"]
        )
        & p["unit_price_cents"].ne(p["expected_unit_rate_cents"])
    )

    p["premium_omitted_line"] = (
        p["threshold_premium_omitted_line"]
        | p["weekend_premium_omitted_line"]
    )

    def infer_volume(row: pd.Series):
        service = row["final_contract_service"]
        if service not in VOLUME_DISCOUNT_RULES:
            return None

        pre_rate = row["pre_volume_rate_cents"]
        billed = row["unit_price_cents"]
        if pd.isna(pre_rate) or pd.isna(billed):
            return None

        candidates = [(Decimal("1.00"), int(pre_rate))]
        for tier in VOLUME_DISCOUNT_RULES[service]:
            candidates.append(
                (
                    tier["rate"],
                    apply_multiplier(pre_rate, tier["rate"]),
                )
            )

        for mult, rate in candidates:
            if int(billed) == int(rate):
                return mult
        return None

    p["billed_volume_multiplier"] = p.apply(infer_volume, axis=1)

    # Convert Decimal/None object columns to numeric values before comparison.
    # Pandas evaluates Series comparisons eagerly, so an object Series containing
    # None cannot safely be compared directly with Decimal values even if a
    # separate notna() mask is present.
    p["billed_volume_multiplier_num"] = pd.to_numeric(
        p["billed_volume_multiplier"].map(
            lambda x: float(x) if x is not None and not pd.isna(x) else np.nan
        ),
        errors="coerce",
    )

    p["expected_volume_multiplier_num"] = pd.to_numeric(
        p["volume_discount_multiplier"].map(
            lambda x: float(x) if x is not None and not pd.isna(x) else np.nan
        ),
        errors="coerce",
    )

    is_volume = p["final_contract_service"].isin(VOLUME_DISCOUNT_RULES)
    known_volume = (
        p["billed_volume_multiplier_num"].notna()
        & p["expected_volume_multiplier_num"].notna()
    )

    p["volume_discount_incorrectly_applied_line"] = (
        eligible
        & is_volume
        & known_volume
        & p["billed_volume_multiplier_num"].lt(
            p["expected_volume_multiplier_num"]
        )
    )

    p["volume_discount_omitted_line"] = (
        eligible
        & is_volume
        & known_volume
        & p["billed_volume_multiplier_num"].gt(
            p["expected_volume_multiplier_num"]
        )
    )

    # Specific contract explanations take precedence over generic price mismatch.
    specific_price_error = (
        p["bundle_not_applied_line"]
        | p["premium_omitted_line"]
        | p["premium_incorrectly_applied_line"]
        | p["volume_discount_incorrectly_applied_line"]
        | p["volume_discount_omitted_line"]
    )

    map_conf = (
        p["final_mapping_confidence"]
        .astype("string")
        .fillna("")
        .str.strip()
        .str.upper()
    )
    reliable = (
        p["final_contract_service"].notna()
        & ~map_conf.isin(UNRELIABLE_MAPPING)
    )

    p["unit_price_mismatch_line"] = (
        eligible
        & reliable
        & p["unit_price_cents"].ne(p["expected_unit_rate_cents"])
        & ~specific_price_error
    )

    # Unit-basis fix: normalize aliases and learn stable billing-system
    # representations only from reliable lines whose price is exactly correct.
    p["normalized_billed_basis"] = p["unit_basis_as_billed"].map(
        normalize_basis
    )
    p["normalized_contract_basis"] = p["final_contract_basis"].map(
        normalize_basis
    )

    calibration = (
        eligible
        & reliable
        & p["normalized_billed_basis"].notna()
        & p["unit_price_cents"].eq(p["expected_unit_rate_cents"])
    )

    counts = (
        p.loc[
            calibration,
            ["final_contract_service", "normalized_billed_basis"],
        ]
        .groupby(
            ["final_contract_service", "normalized_billed_basis"],
            dropna=False,
        )
        .size()
        .rename("basis_count")
        .reset_index()
    )

    if counts.empty:
        accepted = {}
        support = {}
    else:
        support_series = (
            counts.groupby("final_contract_service")["basis_count"].sum()
        )
        counts["service_support"] = counts["final_contract_service"].map(
            support_series
        )
        counts["basis_share"] = (
            counts["basis_count"] / counts["service_support"]
        )
        accepted_rows = counts[
            counts["service_support"].ge(4)
            & counts["basis_count"].ge(2)
            & counts["basis_share"].ge(0.05)
        ]
        accepted = (
            accepted_rows.groupby("final_contract_service")[
                "normalized_billed_basis"
            ]
            .agg(lambda s: set(s.dropna()))
            .to_dict()
        )
        support = support_series.to_dict()

    def allowed_basis(row: pd.Series) -> set:
        allowed = set(accepted.get(row["final_contract_service"], set()))
        contract_basis = row["normalized_contract_basis"]
        if not pd.isna(contract_basis):
            allowed.add(contract_basis)
        return allowed

    p["allowed_basis_set"] = p.apply(allowed_basis, axis=1)

    def basis_allowed(row: pd.Series) -> bool:
        billed = row["normalized_billed_basis"]
        if pd.isna(billed):
            return True
        allowed = row["allowed_basis_set"]
        if not allowed:
            return True
        return billed in allowed

    p["basis_is_allowed"] = p.apply(basis_allowed, axis=1)

    # Unit basis is a line-level attribute. Duplicate invoice IDs make
    # patient-dependent pricing ambiguous, but they do not make the billed
    # unit basis itself ambiguous. Therefore duplicates remain eligible here.
    basis_eligible = p["within_contract_period"].fillna(False)

    p["wrong_unit_basis_line"] = (
        basis_eligible
        & reliable
        & p["normalized_billed_basis"].notna()
        & ~p["basis_is_allowed"]
        & p["unit_price_cents"].eq(p["expected_unit_rate_cents"])
    )

    return p


# =============================================================================
# 6. Non-pricing detectors
# =============================================================================

def detect_nonpricing(
    invoices: pd.DataFrame,
    lines: pd.DataFrame,
    line_context: pd.DataFrame,
    line_audit: pd.DataFrame,
    pricing: pd.DataFrame,
    duplicate_ids: set[str],
) -> dict[str, set[str]]:
    raw = lines.copy()
    raw["service_date_parsed"] = pd.to_datetime(
        raw["service_date"], errors="coerce", format="mixed"
    )

    # Line arithmetic.
    raw["calculated_line_total_cents"] = (
        pd.to_numeric(raw["quantity"], errors="coerce")
        * pd.to_numeric(raw["unit_price_cents"], errors="coerce")
    )
    line_total_ids = set(
        raw.loc[
            raw["calculated_line_total_cents"].ne(raw["line_total_cents"]),
            "invoice_id",
        ]
    )

    # Invoice header arithmetic.
    raw_line_sum = raw.groupby("invoice_id")["line_total_cents"].sum()
    unique_headers = invoices[
        ~invoices["invoice_id"].isin(duplicate_ids)
    ].copy()
    unique_headers["raw_line_sum_cents"] = unique_headers["invoice_id"].map(
        raw_line_sum
    )
    invoice_total_ids = set(
        unique_headers.loc[
            unique_headers["invoice_total_cents"].ne(
                unique_headers["raw_line_sum_cents"]
            ),
            "invoice_id",
        ]
    )

    # Malformed date.
    date_text = raw["service_date"].astype("string")
    malformed = (
        date_text.notna()
        & date_text.str.strip().ne("")
        & raw["service_date_parsed"].isna()
    )
    malformed_ids = set(raw.loc[malformed, "invoice_id"])

    # Out of contract.
    outside_contract = (
        raw["service_date_parsed"].notna()
        & ~raw["service_date_parsed"].between(
            CONTRACT_START, CONTRACT_END
        )
    )
    out_of_window_ids = set(
        raw.loc[outside_contract, "invoice_id"]
    )

    # After invoice date, only for in-contract service dates.
    date_check = line_context.copy()
    date_check["service_date_parsed"] = pd.to_datetime(
        date_check["service_date"], errors="coerce", format="mixed"
    )
    date_check["invoice_date_parsed"] = pd.to_datetime(
        date_check["invoice_date"], errors="coerce", format="mixed"
    )
    after_invoice = (
        date_check["service_date_parsed"].notna()
        & date_check["invoice_date_parsed"].notna()
        & date_check["service_date_parsed"].between(
            CONTRACT_START, CONTRACT_END
        )
        & date_check["service_date_parsed"].gt(
            date_check["invoice_date_parsed"]
        )
    )
    after_invoice_ids = set(
        date_check.loc[after_invoice, "invoice_id"]
    )

    # Contract number.
    contract_mismatch_ids = set(
        invoices.loc[
            invoices["contract_number"]
            .astype("string")
            .str.strip()
            .ne(EXPECTED_CONTRACT_NUMBER),
            "invoice_id",
        ]
    )

    # Cross-invoice duplicate.
    cross = line_context.copy()
    cross["service_date_parsed"] = pd.to_datetime(
        cross["service_date"], errors="coerce", format="mixed"
    )
    cross["admission_date_parsed"] = pd.to_datetime(
        cross["admission_date"], errors="coerce", format="mixed"
    )
    cross["discharge_date_parsed"] = pd.to_datetime(
        cross["discharge_date"], errors="coerce", format="mixed"
    )

    signature = [
        "patient_id",
        "service_date",
        "description",
        "quantity",
        "unit_basis_as_billed",
        "unit_price_cents",
        "line_total_cents",
    ]
    duplicate_count = (
        cross.groupby(signature, dropna=False)["invoice_id"]
        .transform("nunique")
    )
    outside_own_window = (
        cross["service_date_parsed"].notna()
        & cross["admission_date_parsed"].notna()
        & cross["discharge_date_parsed"].notna()
        & (
            cross["service_date_parsed"].lt(
                cross["admission_date_parsed"]
            )
            | cross["service_date_parsed"].gt(
                cross["discharge_date_parsed"]
            )
        )
    )
    cross_ids = set(
        cross.loc[
            duplicate_count.gt(1)
            & cross["patient_id"].notna()
            & outside_own_window,
            "invoice_id",
        ]
    )

    # Exclusion windows.
    exclusion_source = pricing[
        [
            "invoice_id",
            "line_id",
            "patient_id",
            "service_date_parsed",
            "final_contract_service",
        ]
    ].copy()

    exclusion_ids = set()
    for rule in EXCLUSION_RULES:
        excluded = exclusion_source[
            exclusion_source["final_contract_service"].eq(
                rule["excluded_service"]
            )
        ]
        triggers = exclusion_source[
            exclusion_source["final_contract_service"].eq(
                rule["trigger_service"]
            )
        ]

        for row in excluded.itertuples(index=False):
            candidates = triggers[
                triggers["patient_id"].eq(row.patient_id)
            ].copy()
            if candidates.empty or pd.isna(row.service_date_parsed):
                continue

            diff = (
                candidates["service_date_parsed"] - row.service_date_parsed
            ).abs().dt.days
            if diff.le(rule["window_days"]).any():
                exclusion_ids.add(row.invoice_id)

    return {
        "unknown_service": set(
            line_audit.loc[
                line_audit["unknown_service_line"], "invoice_id"
            ]
        ),
        "line_total_arithmetic": line_total_ids,
        "invoice_total_mismatch": invoice_total_ids,
        "malformed_service_date": malformed_ids,
        "service_date_after_invoice_date": after_invoice_ids,
        "duplicate_invoice_id": duplicate_ids,
        "contract_number_mismatch": contract_mismatch_ids,
        "service_date_out_of_window": out_of_window_ids,
        "daily_cap_exceeded": set(
            pricing.loc[pricing["daily_cap_exceeded"], "invoice_id"]
        ),
        "exclusion_window_violation": exclusion_ids,
        "cross_invoice_duplicate": cross_ids,
    }


# =============================================================================
# 7. Assemble and evaluate all 18 categories
# =============================================================================

CATEGORY_ORDER = [
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


def assemble_categories(
    pricing: pd.DataFrame,
    nonpricing: dict[str, set[str]],
) -> dict[str, set[str]]:
    result = dict(nonpricing)
    line_flags = {
        "wrong_unit_basis": "wrong_unit_basis_line",
        "unit_price_mismatch": "unit_price_mismatch_line",
        "premium_incorrectly_applied": "premium_incorrectly_applied_line",
        "bundle_not_applied": "bundle_not_applied_line",
        "volume_discount_incorrectly_applied":
            "volume_discount_incorrectly_applied_line",
        "volume_discount_omitted": "volume_discount_omitted_line",
        "premium_omitted": "premium_omitted_line",
    }

    for category, col in line_flags.items():
        result[category] = set(
            pricing.loc[pricing[col].fillna(False), "invoice_id"]
        )

    return result


def evaluate(
    labels: pd.DataFrame,
    categories: dict[str, set[str]],
) -> pd.DataFrame:
    rows = []

    for category in CATEGORY_ORDER:
        true_ids = set(
            labels.loc[
                labels["error_categories"]
                .fillna("")
                .astype(str)
                .str.split("|")
                .apply(lambda values: category in values),
                "invoice_id",
            ]
        )
        pred_ids = categories.get(category, set())

        tp_ids = true_ids & pred_ids
        fp_ids = pred_ids - true_ids
        fn_ids = true_ids - pred_ids

        tp, fp, fn = len(tp_ids), len(fp_ids), len(fn_ids)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0
        )

        rows.append(
            {
                "category": category,
                "true_count": len(true_ids),
                "predicted_count": len(pred_ids),
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "false_positives": "|".join(sorted(fp_ids)),
                "false_negatives": "|".join(sorted(fn_ids)),
            }
        )

    return pd.DataFrame(rows)


def build_invoice_predictions(
    labels: pd.DataFrame,
    categories: dict[str, set[str]],
) -> pd.DataFrame:
    rows = []
    for invoice_id in sorted(labels["invoice_id"].unique()):
        errors = [
            c for c in CATEGORY_ORDER
            if invoice_id in categories.get(c, set())
        ]
        rows.append(
            {
                "invoice_id": invoice_id,
                "predicted_error_categories": "|".join(errors),
                "predicted_is_erroneous": int(bool(errors)),
            }
        )
    return pd.DataFrame(rows)


# =============================================================================
# 8. Main
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Repository root containing invoices/ and labels/.",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs",
        help="Directory for generated H1 files.",
    )
    args = parser.parse_args()

    root = locate_data_dir(args.data_dir)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)

    invoices, lines, labels = load_h1(root)
    contract = build_contract_table()
    line_context = build_source_row_context(invoices, lines)

    line_audit, _ = build_line_mapping(lines, contract)
    pricing, duplicate_ids = build_pricing(
        line_audit, line_context, invoices
    )
    pricing = detect_pricing_errors(pricing, duplicate_ids)

    nonpricing = detect_nonpricing(
        invoices,
        lines,
        line_context,
        line_audit,
        pricing,
        duplicate_ids,
    )
    categories = assemble_categories(pricing, nonpricing)

    evaluation = evaluate(labels, categories)
    predictions = build_invoice_predictions(labels, categories)

    evaluation.to_csv(
        out / "hospital_1_category_evaluation.csv", index=False
    )
    predictions.to_csv(
        out / "hospital_1_category_predictions.csv", index=False
    )
    line_audit.to_csv(
        out / "hospital_1_line_mapping.csv", index=False
    )

    print("\nHOSPITAL 1 — CATEGORY EVALUATION")
    print("=" * 110)
    print(
        evaluation[
            [
                "category",
                "true_count",
                "predicted_count",
                "tp",
                "fp",
                "fn",
                "precision",
                "recall",
                "f1",
            ]
        ].to_string(
            index=False,
            formatters={
                "precision": lambda x: f"{x:.3f}",
                "recall": lambda x: f"{x:.3f}",
                "f1": lambda x: f"{x:.3f}",
            },
        )
    )

    perfect = evaluation[
        evaluation["fp"].eq(0) & evaluation["fn"].eq(0)
    ]["category"].tolist()

    print(f"\nPerfect categories: {len(perfect)}/{len(CATEGORY_ORDER)}")
    print(perfect)

    failures = evaluation[
        evaluation["fp"].gt(0) | evaluation["fn"].gt(0)
    ]
    if not failures.empty:
        print("\nRemaining review:")
        for row in failures.itertuples(index=False):
            print(f"  {row.category}")
            if row.false_positives:
                print(f"    FP: {row.false_positives}")
            if row.false_negatives:
                print(f"    FN: {row.false_negatives}")

    print("\nSaved:")
    print(out / "hospital_1_category_evaluation.csv")
    print(out / "hospital_1_category_predictions.csv")
    print(out / "hospital_1_line_mapping.csv")


if __name__ == "__main__":
    main()
