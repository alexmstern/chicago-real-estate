-- Schema definition for Supabase database

-- Enable PostGIS extension for spatial data support
create extension if not exists postgis;

-- parcel table definition
create table if not exists parcels (
    pin text primary key,
    zip_code text not null,
    township_name text,
    lat double precision not null,
    lon double precision not null,
    x_3435 double precision not null,
    y_3435 double precision not null,
    class text,
    nbhd_code text,
    community_area text,
    walk_score numeric,
    school_elementary_district text,
    school_secondary_district text,
    in_flood_zone boolean,
    geom geometry(Point, 4326) generated always as (
        ST_SetSRID(ST_MakePoint(lon, lat), 4326)
    ) stored,
    inserted_at timestamptz not null default now()
);

create index if not exists parcels_zip_idx on parcels (zip_code);
create index if not exists parcels_geom_idx on parcels using gist (geom);
create index if not exists parcels_class_idx on parcels (class);

-- sales table definition
create table if not exists sales (
    doc_no text primary key,
    pin text not null references parcels(pin),
    sale_date date not null,
    sale_price numeric not null,
    deed_type text,
    is_multisale boolean,
    inserted_at timestamptz not null default now()
);

create index if not exists sales_pin_idx on sales (pin);
create index if not exists sales_date_idx on sales (sale_date);
