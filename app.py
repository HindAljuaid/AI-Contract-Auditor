from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st

from src.ai import (
    AIAuthenticationError,
    AIConnectionError,
    AIQuotaError,
    AIRateLimitError,
    AIServiceError,
    explain_audit_evidence,
    extract_contract_spec,
)
from src.audit_engine import audit_invoices
from src.cache_utils import save_contract_spec
from src.data_utils import (
    REQUIRED_INVOICE_COLUMNS,
    REQUIRED_LINE_COLUMNS,
    exercise_contract_files,
    load_exercise_hospital,
    read_csv_any,
    validate_columns,
)
from src.explain import build_invoice_evidence, deterministic_explanation_markdown
from src.h1_benchmark import run_h1_reference
from src.mapping import map_descriptions
from src.mapping_snapshots import load_reviewed_mapping_snapshot
from src.models import ContractSpec


PROJECT_ROOT = Path(__file__).resolve().parent
EXERCISE_ROOT = PROJECT_ROOT / "exercise_data" / "insurance_auditing-main"


st.set_page_config(
    page_title="AI Contract Auditor",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
    .block-container {padding-top: 1.5rem; padding-bottom: 3rem; max-width: 1400px;}
    [data-testid="stSidebar"] {border-right: 1px solid rgba(128,128,128,.18);}
    .small-note {opacity: .72; font-size: .86rem;}

    .app-hero {
        padding: 1.35rem 1.5rem;
        margin-bottom: 1.1rem;
        border: 1px solid rgba(77, 126, 255, 0.28);
        border-radius: 16px;
        background: linear-gradient(
            135deg,
            rgba(77, 126, 255, 0.12),
            rgba(139, 92, 246, 0.10)
        );
    }

    .app-hero h1 {
        margin: 0 0 .35rem 0;
        font-size: 2rem;
        line-height: 1.2;
    }

    .app-hero .subtitle {
        margin: 0 0 .35rem 0;
        font-size: 1.02rem;
        font-weight: 500;
    }

    .app-hero .description {
        margin: 0;
        opacity: .78;
        font-size: .92rem;
    }

</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="app-hero">
        <h1>AI Contract Auditor</h1>
        <p class="subtitle">AI-assisted contract interpretation with deterministic invoice auditing.</p>
        <p class="description">
            AI helps interpret contract language and unclear service descriptions.
            Financial calculations and audit findings are performed in Python.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)



def get_secret_key() -> str:
    env_key = os.getenv("OPENAI_API_KEY", "").strip()
    if env_key:
        return env_key
    try:
        secret = str(st.secrets.get("OPENAI_API_KEY", "")).strip()
        if secret:
            return secret
    except Exception:
        pass
    return ""


def reset_analysis_state():
    for key in [
        "contract_spec",
        "contract_spec_source",
        "contract_spec_source_key",
        "mapping",
        "predictions",
        "line_audit",
        "source_label",
        "rule_reviewed",
        "ai_explanations",
        "last_api_error",
        "workflow_review_ack",
        "rules_review_ack",
        "_loaded_rules_signature",
    ]:
        st.session_state.pop(key, None)


def show_ai_error(exc: Exception):
    st.session_state["last_api_error"] = str(exc)
    if isinstance(exc, AIQuotaError):
        st.error("OpenAI API credits are currently unavailable.")
        st.info(
            "Add API credits and retry. Hospital 1 Validation remains available without an API call."
        )
    elif isinstance(exc, AIAuthenticationError):
        st.error("The OpenAI API key was rejected. Check the key in the sidebar.")
    elif isinstance(exc, AIRateLimitError):
        st.warning("The OpenAI API rate limit was reached. Please retry later.")
    elif isinstance(exc, AIConnectionError):
        st.warning("The OpenAI API could not be reached. Check your connection and retry.")
    elif isinstance(exc, AIServiceError):
        st.error(str(exc))
    else:
        st.error(f"Operation failed: {exc}")


def source_slug(mode: str, hospital_number: int | None) -> str:
    if mode == "provided":
        if hospital_number is not None:
            return f"hospital_{hospital_number}"
        return "provided_no_hospital"
    return "uploaded_dataset"


def active_contract_spec(cache_key: str) -> ContractSpec | None:
    """Return rules only when they belong to the currently selected data source."""
    if st.session_state.get("contract_spec_source_key") != cache_key:
        return None
    return st.session_state.get("contract_spec")


def expected_bundled_contract_identity(
    project_root: Path,
    hospital_number: int | None,
) -> tuple[str | None, str | None] | None:
    """Read only contract identity metadata for the selected bundled hospital."""
    if hospital_number is None:
        return None

    rules_path = (
        project_root
        / "demo_outputs"
        / f"hospital_{hospital_number}"
        / f"hospital_{hospital_number}_contract_rules.json"
    )
    if not rules_path.exists():
        return None

    try:
        expected = ContractSpec.model_validate_json(rules_path.read_bytes())
    except Exception:
        return None

    return expected.contract_number, expected.provider_name


