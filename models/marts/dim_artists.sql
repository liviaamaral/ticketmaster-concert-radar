WITH artists AS (
    SELECT DISTINCT
        artist_id,
        artist_name
    FROM {{ ref('stg_events') }}
    WHERE artist_id IS NOT NULL
      AND artist_name IS NOT NULL
)

SELECT
    artist_id,
    artist_name
FROM artists
