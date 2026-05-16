SELECT
    fetched_city,
    event_date,
    genre,
    COUNT(*)                                    AS total_events,
    COUNT(DISTINCT artist_id)                   AS unique_artists,
    COUNT(DISTINCT venue_id)                    AS unique_venues,
    MIN(price_min)                              AS min_ticket_price,
    MAX(price_max)                              AS max_ticket_price,
    AVG((price_min + price_max) / 2.0)          AS avg_ticket_price
FROM {{ ref('fct_events') }}
WHERE event_date IS NOT NULL
GROUP BY 1, 2, 3