def review_queue(predictions: pd.DataFrame) -> pd.DataFrame:
    return predictions[
        predictions["review_required"] | predictions["confidence"].lt(0.75)
    ].sort_values(["confidence", "invoice_id"])


def audit_results_zip_bytes(
    prefix: str,
    predictions: pd.DataFrame,
    mapping: pd.DataFrame | None,
    line_audit: pd.DataFrame | None,
) -> bytes:
    """Package final audit outputs without duplicating the contract-rule JSON."""
    buf = io.BytesIO()
    submission = predictions[
        [
            "invoice_id",
            "flagged",
            "error_category",
            "expected_total_cents",
            "billed_total_cents",
            "confidence",
        ]
    ].copy()
    review = review_queue(predictions)

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{prefix}_submission.csv", submission.to_csv(index=False))
        zf.writestr(f"{prefix}_review_queue.csv", review.to_csv(index=False))
        if mapping is not None:
            zf.writestr(f"{prefix}_service_mapping.csv", mapping.to_csv(index=False))
        if line_audit is not None:
            zf.writestr(f"{prefix}_line_audit.csv", line_audit.to_csv(index=False))
    return buf.getvalue()


# -----------------------------------------------------------------------------
# Sidebar / data selection
# -----------------------------------------------------------------------------
contract_files = []
invoices = None
lines = None
source_label = None
labels = None
hospital_number: int | None = None
invoice_file = None
line_file = None

with st.sidebar:
    st.header("Audit setup")

    mode = st.radio(
        "Data source",
        ["provided", "upload"],
        key="data_source_mode",
        format_func=lambda value: (
            "Provided hospital data" if value == "provided" else "Upload my own files"
        ),
        help=(
            "Provided hospital data uses the Hospital 1–5 files bundled with this project. "
            "Choose Upload my own files to audit a different contract and invoice set."
        ),
    )

    if mode == "provided":
        hospital_number = st.selectbox(
            "Hospital",
            [1, 2, 3, 4, 5],
            index=None,
            placeholder="Select a hospital...",
            key="selected_hospital",
        )
        st.caption("Choose a hospital to load its bundled contract and invoice data.")
    else:
        st.markdown("#### Files")
        contract_files = st.file_uploader(
            "Contract document(s)",
            type=["pdf", "txt", "md", "docx", "doc", "rtf"],
            accept_multiple_files=True,
        )
        invoice_file = st.file_uploader("Invoice CSV", type=["csv"], key="invoice_csv")
        line_file = st.file_uploader("Line-item CSV", type=["csv"], key="line_csv")

    cache_key = source_slug(mode, hospital_number)

    # Clear prior results when the user switches to a different bundled hospital/data source.
    active_source = cache_key
    previous_source = st.session_state.get("_active_source")
    if previous_source is not None and previous_source != active_source:
        reset_analysis_state()
    st.session_state["_active_source"] = active_source

    # Keep reusable rules visible instead of hiding them under Advanced settings.
    st.markdown("#### Reuse saved contract rules")
    st.caption(
        "Already analyzed this contract? Upload its reviewed rules JSON to skip AI contract analysis "
        "and run the audit without spending API credits."
    )

    rules_upload = None
    if mode == "provided" and hospital_number is None:
        st.info("Select a hospital first, then upload its saved contract rules JSON.")
    else:
        rules_upload = st.file_uploader(
            "Upload contract rules JSON",
            type=["json"],
            key=f"contract_rules_json_{cache_key}",
            help="Use a previously reviewed rules file generated by this app.",
        )

    if rules_upload is not None:
        try:
            loaded_spec = ContractSpec.model_validate_json(rules_upload.getvalue())

            # For bundled data, prevent accidental cross-hospital audits such as
            # loading Hospital 1 rules while Hospital 4 invoices are selected.
            identity_mismatch = False
            if mode == "provided":
                expected_identity = expected_bundled_contract_identity(
                    PROJECT_ROOT,
                    hospital_number,
                )
                if expected_identity is not None:
                    expected_contract, expected_provider = expected_identity

                    contract_matches = (
                        not expected_contract
                        or not loaded_spec.contract_number
                        or loaded_spec.contract_number == expected_contract
                    )
                    provider_matches = (
                        not expected_provider
                        or not loaded_spec.provider_name
                        or loaded_spec.provider_name.strip().casefold()
                        == expected_provider.strip().casefold()
                    )

                    if not (contract_matches and provider_matches):
                        identity_mismatch = True
                        st.error(
                            f"The uploaded rules do not match Hospital {hospital_number}. "
                            "Select the hospital that belongs to this rules file, or upload "
                            f"the Hospital {hospital_number} rules JSON."
                        )

            if not identity_mismatch:
                upload_signature = (
                    cache_key,
                    rules_upload.name,
                    getattr(rules_upload, "size", None),
                    loaded_spec.contract_number,
                )

                if st.session_state.get("_loaded_rules_signature") != upload_signature:
                    st.session_state["contract_spec"] = loaded_spec
                    st.session_state["contract_spec_source"] = "Uploaded contract rules JSON"
                    st.session_state["contract_spec_source_key"] = cache_key
                    st.session_state["rule_reviewed"] = False

                    # A new rule set invalidates any old mapping/audit outputs.
                    st.session_state.pop("mapping", None)
                    st.session_state.pop("predictions", None)
                    st.session_state.pop("line_audit", None)
                    st.session_state.pop("ai_explanations", None)

                    st.session_state["_loaded_rules_signature"] = upload_signature

                selected_label = (
                    f"Hospital {hospital_number}"
                    if mode == "provided"
                    else "the uploaded dataset"
                )
                st.success(f"Contract rules loaded for {selected_label}")

        except Exception:
            st.error(
                "This JSON file is not a valid contract-rules file generated by the app."
            )

    st.divider()
    st.markdown("#### AI assistance")

    use_ai_contract = st.toggle(
        "Use AI to read contract",
        value=True,
    )

    use_ai_mapping = st.toggle(
        "Use AI to help match unclear services",
        value=True,
        help="AI is used only when deterministic/local service matching is uncertain.",
    )

    st.caption(
        "AI helps interpret text; all financial calculations are performed in Python."
    )

    stored_key = get_secret_key()
    api_key = stored_key
    ai_enabled = bool(use_ai_contract or use_ai_mapping)

    if ai_enabled:
        if not stored_key:
            api_key = st.text_input(
                "OpenAI API key",
                type="password",
                help=(
                    "Used server-side for contract interpretation, optional ambiguous mapping, "
                    "and optional reviewer explanations. It is never written to disk."
                ),
            )
        if api_key:
            st.caption("✓ API key provided")
        else:
            st.caption("Add an API key to use AI features.")
    else:
        st.caption("AI assistance is off.")

    with st.expander("Advanced settings", expanded=False):
        model = st.selectbox(
            "Model",
            ["gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.6-luna"],
            index=0,
            help="Model used for contract interpretation and optional AI assistance.",
        )

        max_ai_items = st.number_input(
            "AI mapping limit",
            min_value=0,
            max_value=500,
            value=180,
            step=20,
            disabled=not use_ai_mapping,
            help="Maximum number of unresolved unique service descriptions sent for AI review.",
        )



