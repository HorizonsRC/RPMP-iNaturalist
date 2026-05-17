#!/usr/bin/env python
# coding: utf-8

"""
Backup script — resend iNaturalist staff notifications for recent
Eradication / Exclusion observations.

Use when the main pipeline fails to send notifications. Two modes:

  Default (AGOL, observed_on):
      Pulls features from iNat_Eradication / iNat_Exclusion in AGOL and
      filters by observed_on within the past N days. Fast, but misses obs
      that were observed long ago and uploaded recently.

  --by-upload-date (iNat API, created_at):
      Queries the iNat API for observations created (uploaded) in the past
      N days, intersects with the AGOL priority layers to pick up the
      operating area / staff assignment, then emails. Matches "what should
      have been notified" most accurately.

Defaults to DRY-RUN — prints what would be sent. Add --send to actually send.

Usage:
    python resend_notifications.py                          # AGOL, last 7 days, dry-run
    python resend_notifications.py --days 30                # AGOL, last 30 days, dry-run
    python resend_notifications.py --by-upload-date         # iNat upload date, last 7 days, dry-run
    python resend_notifications.py --by-upload-date --days 14 --send
"""

import argparse
import datetime
import json
import os
import sys
import time
import traceback

from arcgis.gis import GIS
from requests_oauthlib import OAuth2Session

try:
    import config
except ImportError:
    print("ERROR: config.py not found.")
    sys.exit(1)

import inat_email_notifications
from inat_email_notifications import create_immediate_alert_email, send_email

LAYER_NAMES = ["iNat_Eradication", "iNat_Exclusion"]
INAT_API_BASE = "https://api.inaturalist.org/v1"


# ----------------------------------------------------------------------------
# AGOL connection
# ----------------------------------------------------------------------------

def get_agol_connection():
    try:
        gis = GIS("pro")
        _ = gis.users.me  # force auth check
        return gis
    except Exception:
        return GIS("https://www.arcgis.com", config.AGOL_USERNAME, config.AGOL_PASSWORD)


def get_priority_layers(gis):
    item = gis.content.get(config.AGOL_SERVICE_ITEM_ID)
    if item is None:
        raise RuntimeError(f"AGOL service item not found: {config.AGOL_SERVICE_ITEM_ID}")
    layers = {}
    for layer_name in LAYER_NAMES:
        lyr = next((l for l in item.layers if l.properties.name == layer_name), None)
        if lyr is None:
            print(f"  ⚠ Layer not found: {layer_name}")
            continue
        layers[layer_name] = lyr
    return layers


# ----------------------------------------------------------------------------
# Mode 1 — AGOL by observed_on
# ----------------------------------------------------------------------------

