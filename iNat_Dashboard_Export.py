#!/usr/bin/env python
# coding: utf-8

"""
iNat_Dashboard_Export.py
------------------------
Standalone script that reads from the RPMP iNaturalist pipeline outputs
and writes dashboard_data.json to a GitHub Pages repo, then pushes it.

Run this on its own Task Scheduler entry, a few minutes after the main
pipeline (RPMP_iNat_PROD.py) completes.

Data sources (in priority order):
  1. GDB  — observation features, species, dates, SMU matches
  2. Log  — AGOL status, email status, new obs count, run warnings
  3. AGOL — live feature counts as cross-check / fallback

Requirements:
  pip install geopandas gitpython arcgis
  (arcpy is available in the ArcGIS Pro Python environment)
"""

import os
import re
import sys
import json
import glob
import logging
import datetime
import traceback
from pathlib import Path

import geopandas as gpd
import pandas as pd

# ============================================================================
# Load Config
# ============================================================================
# All sensitive values (credentials, paths) live in config.py
# config.py is listed in .gitignore and is never uploaded to GitHub
# If setting up on a new machine, copy config.example.py → config.py
# and fill in the real values.

try:
    import config
except ImportError:
    print("ERROR: config.py not found.")
    print("Copy config.example.py to config.py and fill in your credentials.")
    sys.exit(1)

# ============================================================================
# CONFIG — all values now loaded from config.py
# ============================================================================

GDB_PATH        = config.OUTPUT_GDB
GDB_LAYER_ALL   = "iNat_AllProgrammes"
GDB_LAYER_ERAD  = "iNat_Eradication"
GDB_LAYER_EXCL  = "iNat_Exclusion"
GDB_LAYER_PROG  = "iNat_ProgressiveContainment"

LOG_DIR         = config.LOG_DIR
LOG_PATTERN     = "iNat_Pipeline_*.log"

TRACKING_FILE   = config.TRACKING_FILE
AGOL_SERVICE_ID = config.AGOL_SERVICE_ITEM_ID

GITHUB_REPO_PATH = config.GITHUB_REPO_PATH
OUTPUT_JSON      = os.path.join(GITHUB_REPO_PATH, "dashboard_data.json")

FEED_LIMIT = 20

SPECIES_LIST_COUNTS = {
    "Eradication": 27,
    "Exclusion": 13,
    "Progressive Containment": 23,
}

# ============================================================================
# Logging
# ============================================================================

dashboard_log_dir  = config.DASHBOARD_LOG_DIR   # separate from PROD script logs
if not os.path.exists(dashboard_log_dir):
    os.makedirs(dashboard_log_dir)
