# config.example.py
# ============================================================================
# CONFIGURATION TEMPLATE — SAFE TO COMMIT TO GITHUB
# ============================================================================
# This file shows what config.py should look like, but with no real values.
#
# To set up on a new machine:
#   1. Copy this file and rename the copy to config.py
#   2. Replace every placeholder (e.g. YOUR_CLIENT_ID_HERE) with real values
#   3. Never commit config.py — it is listed in .gitignore
# ============================================================================


# ----------------------------------------------------------------------------
# iNaturalist OAuth Credentials
# Get these from: https://www.inaturalist.org/oauth/applications
# ----------------------------------------------------------------------------
INAT_CLIENT_ID     = "YOUR_INATURALIST_CLIENT_ID_HERE"
INAT_CLIENT_SECRET = "YOUR_INATURALIST_CLIENT_SECRET_HERE"

# iNaturalist project ID (not sensitive, but kept here for easy editing)
INAT_PROJECT_ID = 000000  # Replace with your iNaturalist project ID

# Path to the stored OAuth token file (local machine)
INAT_TOKEN_FILE = r"D:\Scripts\iNaturalist\inat_token.json"


# ----------------------------------------------------------------------------
# ArcGIS Online (AGOL) Connection
#
# The org signs in with SSO, so there is no built-in AGOL password to script
# with. The pipeline therefore authenticates using the ArcGIS Pro session
# (GIS("pro")) — and so does arcpy, for the Append step.
#
# ⚠ CONSEQUENCE: whichever account ArcGIS Pro is signed into IS the account the
# pipeline runs as. Signing Pro into a different account breaks the scheduled
# run — the layers still read fine, but every delete fails with the unhelpful
# "This operation is not supported. (Error Code: 400)".
#
# ArcGIS Pro on the scheduled-task machine must stay signed in as
# AGOL_EXPECTED_USERNAME below. The pipeline verifies this before editing
# anything and aborts the AGOL step with a clear message if it doesn't match,
# rather than half-failing.
# ----------------------------------------------------------------------------

# The account with edit rights on the service (normally the service owner).
# Must exactly match the username ArcGIS Pro reports — note AGOL org usernames
# are usually suffixed with the org short name, e.g. "JSmith_HorizonsRC".
AGOL_EXPECTED_USERNAME = "YOUR_AGOL_USERNAME_HERE"

# The hosted feature service item ID in AGOL
# Find this in the item URL in ArcGIS Online
AGOL_SERVICE_ITEM_ID = "YOUR_SERVICE_ITEM_ID_HERE"


# ----------------------------------------------------------------------------
# File Paths — GDB and SDE (internal network paths)
# Update these to match your network/machine setup
# ----------------------------------------------------------------------------
GDB_SMU_PATH = r"\\yourserver\path\to\SMU_Layers.gdb"
# OperatingAreas fallback FC lives in a different (older) GDB than the SMU layers.
GDB_OPERATING_AREAS_PATH = r"\\yourserver\path\to\SMU Map.gdb"
SDE_PATH     = r"\\yourserver\path\to\connection.sde"
OUTPUT_GDB   = r"\\yourserver\path\to\output.gdb"

TRACKING_FILE     = r"\\yourserver\path\to\processed_observations.json"
NOTIFICATION_FILE = r"\\yourserver\path\to\pending_notifications.json"

LOG_DIR           = r"D:\Scripts\iNaturalist\Logs"
DASHBOARD_LOG_DIR = r"D:\Scripts\iNaturalist\RPMP_iNat_Dashboard\Logs"

# Log rotation: at the start of each run, delete log files older than this many
# days from the directories above. Set to 0 to disable automatic cleanup.
LOG_RETENTION_DAYS = 30


# ----------------------------------------------------------------------------
# Dashboard Export — GitHub repo path (gh-pages worktree)
# The export writes dashboard_data.json here and pushes it to the gh-pages
# branch (the published GitHub Pages site), kept separate from the pipeline
# code on main. Create the worktree once with:
#   git worktree add --orphan -b gh-pages D:\Scripts\iNaturalist-pages
# ----------------------------------------------------------------------------
GITHUB_REPO_PATH = r"D:\Scripts\iNaturalist-pages"


# ----------------------------------------------------------------------------
# Admin email (for run summary and error alerts)
# ----------------------------------------------------------------------------
ADMIN_EMAIL = "your.email@horizons.govt.nz"


# ----------------------------------------------------------------------------
# Email / SMTP Configuration
# Used by inat_email_notifications.py to send alerts and summaries
# ----------------------------------------------------------------------------
SMTP_SERVER  = "mail.horizons.govt.nz"   # Internal SMTP — no auth required on Horizons network
SENDER_EMAIL = "your.email@horizons.govt.nz"
SENDER_NAME  = "Horizons Biosecurity Team"


# ----------------------------------------------------------------------------
# Staff Emails — used to send alerts to the right person per operating area
# Update these if staff members change
# ----------------------------------------------------------------------------
STAFF_EMAILS = {
    'Staff Name 1': 'firstname.lastname@horizons.govt.nz',
    'Staff Name 2': 'firstname.lastname@horizons.govt.nz',
    # Add more staff here as needed
}

# Map operating areas to the responsible staff member.
#
# ⚠ Keys must match the RAW value stored in the GDB, not what you see in Pro.
# The SMU layer's `operatingArea` field uses a CODED-VALUE DOMAIN: ArcGIS Pro
# displays "Palmerston North", but arcpy's SearchCursor returns the stored code
# "PN". Keying this dict on the descriptions silently sends every notification
# to "Unassigned", where it is dropped.
#
# The OperatingAreas fallback GDB still stores full descriptions, so BOTH forms
# can reach this lookup — keep keys for both.
#
# Current SMU domain (check with arcpy.da.ListDomains if areas change):
#   PN -> Palmerston North   TR -> Tararua     HW -> Horowhenua
#   WH -> Whanganui          TH -> Taihape     TG -> Tongario
#   OH -> Ohura
AREA_TO_STAFF = {
    # Domain codes (what the SMU layer actually stores)
    'PN':               'Staff Name 1',
    'TR':               'Staff Name 2',
    # Full descriptions (what the OperatingAreas fallback GDB stores)
    'Palmerston North': 'Staff Name 1',
    'Tararua':          'Staff Name 2',
    # Add more areas here as needed — add BOTH the code and the description
}