def parse_observed_on(val):
    if val is None:
        return None
    if isinstance(val, (int, float)):
        # AGOL Date fields return epoch milliseconds
        try:
            return datetime.datetime.utcfromtimestamp(val / 1000.0).date()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(val, str):
        try:
            return datetime.datetime.strptime(val[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def fetch_recent_by_observed_on(gis, days):
    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    layers = get_priority_layers(gis)

    matched = []
    for layer_name, lyr in layers.items():
        fs = lyr.query(where="1=1", out_fields="*", return_geometry=False)
        recent = [
            f.attributes
            for f in fs.features
            if (d := parse_observed_on(f.attributes.get("observed_on"))) is not None and d >= cutoff
        ]
        matched.extend(recent)
        print(f"  ✓ {layer_name}: {len(recent)} obs in window (of {len(fs.features)} total)")
    return matched, cutoff


# ----------------------------------------------------------------------------
# Mode 2 — iNat API by created_at, joined to AGOL by id
# ----------------------------------------------------------------------------

def get_inat_session():
    if not os.path.exists(config.INAT_TOKEN_FILE):
        raise RuntimeError(f"iNat token not found: {config.INAT_TOKEN_FILE}")
    with open(config.INAT_TOKEN_FILE, "r") as f:
        token = json.load(f)
    return OAuth2Session(config.INAT_CLIENT_ID, token=token)


def fetch_recent_inat_ids(days):
    """Return set of iNat observation IDs created within the past N days."""
    session = get_inat_session()
    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    params = {
        "project_id": config.INAT_PROJECT_ID,
        "created_d1": cutoff.isoformat(),
        "per_page": 200,
        "page": 1,
        "order": "desc",
        "order_by": "created_at",
        "quality_grade": "any",
    }
    ids = set()
    page_count = 0
    while True:
        r = session.get(f"{INAT_API_BASE}/observations", params=params, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"iNat API failed: HTTP {r.status_code} — {r.text[:200]}")
        data = r.json()
        results = data.get("results") or []
        if not results:
            break
        for obs in results:
            obs_id = obs.get("id")
            if obs_id is not None:
                ids.add(int(obs_id))
        page_count += 1
        print(f"  iNat page {params['page']}: {len(results)} obs (running total: {len(ids)})")
        if len(results) < params["per_page"]:
            break
        params["page"] += 1
        time.sleep(0.5)  # be polite
    print(f"  ✓ {len(ids)} iNat obs created since {cutoff.isoformat()} across {page_count} page(s)")
    return ids, cutoff


def fetch_agol_features_by_ids(gis, ids):
    """Query priority AGOL layers for features whose id is in the given set."""
    if not ids:
        return []
    layers = get_priority_layers(gis)
    matched = []
    id_list = list(ids)
    chunk_size = 500  # avoid URL length issues
    for layer_name, lyr in layers.items():
        layer_features = []
        for i in range(0, len(id_list), chunk_size):
            chunk = id_list[i:i + chunk_size]
            where = f"id IN ({','.join(str(x) for x in chunk)})"
            fs = lyr.query(where=where, out_fields="*", return_geometry=False)
            layer_features.extend(f.attributes for f in fs.features)
        matched.extend(layer_features)
        print(f"  ✓ {layer_name}: {len(layer_features)} priority obs matched in AGOL")
    return matched


# ----------------------------------------------------------------------------
# Common — build notifications + send
# ----------------------------------------------------------------------------

def to_notification(attrs):
    operating_area = attrs.get("operatingArea") or "Unknown"
    staff = inat_email_notifications.AREA_TO_STAFF.get(operating_area, "Unassigned")
    obs_id = attrs.get("id")
    return {
        "observation_id":  obs_id,
        "observation_url": attrs.get("observation_url") or f"https://www.inaturalist.org/observations/{obs_id}",
        "programme":       attrs.get("programme"),
        "taxon_name":      attrs.get("taxon_name") or "",
        "species_name":    attrs.get("speciesName") or attrs.get("species_guess") or attrs.get("taxon_name") or "Unknown",
        "observed_on":     attrs.get("observed_on") or "",
        "operating_area":  operating_area,
        "staff_member":    staff,
        "latitude":        attrs.get("latitude"),
        "longitude":       attrs.get("longitude"),
        "quality_grade":   attrs.get("quality_grade") or "",
        "user_name":       attrs.get("user_name") or "",
        "description":     attrs.get("description") or "",
        "flowers_fruits":  attrs.get("flowers_fruits") or "",
        "photoURL_1":      attrs.get("photoURL_1") or "",
        "is_in_site":      attrs.get("is_in_site") or "N",
        "BaseSiteID":      attrs.get("BaseSiteID"),
    }


def main():
    p = argparse.ArgumentParser(description="Resend iNat staff notifications for recent priority observations")
    p.add_argument("--days", type=int, default=7, help="Look back N days (default 7)")
    p.add_argument("--send", action="store_true", help="Actually send emails. Default is dry-run.")
    p.add_argument("--by-upload-date", action="store_true",
                   help="Filter by iNat upload date (created_at) instead of observed_on. "
                        "Best when catching up after a pipeline failure.")
    args = p.parse_args()

    mode = "SEND" if args.send else "DRY-RUN"
    filter_label = "iNat upload date" if args.by_upload_date else "observed_on"
    print("=" * 70)
    print(f"RESEND iNAT NOTIFICATIONS — {mode} — last {args.days} days ({filter_label})")
    print("=" * 70)

    try:
        gis = get_agol_connection()
        print(f"✓ Connected to AGOL as: {gis.users.me.username}\n")
    except Exception as e:
        print(f"✗ AGOL connection failed: {e}")
        sys.exit(1)

    try:
        if args.by_upload_date:
            print(f"Fetching iNat observations created in the past {args.days} days...")
            ids, cutoff = fetch_recent_inat_ids(args.days)
            print(f"\nLooking up matching priority features in AGOL...")
            features = fetch_agol_features_by_ids(gis, ids)
        else:
            features, cutoff = fetch_recent_by_observed_on(gis, args.days)
    except Exception as e:
        print(f"✗ Fetch failed: {e}\n{traceback.format_exc()}")
        sys.exit(1)

    if not features:
        print(f"\n✓ No priority observations found in window (cutoff {cutoff.isoformat()})")
        return

    notifications = [to_notification(f) for f in features]

    by_staff = {}
    for n in notifications:
        by_staff.setdefault(n["staff_member"], []).append(n)

    print(f"\n{len(notifications)} observation(s) across {len(by_staff)} staff member(s):")
    for staff, notifs in by_staff.items():
        email = inat_email_notifications.STAFF_EMAILS.get(staff)
        print(f"\n  {staff} ({email or 'NO EMAIL CONFIGURED'}): {len(notifs)} obs")
        for n in notifs:
            print(f"    - [{n['programme']}] {n['species_name']} on {n['observed_on']} "
                  f"({n['operating_area']}) — obs {n['observation_id']}")

    if not args.send:
        print(f"\n{'=' * 70}\nDRY-RUN — no emails sent. Re-run with --send to send.\n{'=' * 70}")
        return

    print(f"\n{'=' * 70}\nSENDING EMAILS\n{'=' * 70}")
    sent, failed = 0, 0
    for staff, notifs in by_staff.items():
        email = inat_email_notifications.STAFF_EMAILS.get(staff)
        if not email:
            print(f"  ⚠ No email configured for {staff} — skipping {len(notifs)} obs")
            failed += len(notifs)
            continue
        for programme in ["Eradication", "Exclusion"]:
            prog_obs = [n for n in notifs if n["programme"] == programme]
            if not prog_obs:
                continue
            operating_area = prog_obs[0]["operating_area"]
            subject, html_body = create_immediate_alert_email(prog_obs, staff, operating_area)
            if send_email(email, subject, html_body):
                print(f"  ✓ Sent {len(prog_obs)} {programme} obs to {staff} ({email})")
                sent += len(prog_obs)
            else:
                print(f"  ✗ Failed to send {programme} to {staff}")
                failed += len(prog_obs)

    print(f"\n{'=' * 70}\nSent: {sent} | Failed: {failed}\n{'=' * 70}")


if __name__ == "__main__":
    main()