# Load the selected data after the sidebar has collected the user's choices.
if mode == "provided":
    if hospital_number is None:
        source_label = "Select a hospital"
    else:
        source_label = f"Hospital {hospital_number}"
        try:
            invoices, lines = load_exercise_hospital(EXERCISE_ROOT, hospital_number)
            contract_files = exercise_contract_files(EXERCISE_ROOT, hospital_number)
            if hospital_number == 1:
                label_path = EXERCISE_ROOT / "labels" / "hospital_1_labels.csv"
                if label_path.exists():
                    labels = pd.read_csv(label_path)
        except Exception as exc:
            st.error(f"Could not load the provided hospital data: {exc}")
else:
    if invoice_file is not None and line_file is not None:
        try:
            invoices = read_csv_any(invoice_file)
            lines = read_csv_any(line_file)
            validate_columns(invoices, REQUIRED_INVOICE_COLUMNS, "Invoice CSV")
            validate_columns(lines, REQUIRED_LINE_COLUMNS, "Line-item CSV")
            source_label = "Uploaded dataset"
        except Exception as exc:
            st.error(str(exc))

def format_money_cents(value, currency: str | None) -> str:
    """Format integer cents for display without changing the underlying audit data."""
    if value is None or pd.isna(value):
        return "—"
    amount = float(value) / 100.0
    code = (currency or "").upper()
    symbols = {"GBP": "£", "USD": "$", "EUR": "€"}
    if code == "SAR":
        return f"SAR {amount:,.2f}"
    if code in symbols:
        return f"{symbols[code]}{amount:,.2f}"
    if code:
        return f"{code} {amount:,.2f}"
    return f"{amount:,.2f}"


# -----------------------------------------------------------------------------
# Main app tabs
# -----------------------------------------------------------------------------
tab_workflow, tab_contract, tab_results, tab_h1 = st.tabs(
    ["Workflow", "Contract", "Results", "H1 Validation"]
)


