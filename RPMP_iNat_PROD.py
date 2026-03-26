#!/usr/bin/env python
# coding: utf-8

# RPMP iNaturalist Data Pipeline - Automated Version
# For use with Task Scheduler - No manual interaction required

import requests, pandas as pd, geopandas as gpd, json, os
from requests_oauthlib import OAuth2Session
import datetime, time, sys
from arcgis.gis import GIS
from arcgis.features import FeatureLayerCollection
import arcpy, shapely.wkb, shutil, logging, traceback
import inat_email_notifications

# ============================================================================
# Load Config — all sensitive values live in config.py (never committed to Git)
# ============================================================================
try:
    import config
except ImportError:
    print("ERROR: config.py not found. Copy config.example.py → config.py and fill in values.")
    sys.exit(1)

# ============================================================================
# AGOL Connection
# ============================================================================
try:
    gis = GIS("pro")
except Exception:
    gis = GIS("https://www.arcgis.com", config.AGOL_USERNAME, config.AGOL_PASSWORD)

# ============================================================================
# Logging Setup
# ============================================================================
log_dir = config.LOG_DIR
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

log_filename = os.path.join(log_dir, f"iNat_Pipeline_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler(log_filename, encoding='utf-8'), logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

logger.info("="*70)
logger.info("RPMP iNaturalist Data Pipeline - Script Started")
logger.info("="*70)
logger.info(f"Log file: {log_filename}")
logger.info(f"Python: {sys.version}, Pandas: {pd.__version__}, GeoPandas: {gpd.__version__}")
script_start_time = datetime.datetime.now()

# ============================================================================
# OAuth Authentication — credentials from config, not hardcoded
# ============================================================================
CLIENT_ID     = config.INAT_CLIENT_ID
CLIENT_SECRET = config.INAT_CLIENT_SECRET
REDIRECT_URI  = "urn:ietf:wg:oauth:2.0:oob"
TOKEN_FILE    = config.INAT_TOKEN_FILE
TOKEN_URL     = "https://www.inaturalist.org/oauth/token"
API_BASE_URL  = "https://api.inaturalist.org/v1"

def load_token():
    logger.info("Loading authentication token...")
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            token = json.load(f)
        logger.info("✓ Token loaded")
        return token
    logger.warning("✗ Token file not found")
    return None

def save_token(token):
    with open(TOKEN_FILE, "w") as f:
        json.dump(token, f, indent=2)
    logger.info("✓ Token saved")

def validate_token(session):
    try:
        r = session.get(f"{API_BASE_URL}/me", timeout=10)
        if r.status_code == 401:
            logger.critical("Token invalid — generate new token at https://www.inaturalist.org/oauth/applications")
            return False
        elif r.status_code == 200:
            logger.info(f"✓ Token valid. Authenticated as: {r.json().get('login','Unknown')}")
            return True
        return True
    except Exception as e:
        logger.warning(f"⚠ Could not validate token: {e} — continuing anyway")
        return True

def refresh_access_token(token):
    logger.info("Refreshing access token...")
    try:
        r = requests.post(TOKEN_URL, data={"grant_type": "refresh_token", "refresh_token": token["refresh_token"],
                                            "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET})
        r.raise_for_status()
        new_token = r.json()
        if "expires_in" in new_token and "expires_at" not in new_token:
            new_token["expires_at"] = time.time() + new_token["expires_in"]
        save_token(new_token)
        logger.info("✓ Token refreshed")
        return new_token
    except Exception as e:
        logger.error(f"CRITICAL: Token refresh failed: {e}")
        try:
            inat_email_notifications.send_refresh_token_warning(0, config.ADMIN_EMAIL)
        except Exception:
            pass
        sys.exit(1)

logger.info("="*70 + "\nOAUTH AUTHENTICATION\n" + "="*70)
token = load_token()
if token is None:
    logger.critical(f"No token file found at {TOKEN_FILE}. Run RPMP_iNat.ipynb to authenticate first.")
    sys.exit(1)

session = OAuth2Session(CLIENT_ID, token=token)
if not validate_token(session):
    sys.exit(1)
logger.info("✓ Ready to make authenticated API calls\n")

# ============================================================================
# Programme Species Lists
# ============================================================================
logger.info("="*70 + "\nDEFINING PROGRAMME SPECIES LISTS\n" + "="*70)

programme_species = {
    "Progressive Containment": {
        "names": ["Banana Passionfruit","Boneseed","Darwin's Barberry","Evergreen Buckthorn","Rhamnus alaternus","Grey Willow","Salix cinerea","Moth Plant",
                  "Old Man's Beard","Lodgepole Pine","Mountain Pine","Scots Pine","Dwarf Mountain Pine",
                  "Passiflora tarminiana","Passiflora tripartita","Passiflora tarminiana × tripartita","Passiflora tripartita mollissima",
                  "Clematis vitalba","Osteospermum moniliferum","Osteospermum moniliferum moniliferum","Elkea", "Passiflora tripartita var. mollissima"],
        "taxon_ids": [1442036,61400,75751,82856,168326,75499,67747,48934,135715,58722,135727, 879226,
                      1442036,1442037,1442036,404420,412975,133171,133168,160697,61400,61400,600447,133169,78358]
    },
    "Eradication": {
        "names": ["Alligator Weed","Blue Passionflower","Cathedral Bells","Chilean Rhubarb","Giant Rhubarb","Chinese Pennisetum",
                  "Climbing Alstroemeria","Climbing Spindleberry","Himalayan Balsam","Chilean Needle Grass","Mexican Feathergrass",
                  "Serrated Tussock","Purple Loosestrife","Queensland Poplar","Homalanthus populifolius","Black Cherry","Rum Cherry","Senegal Tea",
                  "Saltmarsh Cordgrass","Sporobolus alterniflorus × foliosus","Common Cordgrass","Small Cord-Grass",
                  "Dense-flowered Cord Grass","Townsend's Cord-Grass","Woolly Nightshade","Cobaea scandens",
                  "Reynoutria japonica","Bomarea multiflora","Japanese knotweed", "Cup-and-saucer Vine"],
        "taxon_ids": [75386,51454,164333,77310,1432862,1030051,283354,64540,47892,165658,165660,165660,61321,369932,
                      54834,54834,407490,772903,773011,772983,772998,772990,773009,133287,164333,430005,914922,285911]
    },
    "Exclusion": {
        "names": ["African Feathergrass","California Bulrush","Chilean Needle Grass","Heath Rush","Humped Bladderwort",
                  "Manchurian Wild Rice","Noogoora Burr","Common Reed","Saffron Thistle","Arrowhead",
                  "Sweet Pittosporum","Tussock Hawkweed","Sagittaria platyphylla"],
        "taxon_ids": [1080223,47159,165658,164948,79464,407086,57920,64237,64232,48071,51594,409445,69816]
    }
}

for prog, data in programme_species.items():
    logger.info(f"  {prog}: {len(data['taxon_ids'])} taxon IDs")

# ============================================================================
# Fetch Observations from iNaturalist
# ============================================================================
logger.info("="*70 + "\nFETCHING OBSERVATIONS FROM iNATURALIST API\n" + "="*70)

project_id = config.INAT_PROJECT_ID
url = f"{API_BASE_URL}/observations"
params = {"project_id": project_id, "per_page": 200, "page": 1, "order": "desc", "order_by": "created_at", "quality_grade": "any"}
observations, page_count = [], 0

try:
    while True:
        logger.info(f"Fetching page {params['page']}...")
        max_retries, retry_count, response = 3, 0, None
        while retry_count < max_retries:
            try:
                response = session.get(url, params=params, timeout=30)
                break
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                retry_count += 1
                if retry_count < max_retries:
                    wait_time = 5 * retry_count
                    logger.warning(f"Connection error (attempt {retry_count}/{max_retries}): {e}")
                    time.sleep(wait_time)
                else:
                    raise

        if response is None: break
        if response.status_code != 200:
            logger.error(f"API failed: {response.status_code}")
            break
        data = response.json()
        if "results" not in data or not data["results"]: break
        observations.extend(data["results"])
        page_count += 1
        logger.info(f"  Page {params['page']}: {len(data['results'])} obs (total: {len(observations)})")
        if len(data["results"]) < params["per_page"]: break
        params["page"] += 1

    logger.info(f"\n✓ Fetched {len(observations)} observations across {page_count} pages")
except Exception as e:
    logger.error(f"Error fetching observations: {e}\n{traceback.format_exc()}")
    sys.exit(1)

# ============================================================================
# Create Lookup Dictionaries
# ============================================================================
taxon_to_programme, name_to_programme = {}, {}
for programme, species_data in programme_species.items():
    for tid in species_data["taxon_ids"]: taxon_to_programme[tid] = programme
    for name in species_data["names"]: name_to_programme[name.lower().strip()] = programme
logger.info(f"Taxon ID lookup: {len(taxon_to_programme)} entries, Name lookup: {len(name_to_programme)} entries")
logger.debug(f"Name lookup keys (first 20): {list(name_to_programme.keys())[:20]}")

# ============================================================================
# Build DataFrame
# ============================================================================
logger.info("="*70 + "\nBUILDING DATAFRAME\n" + "="*70)
rows, stats = [], {"total":0,"with_private_coords":0,"obscured":0,"with_photos":0,"with_annotations":0}

try:
    for obs in observations:
        stats["total"] += 1
        private_lat, private_lon = obs.get("private_latitude"), obs.get("private_longitude")
        geojson_coords = obs.get("geojson", {}).get("coordinates", [None, None])
        lat = private_lat if private_lat is not None else geojson_coords[1]
        lon = private_lon if private_lon is not None else geojson_coords[0]
        is_obscured = obs.get("obscured", False)
        has_private_coords = private_lat is not None and private_lon is not None
        if has_private_coords: stats["with_private_coords"] += 1
        if is_obscured: stats["obscured"] += 1

        photos = obs.get("photos", [])
        if photos: stats["with_photos"] += 1
        photo1 = photos[0]["url"].replace("square","original") if len(photos)>=1 else None
        photo2 = photos[1]["url"].replace("square","original") if len(photos)>=2 else None
        photo3 = photos[2]["url"].replace("square","original") if len(photos)>=3 else None

        of_dict = {f.get("name") or f.get("field_id"): f.get("value") for f in (obs.get("observation_fields") or [])}
        taxon = obs.get("taxon", {})
        taxon_id, taxon_name, species_guess = taxon.get("id"), taxon.get("name",""), obs.get("species_guess","")
        # Ensure taxon_id is int for lookup (API may return as string or float)
        try:
            taxon_id = int(taxon_id) if taxon_id is not None else None
        except (ValueError, TypeError):
            taxon_id = None
        programme = (taxon_to_programme.get(taxon_id) or
                     name_to_programme.get(taxon_name.lower().strip()) or
                     name_to_programme.get(species_guess.lower().strip()) if species_guess else None)

        flowers_fruits = None
        for ann in obs.get("annotations", []):
            if ann.get("controlled_attribute_id") == 12:
                stats["with_annotations"] += 1
                vid = ann.get("controlled_value_id")
                if vid == 13: flowers_fruits = "Flowering"
                elif vid == 14: flowers_fruits = "Fruiting"
                elif vid == 15: flowers_fruits = "Flower Budding"

        rows.append({"id":obs.get("id"), "observation_url":f"https://www.inaturalist.org/observations/{obs.get('id')}",
            "taxon_id":taxon_id, "taxon_name":taxon_name, "species_guess":species_guess, "programme":programme,
            "observed_on":obs.get("observed_on"), "description":obs.get("description"),
            "user_login":obs.get("user",{}).get("login"), "user_name":obs.get("user",{}).get("name"),
            "place_guess":obs.get("place_guess"), "quality_grade":obs.get("quality_grade"),
            "geoprivacy":obs.get("geoprivacy"), "is_obscured":is_obscured, "has_private_coords":has_private_coords,
            "latitude":lat, "longitude":lon, "photoURL_1":photo1, "photoURL_2":photo2, "photoURL_3":photo3,
            "private_place_guess":obs.get("private_place_guess"), "private_latitude":obs.get("private_latitude"),
            "private_longitude":obs.get("private_longitude"), "obs_fields":of_dict, "flowers_fruits":flowers_fruits})

    df = pd.DataFrame(rows)
    logger.info(f"✓ DataFrame: {len(df)} rows | Private coords: {stats['with_private_coords']} | Photos: {stats['with_photos']}")

except Exception as e:
    logger.error(f"Error building DataFrame: {e}\n{traceback.format_exc()}")
    sys.exit(1)

def categorize_observation_date(date_string):
    if pd.isna(date_string) or date_string == "": return "Unknown Date"
    try:
        days_ago = (datetime.datetime.now().date() - datetime.datetime.strptime(date_string, "%Y-%m-%d").date()).days
        if days_ago < 0: return "Future Date"
        if days_ago == 0: return "Today"
        if days_ago <= 7: return "Last 7 Days"
        if days_ago <= 30: return "Last 30 Days"
        if days_ago <= 90: return "Last 3 Months"
        if days_ago <= 365: return "Last Year"
        return "Older than 1 Year"
    except: return "Invalid Date"

df["date_category"] = df["observed_on"].apply(categorize_observation_date)
logger.info("\nDate categorization:")
for cat, cnt in df["date_category"].value_counts().sort_index().items(): logger.info(f"  {cat}: {cnt}")
logger.info("\nProgramme categorization:")
for prog, cnt in df["programme"].value_counts(dropna=False).items(): logger.info(f"  {prog if pd.notna(prog) else 'Uncategorized'}: {cnt}")
categorized = df["programme"].notna().sum()
uncategorized = df["programme"].isna().sum()
logger.info(f"\nCategorized: {categorized} ({categorized/len(df)*100:.1f}%) | Uncategorized: {uncategorized}")
if uncategorized > 0:
    logger.warning(f"⚠ {uncategorized} uncategorized observations:")
    for _, row in df[df["programme"].isna()][["taxon_id","taxon_name","species_guess","id"]].drop_duplicates("taxon_name").iterrows():
        logger.warning(f"  - ID: {row['id']}")
        logger.warning(f"    taxon_id: {row['taxon_id']}")
        logger.warning(f"    taxon_name: {repr(row['taxon_name'])}")
        logger.warning(f"    species_guess: {repr(row['species_guess'])}")

# ============================================================================
# Convert to GeoDataFrame and Reproject
# ============================================================================
logger.info("="*70 + "\nCONVERTING TO GEODATAFRAME\n" + "="*70)
try:
    from shapely.geometry import Point
    df_clean = df.dropna(subset=["latitude","longitude"]).copy()
    if len(df) - len(df_clean) > 0: logger.warning(f"Dropped {len(df)-len(df_clean)} observations with missing coordinates")
    gdf = gpd.GeoDataFrame(df_clean, geometry=[Point(xy) for xy in zip(df_clean["longitude"], df_clean["latitude"])], crs="EPSG:4326")
    gdf_nztm = gdf.to_crs(epsg=2193)
    logger.info(f"✓ GeoDataFrame: {len(gdf_nztm)} features in NZTM2000 (EPSG:2193)")
except Exception as e:
    logger.error(f"Error creating GeoDataFrame: {e}\n{traceback.format_exc()}")
    sys.exit(1)

# ============================================================================
# Species to SMU and Common Name Mappings
# ============================================================================
taxon_name_to_smu = {
    "Passiflora tripartita":"SMU_Banana_Passionfruit","Passiflora tarminiana":"SMU_Banana_Passionfruit",
    "Passiflora tripartita mollissima":"SMU_Banana_Passionfruit","Passiflora tripartita azuayensis":"SMU_Banana_Passionfruit",
    "Elkea":"SMU_Banana_Passionfruit","Tacsonia":"SMU_Banana_Passionfruit",
    "Osteospermum moniliferum":"SMU_Boneseed","Osteospermum moniliferum moniliferum":"SMU_Boneseed",
    "Berberis darwinii":"SMU_Darwins_barberry","Rhamnus alaternus":None,"Salix cinerea":None,
    "Araujia hortorum":"SMU_Mothplant","Araujia sericifera":"SMU_Mothplant","Clematis vitalba":"SMU_Old_mans_beard",
    "Pinus contorta":"SMU_Pest_conifers","Pinus uncinata":"SMU_Pest_conifers","Pinus mugo":"SMU_Pest_conifers","Pinus sylvestris":"SMU_Pest_conifers",
    "Alternanthera philoxeroides":"SMU_Master_Lay_Alligator_Weed","Passiflora caerulea":"SMU_Blue_passion_flower",
    "Cobaea scandens":"SMU_Cathedral_Bells","Gunnera tinctoria":"SMU_Gunnera","Gunnera manicata":"SMU_Gunnera",
    "Pennisetum alopecuroides":"SMU_Chinese_pennisetum","Bomarea multiflora":"SMU_Climbing_Alstromeria",
    "Celastrus orbiculatus":"SMU_Climbing_Spindleberry","Impatiens glandulifera":"SMU_Himalayan_Balsam",
    "Nasella neesiana":"SMU_Nasella_Tussock","Nassella trichotoma":"SMU_Nasella_Tussock","Nassella tenuissima":"SMU_Nasella_Tussock",
    "Lythrum salicaria":"SMU_Purple_loosestrife","Homalanthus populifolius":"SMU_Queensland_poplar",
    "Prunus serotina":"SMU_Rum_Cherry","Gymnocoronis spilanthoides":"SMU_Senegal_tea",
    "Spartina alterniflora":"SMU_Spartina","Spartina anglica":"SMU_Spartina","Sporobolus anglicus":"SMU_Spartina",
    "Sporobolus × townsendii":"SMU_Spartina","Spartina densiflora":"SMU_Spartina","Spartina maritima":"SMU_Spartina","Spartina patens":"SMU_Spartina",
    "Solanum mauritianum":"SMU_Woolly_Nightshade","Reynoutria japonica":"SMU_knotweed","Fallopia japonica":"SMU_knotweed",
    "Pennisetum macrourum":"SMU_African_Feather_Grass","Sagittaria platyphylla":"SMU_Sagittaria","Sagittaria montevidensis":"SMU_Arrowhead",
    "Bolboschoenus robustus":None,"Juncus squarrosus":None,"Utricularia gibba":None,"Zizania latifolia":None,
    "Xanthium occidentale":None,"Phragmites australis":None,"Carthamus lanatus":None,"Pittosporum undulatum":None,"Hieracium lepidulum":None,
}

taxon_name_to_common = {
    "Passiflora tripartita":"Banana Passionfruit","Passiflora tarminiana":"Banana Passionfruit",
    "Passiflora tripartita mollissima":"Banana Passionfruit","Passiflora tripartita azuayensis":"Banana Passionfruit",
    "Elkea":"Banana Passionfruit","Tacsonia":"Banana Passionfruit",
    "Osteospermum moniliferum":"Boneseed","Osteospermum moniliferum moniliferum":"Boneseed",
    "Berberis darwinii":"Darwin's Barberry","Rhamnus alaternus":"Evergreen Buckthorn","Salix cinerea":"Grey Willow",
    "Araujia hortorum":"Moth Plant","Araujia sericifera":"Moth Plant","Clematis vitalba":"Old Man's Beard",
    "Pinus contorta":"Pest Conifers","Pinus uncinata":"Pest Conifers","Pinus mugo":"Pest Conifers","Pinus sylvestris":"Pest Conifers",
    "Alternanthera philoxeroides":"Alligator Weed","Passiflora caerulea":"Blue Passionflower","Cobaea scandens":"Cathedral Bells",
    "Gunnera tinctoria":"Chilean Rhubarb","Gunnera manicata":"Chilean Rhubarb","Pennisetum alopecuroides":"Chinese Pennisetum",
    "Bomarea multiflora":"Climbing Alstroemeria","Celastrus orbiculatus":"Climbing Spindleberry","Impatiens glandulifera":"Himalayan Balsam",
    "Nasella neesiana":"Nassella Tussock","Nassella trichotoma":"Nassella Tussock","Nassella tenuissima":"Nassella Tussock",
    "Lythrum salicaria":"Purple Loosestrife","Homalanthus populifolius":"Queensland Poplar","Prunus serotina":"Rum Cherry",
    "Gymnocoronis spilanthoides":"Senegal Tea","Spartina alterniflora":"Spartina","Spartina anglica":"Spartina",
    "Sporobolus anglicus":"Spartina","Sporobolus × townsendii":"Spartina","Spartina densiflora":"Spartina","Spartina maritima":"Spartina","Spartina patens":"Spartina",
    "Solanum mauritianum":"Woolly Nightshade","Reynoutria japonica":"Japanese Knotweed","Fallopia japonica":"Japanese Knotweed",
    "Pennisetum macrourum":"African Feathergrass","Sagittaria platyphylla":"Arrowhead","Sagittaria montevidensis":"Arrowhead",
    "Bolboschoenus robustus":"California Bulrush","Juncus squarrosus":"Heath Rush","Utricularia gibba":"Humped Bladderwort",
    "Zizania latifolia":"Manchurian Wild Rice","Xanthium occidentale":"Noogoora Burr","Phragmites australis":"Common Reed",
    "Carthamus lanatus":"Saffron Thistle","Pittosporum undulatum":"Sweet Pittosporum","Hieracium lepidulum":"Tussock Hawkweed",
}

# ============================================================================
# Split by Programme and Apply Mappings
# ============================================================================
logger.info("="*70 + "\nSPLITTING BY PROGRAMME\n" + "="*70)
gdf_progressive = gdf_nztm[gdf_nztm["programme"] == "Progressive Containment"].copy()
gdf_eradication = gdf_nztm[gdf_nztm["programme"] == "Eradication"].copy()
gdf_exclusion   = gdf_nztm[gdf_nztm["programme"] == "Exclusion"].copy()
logger.info(f"Progressive: {len(gdf_progressive)}, Eradication: {len(gdf_eradication)}, Exclusion: {len(gdf_exclusion)}")

def assign_smu_layer(row):
    return taxon_name_to_smu.get(row["taxon_name"]) if pd.notna(row["taxon_name"]) else None

def get_standardized_name(row):
    if pd.notna(row["taxon_name"]) and row["taxon_name"] in taxon_name_to_common:
        return taxon_name_to_common[row["taxon_name"]]
    return row["species_guess"] if pd.notna(row["species_guess"]) else row["taxon_name"]

for gdf_x in [gdf_progressive, gdf_eradication, gdf_exclusion]:
    gdf_x["smu_layer"]   = gdf_x.apply(assign_smu_layer, axis=1)
    gdf_x["speciesName"] = gdf_x.apply(get_standardized_name, axis=1)

logger.info("✓ SMU assignments and standardized names applied")
for prog_name, gdf_prog in [("Progressive Containment",gdf_progressive),("Eradication",gdf_eradication),("Exclusion",gdf_exclusion)]:
    no_smu = gdf_prog[gdf_prog["smu_layer"].isna()]
    if len(no_smu) > 0:
        logger.warning(f"⚠ {prog_name}: {len(no_smu)} without SMU layer")
        for _, row in no_smu[["taxon_name","speciesName"]].drop_duplicates().iterrows():
            logger.warning(f"  - {row['taxon_name']} ({row['speciesName']})")

# ============================================================================
# Spatial Join Helper Functions — paths from config, not hardcoded
# ============================================================================
gdb_path = config.GDB_SMU_PATH
sde_path = config.SDE_PATH

def arc_sde_feature_to_gdf(sde_conn_path, feature_path_within_sde):
    full_path = feature_path_within_sde if sde_conn_path in feature_path_within_sde else fr"{sde_conn_path}\{feature_path_within_sde}"
    logger.info(f"  Loading SDE feature: {full_path}")
    try: desc = arcpy.Describe(full_path)
    except Exception as e: raise RuntimeError(f"arcpy.Describe failed for '{full_path}': {e}")
    sr = desc.spatialReference
    epsg = None
    try:
        wkid = getattr(sr, "factoryCode", None)
        if wkid and int(wkid) != 0: epsg = int(wkid)
    except Exception: pass
    fields = [f.name for f in arcpy.ListFields(full_path) if f.type not in ("Geometry","OID")]
    features = []
    with arcpy.da.SearchCursor(full_path, ["SHAPE@WKB"]+fields) as cursor:
        for row in cursor:
            geom = None
            if row[0]:
                try: geom = shapely.wkb.loads(row[0])
                except Exception: geom = shapely.wkb.loads(bytes(row[0]))
            attr = {fld: val for fld, val in zip(fields, row[1:])}
            attr["geometry"] = geom
            features.append(attr)
    gdf = gpd.GeoDataFrame(features, crs=(f"EPSG:{epsg}" if epsg else None))
    logger.info(f"  ✓ Loaded {len(gdf)} features")
    return gdf

def spatial_join_with_smu(gdf, programme_name, distance_threshold=100):
    logger.info(f"\n{'='*70}\nSPATIAL JOIN: {programme_name}\n{'='*70}")
    logger.info(f"Input: {len(gdf)} observations, threshold: {distance_threshold}m")
    for col in ["operatingArea","Name","SMU_Name","Designation","Status_25_26"]:
        if col not in gdf.columns: gdf[col] = None

    for smu_layer in gdf["smu_layer"].dropna().unique():
        logger.info(f"\n  Processing {smu_layer}...")
        try:
            smu_gdf = gpd.read_file(gdb_path, layer=smu_layer)
            mask = gdf["smu_layer"] == smu_layer
            obs_for_smu = gdf[mask].copy()
            joined = gpd.sjoin(obs_for_smu, smu_gdf[["operatingArea","Name","SMU_Name","Designation","Status_25_26","geometry"]], how="left", predicate="within")
            field_map = {f: (f"{f}_right" if f"{f}_right" in joined.columns else f) for f in ["operatingArea","Name","SMU_Name","Designation","Status_25_26"]}
            matched, unmatched = 0, []
            for idx in joined.index:
                if pd.notna(joined.loc[idx, "index_right"]):
                    matched += 1
                    for field, col in field_map.items():
                        if pd.notna(joined.loc[idx, col]): gdf.at[idx, field] = joined.loc[idx, col]
                else: unmatched.append(idx)
            logger.info(f"    ✓ Within join: {matched}/{len(obs_for_smu)} matched")
            if unmatched:
                logger.info(f"    Nearest join for {len(unmatched)} unmatched...")
                nearest_matched = 0
                for idx in unmatched:
                    point = obs_for_smu.loc[idx, "geometry"]
                    smu_gdf["distance"] = smu_gdf.geometry.distance(point)
                    ni = smu_gdf["distance"].idxmin()
                    if smu_gdf.loc[ni, "distance"] <= distance_threshold:
                        nearest_matched += 1
                        for field in ["operatingArea","Name","SMU_Name","Designation","Status_25_26"]:
                            if field in smu_gdf.columns and pd.notna(smu_gdf.loc[ni, field]): gdf.at[idx, field] = smu_gdf.loc[ni, field]
                if nearest_matched: logger.info(f"    ✓ Nearest: {nearest_matched} additional matches")
                if "distance" in smu_gdf.columns: smu_gdf.drop(columns=["distance"], inplace=True)
        except Exception as e:
            logger.error(f"    ✗ Error loading {smu_layer}: {e}\n{traceback.format_exc()}")

    # PC special handling
    if programme_name == "Progressive Containment":
        target_species = ["Evergreen Buckthorn","Grey Willow"]
        needs_pc = gdf["SMU_Name"].isna() & gdf["speciesName"].isin(target_species)
        if needs_pc.sum() > 0:
            logger.info(f"\n  Special PC handling for {needs_pc.sum()} observations ({', '.join(target_species)})")
            try:
                pc_zone_gdf = arc_sde_feature_to_gdf(sde_path, "biosecurity.GISADMIN.Weeds_ProgressiveContainmentMappedZone")
                obs_need_pc = gdf[needs_pc].copy()
                if "Species" in pc_zone_gdf.columns:
                    pc_zone_gdf = pc_zone_gdf[pc_zone_gdf["Species"].isin(obs_need_pc["speciesName"].unique())]
                if pc_zone_gdf.crs is not None and obs_need_pc.crs is not None and pc_zone_gdf.crs != obs_need_pc.crs:
                    obs_need_pc = obs_need_pc.to_crs(pc_zone_gdf.crs)
                matched_pc = 0
                for species in obs_need_pc["speciesName"].unique():
                    obs_sp = obs_need_pc[obs_need_pc["speciesName"] == species]
                    pc_sp = pc_zone_gdf[pc_zone_gdf["Species"] == species] if "Species" in pc_zone_gdf.columns else pd.DataFrame()
                    if len(pc_sp) == 0: continue
                    joined = gpd.sjoin(obs_sp, pc_sp[["Label","geometry"]], how="left", predicate="within")
                    for idx in obs_sp.index:
                        if idx in joined.index:
                            lv = joined.loc[idx, "Label"]
                            if pd.notna(lv):
                                gdf.at[idx, "Designation"] = lv.iloc[0] if hasattr(lv,"iloc") else lv
                                matched_pc += 1
                logger.info(f"    ✓ PC Mapped Zone: {matched_pc}/{len(obs_need_pc)} matched")
                oa_gdf = gpd.read_file(gdb_path, layer="OperatingAreas")
                oa_obs = obs_need_pc.to_crs(oa_gdf.crs) if oa_gdf.crs != obs_need_pc.crs else obs_need_pc
                j_oa = gpd.sjoin(oa_obs, oa_gdf[["operatingArea","Name","geometry"]], how="left", predicate="within")
                oa_col = "operatingArea_right" if "operatingArea_right" in j_oa.columns else "operatingArea"
                nm_col = "Name_right" if "Name_right" in j_oa.columns else "Name"
                moa = 0
                for idx in j_oa.index:
                    if idx not in gdf.index: continue
                    if pd.notna(j_oa.loc[idx,"index_right"]):
                        if pd.notna(j_oa.loc[idx,oa_col]): gdf.at[idx,"operatingArea"] = j_oa.loc[idx,oa_col]
                        if pd.notna(j_oa.loc[idx,nm_col]): gdf.at[idx,"Name"] = j_oa.loc[idx,nm_col]
                        moa += 1
                logger.info(f"    ✓ Operating Areas: {moa}/{len(obs_need_pc)} matched")
            except Exception as e:
                logger.error(f"    ✗ PC zone fallback error: {e}\n{traceback.format_exc()}")

    # Tertiary fallback
    no_smu = gdf["SMU_Name"].isna()
    if programme_name == "Progressive Containment":
        no_smu = gdf["speciesName"].isin(["Evergreen Buckthorn","Grey Willow"]) & gdf["SMU_Name"].isna()
    if no_smu.sum() > 0:
        logger.info(f"\n  Tertiary fallback (OperatingAreas) for {no_smu.sum()} remaining...")
        try:
            oa_gdf = gpd.read_file(gdb_path, layer="OperatingAreas")
            j = gpd.sjoin(gdf[no_smu].copy(), oa_gdf[["operatingArea","Name","geometry"]], how="left", predicate="within")
            ma, un = 0, []
            for idx in j.index:
                if pd.notna(j.loc[idx,"index_right"]):
                    ma += 1
                    if "operatingArea_right" in j.columns and pd.notna(j.loc[idx,"operatingArea_right"]): gdf.at[idx,"operatingArea"]=j.loc[idx,"operatingArea_right"]
                    if "Name_right" in j.columns and pd.notna(j.loc[idx,"Name_right"]): gdf.at[idx,"Name"]=j.loc[idx,"Name_right"]
                    if programme_name in ["Eradication","Exclusion"] and pd.isna(gdf.at[idx,"Designation"]): gdf.at[idx,"Designation"]="AMZ"
                else: un.append(int(gdf.at[idx,"id"]))
            logger.info(f"    ✓ Matched {ma}/{no_smu.sum()} to Operating Areas")
            if un: logger.warning(f"    ⚠ {no_smu.sum()-ma} still unmatched: {un}")
        except Exception as e:
            logger.error(f"    ✗ Operating Areas fallback error: {e}\n{traceback.format_exc()}")

    if programme_name in ["Eradication","Exclusion"]:
        still_none = gdf["Designation"].isna()
        if still_none.sum() > 0:
            gdf.loc[still_none, "Designation"] = "AMZ"
            logger.info(f"  Final fallback: {still_none.sum()} set to Designation='AMZ'")

    logger.info(f"\n✓ SPATIAL JOIN COMPLETE: {programme_name}")
    logger.info(f"  SMU: {gdf['SMU_Name'].notna().sum()}/{len(gdf)}, Area: {gdf['operatingArea'].notna().sum()}/{len(gdf)}, Designation: {gdf['Designation'].notna().sum()}/{len(gdf)}")
    return gdf

# ============================================================================
# Perform Spatial Joins
# ============================================================================
logger.info("="*70 + "\nPERFORMING SPATIAL JOINS\n" + "="*70)
try:
    gdf_progressive_joined = spatial_join_with_smu(gdf_progressive.copy(), "Progressive Containment")
    gdf_eradication_joined = spatial_join_with_smu(gdf_eradication.copy(), "Eradication")
    gdf_exclusion_joined   = spatial_join_with_smu(gdf_exclusion.copy(), "Exclusion")
    logger.info("\n✓ All spatial joins completed")
except Exception as e:
    logger.error(f"✗ Critical error in spatial joins: {e}\n{traceback.format_exc()}")
    sys.exit(1)

# ============================================================================
# Spatial Join — Managed Pest Plant Sites
# ============================================================================
# Intersects Eradication and Progressive Containment observations against the
# BioS Pest Plant Sites layer (active sites only, species-matched).
# Adds is_in_site (Y/N) and BaseSiteID to both layers.
# Exclusion gets is_in_site = 'N' and BaseSiteID = None by default.
# ============================================================================

logger.info("="*70 + "\nSPATIAL JOIN — MANAGED PEST PLANT SITES\n" + "="*70)

PEST_PLANT_SITES_URL = "https://services1.arcgis.com/VuN78wcRdq1Oj69W/arcgis/rest/services/BioS_Pest_Plants_Sites/FeatureServer/0"
SITE_BUFFER_METRES   = 10

# Maps site speciesID code → iNat speciesName
SITE_SPECIES_CODE_TO_INAT = {
    "AFG": "African Feathergrass",
    "ALW": "Alligator Weed",
    "ARH": "Arrowhead",
    "BPF": "Blue Passionflower",
    "CAL": "Climbing Alstroemeria",
    "CBS": "Cathedral Bells",
    "CHR": "Chilean Rhubarb",
    "CPS": "Chinese Pennisetum",
    "CSB": "Climbing Spindleberry",
    "HBA": "Himalayan Balsam",
    "KNW": "Japanese Knotweed",
    "NAS": "Nassella Tussock",
    "PLS": "Purple Loosestrife",
    "QPL": "Queensland Poplar",
    "RCY": "Rum Cherry",
    "SNT": "Senegal Tea",
    "SPT": "Spartina",
    "WNS": "Woolly Nightshade",
    "BAP": "Banana Passionfruit",
    "BSD": "Boneseed",
    "CON": "Pest Conifers",
    "DBY": "Darwin's Barberry",
    "DMP": "Pest Conifers",
    "EBT": "Evergreen Buckthorn",
    "GWO": "Grey Willow",
    "MPT": "Moth Plant",
    "OMB": "Old Man's Beard",
    "SCP": "Pest Conifers",
}

PROGRAMME_TO_PROJECT_TYPE = {
    "Eradication":             "Eradication",
    "Progressive Containment": "Progressive Containment - Mapped",
}

def fetch_pest_plant_sites_prod(layer_url, project_type_filter):
    """
    Fetch active BioS Pest Plant Sites using arcpy (authenticated via ArcGIS Pro).
    Filters to activeSite = 'Y' and the given projectType.
    Returns a GeoDataFrame in NZTM2000 (EPSG:2193), or None on failure.
    """
    try:
        logger.info(f"  Fetching active sites for projectType = '{project_type_filter}'...")
        where = f"projectType = '{project_type_filter}' AND activeSite = 'Y'"
        rows = []
        with arcpy.da.SearchCursor(layer_url, ["SHAPE@", "BaseSiteID", "specieID"], where_clause=where) as cursor:
            for row in cursor:
                shape, base_site_id, species_id = row
                if shape is None:
                    continue
                try:
                    wkb = bytes(shape.WKB)
                    geom = shapely.wkb.loads(wkb)
                    if not geom.is_valid:
                        geom = geom.buffer(0)
                    rows.append({
                        "BaseSiteID":   base_site_id,
                        "inat_species": SITE_SPECIES_CODE_TO_INAT.get(species_id),
                        "geometry":     geom
                    })
                except Exception:
                    continue

        if not rows:
            logger.warning(f"  ⚠ No valid features found for '{project_type_filter}'")
            return None

        sites_gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:2193")
        sites_gdf = sites_gdf[sites_gdf.geometry.is_valid & sites_gdf.geometry.notna()]
        logger.info(f"  ✓ Fetched {len(sites_gdf)} active sites")
        return sites_gdf

    except Exception as e:
        logger.error(f"  ✗ Error fetching pest plant sites: {e}\n{traceback.format_exc()}")
        return None


def add_site_fields_prod(obs_gdf, sites_gdf, programme_name):
    """
    Spatially intersect observations with pest plant sites (10m buffer).
    Only matches where site speciesID maps to the same iNat speciesName
    as the observation — prevents cross-species false matches.
    Adds is_in_site ('Y'/'N') and BaseSiteID.
    """
    obs_gdf = obs_gdf.copy()
    obs_gdf["is_in_site"] = "N"
    obs_gdf["BaseSiteID"] = None

    if sites_gdf is None or len(sites_gdf) == 0:
        logger.warning(f"  ⚠ No sites available for {programme_name} — all set to is_in_site='N'")
        return obs_gdf

    if obs_gdf.crs != sites_gdf.crs:
        obs_gdf = obs_gdf.to_crs(sites_gdf.crs)

    sites_buffered = sites_gdf.copy()
    sites_buffered["geometry"] = sites_gdf.geometry.buffer(SITE_BUFFER_METRES)

    joined = gpd.sjoin(
        obs_gdf[["speciesName", "geometry"]],
        sites_buffered[["BaseSiteID", "inat_species", "geometry"]],
        how="left",
        predicate="within"
    )

    # Deduplicate — keep first match per observation
    joined_deduped = joined[~joined.index.duplicated(keep="first")]

    match_count = 0
    for idx in joined_deduped.index:
        site_species = joined_deduped.loc[idx, "inat_species"]
        obs_species  = joined_deduped.loc[idx, "speciesName"]
        base_id      = joined_deduped.loc[idx, "BaseSiteID"]

        if pd.notna(base_id) and pd.notna(site_species) and site_species == obs_species:
            obs_gdf.at[idx, "is_in_site"] = "Y"
            obs_gdf.at[idx, "BaseSiteID"] = str(base_id)
            match_count += 1

    logger.info(f"  ✓ {programme_name}: {match_count}/{len(obs_gdf)} matched to an active managed site (species-matched, within {SITE_BUFFER_METRES}m)")
    return obs_gdf


try:
    logger.info("\n[1/2] Eradication sites...")
    erad_sites_gdf = fetch_pest_plant_sites_prod(PEST_PLANT_SITES_URL, PROGRAMME_TO_PROJECT_TYPE["Eradication"])
    logger.info("\n[2/2] Progressive Containment sites...")
    prog_sites_gdf = fetch_pest_plant_sites_prod(PEST_PLANT_SITES_URL, PROGRAMME_TO_PROJECT_TYPE["Progressive Containment"])

    logger.info("\nApplying site intersection...")
    gdf_eradication_joined  = add_site_fields_prod(gdf_eradication_joined,  erad_sites_gdf, "Eradication")
    gdf_progressive_joined  = add_site_fields_prod(gdf_progressive_joined,  prog_sites_gdf, "Progressive Containment")

    # Exclusion does not participate in site join — initialise fields as N/None
    gdf_exclusion_joined["is_in_site"] = "N"
    gdf_exclusion_joined["BaseSiteID"] = None

    erad_in = (gdf_eradication_joined["is_in_site"] == "Y").sum()
    prog_in = (gdf_progressive_joined["is_in_site"] == "Y").sum()
    logger.info(f"\n✓ PEST PLANT SITES JOIN COMPLETE")
    logger.info(f"  Eradication:             {erad_in}/{len(gdf_eradication_joined)} in an active managed site")
    logger.info(f"  Progressive Containment: {prog_in}/{len(gdf_progressive_joined)} in an active managed site")

except Exception as e:
    logger.error(f"✗ Error in pest plant sites join: {e}\n{traceback.format_exc()}")
    logger.warning("  Continuing without site fields — is_in_site and BaseSiteID will be empty")
    for gdf_x in [gdf_eradication_joined, gdf_progressive_joined, gdf_exclusion_joined]:
        gdf_x["is_in_site"] = "N"
        gdf_x["BaseSiteID"] = None

# ============================================================================
# Export to GDB — output path from config, not hardcoded
# ============================================================================
logger.info("="*70 + "\nEXPORTING TO GEODATABASE\n" + "="*70)
output_gdb = config.OUTPUT_GDB
logger.info(f"Output GDB: {output_gdb}")

def prepare_for_export(gdf):
    gdf_export = gdf.copy()
    for col in ["photoURL_1","photoURL_2","photoURL_3"]:
        if col in gdf_export.columns: gdf_export[col] = gdf_export[col].fillna("")
    if "obs_fields" in gdf_export.columns: gdf_export["obs_fields"] = gdf_export["obs_fields"].apply(lambda x: str(x) if x else None)
    if "smu_layer" in gdf_export.columns: gdf_export = gdf_export.drop(columns=["smu_layer"])
    return gdf_export

def set_field_aliases(gdb_path, fc_name, alias_dict):
    fc_path = os.path.join(gdb_path, fc_name)
    cnt = 0
    for fn, alias in alias_dict.items():
        try: arcpy.management.AlterField(fc_path, fn, new_field_alias=alias); cnt += 1
        except: pass
    logger.info(f"  Set {cnt} field aliases")

field_aliases = {"observation_url":"iNaturalist Observation URL Link","taxon_name":"Taxon Name","place_guess":"Location",
    "programme":"RPMP Programme","observed_on":"Observation Date","user_login":"Observer User Name","Name":"Operator Name",
    "operatingArea":"Operating Area","SMU_Name":"SMU Name","Status_25_26":"Status 25-26",
    "quality_grade":"Observation Quality Grade","flowers_fruits":"Flowers or Fruit","description":"Description",
    "is_in_site":"In Managed Site (Y/N)","BaseSiteID":"Managed Site ID (if applicable)"}

try:
    for label, gdf_x, layer_name in [
        ("Progressive Containment", gdf_progressive_joined, "iNat_ProgressiveContainment"),
        ("Eradication",             gdf_eradication_joined, "iNat_Eradication"),
        ("Exclusion",               gdf_exclusion_joined,   "iNat_Exclusion")]:
        exp = prepare_for_export(gdf_x)
        exp.to_file(output_gdb, layer=layer_name, driver="OpenFileGDB")
        set_field_aliases(output_gdb, layer_name, field_aliases)
        logger.info(f"✓ {layer_name} exported ({len(exp)} features)")

    gdf_all = pd.concat([gdf_progressive_joined, gdf_eradication_joined, gdf_exclusion_joined], ignore_index=True)
    gdf_all_export = prepare_for_export(gdf_all)
    gdf_all_export.to_file(output_gdb, layer="iNat_AllProgrammes", driver="OpenFileGDB")
    set_field_aliases(output_gdb, "iNat_AllProgrammes", field_aliases)
    logger.info(f"✓ iNat_AllProgrammes exported ({len(gdf_all_export)} features)")
    logger.info(f"\n✓ ALL FEATURE CLASSES EXPORTED — {len(gdf_all_export)} total to {output_gdb}")
except Exception as e:
    logger.error(f"✗ Export error: {e}\n{traceback.format_exc()}")
    sys.exit(1)

# ============================================================================
# Track New Observations — tracking file path from config, not hardcoded
# ============================================================================
logger.info("="*70 + "\nTRACKING NEW OBSERVATIONS\n" + "="*70)
tracking_file = config.TRACKING_FILE

def load_previous_observations(fp):
    if os.path.exists(fp):
        try:
            with open(fp,"r") as f: data = json.load(f)
            logger.info(f"✓ Loaded {len(data.get('observation_ids',[]))} previous obs (last run: {data.get('last_run','Unknown')})")
            return set(data.get("observation_ids",[]))
        except Exception as e: logger.error(f"Error loading tracking: {e}"); return set()
    logger.info("No tracking file — first run"); return set()

def save_current_observations(fp, obs_ids):
    try:
        with open(fp,"w") as f:
            json.dump({"last_run":datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),"total_observations":len(obs_ids),"observation_ids":list(obs_ids)}, f, indent=2)
        logger.info(f"✓ Saved {len(obs_ids)} observation IDs"); return True
    except Exception as e: logger.error(f"✗ Error saving tracking: {e}"); return False

previous_obs_ids = load_previous_observations(tracking_file)
current_obs_ids  = set(gdf_all["id"].tolist())
new_obs_ids      = current_obs_ids - previous_obs_ids
logger.info(f"Previous: {len(previous_obs_ids)} | Current: {len(current_obs_ids)} | New: {len(new_obs_ids)}")

if new_obs_ids:
    logger.info(f"\n⚠ {len(new_obs_ids)} new observations detected")
    new_observations = gdf_all[gdf_all["id"].isin(new_obs_ids)].copy()
    for prog in ["Progressive Containment","Eradication","Exclusion"]:
        cnt = len(new_observations[new_observations["programme"] == prog])
        if cnt: logger.info(f"  {prog}: {cnt}")

    priority_new_obs = new_observations[new_observations["programme"].isin(["Eradication","Exclusion"])].copy()
    if len(priority_new_obs) > 0:
        logger.warning(f"\n🔔 PRIORITY: {len(priority_new_obs)} new Eradication/Exclusion observations")
        notification_data = []
        for _, row in priority_new_obs.iterrows():
            oa = row.get("operatingArea","Unknown")
            staff = inat_email_notifications.AREA_TO_STAFF.get(oa, "Unassigned")
            notification_data.append({"observation_id":row["id"],"observation_url":row.get("observation_url",f"https://www.inaturalist.org/observations/{row['id']}"),
                "programme":row["programme"],"taxon_name":row["taxon_name"],"species_name":row.get("speciesName","Unknown"),
                "observed_on":row["observed_on"],"operating_area":oa,"staff_member":staff,"latitude":row["latitude"],"longitude":row["longitude"],
                "quality_grade":row["quality_grade"],"user_name":row["user_name"],"description":row.get("description",""),
                "flowers_fruits":row.get("flowers_fruits",""),"photoURL_1":row.get("photoURL_1",""),
                "is_in_site":row.get("is_in_site","N"),"BaseSiteID":row.get("BaseSiteID",None)})

        notification_file = config.NOTIFICATION_FILE  # from config, not hardcoded
        try:
            staff_notifs = {}
            for n in notification_data:
                staff_notifs.setdefault(n["staff_member"],[]).append(n)
            for sn, notifs in staff_notifs.items(): logger.info(f"  {sn}: {len(notifs)} obs")
            with open(notification_file,"w") as f:
                json.dump({"generated_at":datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),"total_notifications":len(notification_data),"notifications":notification_data},f,indent=2)
            logger.info(f"✓ Notification data saved: {len(notification_data)} notifications")
        except Exception as e: logger.error(f"✗ Error saving notifications: {e}\n{traceback.format_exc()}")
    else:
        logger.info("\n✓ No new Eradication/Exclusion observations")
        nf = config.NOTIFICATION_FILE
        if os.path.exists(nf):
            try: os.remove(nf); logger.info("  Cleared previous notification file")
            except Exception as e: logger.warning(f"  Could not remove notification file: {e}")
else:
    logger.info("✓ No new observations since last run")

# ============================================================================
# Update ArcGIS Online
# ============================================================================
logger.info("="*70 + "\nUPDATING ARCGIS ONLINE\n" + "="*70)

try:
    gis = GIS("pro")
    connected_username = None
    try: connected_username = gis.users.me.username
    except Exception:
        try:
            up = gis.properties.get("user",None)
            if isinstance(up,dict): connected_username = up.get("username")
            elif hasattr(up,"username"): connected_username = up.username
        except Exception: pass
    if not connected_username: connected_username = "unknown"
    logger.info(f"✓ Connected as: {connected_username} ({gis.properties.get('portalName','unknown')})")
    if connected_username == "unknown": raise RuntimeError("GIS('pro') unknown user")
except Exception as e:
    logger.warning(f"⚠ GIS('pro') failed: {e}. Using explicit credentials fallback...")
    try:
        gis = GIS("https://www.arcgis.com", config.AGOL_USERNAME, config.AGOL_PASSWORD)  # from config
        connected_username = gis.users.me.username if getattr(gis.users.me,"username",None) else "unknown"
        if connected_username == "unknown": raise RuntimeError("Fallback yielded unknown user")
        logger.info(f"✓ Connected (fallback) as: {connected_username}")
    except Exception as e2:
        logger.error(f"✗ AGOL connection failed: {e2}\n{traceback.format_exc()}")
        sys.exit(1)

SERVICE_ITEM_ID = config.AGOL_SERVICE_ITEM_ID  # from config, not hardcoded
logger.info(f"Target service ID: {SERVICE_ITEM_ID}")

def update_hosted_service(item_id, gdb_path, temp_pc_path=None):
    try:
        item = gis.content.get(item_id)
        if item is None: logger.error(f"✗ Item not found: {item_id}"); return False
        logger.info(f"Found service: {item.title} (Owner: {item.owner})")
        flc = FeatureLayerCollection.fromitem(item)
        layer_mapping = {"iNat_AllProgrammes":"iNat_AllProgrammes","iNat_Eradication":"iNat_Eradication",
                         "iNat_ProgressiveContainment":"iNat_ProgressiveContainment","iNat_Exclusion":"iNat_Exclusion"}
        ok, fail = 0, 0
        for gdb_layer, svc_layer in layer_mapping.items():
            logger.info(f"\n[{ok+fail+1}/{len(layer_mapping)}] {svc_layer}...")
            lyr = next((l for l in flc.layers if l.properties.name == svc_layer), None)
            if lyr is None: logger.warning(f"  ⚠ Layer not found — skipping"); fail += 1; continue
            try: old_cnt = lyr.query(return_count_only=True); logger.info(f"  Current features: {old_cnt}")
            except: old_cnt = "unknown"
            try: lyr.delete_features(where="1=1"); logger.info("  ✓ Deleted existing features")
            except Exception as e: logger.error(f"  ✗ Delete failed: {e}"); fail += 1; continue
            gdb_fc = temp_pc_path if (gdb_layer == "iNat_ProgressiveContainment" and temp_pc_path) else os.path.join(gdb_path, gdb_layer)
            try:
                arcpy.env.workspace = gdb_path; arcpy.ClearWorkspaceCache_management()
                if gdb_layer not in arcpy.ListFeatureClasses(): logger.error(f"  ✗ FC not found"); fail += 1; continue
                arcpy.env.workspace = ""; arcpy.ClearWorkspaceCache_management(); time.sleep(2)
                arcpy.env.overwriteOutput = True
                arcpy.management.Append(inputs=gdb_fc, target=lyr.url, schema_type="NO_TEST")
                arcpy.ClearWorkspaceCache_management(); time.sleep(0.5)
                new_cnt = lyr.query(return_count_only=True)
                logger.info(f"  ✓ Append: {old_cnt} → {new_cnt} features"); ok += 1
            except Exception as e:
                logger.error(f"  ✗ Append failed: {e}\n{traceback.format_exc()}"); fail += 1
                try: arcpy.env.workspace = ""; arcpy.ClearWorkspaceCache_management()
                except: pass
        logger.info(f"\nAGOL: {ok}/{len(layer_mapping)} successful, {fail} failed")
        return ok == len(layer_mapping)
    except Exception as e:
        logger.error(f"✗ Critical AGOL error: {e}\n{traceback.format_exc()}"); return False

# ============================================================================
# Send Alert Emails (Before AGOL Update)
# ============================================================================
logger.info("="*70 + "\nSENDING ALERT EMAILS (Pre-AGOL)\n" + "="*70)
email_success = False
try:
    nf = config.NOTIFICATION_FILE
    if os.path.exists(nf):
        with open(nf,"r") as f: notif_data = json.load(f)
        if notif_data.get("total_notifications",0) > 0:
            from inat_email_notifications import send_eradication_exclusion_alert
            staff_notifs = {}
            for n in notif_data.get("notifications",[]): staff_notifs.setdefault(n.get("staff_member","Unassigned"),[]).append(n)
            sent = 0
            for sn, notifs in staff_notifs.items():
                try:
                    if send_eradication_exclusion_alert(notifs, inat_email_notifications.STAFF_EMAILS.get(sn)): sent += len(notifs); logger.info(f"  ✓ Sent {len(notifs)} to {sn}")
                    else: logger.warning(f"  ⚠ Failed to send to {sn}")
                except Exception as e: logger.error(f"  ✗ Error sending to {sn}: {e}")
            if sent: email_success = True; logger.info(f"✓ {sent} alert email(s) sent")
    else: logger.info("  No pending notifications")
except Exception as e: logger.error(f"✗ Alert email error: {e}\n{traceback.format_exc()}")

# ============================================================================
# AGOL Update
# ============================================================================
logger.info("\n" + "="*70 + "\nUPDATING ARCGIS ONLINE\n" + "="*70)
agol_success = False
try:
    arcpy.env.workspace = ""; arcpy.ClearWorkspaceCache_management(); time.sleep(1)
    arcpy.env.workspace = output_gdb; arcpy.ClearWorkspaceCache_management()
    fcs = arcpy.ListFeatureClasses()
    missing = [l for l in ["iNat_ProgressiveContainment","iNat_Eradication","iNat_Exclusion","iNat_AllProgrammes"] if l not in fcs]
    if missing: raise Exception(f"Missing feature classes: {missing}")
    logger.info(f"✓ Feature classes verified: {', '.join(fcs)}")
    arcpy.env.workspace = ""; arcpy.ClearWorkspaceCache_management(); time.sleep(1)
    success = update_hosted_service(SERVICE_ITEM_ID, output_gdb, None)
    if success:
        logger.info("✓ AGOL update successful"); agol_success = True
        if save_current_observations(tracking_file, current_obs_ids): logger.info("✓ Tracking file updated")
        else: logger.warning("⚠ Tracking file failed to save")
    else: logger.error("✗ AGOL update failed — tracking NOT updated")
    arcpy.env.workspace = ""; arcpy.ClearWorkspaceCache_management()
except Exception as e:
    logger.error(f"✗ AGOL update error: {e}\n{traceback.format_exc()}"); success = False

# ============================================================================
# Send Email Notifications (Post AGOL)
# ============================================================================
logger.info("="*70 + "\nSENDING EMAIL NOTIFICATIONS\n" + "="*70)
try:
    sys.path.append(r"D:\Scripts\iNaturalist")
    import inat_email_notifications
    nf = config.NOTIFICATION_FILE
    if os.path.exists(nf):
        results = inat_email_notifications.process_notifications(nf)
        logger.info(f"✓ Processed: {results['notifications_processed']}, Sent: {results['emails_sent']}, Failed: {results.get('emails_failed',0)}")
        if results.get("staff_notifications"):
            for sn, ei in results["staff_notifications"].items(): logger.info(f"  {sn} ({ei['email']}): {ei['count']} obs")
    else:
        logger.info("No pending notifications"); results = {"notifications_processed":0,"emails_sent":0,"emails_failed":0}
except ImportError as e:
    logger.error(f"✗ Could not import email module: {e}"); results = {"notifications_processed":0,"emails_sent":0,"emails_failed":0}
except Exception as e:
    logger.error(f"✗ Email error: {e}\n{traceback.format_exc()}"); results = {"notifications_processed":0,"emails_sent":0,"emails_failed":0}

# ============================================================================
# Script Summary
# ============================================================================
elapsed = (datetime.datetime.now() - script_start_time).total_seconds()
logger.info("\n" + "="*70)
logger.info(f"COMPLETE — {elapsed:.1f}s ({elapsed/60:.1f}min) — {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
logger.info("="*70)
logger.info(f"[DATA]       Fetched:{len(observations)} Processed:{len(gdf_all)} Cat:{df['programme'].notna().sum()} Uncat:{df['programme'].isna().sum()}")
logger.info(f"[PROGRAMMES] PC:{len(gdf_progressive_joined)} Erad:{len(gdf_eradication_joined)} Excl:{len(gdf_exclusion_joined)}")
logger.info(f"[NEW OBS]    {len(new_obs_ids)} detected")
logger.info(f"[GDB]        {len(gdf_all_export)} features → {output_gdb}")
logger.info(f"[AGOL]       {'✓ SUCCESS' if ('success' in dir() and success) else '✗ FAILED'}")
logger.info(f"[EMAIL]      Sent:{results.get('emails_sent',0)} Failed:{results.get('emails_failed',0)}")
logger.info(f"[LOG]        {log_filename}")

# Run Summary Email
try:
    from inat_email_notifications import send_run_summary, ADMIN_EMAIL
    summary = {"success":agol_success,"total_observations":len(gdf_all),"new_observations":len(new_obs_ids),
               "observations_by_programme":{"Progressive Containment":len(gdf_progressive_joined),"Eradication":len(gdf_eradication_joined),"Exclusion":len(gdf_exclusion_joined)},
               "agol_updated":agol_success,"email_alerts_sent":email_success,"staff_notified":[],"errors":[]}
    if send_run_summary(summary, ADMIN_EMAIL): logger.info("✓ Run summary email sent")
    else: logger.warning("⚠ Run summary email failed")
except Exception as e: logger.warning(f"⚠ Could not send run summary: {e}")

# Final Exit Code
final_exit_code = 0
if "gdf_all_export" not in dir() or len(gdf_all_export) == 0:
    logger.error("CRITICAL: GDB export failed"); final_exit_code = 1
if not email_success and len(new_obs_ids) > 0:
    logger.error("CRITICAL: New observations detected but staff NOT notified"); final_exit_code = 1
if not agol_success: logger.warning("AGOL failed — data safely in GDB for manual upload")

logger.info("\n" + "="*70)
logger.info(f"GDB: {'✓' if 'gdf_all_export' in dir() else '✗'} | Email: {'✓' if email_success else '✗'} | AGOL: {'✓' if agol_success else '✗'}")
logger.info(f"{'✓ COMPLETED SUCCESSFULLY' if final_exit_code == 0 else '✗ COMPLETED WITH ERRORS'} (exit code: {final_exit_code})")
logger.info("="*70 + "\n")
sys.exit(final_exit_code)
