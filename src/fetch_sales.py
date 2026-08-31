"""Fetch sales for our tracked parcels from Cook County's Parcel Sales dataset
(https://datacatalog.cookcountyil.gov/Property-Taxation/Assessor-Parcel-Sales/wvhk-k5uv)
and load them into the `sales` table.
"""
import os
import time

import requests
from psycopg2.extras import execute_values

from src.db import get_connection

DOMAIN = "datacatalog.cookcountyil.gov"
DATASET_ID = "wvhk-k5uv"  # Assessor - Parcel Sales
MIN_SALE_DATE = "2019-01-01T00:00:00"  # matches the project's train/test window
PIN_CHUNK_SIZE = 300  # keeps the `pin in (...)` clause well under URL length limits

# For this project, we are only interested in residential units (houses, condos, etc.),
# so we are only interested in parcels of certain Cook County property classes.
# Class definitions: https://prodassets.cookcountyassessoril.gov/s3fs-public/form_documents/Class_codes_definitions_12.16.24.pdf
RESIDENTIAL_CLASSES = [
    "202", "203", "204", "205", "206", "207", "208", "209", "210", "211", "212", "234", "278", "295", "299",
    "313", "314", "315", "318", "391", "396", "399",
]


def _get(url, params, headers):
    resp = requests.get(url, params=params, headers=headers, timeout=60)
    resp.raise_for_status()
    return resp.json()


def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def get_tracked_pins():
    """PINs already loaded into `parcels` (scoped to our zip codes)."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("select pin from parcels")
        return [row[0] for row in cur.fetchall()]


def fetch_sales_for_pins(pins):
    """Pull arm's-length sales since MIN_SALE_DATE for the given PINs,
    chunking the PIN list since it's too large for one request."""
    url = f"https://{DOMAIN}/resource/{DATASET_ID}.json"
    token = os.environ.get("SOCRATA_APP_TOKEN")
    headers = {"X-App-Token": token} if token else {}

    classes_clause = ", ".join(f"'{c}'" for c in RESIDENTIAL_CLASSES)

    rows = []
    for pin_chunk in chunked(pins, PIN_CHUNK_SIZE):
        pins_clause = ", ".join(f"'{p}'" for p in pin_chunk)
        where = (
            f"pin in ({pins_clause}) "
            f"AND sale_date >= '{MIN_SALE_DATE}' "
            f"AND class in ({classes_clause}) "  # livable units only, no vacant land/garages
            f"AND is_multisale = false "  # bundled sales don't have a per-parcel price
            f"AND sale_filter_same_sale_within_365 = false "
            f"AND sale_filter_less_than_10k = false "
            f"AND sale_filter_deed_type = false"
        )
        params = {
            "$select": "doc_no,pin,sale_date,sale_price,deed_type,is_multisale",
            "$where": where,
            "$limit": 10_000,
        }
        batch = _get(url, params, headers)
        rows.extend(batch)
        time.sleep(0.2)

    return rows


def load_sales(rows):
    """Upsert rows into `sales`, keyed on doc_no, skipping rows with missing sales data."""
    values = []
    skipped = 0
    for r in rows:
        if not r.get("doc_no") or not r.get("sale_price") or not r.get("sale_date"):
            skipped += 1
            continue
        values.append(
            (
                r["doc_no"],
                r["pin"],
                r["sale_date"][:10],  # "2023-01-12T00:00:00.000" -> "2023-01-12"
                float(r["sale_price"]),
                r.get("deed_type"),
                bool(r.get("is_multisale")),
            )
        )

    if skipped:
        print(f"Skipped {skipped} rows missing doc_no/sale_price/sale_date")

    with get_connection() as conn, conn.cursor() as cur:
        execute_values(
            cur,
            """
            insert into sales (doc_no, pin, sale_date, sale_price, deed_type, is_multisale)
            values %s
            on conflict (doc_no) do update set
                pin = excluded.pin,
                sale_date = excluded.sale_date,
                sale_price = excluded.sale_price,
                deed_type = excluded.deed_type,
                is_multisale = excluded.is_multisale
            """,
            values,
        )


if __name__ == "__main__":
    pins = get_tracked_pins()
    print(f"Loaded {len(pins)} PINs from parcels table")
    sales = fetch_sales_for_pins(pins)
    print(f"Fetched {len(sales)} sales since {MIN_SALE_DATE}")
    load_sales(sales)
    print("Loaded into `sales` table.")