dashboard_log_file = os.path.join(
    dashboard_log_dir,
    f"iNat_Dashboard_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(dashboard_log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# ============================================================================
# STEP 1: Parse most recent pipeline log
# ============================================================================

def find_latest_log(log_dir: str, pattern: str) -> str | None:
    """Return path to the most recently modified pipeline log file."""
    files = glob.glob(os.path.join(log_dir, pattern))
    files = [f for f in files if "Dashboard" not in os.path.basename(f)]
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def parse_log(log_path: str) -> dict:
    """
    Extract key facts from the pipeline log.
    Returns a dict with agol_status, email_status, new_obs_count,
    run_timestamp, warnings.
    """
    result = {
        "agol_status": "unknown",
        "email_status": "unknown",
        "new_obs_count": 0,
        "run_timestamp": None,
        "warnings": [],
        "log_path": log_path,
    }

    if not log_path or not os.path.exists(log_path):
        logger.warning("No pipeline log found — system status will show as unknown")
        return result

    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            content = f.read()

        if "ALL LAYERS UPDATED SUCCESSFULLY" in content or "AGOL update successful" in content:
            result["agol_status"] = "success"
        elif "AGOL Update: ✓ SUCCESS" in content:
            result["agol_status"] = "success"
        elif "ALL UPDATES FAILED" in content or "AGOL Update: ✗ FAILED" in content:
            result["agol_status"] = "failed"
        elif "PARTIAL SUCCESS" in content:
            result["agol_status"] = "partial"

        if "Email Alerts: ✓" in content or "Run summary email sent successfully" in content:
            result["email_status"] = "success"
        if "Email Alerts: ✗ FAILED" in content or "Email notifications failed to send" in content:
            result["email_status"] = "failed"
        if "No pending notification" in content or "No new priority observations" in content:
            result["email_status"] = "none_needed"

        m = re.search(r"New observations detected:\s*(\d+)", content)
        if m:
            result["new_obs_count"] = int(m.group(1))
        else:
            m = re.search(r"New observations:\s+(\d+)", content)
            if m:
                result["new_obs_count"] = int(m.group(1))

        m = re.search(r"Completed at:\s*([\d\-]+ [\d:]+)", content)
        if m:
            result["run_timestamp"] = m.group(1)

        for match in re.finditer(r"⚠ ([\w\s]+):\s*(\d+) observations without SMU layer", content):
            result["warnings"].append(f"{match.group(1).strip()}: {match.group(2)} observations without SMU layer")

        if "CRITICAL: New observations detected but staff were NOT notified" in content:
            result["warnings"].append("Staff notification email failed — new observations unnotified")

        logger.info(f"✓ Log parsed: AGOL={result['agol_status']}, Email={result['email_status']}, NewObs={result['new_obs_count']}")

    except Exception as e:
        logger.error(f"Error parsing log file: {e}")

    return result


# ============================================================================
# STEP 2: Read GDB
# ============================================================================

def date_category(date_str: str) -> str:
    """Recompute date category — mirrors the logic in the main pipeline."""
    if not date_str or pd.isna(date_str):
        return "Unknown Date"
    try:
        obs_date = datetime.datetime.strptime(str(date_str)[:10], "%Y-%m-%d").date()
        today = datetime.datetime.now().date()
        days_ago = (today - obs_date).days
        if days_ago < 0:
            return "Future Date"
        if days_ago == 0:
            return "Today"
        if days_ago <= 7:
            return "Last 7 Days"
        if days_ago <= 30:
            return "Last 30 Days"
        if days_ago <= 90:
            return "Last 3 Months"
        if days_ago <= 365:
            return "Last Year"
        return "Older than 1 Year"
    except Exception:
        return "Unknown Date"


def read_gdb_layer(gdb_path: str, layer: str) -> gpd.GeoDataFrame | None:
    """Read a single layer from the GDB. Returns None on failure."""
    try:
        gdf = gpd.read_file(gdb_path, layer=layer)
        logger.info(f"  ✓ {layer}: {len(gdf)} features")
        return gdf
    except Exception as e:
        logger.error(f"  ✗ Could not read {layer}: {e}")
        return None


def read_gdb(gdb_path: str) -> dict:
    """
    Read all four GDB layers. Returns dict with keys:
      all, eradication, exclusion, progressive, ok (bool)
    """
    logger.info(f"Reading GDB: {gdb_path}")
    result = {"all": None, "eradication": None, "exclusion": None, "progressive": None, "ok": False}

    if not os.path.exists(gdb_path):
        logger.error(f"GDB not found: {gdb_path}")
        return result

    result["all"]         = read_gdb_layer(gdb_path, GDB_LAYER_ALL)
    result["eradication"] = read_gdb_layer(gdb_path, GDB_LAYER_ERAD)
    result["exclusion"]   = read_gdb_layer(gdb_path, GDB_LAYER_EXCL)
    result["progressive"] = read_gdb_layer(gdb_path, GDB_LAYER_PROG)
    result["ok"]          = result["all"] is not None

    return result


# ============================================================================
# STEP 3: Read tracking file
# ============================================================================

def read_tracking_file(path: str) -> dict:
    """Read the processed_observations.json tracking file."""
    if not os.path.exists(path):
        logger.warning("Tracking file not found")
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"✓ Tracking file read: {data.get('total_observations', 0)} obs, last run {data.get('last_run', 'unknown')}")
        return data
    except Exception as e:
        logger.error(f"Error reading tracking file: {e}")
        return {}


# ============================================================================
# STEP 4: Query AGOL for live feature counts (optional cross-check)
# ============================================================================