with tab_workflow:
    st.subheader(source_label or "Workflow")

    if mode == "provided" and hospital_number is None:
        st.info("Select a hospital from the sidebar to begin.")

    # Compact data summary.
    if contract_files:
        st.caption("✓ Contract loaded")
    else:
        st.warning("No contract document is loaded yet.")

    c1, c2, c3 = st.columns(3)
    c1.metric("Invoices", len(invoices) if invoices is not None else 0)
    c2.metric("Line items", len(lines) if lines is not None else 0)
    c3.metric(
        "Unique descriptions",
        int(lines["description"].nunique())
        if lines is not None and "description" in lines.columns
        else 0,
    )

    st.divider()
    st.markdown("### Workflow")
    st.caption("Complete the two steps from left to right.")

    # Keep the two primary workflow steps visually separated.
    contract_col, audit_col = st.columns(2, gap="large")

    # -------------------------------------------------------------------------
    # Step 1 — Contract analysis
    # -------------------------------------------------------------------------
    with contract_col:
        with st.container(border=True, height=370):
            st.caption("STEP 1")
            st.markdown("### Contract analysis")
            st.write("Extract services, rates, and billing rules from the contract.")

            analyze_col, reset_col = st.columns([2.2, 1])

            with analyze_col:
                extract_clicked = st.button(
                    "Analyze contract",
                    type="primary",
                    disabled=(not contract_files or not use_ai_contract),
                    use_container_width=True,
                )

            with reset_col:
                has_analysis = active_contract_spec(cache_key) is not None

                if st.button(
                    "Reset",
                    disabled=not has_analysis,
                    use_container_width=True,
                ):
                    reset_analysis_state()
                    st.rerun()

            if not use_ai_contract:
                st.caption(
                    "AI contract reading is off. Turn it on to analyze a new contract."
                )

            if extract_clicked:
                if not api_key:
                    st.warning(
                        "Add your OpenAI API key in the sidebar to analyze the contract."
                    )
                else:
                    with st.spinner("Analyzing contract..."):
                        try:
                            spec = extract_contract_spec(
                                contract_files,
                                api_key=api_key,
                                model=model,
                            )
                            st.session_state["contract_spec"] = spec
                            st.session_state["contract_spec_source"] = "OpenAI structured extraction"
                            st.session_state["contract_spec_source_key"] = cache_key
                            st.session_state["rule_reviewed"] = False
                            st.session_state.pop("mapping", None)
                            st.session_state.pop("predictions", None)
                            st.session_state.pop("line_audit", None)
                            save_contract_spec(PROJECT_ROOT, cache_key, spec)
                            st.session_state.pop("last_api_error", None)
                        except Exception as exc:
                            show_ai_error(exc)

            spec = active_contract_spec(cache_key)

            st.divider()
            if spec is not None:
                pricing_rule_count = (
                    len(spec.threshold_premiums)
                    + len(spec.weekend_uplifts)
                    + len(spec.volume_discounts)
                    + len(spec.facility_multipliers)
                    + len(spec.plan_multipliers)
                )
                st.markdown("**Status:** ✅ Contract rules ready")
                st.caption(
                    f"{len(spec.services)} services · "
                    f"{pricing_rule_count} pricing rules · "
                    f"{spec.extraction_confidence:.0%} confidence"
                )
            else:
                st.markdown("**Status:** Waiting for contract rules")
                st.caption("Analyze the contract or load reusable rules to continue.")

    # -------------------------------------------------------------------------
    # Step 2 — Invoice audit
    # -------------------------------------------------------------------------
    with audit_col:
        with st.container(border=True, height=370):
            st.caption("STEP 2")
            st.markdown("### Invoice audit")
            st.write(
                "Audit invoices using the extracted contract rules."
            )

            spec = active_contract_spec(cache_key)

            run_disabled = (
                invoices is None
                or lines is None
                or spec is None
            )

            run_clicked = st.button(
                "Run audit",
                type="primary",
                disabled=run_disabled,
                use_container_width=True,
            )

            # Run immediately below the button so the spinner appears directly under it.
            if run_clicked:
                with st.spinner("Mapping services and auditing invoices..."):
                    try:
                        # For bundled datasets, prefer a previously reviewed mapping
                        # snapshot when it exactly matches the current descriptions and
                        # contract service catalogue. This makes repeated audits
                        # reproducible and avoids spending API credits on the same
                        # ambiguous descriptions. Custom/new datasets still use the
                        # normal deterministic + optional AI mapping pipeline.
                        mapping = None
                        if mode == "provided":
                            mapping = load_reviewed_mapping_snapshot(
                                PROJECT_ROOT, cache_key, lines, spec
                            )

                        if mapping is None:
                            mapping = map_descriptions(
                                lines,
                                spec,
                                api_key=api_key if use_ai_mapping else None,
                                model=model,
                                use_ai_for_ambiguous=bool(use_ai_mapping and api_key),
                                max_ai_items=max_ai_items,
                            )
                        predictions, line_audit = audit_invoices(
                            invoices,
                            lines,
                            spec,
                            mapping,
                        )
                        st.session_state["mapping"] = mapping
                        st.session_state["predictions"] = predictions
                        st.session_state["line_audit"] = line_audit
                        st.session_state["source_label"] = source_label
                        st.session_state["ai_explanations"] = {}

                        ai_warning = mapping.attrs.get("ai_warning")
                        if ai_warning:
                            st.warning(
                                "AI mapping was unavailable. The audit continued using local matching, "
                                "and uncertain cases remain marked for review."
                            )

                        st.success("✓ Audit completed — view the Results tab.")
                    except Exception as exc:
                        show_ai_error(exc)

            st.divider()
            if spec is None:
                st.markdown("**Status:** 🔒 Waiting for Step 1")
                st.caption("Contract rules must be ready before the audit can run.")
            elif st.session_state.get("rule_reviewed", False):
                st.markdown("**Status:** ✅ Ready to audit")
                st.caption("Contract rules have been reviewed.")
            else:
                st.markdown("**Status:** Ready to test")
                st.caption(
                    "Review the Contract tab before treating the results as final."
                )

    # One compact review notice instead of multiple large warning blocks.
    spec = active_contract_spec(cache_key)
    if spec is not None:
        review_count = len(spec.ambiguities) + len(spec.unsupported_rules)
        if review_count:
            st.warning(
                f"⚠ {review_count} contract item(s) need review. "
                "See the Contract tab for details."
            )


