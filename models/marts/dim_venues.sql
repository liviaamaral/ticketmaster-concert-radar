WITH venues AS (
    SELECT
        venue_id,
        venue_name,
        venue_city,
        venue_state_code,
        venue_country_code,
        venue_address,
        venue_latitude,
        venue_longitude
    FROM {{ ref('stg_events') }}
    WHERE venue_id IS NOT NULL
    QUALIFY ROW_NUMBER() OVER (PARTITION BY venue_id ORDER BY ingested_at DESC) = 1
)

SELECT
    venue_id,
    venue_name,
    venue_city,
    venue_state_code,
    venue_country_code,
    venue_address,
    venue_latitude,
    venue_longitude
FROM venues