def query_agol_counts(service_id: str) -> dict | None:
    """
    Query AGOL feature service for live layer counts.
    Returns dict of {layer_name: count} or None on failure.
    Uses GIS("pro") — same auth as main pipeline.
    """
    try:
        from arcgis.gis import GIS
        from arcgis.features import FeatureLayerCollection
        logger.info("Connecting to AGOL for live counts...")
        gis = GIS("pro")
        item = gis.content.get(service_id)
        if item is None:
            logger.warning("Could not find AGOL service item")
            return None
        flc = FeatureLayerCollection.fromitem(item)
        counts = {}
        for lyr in flc.layers:
            name = lyr.properties.name
            count = lyr.query(return_count_only=True)
            counts[name] = count
            logger.info(f"  AGOL {name}: {count} features")
        return counts
    except Exception as e:
        logger.warning(f"AGOL query skipped (non-critical): {e}")
        return None


# ============================================================================
# STEP 5: Build the JSON payload
# ============================================================================

def build_payload(gdb: dict, log_info: dict, tracking: dict, agol_counts: dict | None) -> dict:
    """Assemble dashboard_data.json from all sources."""

    now_utc = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    date_breakdown = {
        "last_7_days": 0, "last_30_days": 0, "last_3_months": 0,
        "last_year": 0, "older_than_1_year": 0, "unknown": 0,
    }
    total_observations = 0

    if gdb["all"] is not None:
        gdf_all = gdb["all"]
        total_observations = len(gdf_all)

        if "date_category" in gdf_all.columns:
            cats = gdf_all["date_category"]
        else:
            cats = gdf_all["observed_on"].apply(date_category)

        vc = cats.value_counts().to_dict()
        date_breakdown["last_7_days"]       = int(vc.get("Last 7 Days", 0) + vc.get("Today", 0))
        date_breakdown["last_30_days"]      = int(vc.get("Last 30 Days", 0))
        date_breakdown["last_3_months"]     = int(vc.get("Last 3 Months", 0))
        date_breakdown["last_year"]         = int(vc.get("Last Year", 0))
        date_breakdown["older_than_1_year"] = int(vc.get("Older than 1 Year", 0))
        date_breakdown["unknown"]           = int(vc.get("Unknown Date", 0) + vc.get("Invalid Date", 0))

    def cat_stats(gdf: gpd.GeoDataFrame | None, prog_key: str) -> dict:
        if gdf is None:
            return {
                "count": agol_counts.get(f"iNat_{prog_key}", 0) if agol_counts else 0,
                "species_in_list": SPECIES_LIST_COUNTS.get(prog_key.replace("_", " "), 0),
                "unique_observed": 0,
                "smu_match_rate": None,
                "in_managed_site": None,
                "not_in_managed_site": None,
                "gpnz_excluded": None,
                "source": "agol_fallback" if agol_counts else "unavailable",
            }

        smu_col = "SMU_Name" if "SMU_Name" in gdf.columns else None
        smu_rate = None
        if smu_col:
            matched = int(gdf[smu_col].notna().sum())
            smu_rate = round(matched / len(gdf) * 100, 1) if len(gdf) > 0 else 0.0

        unique = 0
        for col in ("speciesName", "taxon_name", "species_guess"):
            if col in gdf.columns:
                unique = int(gdf[col].nunique())
                break

        programme_name = prog_key.replace("_", " ")
        sp_count = SPECIES_LIST_COUNTS.get(programme_name, 0)

        most_recent = {}
        date_col = next((c for c in ("observed_on",) if c in gdf.columns), None)
        name_col = next((c for c in ("speciesName", "taxon_name", "species_guess") if c in gdf.columns), None)
        loc_col  = next((c for c in ("operatingArea", "place_guess") if c in gdf.columns), None)
        if date_col:
            try:
                sorted_gdf = gdf.dropna(subset=[date_col]).sort_values(date_col, ascending=False)
                if len(sorted_gdf) > 0:
                    row = sorted_gdf.iloc[0]
                    most_recent = {
                        "date":     str(row[date_col])[:10],
                        "species":  str(row[name_col]) if name_col and pd.notna(row[name_col]) else "",
                        "location": str(row[loc_col])  if loc_col  and pd.notna(row[loc_col])  else "",
                    }
            except Exception:
                pass

        species_breakdown = []
        if name_col:
            try:
                counts = gdf[name_col].value_counts()
                species_breakdown = [
                    {"species": str(k), "count": int(v)}
                    for k, v in counts.items()
                    if pd.notna(k)
                ]
            except Exception:
                pass

        in_managed_site = None
        not_in_managed_site = None
        gpnz_excluded = None

        if prog_key in ("Eradication", "Progressive Containment") and "is_in_site" in gdf.columns:
            if prog_key == "Progressive Containment" and "Designation" in gdf.columns:
                gpnz_mask = gdf["Designation"] == "GPNZ"
                gpnz_excluded = int(gpnz_mask.sum())
                gdf_work = gdf[~gpnz_mask]
            else:
                gdf_work = gdf
            in_managed_site = int((gdf_work["is_in_site"] == "Y").sum())
            not_in_managed_site = int((gdf_work["is_in_site"] == "N").sum())

        return {
            "count": int(len(gdf)),
            "species_in_list": sp_count,
            "unique_observed": unique,
            "smu_match_rate": smu_rate,
            "in_managed_site": in_managed_site,
            "not_in_managed_site": not_in_managed_site,
            "gpnz_excluded": gpnz_excluded,
            "most_recent": most_recent,
            "species_breakdown": species_breakdown,
            "source": "gdb",
        }

    categories = {
        "eradication":             cat_stats(gdb["eradication"],  "Eradication"),
        "exclusion":               cat_stats(gdb["exclusion"],    "Exclusion"),
        "progressive_containment": cat_stats(gdb["progressive"],  "Progressive Containment"),
    }

    recent_observations = []
    if gdb["all"] is not None:
        gdf_all = gdb["all"]
        date_col = "observed_on" if "observed_on" in gdf_all.columns else None
        if date_col:
            try:
                sorted_gdf = gdf_all.sort_values(date_col, ascending=False)
            except Exception:
                sorted_gdf = gdf_all
        else:
            sorted_gdf = gdf_all

        name_col = next((c for c in ("speciesName", "taxon_name", "species_guess") if c in sorted_gdf.columns), None)
        loc_col  = next((c for c in ("operatingArea", "Name", "SMU_Name", "place_guess") if c in sorted_gdf.columns), None)
        cat_col  = "programme" if "programme" in sorted_gdf.columns else None
        id_col   = "id" if "id" in sorted_gdf.columns else None

        for _, row in sorted_gdf.head(FEED_LIMIT).iterrows():
            recent_observations.append({
                "species":     str(row[name_col])  if name_col  and pd.notna(row[name_col])  else "Unknown",
                "category":    str(row[cat_col])   if cat_col   and pd.notna(row[cat_col])   else "Unknown",
                "location":    str(row[loc_col])   if loc_col   and pd.notna(row[loc_col])   else "",
                "observed_on": str(row[date_col])[:10] if date_col and pd.notna(row[date_col]) else "",
                "id":          int(row[id_col])    if id_col    and pd.notna(row[id_col])    else None,
            })

    email_label = log_info.get("email_status", "unknown")
    if email_label == "none_needed":
        email_label = "none needed"

    system = {
        "agol_status":       log_info.get("agol_status", "unknown"),
        "email_status":      email_label,
        "last_pipeline_run": log_info.get("run_timestamp"),
        "log_file":          os.path.basename(log_info.get("log_path", "")) if log_info.get("log_path") else None,
    }

    if agol_counts:
        system["agol_live_counts"] = agol_counts

    warnings = log_info.get("warnings", [])

    if agol_counts and gdb["ok"]:
        for gdb_layer, agol_key, label in [
            (gdb["eradication"],  "iNat_Eradication",           "Eradication"),
            (gdb["exclusion"],    "iNat_Exclusion",              "Exclusion"),
            (gdb["progressive"],  "iNat_ProgressiveContainment", "Progressive Containment"),
        ]:
            if gdb_layer is not None and agol_key in agol_counts:
                gdb_n  = len(gdb_layer)
                agol_n = agol_counts[agol_key]
                if gdb_n != agol_n:
                    warnings.append(f"{label}: GDB has {gdb_n} features, AGOL has {agol_n} — possible sync issue")

    payload = {
        "last_updated":        now_utc,
        "total_observations":  total_observations,
        "new_observations":    log_info.get("new_obs_count", 0),
        "date_breakdown":      date_breakdown,
        "categories":          categories,
        "system":              system,
        "warnings":            warnings,
        "recent_observations": recent_observations,
    }

    return payload


