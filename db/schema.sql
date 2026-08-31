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
    geom geometry(Point, 4326) generated always as (
        ST_SetSRID(ST_MakePoint(lon, lat), 4326)
    ) stored,
    inserted_at timestamptz not null default now()
);

create index if not exists parcels_zip_idx on parcels (zip_code);
create index if not exists parcels_geom_idx on parcels using gist (geom);
