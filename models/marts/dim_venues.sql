WITH source AS (
    SELECT
        payload:_embedded.venues[0].id::STRING              AS venue_id,
        payload:_embedded.venues[0].name::STRING            AS venue_name,
        payload:_embedded.venues[0].city.name::STRING       AS venue_city,
        payload:_embedded.venues[0].state.stateCode::STRING AS venue_state_code,
        payload:_embedded.venues[0].country.countryCode::STRING AS venue_country_code,
        payload:_embedded.venues[0].address.line1::STRING   AS venue_address,
        payload:_embedded.venues[0].location.latitude::FLOAT  AS venue_latitude,
        payload:_embedded.venues[0].location.longitude::FLOAT AS venue_longitude,
        ingested_at
    FROM {{ source('raw', 'raw_events') }}
    WHERE payload:_embedded.venues[0].id IS NOT NULL
),

-- One row per (venue_id, ingested_at) to avoid duplicate change signals
deduped AS (
    SELECT
        venue_id, venue_name, venue_city, venue_state_code, venue_country_code,
        venue_address, venue_latitude, venue_longitude, ingested_at
    FROM source
    QUALIFY ROW_NUMBER() OVER (PARTITION BY venue_id, ingested_at ORDER BY ingested_at) = 1
),

change_detection AS (
    SELECT
        *,
        CASE
            WHEN LAG(venue_name)       OVER (PARTITION BY venue_id ORDER BY ingested_at) IS DISTINCT FROM venue_name       THEN 1
            WHEN LAG(venue_city)       OVER (PARTITION BY venue_id ORDER BY ingested_at) IS DISTINCT FROM venue_city       THEN 1
            WHEN LAG(venue_state_code) OVER (PARTITION BY venue_id ORDER BY ingested_at) IS DISTINCT FROM venue_state_code THEN 1
            WHEN LAG(venue_address)    OVER (PARTITION BY venue_id ORDER BY ingested_at) IS DISTINCT FROM venue_address    THEN 1
            ELSE 0
        END AS is_new_version
    FROM deduped
),

versions AS (
    SELECT
        *,
        SUM(is_new_version) OVER (
            PARTITION BY venue_id
            ORDER BY ingested_at
            ROWS UNBOUNDED PRECEDING
        ) AS version
    FROM change_detection
),

-- First observed row per (venue_id, version) = start of that version
versioned AS (
    SELECT
        venue_id, venue_name, venue_city, venue_state_code, venue_country_code,
        venue_address, venue_latitude, venue_longitude, ingested_at AS valid_from
    FROM versions
    QUALIFY ROW_NUMBER() OVER (PARTITION BY venue_id, version ORDER BY ingested_at) = 1
)

SELECT
    MD5(CONCAT_WS('|',
        COALESCE(CAST(venue_id   AS VARCHAR), ''),
        COALESCE(CAST(valid_from AS VARCHAR), '')
    ))                                                              AS venue_sk,
    venue_id,
    venue_name,
    venue_city,
    venue_state_code,
    venue_country_code,
    venue_address,
    venue_latitude,
    venue_longitude,
    valid_from,
    LEAD(valid_from) OVER (PARTITION BY venue_id ORDER BY valid_from) AS valid_to,
    LEAD(valid_from) OVER (PARTITION BY venue_id ORDER BY valid_from) IS NULL AS is_current
FROM versioned