# ============================================================================
# STEP 6: Write JSON
# ============================================================================

def write_json(payload: dict, output_path: str) -> bool:
    try:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)
        logger.info(f"✓ dashboard_data.json written → {output_path}")
        return True
    except Exception as e:
        logger.error(f"✗ Failed to write JSON: {e}")
        return False


# ============================================================================
# STEP 7: Push to GitHub
# ============================================================================

def push_to_github(repo_path: str, payload: dict, filename: str = "dashboard_data.json") -> tuple[bool, bool]:
    json_ok = False
    push_ok = False
    try:
        from git import Repo, InvalidGitRepositoryError
    except ImportError:
        logger.error("gitpython not installed — run: pip install gitpython")
        return json_ok, push_ok

    try:
        repo = Repo(repo_path)
    except Exception as e:
        logger.error(f"Not a valid git repo at {repo_path}: {e}")
        return json_ok, push_ok

    output_path = os.path.join(repo_path, filename)

    try:
        origin = repo.remotes.origin
        try:
            origin.pull()
            logger.info("✓ Pulled latest changes from remote")
        except Exception as e:
            logger.warning(f"Pull failed: {e} — proceeding with push")

        json_ok = write_json(payload, output_path)
        if not json_ok:
            return json_ok, push_ok

        repo.index.add([filename])

        if not repo.index.diff("HEAD") and not repo.untracked_files:
            logger.info("No changes to dashboard_data.json — skipping push")
            push_ok = True
            return json_ok, push_ok

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        commit_msg = f"Dashboard update: {timestamp}"
        repo.index.commit(commit_msg)
        logger.info(f"✓ Committed: {commit_msg}")

        branch = repo.active_branch.name
        push_info = origin.push(refspec=f"{branch}:{branch}")

        push_ok = True
        for info in push_info:
            if info.flags & info.ERROR:
                logger.error(f"Push failed: {info.summary}")
                push_ok = False
                break

        if push_ok:
            logger.info(f"✓ Pushed to origin/{branch}")

        return json_ok, push_ok

    except Exception as e:
        logger.error(f"Git push failed: {e}")
        logger.error(traceback.format_exc())
        return json_ok, push_ok


