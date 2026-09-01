"""Fetch PINs from Lincoln Park and Lakeview from Cook County's Parcel Universe
dataset (https://datacatalog.cookcountyil.gov/Property-Taxation/Assessor-Parcel-Universe/nj4t-kc8j)
and load them into the `parcels` table.
"""
import os
import time

import requests
from psycopg2.extras import execute_values

from src.db import get_connection

DOMAIN = "datacatalog.cookcountyil.gov"
DATASET_ID = "nj4t-kc8j"  # Assessor - Parcel Universe
ZIP_CODES = ["60614", "60657"]  # Lincoln Park, Lakeview
PAGE_SIZE = 50_000


def _get(url, params, headers):
    resp = requests.get(url, params=params, headers=headers, timeout=60)
    resp.raise_for_status()
    return resp.json()


def get_latest_year(url, headers):
    """Filter the dataset to find the latest year of data available."""
    result = _get(url, {"$select": "max(year)"}, headers)
    return int(float(result[0]["max_year"]))


def fetch_parcel_universe(zip_codes):
    """Pull pin/zip/location rows for the given zip codes, latest year only."""
    url = f"https://{DOMAIN}/resource/{DATASET_ID}.json"
    token = os.environ.get("SOCRATA_APP_TOKEN")
    headers = {"X-App-Token": token} if token else {}

    latest_year = get_latest_year(url, headers)
    zips_clause = ", ".join(f"'{z}'" for z in zip_codes)
    where = f"zip_code in ({zips_clause}) AND year = {latest_year}"

    rows = []
    offset = 0
    while True:
        params = {
            "$select": (
                "pin,zip_code,township_name,lat,lon,x_3435,y_3435,class,"
                "nbhd_code,chicago_community_area_name,access_cmap_walk_total_score,"
                "school_elementary_district_name,school_secondary_district_name,"
                "env_flood_fema_sfha"
            ),
            "$where": where,
            "$order": "pin",  # keeps pagination deterministic across requests
            "$limit": PAGE_SIZE,
            "$offset": offset,
        }
        batch = _get(url, params, headers)
        rows.extend(batch)

        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
        time.sleep(0.2)

    return rows


def load_parcels(rows):
    """Upsert rows into `parcels`, keyed on pin, skipping pins with missing coordinates."""
    required = ("lat", "lon", "x_3435", "y_3435")
    values = []
    skipped = 0
    for r in rows:
        if not all(r.get(f) for f in required):
            skipped += 1
            continue
        walk_score = r.get("access_cmap_walk_total_score")
        values.append(
            (
                r["pin"],
                r["zip_code"],
                r.get("township_name"),
                float(r["lat"]),
                float(r["lon"]),
                float(r["x_3435"]),
                float(r["y_3435"]),
                r.get("class"),
                r.get("nbhd_code"),
                r.get("chicago_community_area_name"),
                float(walk_score) if walk_score else None,
                r.get("school_elementary_district_name"),
                r.get("school_secondary_district_name"),
                bool(r.get("env_flood_fema_sfha")),
            )
        )

    if skipped:
        print(f"Skipped {skipped} rows missing lat/lon/x_3435/y_3435")

    with get_connection() as conn, conn.cursor() as cur:
        execute_values(
            cur,
            """
            insert into parcels (
                pin, zip_code, township_name, lat, lon, x_3435, y_3435,
                class, nbhd_code, community_area, walk_score,
                school_elementary_district, school_secondary_district, in_flood_zone
            )
            values %s
            on conflict (pin) do update set
                zip_code = excluded.zip_code,
                township_name = excluded.township_name,
                lat = excluded.lat,
                lon = excluded.lon,
                x_3435 = excluded.x_3435,
                y_3435 = excluded.y_3435,
                class = excluded.class,
                nbhd_code = excluded.nbhd_code,
                community_area = excluded.community_area,
                walk_score = excluded.walk_score,
                school_elementary_district = excluded.school_elementary_district,
                school_secondary_district = excluded.school_secondary_district,
                in_flood_zone = excluded.in_flood_zone
            """,
            values,
        )


if __name__ == "__main__":
    parcels = fetch_parcel_universe(ZIP_CODES)
    print(f"Fetched {len(parcels)} parcels for zips {ZIP_CODES}")
    load_parcels(parcels)
    print("Loaded into `parcels` table.")
