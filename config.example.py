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
# ArcGIS Online (AGOL) Credentials
# Used as a fallback if GIS("pro") doesn't work
# ----------------------------------------------------------------------------
AGOL_USERNAME = "YOUR_AGOL_USERNAME_HERE"
AGOL_PASSWORD = "YOUR_AGOL_PASSWORD_HERE"

# The hosted feature service item ID in AGOL
# Find this in the item URL in ArcGIS Online
AGOL_SERVICE_ITEM_ID = "YOUR_SERVICE_ITEM_ID_HERE"


# ----------------------------------------------------------------------------
# File Paths — GDB and SDE (internal network paths)
# Update these to match your network/machine setup
# ----------------------------------------------------------------------------
GDB_SMU_PATH = r"\\yourserver\path\to\SMU Map.gdb"
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
# Dashboard Export — GitHub repo path (local clone of this repo)
# ----------------------------------------------------------------------------
GITHUB_REPO_PATH = r"D:\Scripts\iNaturalist\RPMP-iNaturalist"


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

# Map operating areas to the responsible staff member
# Keys must match the 'operatingArea' values in the GDB exactly
AREA_TO_STAFF = {
    'Tongariro':        'Staff Name 1',
    'Taihape':          'Staff Name 2',
    # Add more areas here as needed
}