# ============================================================================
# MAIN
# ============================================================================

def main():
    start = datetime.datetime.now()
    logger.info("=" * 70)
    logger.info("iNat Dashboard Export — Script Started")
    logger.info("=" * 70)

    exit_code = 0

    logger.info("\n[1/5] Parsing pipeline log...")
    latest_log = find_latest_log(LOG_DIR, LOG_PATTERN)
    if latest_log:
        logger.info(f"  Using log: {os.path.basename(latest_log)}")
    log_info = parse_log(latest_log)

    logger.info("\n[2/5] Reading GDB...")
    gdb = read_gdb(GDB_PATH)
    if not gdb["ok"]:
        logger.warning("  GDB unavailable — will use AGOL counts as fallback for observation totals")

    logger.info("\n[3/5] Reading tracking file...")
    tracking = read_tracking_file(TRACKING_FILE)

    logger.info("\n[4/5] Querying AGOL for live counts (optional)...")
    agol_counts = query_agol_counts(AGOL_SERVICE_ID)

    logger.info("\n[5/5] Building dashboard_data.json...")
    payload = build_payload(gdb, log_info, tracking, agol_counts)

    logger.info("\nPushing to GitHub Pages...")
    json_ok, push_ok = push_to_github(GITHUB_REPO_PATH, payload)
    if not push_ok:
        logger.warning("⚠ GitHub push failed — JSON was written locally but not published")
        exit_code = 1

    elapsed = (datetime.datetime.now() - start).total_seconds()
    logger.info("\n" + "=" * 70)
    logger.info("DASHBOARD EXPORT SUMMARY")
    logger.info("=" * 70)
    logger.info(f"  GDB read:         {'✓' if gdb['ok'] else '✗ (fallback used)'}")
    logger.info(f"  Log parsed:       {'✓' if latest_log else '✗ (not found)'}")
    logger.info(f"  AGOL cross-check: {'✓' if agol_counts else '— (skipped)'}")
    logger.info(f"  JSON written:     {'✓' if json_ok else '✗'}")
    logger.info(f"  Total obs:        {payload.get('total_observations', 0)}")
    logger.info(f"  New this run:     {payload.get('new_observations', 0)}")
    logger.info(f"  Execution time:   {elapsed:.1f}s")
    logger.info("=" * 70)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
