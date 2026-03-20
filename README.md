# RPMP iNaturalist Dashboard

Repository supporting the **RPMP iNaturalist Dashboard** on AGOL Experience Builder.  
Contains Python pipelines for extracting and processing iNaturalist observations, automated data exports, and HTML files embedded in the dashboard interface.

---

## What This Repo Does

Horizons Regional Council runs a [collection project on iNaturalist](https://www.inaturalist.org/projects/horizons-regional-council-pest-plants) that automatically aggregates public observations of RPMP pest plant species made within the regional boundary — no joining required.

This repo automates the process of:

1. **Pulling observations** from the iNaturalist API
2. **Categorising them** by RPMP programme (Eradication, Progressive Containment, Exclusion)
3. **Spatially joining** them to SMU (Species Management Unit) polygons and operating areas
4. **Intersecting** Eradication and Progressive Containment observations against managed pest plant sites to flag whether each observation falls within an existing managed site
5. **Exporting** the results to an internal GDB and pushing them to ArcGIS Online (AGOL)
6. **Sending email alerts** to field staff when new priority observations are recorded
7. **Updating a JSON file** (`dashboard_data.json`) that feeds the embedded HTML dashboard in AGOL Experience Builder

---

## Repo Structure

```
RPMP-iNaturalist/
│
├── RPMP_iNat_PROD.py            # Main pipeline — runs twice daily via Task Scheduler
├── RPMP_iNat.ipynb              # Interactive notebook version — use for setup, testing, and token generation
├── iNat_Dashboard_Export.py     # Dashboard JSON updater — runs after main pipeline
├── inat_email_notifications.py  # Email alert module — called by the main pipeline
│
├── html/
│   └── [embedded HTML files]    # HTML widgets embedded in the AGOL ExB dashboard
│
├── dashboard_data.json          # Auto-updated by iNat_Dashboard_Export.py — do not edit manually
│
├── requirements.txt             # Python package dependencies — install with: pip install -r requirements.txt
├── config.example.py            # Template for config.py
├── config.py                    # LOCAL ONLY — never committed (in .gitignore)
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
pip install -r requirements.txt
```
This installs all required packages at the correct versions in one command. Note that `arcpy` is not included — it is bundled with ArcGIS Pro 3.x and cannot be installed via pip.

### 4. Generate the iNaturalist OAuth token
On first run, you need to generate an OAuth token using the notebook (`RPMP_iNat.ipynb`).  
Open it in ArcGIS Pro, run the OAuth Authentication cell, and follow the prompts to log in and authorise.  
The token is saved to the path set in `config.py` (`INAT_TOKEN_FILE`) and reused automatically after that.

---

## Scripts

### `RPMP_iNat_PROD.py` — Main Pipeline

**What it does:**
- Authenticates with the iNaturalist API using a stored OAuth token
- Fetches all observations from the Horizons RPMP iNaturalist project
- Categorises each observation by programme (Eradication / Progressive Containment / Exclusion)
- Performs spatial joins against SMU polygon layers in the internal GDB
- Intersects Eradication and Progressive Containment observations against managed pest plant sites (see [Managed Pest Plant Sites Join](#managed-pest-plant-sites-join) below)
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

### `RPMP_iNat.ipynb` — Interactive Notebook

**What it does:**
- Mirrors the functionality of `RPMP_iNat_PROD.py` but runs cell by cell in ArcGIS Pro
- Used for first-time OAuth token generation, testing, and exploring outputs interactively
- Useful for troubleshooting — you can run individual sections and inspect intermediate results without running the full pipeline

**When to use it:**
- Setting up on a new machine (token generation)
- Testing changes before deploying to the scheduled script
- Diagnosing issues with specific steps (spatial joins, AGOL updates, etc.)

> **Note:** Clear all cell outputs before committing this file to GitHub (**Edit → Clear All Outputs** in ArcGIS Pro). Outputs may contain sensitive information from previous runs.

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

## Managed Pest Plant Sites Join

Eradication and Progressive Containment observations are intersected against the **BioS Pest Plant Sites** hosted feature layer on AGOL to determine whether each observation falls within an existing managed site.

**Source layer:** `BioS_Pest_Plants_Sites` (FeatureServer/0)  
**Filter applied before intersect:**

| iNaturalist Programme | Site `projectType` filter |
|---|---|
| Eradication | `Eradication` |
| Progressive Containment | `Progressive Containment - Mapped` |

Additional filters: `activeSite = 'Y'` (excludes historic sites), species-matched on `specieID` field, 10m buffer applied to site boundaries.

**Fields added to `iNat_Eradication` and `iNat_ProgressiveContainment`:**

| Field | Alias | Type | Description |
|---|---|---|---|
| `is_in_site` | In Managed Site (Y/N) | String | Whether the observation falls within or within 10m of an active managed site of the same species |
| `BaseSiteID` | Managed Site ID (if applicable) | String | The BaseSiteID of the intersected site, or `Null` if no match |

Observations where `is_in_site = 'N'` may indicate a new infestation outside of existing managed areas and should be assessed by the relevant field staff.

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