with tab_contract:
    spec = active_contract_spec(cache_key)
    if spec is None:
        st.info("Analyze the contract first.")
    else:

        st.markdown("### Contract summary")

        c1, c2, c3, c4 = st.columns([1.5, 0.7, 1.6, 0.6])

        with c1:
            st.caption("Contract number")
            st.markdown(f"**{spec.contract_number or '—'}**")

        with c2:
            st.caption("Currency")
            st.markdown(f"**{spec.currency or '—'}**")

        with c3:
            st.caption("Effective period")

            start_date = spec.effective_from or "—"
            end_date = spec.effective_to or "—"

            st.markdown(
                f"**{start_date} → {end_date}**"
            )

        with c4:
            st.caption("Services")
            st.markdown(f"**{len(spec.services)}**")

        st.subheader("Contract rules")

        st.markdown("### Services and rates")
        service_rows = []
        for service in spec.services:
            for rate in service.rates:
                confidence = min(service.confidence, rate.confidence)
                service_rows.append(
                    {
                        "Service": service.service_name,
                        "Unit basis": service.unit_basis,
                        "Rate": format_money_cents(rate.rate_cents, spec.currency),
                        "From": rate.effective_from,
                        "To": rate.effective_to,
                        "Daily cap": service.daily_cap,
                        "Confidence": confidence,
                        "Source": rate.source_note,
                    }
                )
        service_df = pd.DataFrame(service_rows)
        st.dataframe(
            service_df,
            use_container_width=True,
            hide_index=True,
            column_config={"Confidence": st.column_config.ProgressColumn(format="percent", min_value=0.0, max_value=1.0)},
        )

        low_rule_count = int((service_df["Confidence"] < 0.80).sum()) if not service_df.empty else 0
        if low_rule_count:
            st.warning(f"{low_rule_count} service-rate row(s) are below 80% confidence.")

        st.markdown("### Pricing rules")
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Premiums / uplifts", len(spec.threshold_premiums) + len(spec.weekend_uplifts))
        r2.metric("Discounts", len(spec.volume_discounts))
        r3.metric("Bundles", len(spec.bundles))
        r4.metric("Exclusions", len(spec.exclusions))

        with st.expander("Pricing logic", expanded=False):
            st.caption("Order used by the deterministic pricing engine")
            st.code(" → ".join(spec.adjustment_order))
            if spec.facility_multipliers:
                st.markdown("**Facility multipliers**")
                st.dataframe(
                    pd.json_normalize([x.model_dump() for x in spec.facility_multipliers]),
                    use_container_width=True,
                    hide_index=True,
                )
            if spec.plan_multipliers:
                st.markdown("**Plan multipliers**")
                st.dataframe(
                    pd.json_normalize([x.model_dump() for x in spec.plan_multipliers]),
                    use_container_width=True,
                    hide_index=True,
                )

        special_tables = {
            "Premium rules": [x.model_dump() for x in spec.threshold_premiums],
            "Weekend / non-business-day rules": [x.model_dump() for x in spec.weekend_uplifts],
            "Volume discounts": [x.model_dump() for x in spec.volume_discounts],
            "Bundles": [x.model_dump() for x in spec.bundles],
            "Exclusions": [x.model_dump() for x in spec.exclusions],
        }
        for title, rows in special_tables.items():
            if rows:
                with st.expander(title, expanded=False):
                    st.dataframe(pd.json_normalize(rows), use_container_width=True, hide_index=True)

        if spec.interpretation_notes:
            with st.expander("Source and interpretation notes", expanded=False):
                for item in spec.interpretation_notes:
                    st.write(f"• {item}")

        if spec.ambiguities:
            st.warning(f"{len(spec.ambiguities)} contract clause(s) require review.")
            with st.expander("Review contract ambiguities", expanded=False):
                for item in spec.ambiguities:
                    st.write(f"• {item}")

        if spec.unsupported_rules:
            st.warning(f"{len(spec.unsupported_rules)} rule(s) require manual review or implementation.")
            with st.expander("Rules requiring manual review", expanded=False):
                for item in spec.unsupported_rules:
                    st.write(f"• {item}")

        reviewed = st.checkbox(
            "I reviewed the contract rules",
            value=bool(st.session_state.get("rule_reviewed", False)),
            key="rules_review_ack",
        )
        st.session_state["rule_reviewed"] = reviewed
        st.caption("Review the extracted rules before treating audit results as final.")



