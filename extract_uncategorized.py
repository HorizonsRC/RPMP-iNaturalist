#!/usr/bin/env python
# Extract uncategorized observations from iNaturalist API

import requests
import pandas as pd
import json
import sys
from requests_oauthlib import OAuth2Session

try:
    import config
except ImportError:
    print("ERROR: config.py not found")
    sys.exit(1)

# ============================================================================
# OAuth Setup
# ============================================================================
CLIENT_ID     = config.INAT_CLIENT_ID
CLIENT_SECRET = config.INAT_CLIENT_SECRET
TOKEN_FILE    = config.INAT_TOKEN_FILE
TOKEN_URL     = "https://www.inaturalist.org/oauth/token"
API_BASE_URL  = "https://api.inaturalist.org/v1"

def load_token():
    with open(TOKEN_FILE, "r") as f:
        return json.load(f)

# ============================================================================
# Programme Species Lists (same as in main script)
# ============================================================================
programme_species = {
    "Progressive Containment": {
        "taxon_ids": [1442036,61400,75751,82856,168326,75499,67747,48934,135715,58722,135727,
                      1442036,1442037,1442036,404420,412975,133171,133168,160697,61400,61400,600447,1442036]
    },
    "Eradication": {
        "taxon_ids": [75386,51454,164333,77310,1432862,1030051,283354,64540,47892,165658,165660,165660,61321,369932,
                      54834,54834,407490,772903,773011,772983,772998,772990,773009,133287,164333,430005,430005]
    },
    "Exclusion": {
        "taxon_ids": [1080223,47159,165658,164948,79464,407086,57920,64237,64232,48071,51594,409445,69816]
    }
}

# Flatten all programme taxon IDs
all_programme_taxon_ids = set()
for prog, data in programme_species.items():
    all_programme_taxon_ids.update(data['taxon_ids'])

# ============================================================================
# Fetch observations
# ============================================================================
token = load_token()
session = OAuth2Session(CLIENT_ID, token=token)

observations = []
page = 1
project_id = config.INAT_PROJECT_ID

print(f"Fetching observations from iNaturalist project {project_id}...")

while True:
    params = {
        "project_id": project_id,
        "per_page": 200,
        "page": page,
        "order": "desc",
        "order_by": "created_at",
        "quality_grade": "any"
    }

    response = session.get(f"{API_BASE_URL}/observations", params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    if "results" not in data or not data["results"]:
        break

    observations.extend(data["results"])
    print(f"  Page {page}: {len(data['results'])} obs (total: {len(observations)})")

    if len(data["results"]) < 200:
        break

    page += 1

print(f"\nFetched {len(observations)} total observations\n")

# ============================================================================
# Extract uncategorized observations
# ============================================================================
uncategorized = []

for obs in observations:
    taxon = obs.get("taxon", {})
    taxon_id = taxon.get("id")

    if taxon_id not in all_programme_taxon_ids:
        uncategorized.append({
            "id": obs.get("id"),
            "species": taxon.get("name", "Unknown"),
            "taxon_id": taxon_id,
            "observed_date": obs.get("observed_on"),
            "created_at": obs.get("created_at"),
            "latitude": obs.get("latitude"),
            "longitude": obs.get("longitude"),
            "place_name": obs.get("place_guess"),
            "user": obs.get("user", {}).get("login"),
            "quality_grade": obs.get("quality_grade"),
            "photos_count": len(obs.get("photos", []))
        })

print(f"Found {len(uncategorized)} uncategorized observations")

# Export to CSV
df = pd.DataFrame(uncategorized)
output_file = "uncategorized_observations.csv"
df.to_csv(output_file, index=False, encoding='utf-8')
print(f"Exported {len(uncategorized)} observations to {output_file}")

# Also add iNaturalist URL column
df['url'] = df['id'].apply(lambda x: f"https://www.inaturalist.org/observations/{x}")
df_with_url = df[['id', 'species', 'taxon_id', 'observed_date', 'url', 'place_name', 'user', 'quality_grade', 'photos_count']]
output_file_with_url = "uncategorized_observations_with_urls.csv"
df_with_url.to_csv(output_file_with_url, index=False, encoding='utf-8')
print(f"CSV files created successfully")
