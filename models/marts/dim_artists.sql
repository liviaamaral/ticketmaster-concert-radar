SELECT
    artist_id,
    artist_name
FROM {{ ref('stg_events') }}
WHERE artist_id IS NOT NULL
  AND artist_name IS NOT NULL
QUALIFY ROW_NUMBER() OVER (PARTITION BY artist_id ORDER BY ingested_at DESC) = 1
