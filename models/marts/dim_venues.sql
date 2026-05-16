WITH venues AS (
    SELECT DISTINCT
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
