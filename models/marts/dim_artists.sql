WITH source AS (
    SELECT
        payload:_embedded.attractions[0].id::STRING   AS artist_id,
        payload:_embedded.attractions[0].name::STRING AS artist_name,
        ingested_at
    FROM {{ source('raw', 'raw_events') }}
    WHERE payload:_embedded.attractions[0].id   IS NOT NULL
      AND payload:_embedded.attractions[0].name IS NOT NULL
),

-- One row per (artist_id, ingested_at) to avoid duplicate change signals
deduped AS (
    SELECT artist_id, artist_name, ingested_at
    FROM source
    QUALIFY ROW_NUMBER() OVER (PARTITION BY artist_id, ingested_at ORDER BY ingested_at) = 1
),

change_detection AS (
    SELECT
        *,
        CASE
            WHEN LAG(artist_name) OVER (PARTITION BY artist_id ORDER BY ingested_at)
                 IS DISTINCT FROM artist_name THEN 1
            ELSE 0
        END AS is_new_version
    FROM deduped
),

versions AS (
    SELECT
        *,
        SUM(is_new_version) OVER (
            PARTITION BY artist_id
            ORDER BY ingested_at
            ROWS UNBOUNDED PRECEDING
        ) AS version
    FROM change_detection
),

-- First observed row per (artist_id, version) = start of that version
versioned AS (
    SELECT artist_id, artist_name, ingested_at AS valid_from
    FROM versions
    QUALIFY ROW_NUMBER() OVER (PARTITION BY artist_id, version ORDER BY ingested_at) = 1
)

SELECT
    MD5(CONCAT_WS('|',
        COALESCE(CAST(artist_id  AS VARCHAR), ''),
        COALESCE(CAST(valid_from AS VARCHAR), '')
    ))                                                              AS artist_sk,
    artist_id,
    artist_name,
    valid_from,
    LEAD(valid_from) OVER (PARTITION BY artist_id ORDER BY valid_from) AS valid_to,
    LEAD(valid_from) OVER (PARTITION BY artist_id ORDER BY valid_from) IS NULL AS is_current
FROM versioned
