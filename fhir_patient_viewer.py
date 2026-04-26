"""
FHIR Patient Data Viewer — Streamlit App
Supports both bulk upload (ZIP of FHIR JSON bundles) and single patient upload.
Compatible with Synthea-generated FHIR R4 cardiology bundles.
"""

import streamlit as st
import json
import zlib
import struct
import re
import zipfile
import io
from datetime import datetime, date
from collections import defaultdict
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# ─────────────────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="FHIR Patient Viewer",
    page_icon="🫀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# CUSTOM CSS
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
    /* Main header */
    .main-header {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        padding: 1.5rem 2rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        color: white;
    }
    .main-header h1 { margin: 0; font-size: 2rem; font-weight: 700; }
    .main-header p  { margin: 0.3rem 0 0; opacity: 0.8; font-size: 0.95rem; }

    /* Patient card */
    .patient-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem;
        border-radius: 12px;
        color: white;
        margin-bottom: 1rem;
    }
    .patient-name { font-size: 1.6rem; font-weight: 700; margin-bottom: 0.2rem; }
    .patient-meta { opacity: 0.85; font-size: 0.9rem; }

    /* Metric card */
    .metric-row { display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 1rem; }
    .metric-card {
        flex: 1; min-width: 120px;
        background: #f8f9fa;
        border: 1px solid #e9ecef;
        border-radius: 10px;
        padding: 0.9rem 1rem;
        text-align: center;
    }
    .metric-card .val { font-size: 1.8rem; font-weight: 700; color: #1a1a2e; }
    .metric-card .lbl { font-size: 0.75rem; color: #6c757d; text-transform: uppercase; letter-spacing: 0.05em; }

    /* Section header */
    .section-header {
        font-size: 1.05rem;
        font-weight: 600;
        color: #1a1a2e;
        border-left: 4px solid #667eea;
        padding-left: 0.7rem;
        margin: 1.2rem 0 0.7rem;
    }

    /* Status badges */
    .badge {
        display: inline-block;
        padding: 0.2em 0.65em;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 600;
    }
    .badge-active   { background: #d4edda; color: #155724; }
    .badge-inactive { background: #f8d7da; color: #721c24; }
    .badge-resolved { background: #d1ecf1; color: #0c5460; }
    .badge-amber    { background: #fff3cd; color: #856404; }

    /* Sidebar patient list */
    div[data-testid="stSidebarContent"] .patient-item {
        padding: 0.5rem 0.75rem;
        border-radius: 8px;
        cursor: pointer;
        margin-bottom: 0.3rem;
    }

    /* Upload zone */
    .upload-zone {
        border: 2px dashed #667eea;
        border-radius: 12px;
        padding: 2rem;
        text-align: center;
        background: #f0f2ff;
        color: #667eea;
    }
    .upload-icon { font-size: 2.5rem; }

    /* Table tweaks */
    .dataframe { font-size: 0.85rem !important; }
    thead th { background: #1a1a2e !important; color: white !important; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# FHIR PARSING HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _get_coding_display(field: dict | None) -> str:
    if not field:
        return ""
    if "text" in field:
        return field["text"]
    codings = field.get("coding", [])
    if codings:
        return codings[0].get("display", codings[0].get("code", ""))
    return ""


def _age_from_dob(dob_str: str, deceased: str | None = None) -> str:
    try:
        dob = datetime.strptime(dob_str[:10], "%Y-%m-%d").date()
        ref = datetime.strptime(deceased[:10], "%Y-%m-%d").date() if deceased else date.today()
        years = (ref - dob).days // 365
        return str(years)
    except Exception:
        return "?"


def parse_patient(res: dict) -> dict:
    names   = res.get("name", [{}])
    official = next((n for n in names if n.get("use") == "official"), names[0] if names else {})
    given   = " ".join(official.get("given", []))
    family  = official.get("family", "")
    prefix  = " ".join(official.get("prefix", []))
    full    = f"{prefix} {given} {family}".strip()

    addr_list = res.get("address", [{}])
    addr  = addr_list[0] if addr_list else {}
    city  = addr.get("city", "")
    state = addr.get("state", "")
    country = addr.get("country", "")
    location = ", ".join(filter(None, [city, state, country]))

    deceased = res.get("deceasedDateTime")
    race_ext = next(
        (e for e in res.get("extension", [])
         if "race" in e.get("url", "")), None
    )
    race = ""
    if race_ext:
        for sub in race_ext.get("extension", []):
            if sub.get("url") == "text":
                race = sub.get("valueString", "")
                break

    marital = _get_coding_display(res.get("maritalStatus"))

    return {
        "id":         res.get("id", ""),
        "name":       full,
        "given":      given,
        "family":     family,
        "gender":     res.get("gender", "").capitalize(),
        "birthDate":  res.get("birthDate", ""),
        "deceased":   deceased,
        "age":        _age_from_dob(res.get("birthDate", ""), deceased),
        "location":   location,
        "race":       race,
        "marital":    marital,
        "language":   (res.get("communication") or [{}])[0]
                        .get("language", {}).get("text", ""),
    }


def parse_bundle(bundle: dict) -> dict:
    resources = defaultdict(list)
    for entry in bundle.get("entry", []):
        r = entry.get("resource", {})
        rt = r.get("resourceType")
        if rt:
            resources[rt].append(r)

    patient_res = resources.get("Patient", [{}])[0]
    patient_info = parse_patient(patient_res)

    # ── Conditions ────────────────────────────────────────────────────────
    conditions = []
    for c in resources.get("Condition", []):
        status   = _get_coding_display(c.get("clinicalStatus"))
        onset    = c.get("onsetDateTime", c.get("onsetPeriod", {}).get("start", ""))
        abated   = c.get("abatementDateTime", "")
        conditions.append({
            "Condition":   _get_coding_display(c.get("code")),
            "Status":      status.capitalize(),
            "Onset":       onset[:10] if onset else "",
            "Resolved":    abated[:10] if abated else "",
            "id":          c.get("id", ""),
        })

    # ── Medications ───────────────────────────────────────────────────────
    medications = []
    for m in resources.get("MedicationRequest", []):
        med_cc = m.get("medicationCodeableConcept", {})
        medications.append({
            "Medication":  _get_coding_display(med_cc),
            "Status":      m.get("status", "").capitalize(),
            "Authored":    (m.get("authoredOn", "") or "")[:10],
            "Intent":      m.get("intent", "").capitalize(),
        })

    # ── Encounters ────────────────────────────────────────────────────────
    encounters = []
    for e in resources.get("Encounter", []):
        enc_type = (e.get("type") or [{}])[0]
        period   = e.get("period", {})
        cls      = e.get("class", {}).get("code", "")
        encounters.append({
            "Type":   _get_coding_display(enc_type),
            "Class":  cls.upper(),
            "Start":  (period.get("start") or "")[:10],
            "End":    (period.get("end") or "")[:10],
            "Status": e.get("status", "").capitalize(),
        })

    # ── Observations (vital signs & labs) ────────────────────────────────
    vitals = []
    labs   = []
    for obs in resources.get("Observation", []):
        cats = [c.get("code") for cat in obs.get("category", []) for c in cat.get("coding", [])]
        display = _get_coding_display(obs.get("code"))
        date_str = (obs.get("effectiveDateTime") or "")[:10]
        val_q   = obs.get("valueQuantity")
        val_cc  = obs.get("valueCodeableConcept")
        val_str = obs.get("valueString", "")
        comp    = obs.get("component", [])

        if val_q:
            value = f"{val_q.get('value', '')} {val_q.get('unit', '')}".strip()
        elif val_cc:
            value = _get_coding_display(val_cc)
        elif val_str:
            value = val_str
        elif comp:
            parts = []
            for c in comp:
                cv = c.get("valueQuantity", {})
                cd = _get_coding_display(c.get("code"))
                parts.append(f"{cd}: {cv.get('value','')} {cv.get('unit','')}".strip())
            value = " | ".join(parts)
        else:
            value = ""

        row = {"Observation": display, "Value": value, "Date": date_str}

        if "vital-signs" in cats:
            vitals.append(row)
        else:
            labs.append(row)

    # ── Immunizations ─────────────────────────────────────────────────────
    immunizations = []
    for imm in resources.get("Immunization", []):
        immunizations.append({
            "Vaccine":  _get_coding_display(imm.get("vaccineCode")),
            "Date":     (imm.get("occurrenceDateTime") or "")[:10],
            "Status":   imm.get("status", "").capitalize(),
        })

    # ── Procedures ────────────────────────────────────────────────────────
    procedures = []
    for proc in resources.get("Procedure", []):
        perf = proc.get("performedPeriod") or {}
        procedures.append({
            "Procedure": _get_coding_display(proc.get("code")),
            "Status":    proc.get("status", "").capitalize(),
            "Date":      (perf.get("start") or proc.get("performedDateTime") or "")[:10],
        })

    # ── DiagnosticReports ─────────────────────────────────────────────────
    reports = []
    for dr in resources.get("DiagnosticReport", []):
        reports.append({
            "Report":  _get_coding_display(dr.get("code")),
            "Status":  dr.get("status", "").capitalize(),
            "Date":    (dr.get("effectiveDateTime") or dr.get("issued") or "")[:10],
        })

    return {
        "patient":        patient_info,
        "conditions":     conditions,
        "medications":    medications,
        "encounters":     encounters,
        "vitals":         vitals,
        "labs":           labs,
        "immunizations":  immunizations,
        "procedures":     procedures,
        "reports":        reports,
        "summary": {
            "conditions":    len(conditions),
            "medications":   len(medications),
            "encounters":    len(encounters),
            "observations":  len(vitals) + len(labs),
            "procedures":    len(procedures),
            "immunizations": len(immunizations),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# ZIP EXTRACTION  (handles truncated zips with data-descriptor flags)
# ─────────────────────────────────────────────────────────────────────────────

def _extract_local_json_entries_raw(raw_bytes: bytes) -> list[tuple[str, bytes]]:
    """
    Extract (filename, json_bytes) from a ZIP that may lack a central directory
    (e.g. macOS-generated archives uploaded without the EOCD record).
    Uses PK\x03\x04 local-file headers + data-descriptor boundaries.
    """
    offsets = []
    for m in re.finditer(b"PK\x03\x04", raw_bytes):
        off = m.start()
        name_len  = struct.unpack_from("<H", raw_bytes, off + 26)[0]
        extra_len = struct.unpack_from("<H", raw_bytes, off + 28)[0]
        name = raw_bytes[off + 30: off + 30 + name_len].decode("utf-8", errors="replace")
        data_start = off + 30 + name_len + extra_len
        offsets.append((off, name, data_start))

    results = []
    json_idx = [(i, off, name, ds) for i, (off, name, ds) in enumerate(offsets)
                if name.endswith(".json") and "__MACOSX" not in name]

    all_offs = [o[0] for o in offsets]

    for idx, off, name, data_start in json_idx:
        # Find next local-header offset
        my_pos = all_offs.index(off)
        if my_pos + 1 < len(all_offs):
            next_off = all_offs[my_pos + 1]
        else:
            next_off = len(raw_bytes)

        # Strip 16-byte data descriptor (PK\x07\x08 + CRC + compSize + uncompSize)
        potential_dd = next_off - 16
        comp_end = potential_dd if raw_bytes[potential_dd:potential_dd + 4] == b"PK\x07\x08" else next_off - 12

        compressed = raw_bytes[data_start:comp_end]
        try:
            method = struct.unpack_from("<H", raw_bytes, off + 8)[0]
            if method == 8:
                decompressed = zlib.decompress(compressed, -15)
            else:
                decompressed = compressed
            results.append((name, decompressed))
        except Exception:
            pass  # skip corrupt entries

    return results


def load_bundles_from_zip(uploaded_file) -> dict[str, dict]:
    """Returns {filename: parsed_bundle_dict}."""
    raw = uploaded_file.read()
    bundles = {}

    # Try standard zipfile first
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for info in zf.infolist():
                if info.filename.endswith(".json") and "__MACOSX" not in info.filename:
                    content = zf.read(info.filename)
                    try:
                        bundle = json.loads(content)
                        label = info.filename.split("/")[-1].replace(".json", "")
                        bundles[label] = parse_bundle(bundle)
                    except json.JSONDecodeError:
                        pass
        if bundles:
            return bundles
    except Exception:
        pass

    # Fallback: manual local-header scan (handles truncated / EOCD-less ZIPs)
    for fname, json_bytes in _extract_local_json_entries_raw(raw):
        try:
            bundle = json.loads(json_bytes.decode("utf-8"))
            label = fname.split("/")[-1].replace(".json", "")
            bundles[label] = parse_bundle(bundle)
        except Exception:
            pass

    return bundles


def load_single_json(uploaded_file) -> dict | None:
    try:
        content = uploaded_file.read()
        bundle  = json.loads(content)
        return parse_bundle(bundle)
    except Exception as e:
        st.error(f"Could not parse FHIR JSON: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# DISPLAY HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def status_badge(status: str) -> str:
    s = (status or "").lower()
    if s in ("active", "final", "completed", "finished"):
        cls = "badge-active"
    elif s in ("inactive", "entered-in-error", "cancelled"):
        cls = "badge-inactive"
    elif s in ("resolved", "stopped"):
        cls = "badge-resolved"
    else:
        cls = "badge-amber"
    return f'<span class="badge {cls}">{status}</span>'


def show_df(rows: list[dict], height: int = 300):
    if not rows:
        st.info("No records found.")
        return
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, height=height, hide_index=True)


def vitals_timeline(vitals: list[dict], vital_name: str):
    """Plot a specific vital sign over time."""
    rows = [v for v in vitals if vital_name.lower() in v["Observation"].lower()]
    if not rows:
        return
    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"]).sort_values("Date")

    # Extract numeric value
    def extract_num(s):
        try:
            return float(str(s).split()[0])
        except Exception:
            return None

    df["NumericValue"] = df["Value"].apply(extract_num)
    df_clean = df.dropna(subset=["NumericValue"])
    if df_clean.empty:
        return

    unit = df_clean["Value"].iloc[0].split()[-1] if df_clean["Value"].iloc[0].split() else ""
    fig = px.line(
        df_clean, x="Date", y="NumericValue",
        markers=True,
        labels={"NumericValue": unit, "Date": ""},
        title=vital_name,
        template="plotly_white",
    )
    fig.update_traces(line_color="#667eea", marker_color="#764ba2")
    fig.update_layout(margin=dict(l=10, r=10, t=40, b=10), height=280)
    st.plotly_chart(fig, use_container_width=True)


def show_patient_dashboard(data: dict):
    p   = data["patient"]
    sm  = data["summary"]

    # ── Patient header ─────────────────────────────────────────────────────
    deceased_tag = "  🕊 Deceased" if p.get("deceased") else ""
    st.markdown(f"""
    <div class="patient-card">
        <div class="patient-name">{p['name']}{deceased_tag}</div>
        <div class="patient-meta">
            {p['gender']} · Age {p['age']} · DOB {p['birthDate']}
            &nbsp;|&nbsp; {p['location']}
            &nbsp;|&nbsp; {p['race'] or 'Race unknown'}
            &nbsp;|&nbsp; {p['marital'] or ''}
        </div>
        <div class="patient-meta" style="margin-top:0.3rem;opacity:0.7;font-size:0.8rem;">
            FHIR ID: {p['id']}
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Summary metrics ────────────────────────────────────────────────────
    cols = st.columns(6)
    metrics = [
        ("🩺", sm["conditions"],   "Conditions"),
        ("💊", sm["medications"],  "Medications"),
        ("🏥", sm["encounters"],   "Encounters"),
        ("📊", sm["observations"], "Observations"),
        ("⚕️", sm["procedures"],   "Procedures"),
        ("💉", sm["immunizations"],"Immunizations"),
    ]
    for col, (icon, val, lbl) in zip(cols, metrics):
        col.metric(label=f"{icon} {lbl}", value=val)

    st.divider()

    # ── Tabs ───────────────────────────────────────────────────────────────
    tabs = st.tabs([
        "🩺 Conditions", "💊 Medications", "🏥 Encounters",
        "📈 Vitals", "🔬 Labs & Reports", "💉 Immunizations",
        "⚕️ Procedures",
    ])

    # ── Conditions ─────────────────────────────────────────────────────────
    with tabs[0]:
        st.markdown('<div class="section-header">Active & Historical Conditions</div>', unsafe_allow_html=True)
        if data["conditions"]:
            active   = [c for c in data["conditions"] if c["Status"].lower() == "active"]
            inactive = [c for c in data["conditions"] if c["Status"].lower() != "active"]
            if active:
                st.markdown("**Active**")
                show_df(active)
            if inactive:
                st.markdown("**Resolved / Inactive**")
                show_df(inactive)
        else:
            st.info("No conditions recorded.")

    # ── Medications ────────────────────────────────────────────────────────
    with tabs[1]:
        st.markdown('<div class="section-header">Medication Requests</div>', unsafe_allow_html=True)
        show_df(data["medications"])

    # ── Encounters ─────────────────────────────────────────────────────────
    with tabs[2]:
        st.markdown('<div class="section-header">Encounter History</div>', unsafe_allow_html=True)
        if data["encounters"]:
            df_enc = pd.DataFrame(data["encounters"])
            df_enc["Start"] = pd.to_datetime(df_enc["Start"], errors="coerce")
            df_enc = df_enc.sort_values("Start", ascending=False)
            df_enc["Start"] = df_enc["Start"].dt.strftime("%Y-%m-%d")
            st.dataframe(df_enc, use_container_width=True, hide_index=True)

            # Encounter type distribution
            st.markdown('<div class="section-header">Encounter Types</div>', unsafe_allow_html=True)
            type_counts = df_enc["Type"].value_counts().reset_index()
            type_counts.columns = ["Type", "Count"]
            fig = px.bar(
                type_counts.head(15), x="Count", y="Type",
                orientation="h", template="plotly_white",
                color_discrete_sequence=["#667eea"],
            )
            fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=350, yaxis_title="")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No encounters recorded.")

    # ── Vitals ─────────────────────────────────────────────────────────────
    with tabs[3]:
        st.markdown('<div class="section-header">Vital Signs Over Time</div>', unsafe_allow_html=True)
        key_vitals = [
            "Body Height", "Body Weight", "Heart rate",
            "Diastolic Blood Pressure", "Systolic Blood Pressure",
            "Body Mass Index", "Respiratory rate",
        ]
        selected = st.multiselect(
            "Select vitals to chart:",
            options=key_vitals,
            default=["Systolic Blood Pressure", "Diastolic Blood Pressure", "Heart rate"],
        )
        if selected:
            chart_cols = st.columns(min(len(selected), 2))
            for i, vital in enumerate(selected):
                with chart_cols[i % 2]:
                    vitals_timeline(data["vitals"], vital)
        else:
            st.info("Select at least one vital sign above.")

        with st.expander("📋 Full vitals table"):
            show_df(sorted(data["vitals"], key=lambda x: x["Date"], reverse=True), height=400)

    # ── Labs & Reports ─────────────────────────────────────────────────────
    with tabs[4]:
        col1, col2 = st.columns([1, 1])
        with col1:
            st.markdown('<div class="section-header">Lab Observations</div>', unsafe_allow_html=True)
            search = st.text_input("🔍 Filter observations", key="obs_search")
            labs_f = [l for l in data["labs"] if search.lower() in l["Observation"].lower()] if search else data["labs"]
            show_df(sorted(labs_f, key=lambda x: x["Date"], reverse=True), height=380)
        with col2:
            st.markdown('<div class="section-header">Diagnostic Reports</div>', unsafe_allow_html=True)
            show_df(sorted(data["reports"], key=lambda x: x["Date"], reverse=True), height=380)

    # ── Immunizations ──────────────────────────────────────────────────────
    with tabs[5]:
        st.markdown('<div class="section-header">Immunization Record</div>', unsafe_allow_html=True)
        show_df(sorted(data["immunizations"], key=lambda x: x["Date"], reverse=True))

    # ── Procedures ─────────────────────────────────────────────────────────
    with tabs[6]:
        st.markdown('<div class="section-header">Procedures</div>', unsafe_allow_html=True)
        show_df(sorted(data["procedures"], key=lambda x: x["Date"], reverse=True))


# ─────────────────────────────────────────────────────────────────────────────
# BULK OVERVIEW
# ─────────────────────────────────────────────────────────────────────────────

def show_population_overview(bundles: dict[str, dict]):
    st.markdown('<div class="section-header">Population Overview</div>', unsafe_allow_html=True)

    rows = []
    for label, data in bundles.items():
        p  = data["patient"]
        sm = data["summary"]
        rows.append({
            "Name":         p["name"],
            "Gender":       p["gender"],
            "Age":          int(p["age"]) if p["age"].isdigit() else None,
            "DOB":          p["birthDate"],
            "Location":     p["location"],
            "Conditions":   sm["conditions"],
            "Medications":  sm["medications"],
            "Encounters":   sm["encounters"],
            "Observations": sm["observations"],
            "Deceased":     "Yes" if p.get("deceased") else "No",
            "_key":         label,
        })

    df = pd.DataFrame(rows)

    # KPI row
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total Patients", len(df))
    k2.metric("Avg Age", f"{df['Age'].mean():.0f}" if df["Age"].notna().any() else "?")
    k3.metric("Female", int((df["Gender"] == "Female").sum()))
    k4.metric("Male",   int((df["Gender"] == "Male").sum()))

    # Charts row
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown('<div class="section-header">Gender Distribution</div>', unsafe_allow_html=True)
        gdf = df["Gender"].value_counts().reset_index()
        gdf.columns = ["Gender", "Count"]
        fig = px.pie(gdf, names="Gender", values="Count",
                     color_discrete_sequence=["#667eea", "#764ba2", "#a29bfe"],
                     template="plotly_white")
        fig.update_layout(margin=dict(l=5, r=5, t=5, b=5), height=250)
        st.plotly_chart(fig, use_container_width=True)

    with c2:
        st.markdown('<div class="section-header">Age Distribution</div>', unsafe_allow_html=True)
        fig2 = px.histogram(df.dropna(subset=["Age"]), x="Age", nbins=20,
                            color_discrete_sequence=["#667eea"],
                            template="plotly_white")
        fig2.update_layout(margin=dict(l=5, r=5, t=5, b=5), height=250, bargap=0.05)
        st.plotly_chart(fig2, use_container_width=True)

    with c3:
        st.markdown('<div class="section-header">Avg Records per Patient</div>', unsafe_allow_html=True)
        avg_data = {
            "Category": ["Conditions", "Medications", "Encounters", "Observations"],
            "Average":  [
                df["Conditions"].mean(), df["Medications"].mean(),
                df["Encounters"].mean(), df["Observations"].mean(),
            ],
        }
        fig3 = px.bar(avg_data, x="Category", y="Average",
                      color_discrete_sequence=["#667eea"],
                      template="plotly_white")
        fig3.update_layout(margin=dict(l=5, r=5, t=5, b=5), height=250)
        st.plotly_chart(fig3, use_container_width=True)

    # Patient table
    st.markdown('<div class="section-header">Patient Roster</div>', unsafe_allow_html=True)
    display_df = df.drop(columns=["_key"])
    st.dataframe(display_df, use_container_width=True, hide_index=True, height=400)


# ─────────────────────────────────────────────────────────────────────────────
# SESSION STATE INIT
# ─────────────────────────────────────────────────────────────────────────────

if "bundles"       not in st.session_state: st.session_state.bundles       = {}
if "selected_key"  not in st.session_state: st.session_state.selected_key  = None
if "upload_mode"   not in st.session_state: st.session_state.upload_mode   = "Bulk (ZIP)"


# ─────────────────────────────────────────────────────────────────────────────
# APP HEADER
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("""
<div class="main-header">
    <h1>🫀 FHIR Patient Viewer</h1>
    <p>Cardiology patient data explorer — FHIR R4 Bundle format</p>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR — UPLOAD + NAVIGATION
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ⚙️ Upload Data")

    mode = st.radio(
        "Upload mode",
        ["Bulk (ZIP)", "Single Patient (JSON)"],
        index=0 if st.session_state.upload_mode == "Bulk (ZIP)" else 1,
        horizontal=True,
    )
    st.session_state.upload_mode = mode

    st.divider()

    if mode == "Bulk (ZIP)":
        uploaded = st.file_uploader(
            "Upload a ZIP of FHIR JSON bundles",
            type=["zip"],
            key="zip_uploader",
        )
        if uploaded:
            with st.spinner(f"Parsing {uploaded.name} …"):
                bundles = load_bundles_from_zip(uploaded)
            if bundles:
                st.session_state.bundles = bundles
                st.session_state.selected_key = None
                st.success(f"✅ Loaded {len(bundles)} patients")
            else:
                st.error("No valid FHIR bundles found in ZIP.")

    else:  # Single patient
        uploaded = st.file_uploader(
            "Upload a single FHIR JSON bundle",
            type=["json"],
            key="json_uploader",
        )
        if uploaded:
            with st.spinner("Parsing …"):
                parsed = load_single_json(uploaded)
            if parsed:
                key = parsed["patient"]["name"] or uploaded.name
                st.session_state.bundles = {key: parsed}
                st.session_state.selected_key = key
                st.success(f"✅ Loaded: {key}")

    # ── Patient list ──────────────────────────────────────────────────────
    if st.session_state.bundles:
        st.divider()
        st.markdown("### 👥 Patients")

        search_q = st.text_input("🔍 Search patients", placeholder="Name or location…")

        # Sort and filter
        all_keys = sorted(
            st.session_state.bundles.keys(),
            key=lambda k: st.session_state.bundles[k]["patient"]["name"],
        )
        if search_q:
            q = search_q.lower()
            all_keys = [k for k in all_keys if
                        q in st.session_state.bundles[k]["patient"]["name"].lower() or
                        q in st.session_state.bundles[k]["patient"]["location"].lower()]

        if mode == "Bulk (ZIP)":
            overview_btn = st.button("📊 Population Overview", use_container_width=True)
            if overview_btn:
                st.session_state.selected_key = None

        st.markdown(f"*{len(all_keys)} patients*")

        for key in all_keys:
            p   = st.session_state.bundles[key]["patient"]
            dec = " 🕊" if p.get("deceased") else ""
            label = f"{p['name']}{dec}\n{p['gender']}, {p['age']} yrs · {p['location']}"
            if st.button(label, key=f"btn_{key}", use_container_width=True):
                st.session_state.selected_key = key


# ─────────────────────────────────────────────────────────────────────────────
# MAIN CONTENT
# ─────────────────────────────────────────────────────────────────────────────

if not st.session_state.bundles:
    # Landing page
    st.markdown("""
    ### Welcome! Upload patient data to get started.

    **Supported formats:**
    - **Bulk upload** — ZIP file containing multiple FHIR R4 JSON bundles  
      *(e.g. `cardiology_100_fhir.zip` from Synthea)*
    - **Single patient** — A single FHIR JSON bundle file

    **What you'll see:**
    - Patient demographics & summary
    - Conditions, medications, and encounters
    - Interactive vital-sign timelines
    - Lab observations and diagnostic reports
    - Immunization records and procedures
    - Population-level charts (bulk mode)
    """)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("""
        <div class="upload-zone">
            <div class="upload-icon">🗂️</div>
            <h4>Bulk Upload</h4>
            <p>Upload a ZIP archive of FHIR patient bundles<br>to explore the full cohort.</p>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown("""
        <div class="upload-zone">
            <div class="upload-icon">📄</div>
            <h4>Single Patient</h4>
            <p>Upload one FHIR JSON bundle<br>to view an individual patient record.</p>
        </div>
        """, unsafe_allow_html=True)

elif st.session_state.selected_key is None and st.session_state.upload_mode == "Bulk (ZIP)":
    # Population overview
    show_population_overview(st.session_state.bundles)

elif st.session_state.selected_key and st.session_state.selected_key in st.session_state.bundles:
    # Individual patient dashboard
    show_patient_dashboard(st.session_state.bundles[st.session_state.selected_key])

else:
    st.info("Select a patient from the sidebar.")