with tab_results:
    predictions = st.session_state.get("predictions")
    line_audit = st.session_state.get("line_audit")
    mapping = st.session_state.get("mapping")
    spec = active_contract_spec(cache_key)

    if predictions is None:
        st.info("Run an audit first.")
    else:
        st.subheader("Audit results")

        flagged = int(predictions["flagged"].sum())
        review_count = int(predictions["review_required"].sum())
        avg_conf = float(predictions["confidence"].mean()) if len(predictions) else 0.0
        avg_coverage = float(predictions["coverage"].mean()) if len(predictions) else 0.0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Audited", len(predictions))
        c2.metric("Flagged", flagged)
        c3.metric("Needs review", review_count)
        c4.metric("Confidence", f"{avg_conf:.1%}")
        st.caption(f"Service mapping coverage: {avg_coverage:.1%}")

        category_counts = (
            predictions.loc[predictions["error_category"].fillna("").ne(""), "error_category"]
            .str.split("|")
            .explode()
            .value_counts()
        )
        if not category_counts.empty:
            st.markdown("### Error categories")
            st.bar_chart(category_counts)
        else:
            st.success("No invoice errors were detected by the implemented rules.")

        st.markdown("### Invoice results")
        display_results = predictions.copy()
        currency = spec.currency if spec is not None else None
        display_results["Expected total"] = display_results["expected_total_cents"].apply(
            lambda x: format_money_cents(x, currency)
        )
        display_results["Billed total"] = display_results["billed_total_cents"].apply(
            lambda x: format_money_cents(x, currency)
        )
        display_results["Confidence"] = display_results["confidence"]
        display_results["Coverage"] = display_results["coverage"]
        display_results["Status"] = display_results["flagged"].map({True: "Flagged", False: "Clear"})
        display_results["Review"] = display_results["review_required"].map({True: "Yes", False: "No"})
        display_results = display_results.rename(
            columns={"invoice_id": "Invoice", "error_category": "Finding"}
        )
        result_cols = [
            "Invoice", "Status", "Finding", "Expected total", "Billed total", "Confidence", "Coverage", "Review"
        ]
        st.dataframe(
            display_results[result_cols].sort_values(["Status", "Confidence"], ascending=[False, True]),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Confidence": st.column_config.ProgressColumn(format="percent", min_value=0.0, max_value=1.0),
                "Coverage": st.column_config.ProgressColumn(format="percent", min_value=0.0, max_value=1.0),
            },
        )

        st.markdown("### Needs review")
        review_df = review_queue(predictions)
        if review_df.empty:
            st.success("No invoices currently require manual review.")
        else:
            review_display = review_df.copy()
            review_display["Confidence"] = review_display["confidence"]
            review_display["Coverage"] = review_display["coverage"]
            review_display = review_display.rename(
                columns={"invoice_id": "Invoice", "error_category": "Reason"}
            )
            review_cols = [c for c in ["Invoice", "Reason", "Confidence", "Coverage"] if c in review_display.columns]
            st.dataframe(
                review_display[review_cols],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Confidence": st.column_config.ProgressColumn(format="percent", min_value=0.0, max_value=1.0),
                    "Coverage": st.column_config.ProgressColumn(format="percent", min_value=0.0, max_value=1.0),
                },
            )

        if mapping is not None:
            low_map = mapping[
                mapping["service_name"].isna() | mapping["mapping_confidence"].lt(0.80)
            ].sort_values("mapping_confidence")
            if not low_map.empty:
                with st.expander(f"Low-confidence service mappings ({len(low_map)})", expanded=False):
                    low_cols = [
                        c for c in [
                            "description", "normalized_description", "service_name", "mapping_method", "mapping_confidence"
                        ] if c in low_map.columns
                    ]
                    st.dataframe(low_map[low_cols] if low_cols else low_map, use_container_width=True, hide_index=True)

        if line_audit is not None and spec is not None:
            st.markdown("### Invoice details")
            st.caption("Choose an invoice to inspect its audit result and source-record evidence.")

            options = (
                predictions
                .sort_values(["flagged", "review_required", "confidence"], ascending=[False, False, True])
                ["invoice_id"]
                .astype(str)
                .tolist()
            )

            selected = st.selectbox(
                "Select invoice",
                options,
                index=None,
                placeholder="Choose an invoice...",
                key="results_invoice_select",
            )

            if selected is None:
                st.info("Select an invoice above to view its audit details.")
            else:
                evidence = build_invoice_evidence(selected, predictions, line_audit, spec)

                duplicate_count = int(evidence.get("duplicate_record_count", 1) or 1)
                canonical_row_no = evidence.get("canonical_invoice_row_no")
                status = "Flagged" if evidence["flagged"] else "Clear"
                finding = (evidence.get("error_category") or "No detected issue").replace("|", ", ")

                s1, s2, s3, s4 = st.columns(4)
                s1.metric("Status", status)
                s2.metric(
                    "Submission billed total" if duplicate_count > 1 else "Billed total",
                    format_money_cents(evidence.get("billed_total_cents"), spec.currency),
                )
                s3.metric(
                    "Submission expected total" if duplicate_count > 1 else "Expected total",
                    format_money_cents(evidence.get("expected_total_cents"), spec.currency),
                )
                s4.metric("Confidence", f"{evidence.get('confidence', 0.0):.1%}")

                if evidence["flagged"]:
                    st.warning(f"Finding: {finding}")
                else:
                    st.success("No implemented audit issue was detected for this invoice.")

                review_text = "Yes" if evidence.get("review_required") else "No"
                st.caption(
                    f"Mapping coverage: {evidence.get('coverage', 0.0):.1%} · "
                    f"Human review required: {review_text}"
                )

                if duplicate_count > 1:
                    canonical_text = (
                        f" The submission uses the latest source record (row {canonical_row_no})."
                        if canonical_row_no is not None
                        else ""
                    )
                    st.warning(
                        f"Duplicate invoice ID: `{selected}` occurs in {duplicate_count} source invoice records."
                        f"{canonical_text} The records are shown separately below and are not summed together."
                    )

                def render_line_table(record_lines):
                    line_rows = []
                    for line in record_lines:
                        reasons = list(line.get("pricing_error_reasons") or [])
                        if line.get("wrong_unit_basis"):
                            reasons.append("wrong_unit_basis")
                        if line.get("line_arithmetic_error"):
                            reasons.append("line_total_arithmetic")
                        finding_text = ", ".join(dict.fromkeys(reasons)) if reasons else "—"

                        line_rows.append(
                            {
                                "Line": line.get("line_id"),
                                "Description": line.get("description"),
                                "Mapped service": line.get("mapped_service") or "UNRESOLVED",
                                "Mapping": line.get("mapping_method") or "—",
                                "Mapping confidence": line.get("mapping_confidence", 0.0),
                                "Billed rate": format_money_cents(line.get("billed_unit_price_cents"), spec.currency),
                                "Expected rate": format_money_cents(line.get("expected_unit_rate_cents"), spec.currency),
                                "Finding": finding_text,
                            }
                        )

                    line_summary = pd.DataFrame(line_rows)
                    if not line_summary.empty:
                        st.dataframe(
                            line_summary,
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "Mapping confidence": st.column_config.ProgressColumn(
                                    format="percent", min_value=0.0, max_value=1.0
                                )
                            },
                        )

                source_records = evidence.get("source_records") or []

                if duplicate_count > 1 and source_records:
                    st.markdown("#### Source invoice records")
                    for i, record in enumerate(source_records, start=1):
                        row_no = record.get("invoice_row_no")
                        label = f"Record {i}"
                        if row_no is not None:
                            label += f" · source row {row_no}"
                        if record.get("is_submission_record"):
                            label += " · submission record"

                        with st.expander(label, expanded=bool(record.get("is_submission_record"))):
                            r1, r2, r3 = st.columns(3)
                            r1.metric(
                                "Header billed total",
                                format_money_cents(record.get("billed_total_cents"), spec.currency),
                            )
                            r2.metric(
                                "Expected total",
                                format_money_cents(record.get("expected_total_cents"), spec.currency),
                            )
                            r3.metric("Lines", len(record.get("lines", [])))

                            details = []
                            if record.get("patient_id"):
                                details.append(f"Patient: {record.get('patient_id')}")
                            if record.get("invoice_date"):
                                details.append(f"Invoice date: {record.get('invoice_date')}")
                            if record.get("facility_code"):
                                details.append(f"Facility: {record.get('facility_code')}")
                            if record.get("plan_tier"):
                                details.append(f"Plan: {record.get('plan_tier')}")
                            if details:
                                st.caption(" · ".join(details))
                            if record.get("context_note"):
                                st.warning(record.get("context_note"))

                            render_line_table(record.get("lines", []))
                else:
                    st.markdown("#### Line items")
                    normal_lines = source_records[0].get("lines", []) if source_records else evidence.get("lines", [])
                    render_line_table(normal_lines)

                with st.expander("Detailed deterministic explanation", expanded=False):
                    st.markdown(deterministic_explanation_markdown(evidence))

                with st.expander("Technical evidence", expanded=False):
                    evidence_df = pd.DataFrame(evidence.get("lines", []))
                    st.dataframe(evidence_df, use_container_width=True, hide_index=True)

                with st.expander("AI summary", expanded=False):
                    st.caption(
                        "Optional: OpenAI rewrites the deterministic evidence in plain language. "
                        "It does not recalculate or change the audit finding."
                    )
                    if not api_key:
                        st.info("An API key with available credit is required only for this optional summary.")
                    else:
                        if st.button("Explain in plain language", key="ai_explain_btn"):
                            with st.spinner("Writing a plain-language explanation..."):
                                try:
                                    explanation = explain_audit_evidence(evidence, api_key=api_key, model=model)
                                    cache = st.session_state.setdefault("ai_explanations", {})
                                    cache[str(selected)] = explanation
                                    st.session_state.pop("last_api_error", None)
                                except Exception as exc:
                                    show_ai_error(exc)
                        cached_explanation = st.session_state.get("ai_explanations", {}).get(str(selected))
                        if cached_explanation:
                            st.info(cached_explanation)

        st.markdown("### Downloads")
        st.caption(
            "Contract rules are exported as JSON. Audit results are packaged as a ZIP containing the submission, review queue, service mappings, and line-level audit evidence."
        )

        prefix = cache_key
        d1, d2 = st.columns(2)

        with d1:
            if spec is not None:
                st.download_button(
                    "Download contract rules (JSON)",
                    spec.model_dump_json(indent=2),
                    file_name=f"{prefix}_contract_rules.json",
                    mime="application/json",
                    use_container_width=True,
                )

        with d2:
            st.download_button(
                "Download audit results (ZIP)",
                audit_results_zip_bytes(prefix, predictions, mapping, line_audit),
                file_name=f"{prefix}_audit_results.zip",
                mime="application/zip",
                type="primary",
                use_container_width=True,
            )


