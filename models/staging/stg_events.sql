WITH source AS (
    SELECT *
    FROM {{ source('raw', 'raw_events') }}
),

-- Keep only the most-recently-ingested row per (event_id, fetched_city).
-- The same event can appear for multiple cities (e.g. a tour stop
-- returned by both the "Pittsburgh" and "New York" queries); preserving
-- one row per city enables cross-city comparisons downstream.
deduped AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY event_id, fetched_city
            ORDER BY ingested_at DESC
        ) AS _rn
    FROM source
),

renamed AS (
    SELECT
        -- Keys
        event_id,
        fetched_city,
        ingested_at,

        -- Event basics
        payload:name::STRING                                        AS event_name,
        payload:url::STRING                                         AS event_url,
        payload:dates.start.localDate::DATE                         AS event_date,
        payload:dates.start.localTime::STRING                       AS event_time,
        payload:dates.start.dateTime::TIMESTAMP_NTZ                 AS event_datetime_utc,
        payload:dates.status.code::STRING                           AS event_status,

        -- Classification (first / primary classification)
        payload:classifications[0].genre.name::STRING               AS genre,
        payload:classifications[0].subGenre.name::STRING            AS sub_genre,

        -- Venue (first venue in the embedded array)
        payload:_embedded.venues[0].id::STRING                      AS venue_id,
        payload:_embedded.venues[0].name::STRING                    AS venue_name,
        payload:_embedded.venues[0].city.name::STRING               AS venue_city,
        payload:_embedded.venues[0].state.stateCode::STRING         AS venue_state_code,
        payload:_embedded.venues[0].country.countryCode::STRING     AS venue_country_code,
        payload:_embedded.venues[0].address.line1::STRING           AS venue_address,
        payload:_embedded.venues[0].location.latitude::FLOAT        AS venue_latitude,
        payload:_embedded.venues[0].location.longitude::FLOAT       AS venue_longitude,

        -- Headlining artist (first attraction)
        payload:_embedded.attractions[0].id::STRING                 AS artist_id,
        payload:_embedded.attractions[0].name::STRING               AS artist_name,

        -- Ticket prices
        payload:priceRanges[0].min::FLOAT                           AS price_min,
        payload:priceRanges[0].max::FLOAT                           AS price_max,
        payload:priceRanges[0].currency::STRING                     AS price_currency,

        -- Preserve raw payload for downstream debugging
        payload

    FROM deduped
    WHERE _rn = 1
)

SELECT * FROM renamed
