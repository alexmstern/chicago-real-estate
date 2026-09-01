"""Fetch condo unit characteristics for tracked condo PINs from Cook
County's Residential Condominium Unit Characteristics dataset
(https://datacatalog.cookcountyil.gov/Property-Taxation/Assessor-Residential-Condominium-Unit-Characterist/3r7i-mrz4)
and load them into the `characteristics` table.
"""
import os
import time

from psycopg2.extras import execute_values

from src.db import get_connection
from src.fetch_sales import _get, chunked

DOMAIN = "datacatalog.cookcountyil.gov"
DATASET_ID = "3r7i-mrz4"  # Assessor - Residential Condominium Unit Characteristics
PIN_CHUNK_SIZE = 300


def get_tracked_pins():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("select pin from parcels")
        return [row[0] for row in cur.fetchall()]


def get_latest_year(url, headers):
    result = _get(url, {"$select": "max(year)"}, headers)
    return int(float(result[0]["max_year"]))


def fetch_characteristics_for_pins(pins):
    """Pull latest-year characteristics for the given condo PINs."""
    url = f"https://{DOMAIN}/resource/{DATASET_ID}.json"
    token = os.environ.get("SOCRATA_APP_TOKEN")
    headers = {"X-App-Token": token} if token else {}

    latest_year = get_latest_year(url, headers)

    rows = []
    for pin_chunk in chunked(pins, PIN_CHUNK_SIZE):
        pins_clause = ", ".join(f"'{p}'" for p in pin_chunk)
        where = f"pin in ({pins_clause}) AND year = {latest_year}"
        params = {
            "$select": (
                "pin,class,char_yrblt,char_unit_sf,char_bedrooms,char_full_baths,"
                "char_half_baths,is_parking_space,is_common_area,"
                "char_building_sf,char_building_pins"
            ),
            "$where": where,
            "$limit": 1_000,
        }
        batch = _get(url, params, headers)
        rows.extend(batch)
        time.sleep(0.2)

    return rows


def load_characteristics(rows):
    """Upsert rows into `characteristics`, keyed on pin."""
    values = []
    skipped = 0
    for r in rows:
        if not r.get("pin"):
            skipped += 1
            continue
        values.append(
            (
                r["pin"],
                r.get("class"),
                int(float(r["char_yrblt"])) if r.get("char_yrblt") else None,
                int(float(r["char_unit_sf"])) if r.get("char_unit_sf") else None,
                int(float(r["char_bedrooms"])) if r.get("char_bedrooms") else None,
                int(float(r["char_full_baths"])) if r.get("char_full_baths") else None,
                int(float(r["char_half_baths"])) if r.get("char_half_baths") else None,
                bool(r.get("is_parking_space")),
                bool(r.get("is_common_area")),
                int(float(r["char_building_sf"])) if r.get("char_building_sf") else None,
                int(float(r["char_building_pins"])) if r.get("char_building_pins") else None,
            )
        )

    if skipped:
        print(f"Skipped {skipped} rows missing pin")

    with get_connection() as conn, conn.cursor() as cur:
        execute_values(
            cur,
            """
            insert into characteristics (
                pin, class, year_built, sqft, bedrooms, full_baths, half_baths,
                is_parking_space, is_common_area, building_sf, building_unit_count
            )
            values %s
            on conflict (pin) do update set
                class = excluded.class,
                year_built = excluded.year_built,
                sqft = excluded.sqft,
                bedrooms = excluded.bedrooms,
                full_baths = excluded.full_baths,
                half_baths = excluded.half_baths,
                is_parking_space = excluded.is_parking_space,
                is_common_area = excluded.is_common_area,
                building_sf = excluded.building_sf,
                building_unit_count = excluded.building_unit_count
            """,
            values,
        )


if __name__ == "__main__":
    pins = get_tracked_pins()
    print(f"Loaded {len(pins)} PINs from parcels table")
    rows = fetch_characteristics_for_pins(pins)
    print(f"Fetched {len(rows)} characteristics rows")
    load_characteristics(rows)
    print("Loaded into `characteristics` table.")
