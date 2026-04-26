# FHIR Patient Viewer

FHIR Patient Viewer is a Streamlit web app for exploring patient data stored as FHIR R4 JSON bundles. It supports both bulk ZIP uploads and single-patient JSON uploads, then presents demographics, conditions, medications, encounters, vitals, labs, reports, immunizations, procedures, and population-level summaries.

## Features
- Bulk upload of ZIP archives containing multiple FHIR JSON bundles
- Single-patient upload for individual bundle review
- Patient demographics and summary metrics
- Interactive charts for vital signs and population insights
- Tables for conditions, medications, encounters, labs, diagnostic reports, immunizations, and procedures
- Compatible with Synthea-generated FHIR R4 bundles

## Project Files
- `fhir_patient_viewer.py` - main Streamlit application
- `requirements.txt` - Python dependencies for deployment

## Requirements
- Python 3.10 or newer recommended
- pip

## Local Setup
1. Open a terminal in this folder.
2. Create and activate a virtual environment.
3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Start the app:

```bash
streamlit run fhir_patient_viewer.py
```

5. Open the local URL shown in the terminal, usually:

```text
http://localhost:8501
```

## Deployment
This app is ready to deploy to platforms that support Streamlit apps, such as Streamlit Community Cloud, Render, or any VM/container running Python.

### Recommended start command
```bash
streamlit run fhir_patient_viewer.py --server.port $PORT --server.address 0.0.0.0
```

For platforms that do not provide a `PORT` environment variable, you can use the simpler command below:

```bash
streamlit run fhir_patient_viewer.py
```

## Input Data
The app accepts:
- `.zip` files containing multiple FHIR JSON bundles
- `.json` files containing a single FHIR bundle

## Notes
- The app uses in-memory session state and does not require a database.
- Upload larger ZIP files only on environments with sufficient memory.
- If you deploy to Streamlit Community Cloud, set the main file to `fhir_patient_viewer.py`.

## Troubleshooting
- If `streamlit` is not recognized, install dependencies again with `pip install -r requirements.txt`.
- If charts do not render, confirm `plotly` installed successfully.
- If uploads fail, verify the input files are valid FHIR JSON bundles.
