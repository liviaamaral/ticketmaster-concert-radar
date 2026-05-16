{{
    config(materialized='table')
}}

-- SCD Type 2 history for events.
-- One row per (event_id, fetched_city, version), where a new version is
-- created whenever any of the tracked attributes change between ingestion runs:
-- event_status, event_date, event_time, price_min, price_max.
--
-- valid_from  = ingested_at when the change was first observed
-- valid_to    = ingested_at of the next version (NULL = still current)
-- is_current  = TRUE for the latest version of each event/city pair

WITH source AS (
    SELECT
        event_id,
        fetched_city,
        ingested_at,
        payload:dates.status.code::STRING           AS event_status,
        payload:dates.start.localDate::DATE         AS event_date,
        payload:dates.start.localTime::STRING       AS event_time,
        payload:priceRanges[0].min::FLOAT           AS price_min,
        payload:priceRanges[0].max::FLOAT           AS price_max,
        payload:priceRanges[0].currency::STRING     AS price_currency
    FROM {{ source('raw', 'raw_events') }}
),

-- Flag rows where any tracked attribute differs from the previous snapshot.
-- The very first snapshot per event/city always gets is_new_version = 1
-- because LAG returns NULL, which IS DISTINCT FROM any value.
change_detection AS (
    SELECT
        *,
        CASE
            WHEN LAG(event_status) OVER (PARTITION BY event_id, fetched_city ORDER BY ingested_at) IS DISTINCT FROM event_status THEN 1
            WHEN LAG(event_date)   OVER (PARTITION BY event_id, fetched_city ORDER BY ingested_at) IS DISTINCT FROM event_date   THEN 1
            WHEN LAG(event_time)   OVER (PARTITION BY event_id, fetched_city ORDER BY ingested_at) IS DISTINCT FROM event_time   THEN 1
            WHEN LAG(price_min)    OVER (PARTITION BY event_id, fetched_city ORDER BY ingested_at) IS DISTINCT FROM price_min    THEN 1
            WHEN LAG(price_max)    OVER (PARTITION BY event_id, fetched_city ORDER BY ingested_at) IS DISTINCT FROM price_max    THEN 1
            ELSE 0
        END AS is_new_version
    FROM source
),

-- Cumulative sum of is_new_version gives each distinct attribute state
-- a stable version number (1, 2, 3, ...).
versions AS (
    SELECT
        *,
        SUM(is_new_version) OVER (
            PARTITION BY event_id, fetched_city
            ORDER BY ingested_at
            ROWS UNBOUNDED PRECEDING
        ) AS version
    FROM change_detection
)

SELECT
    event_id,
    fetched_city,
    version,
    ingested_at                                                 AS valid_from,
    LEAD(ingested_at) OVER (
        PARTITION BY event_id, fetched_city
        ORDER BY ingested_at
    )                                                           AS valid_to,
    LEAD(ingested_at) OVER (
        PARTITION BY event_id, fetched_city
        ORDER BY ingested_at
    ) IS NULL                                                   AS is_current,
    event_status,
    event_date,
    event_time,
    price_min,
    price_max,
    price_currency
FROM versions
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY event_id, fetched_city, version
    ORDER BY ingested_at
) = 1
