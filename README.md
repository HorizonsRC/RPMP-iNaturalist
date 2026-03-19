# RPMP iNaturalist Dashboard

Repository supporting the **RPMP iNaturalist Dashboard** on AGOL Experience Builder.  
Contains Python pipelines for extracting and processing iNaturalist observations, automated data exports, and HTML files embedded in the dashboard interface.

---

## What This Repo Does

Horizons Regional Council uses a [iNaturalist](https://www.inaturalist.org/projects/horizons-regional-council-pest-plants) collection project on iNaturalist that automatically aggregates public observations of RPMP pest plant species made within the regional boundary. 

This repo automates the process of:

1. **Pulling observations** from the iNaturalist API
2. **Categorising them** by RPMP programme (Eradication, Progressive Containment, Exclusion)
3. **Spatially joining** them to SMU (Species Management Unit) polygons and operating areas
4. **Exporting** the results to an internal GDB and pushing them to ArcGIS Online (AGOL)
5. **Sending email alerts** to field staff when new priority observations are recorded
6. **Updating a JSON file** (`dashboard_data.json`) that feeds the embedded HTML dashboard in AGOL Experience Builder

---

## Repo Structure

```
RPMP-iNaturalist/
│
├── scripts/
│   ├── RPMP_iNat_PROD.py            # Main pipeline — runs twice daily via Task Scheduler
│   ├── iNat_Dashboard_Export.py     # Dashboard JSON updater — runs after main pipeline
│   └── inat_email_notifications.py  # Email alert module — called by the main pipeline
│
├── html/
│   └── [embedded HTML files]        # HTML widgets embedded in the AGOL ExB dashboard
│
├── dashboard_data.json              # Auto-updated by iNat_Dashboard_Export.py — do not edit manually
│
├── config.example.py                # Template for config.py
├── config.py                        # LOCAL ONLY — never committed (in .gitignore)
├── .gitignore
└── README.md
```

---

## Setup (New Machine)

### 1. Clone the repo
```
git clone https://github.com/HorizonsRC/RPMP-iNaturalist.git
cd RPMP-iNaturalist
```

### 2. Create your config file
```
copy config.example.py config.py
```
Open `config.py` and fill in the real values — see the comments inside for guidance.  
**Never commit `config.py` to GitHub.** It is listed in `.gitignore` so Git will ignore it automatically.

### 3. Install dependencies
This project runs inside the **ArcGIS Pro Python environment** (which includes `arcpy`).  
Open the ArcGIS Pro Python command prompt and run:
```
pip install geopandas requests requests-oauthlib gitpython arcgis
```

### 4. Set up the iNaturalist token
On first run, you need to generate an OAuth token by running the notebook version (`RPMP_iNat.ipynb`).  
The token is saved to the path set in `config.py` (`INAT_TOKEN_FILE`) and reused automatically after that.

---

## Scripts

### `RPMP_iNat_PROD.py` — Main Pipeline

**What it does:**
- Authenticates with the iNaturalist API using a stored OAuth token
- Fetches all observations from the Horizons RPMP iNaturalist project
- Categorises each observation by programme (Eradication / Progressive Containment / Exclusion)
- Performs spatial joins against SMU polygon layers in the internal GDB
- Exports four feature classes to the output GDB:
  - `iNat_Eradication`
  - `iNat_ProgressiveContainment`
  - `iNat_Exclusion`
  - `iNat_AllProgrammes`
- Pushes updated features to the hosted AGOL feature service
- Detects new observations since the last run and sends email alerts to relevant field staff

**Schedule:** Runs twice daily via Windows Task Scheduler (set up on local machine).

**Logs:** Written to the `Logs/` folder (ignored by Git).

---

### `inat_email_notifications.py` — Email Alert Module

**What it does:**
- Called by `RPMP_iNat_PROD.py` — not run directly
- Sends **immediate alerts** to the responsible field staff member when new Eradication or Exclusion species are detected
- Sends **weekly summaries** every Friday including Progressive Containment (AMZ) observations
- Sends a **run summary** to the admin email after every pipeline run (success or failure)
- Sends a **token expiry warning** if the iNaturalist OAuth token needs to be refreshed

**Email recipients** are configured in `config.py` via `STAFF_EMAILS` and `AREA_TO_STAFF` — kept out of GitHub because they contain internal staff details.

**Testing mode:** Set `TESTING_MODE = True` at the top of the script to redirect all emails to a test address without notifying real staff.

---

### `iNat_Dashboard_Export.py` — Dashboard JSON Updater

**What it does:**
- Reads the latest output GDB written by the main pipeline
- Parses the most recent pipeline log to extract run status (AGOL update, email alerts, warnings)
- Optionally queries AGOL directly for live feature counts as a cross-check
- Builds `dashboard_data.json` with observation counts, date breakdowns, species breakdowns, and recent activity
- Commits and pushes `dashboard_data.json` to GitHub so the embedded HTML dashboard can fetch it

**Schedule:** Run via Task Scheduler a few minutes after `RPMP_iNat_PROD.py` completes.

---

## Credentials and Security

All sensitive values (API keys, passwords, email addresses, file paths) are stored in `config.py`, which is **excluded from Git** via `.gitignore`.

| What | Where |
|------|-------|
| iNaturalist Client ID & Secret | `config.py` → `INAT_CLIENT_ID`, `INAT_CLIENT_SECRET` |
| AGOL username & password | `config.py` → `AGOL_USERNAME`, `AGOL_PASSWORD` |
| Internal network paths | `config.py` → `GDB_SMU_PATH`, `SDE_PATH`, `OUTPUT_GDB`, etc. |
| SMTP server & sender email | `config.py` → `SMTP_SERVER`, `SENDER_EMAIL`, `SENDER_NAME` |
| Staff email addresses | `config.py` → `STAFF_EMAILS` |
| Area-to-staff mapping | `config.py` → `AREA_TO_STAFF` |

To set up on a new machine, copy `config.example.py` to `config.py` and fill in the values.  
Contact the Biodiversity team for credentials if you don't have them.

---

## HTML Dashboard Files

The `html/` folder contains HTML files embedded as iframes in the AGOL Experience Builder dashboard.  
These are hosted via GitHub Pages at:

```
https://HorizonsRC.github.io/RPMP-iNaturalist/html/[filename].html
```

GitHub Pages must be enabled on this repo (Settings → Pages → Source: main branch).

---

## Maintainer

**Biodata Information Advisor — Horizons Regional Council**  
For questions about the pipeline, contact the Biosecurity/Biodiversity GIS team.

If you are setting this up after a staff change, see the Setup section above and request credentials from your manager or IT.
