{{
    config(
        materialized='incremental',
        unique_key='event_sk',
        incremental_strategy='merge'
    )
}}

{% if is_incremental() %}
    {%- set max_valid_from_query -%}
        SELECT COALESCE(MAX(valid_from), '1900-01-01'::TIMESTAMP_NTZ) FROM {{ this }}
    {%- endset -%}
    {%- set max_valid_from = run_query(max_valid_from_query).columns[0][0] -%}
{% endif %}

WITH events AS (
    SELECT * FROM {{ ref('stg_event_snapshots') }}
    {% if is_incremental() %}
    WHERE valid_from > '{{ max_valid_from }}'
    {% endif %}
),

-- Static event attributes (name, url, genre, IDs) rarely change;
-- take the latest-known value per (event_id, fetched_city) from stg_events.
event_attrs AS (
    SELECT
        event_id,
        fetched_city,
        event_name,
        event_url,
        event_datetime_utc,
        genre,
        sub_genre,
        venue_id,
        artist_id
    FROM {{ ref('stg_events') }}
),

artists AS (SELECT * FROM {{ ref('dim_artists') }}),
venues  AS (SELECT * FROM {{ ref('dim_venues') }})

SELECT
    -- Surrogate key: one row per (event, city, version)
    MD5(CONCAT_WS('|',
        COALESCE(CAST(e.event_id     AS VARCHAR), ''),
        COALESCE(CAST(e.fetched_city AS VARCHAR), ''),
        COALESCE(CAST(e.version      AS VARCHAR), '')
    ))                              AS event_sk,

    -- Foreign keys to dims (point-in-time versioned)
    a.artist_sk,
    v.venue_sk,

    -- Natural keys (kept for convenience / backward compatibility)
    e.event_id,
    ea.artist_id,
    ea.venue_id,

    -- SCD2 metadata
    e.fetched_city,
    e.version,
    e.valid_from,
    e.valid_to,
    e.is_current,

    -- Slowly changing event attributes (from stg_event_snapshots)
    e.event_status,
    e.event_date,
    e.event_time,
    e.price_min,
    e.price_max,
    e.price_currency,

    -- Static event attributes (from stg_events latest snapshot)
    ea.event_name,
    ea.event_url,
    ea.event_datetime_utc,
    ea.genre,
    ea.sub_genre,

    -- Denormalized convenience columns from dims (current version at valid_from)
    a.artist_name,
    v.venue_name,
    v.venue_city,
    v.venue_state_code

FROM events e
LEFT JOIN event_attrs ea
    ON  e.event_id     = ea.event_id
    AND e.fetched_city = ea.fetched_city
-- Point-in-time join: find the dim version that was active at valid_from
LEFT JOIN artists a
    ON  ea.artist_id  = a.artist_id
    AND e.valid_from >= a.valid_from
    AND (e.valid_from < a.valid_to OR a.valid_to IS NULL)
LEFT JOIN venues v
    ON  ea.venue_id   = v.venue_id
    AND e.valid_from >= v.valid_from
    AND (e.valid_from < v.valid_to OR v.valid_to IS NULL)