with tab_h1:
    st.subheader("Hospital 1 Validation")
    st.write(
        "Hospital 1 is the labeled development dataset used to validate the deterministic audit logic."
    )
    st.caption("This validation is fully offline and does not require OpenAI.")

    if st.button("Run validation", type="primary", use_container_width=False):
        with st.spinner("Running the validated Hospital 1 pipeline..."):
            try:
                evaluation, stdout = run_h1_reference(PROJECT_ROOT)
                st.session_state["h1_evaluation"] = evaluation
                st.session_state["h1_stdout"] = stdout
            except Exception as exc:
                st.error(f"Hospital 1 validation failed: {exc}")

    evaluation = st.session_state.get("h1_evaluation")
    if evaluation is not None:
        perfect = int(((evaluation["fp"] == 0) & (evaluation["fn"] == 0)).sum())
        a, b, c = st.columns(3)
        a.metric("Perfect categories", f"{perfect}/{len(evaluation)}")
        b.metric("Mean precision", f"{evaluation['precision'].mean():.3f}")
        c.metric("Mean recall", f"{evaluation['recall'].mean():.3f}")

        with st.expander("Detailed category results", expanded=False):
            st.dataframe(evaluation, use_container_width=True, hide_index=True)

        with st.expander("Validation run details", expanded=False):
            total_tp = int(evaluation["tp"].sum())
            total_fp = int(evaluation["fp"].sum())
            total_fn = int(evaluation["fn"].sum())

            r1, r2, r3 = st.columns(3)
            r1.metric("True positives", total_tp)
            r2.metric("False positives", total_fp)
            r3.metric("False negatives", total_fn)

            if total_fp == 0 and total_fn == 0:
                st.success(
                    f"Validation completed successfully: all {len(evaluation)} categories matched the labeled development set."
                )
            else:
                st.warning(
                    "Validation completed with differences. Review the detailed category results."
                )

            raw_log = st.session_state.get("h1_stdout", "")

            if raw_log:
                show_raw_log = st.checkbox(
                    "Show raw execution log",
                    value=False,
                    key="show_h1_raw_log",
                )

                if show_raw_log:
                    st.code(raw_log, language="text")


st.divider()
st.caption(
    "Design principle: AI helps interpret language; deterministic Python code calculates money and audit findings. "
    "Uncertainty remains visible for review."
)

