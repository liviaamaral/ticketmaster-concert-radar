from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Iterator

import requests
import snowflake.connector
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Edit this list to control which cities you ingest.
CITIES: list[dict[str, str]] = [
    {"city": "Pittsburgh", "stateCode": "PA", "countryCode": "US"},
    {"city": "New York",   "stateCode": "NY", "countryCode": "US"},
    {"city": "Los Angeles","stateCode": "CA", "countryCode": "US"},
    {"city": "Chicago",    "stateCode": "IL", "countryCode": "US"},
    {"city": "Austin",     "stateCode": "TX", "countryCode": "US"},
    {"city": "Nashville",  "stateCode": "TN", "countryCode": "US"},
    {"city": "Seattle",    "stateCode": "WA", "countryCode": "US"},
]

# Restrict to music events to keep the dataset focused. Ticketmaster's segment
# ID for "Music" is "KZFzniwnSyZfZ7v7nJ".
MUSIC_SEGMENT_ID = "KZFzniwnSyZfZ7v7nJ"

API_BASE = "https://app.ticketmaster.com/discovery/v2/events.json"
PAGE_SIZE = 100              # max allowed
MAX_PAGES_PER_CITY = 10      # safety cap; 10 * 100 = 1000 events/city/day
REQUEST_TIMEOUT = 30
RETRY_BACKOFF = [2, 5, 15]   # seconds; retry on 429/5xx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def fetch_events_for_city(api_key: str, city_params: dict[str, str]) -> Iterator[dict]:
    """Yield event dicts for one city, paginating until exhausted or capped."""
    page = 0
    while page < MAX_PAGES_PER_CITY:
        params = {
            "apikey": api_key,
            "size": PAGE_SIZE,
            "page": page,
            "segmentId": MUSIC_SEGMENT_ID,
            **city_params,
        }
        data = _get_with_retry(API_BASE, params)
        events = data.get("_embedded", {}).get("events", [])
        if not events:
            return
        yield from events

        total_pages = data.get("page", {}).get("totalPages", 0)
        if page + 1 >= total_pages:
            return
        page += 1
        # Polite pause between pages — API allows 5 req/sec but no need to push it
        time.sleep(0.25)


def _get_with_retry(url: str, params: dict) -> dict:
    """GET with simple retry/backoff on 429 and 5xx."""
    last_err: Exception | None = None
    for attempt, backoff in enumerate([0, *RETRY_BACKOFF]):
        if backoff:
            time.sleep(backoff)
        try:
            r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                log.warning("HTTP %s on attempt %s; will retry", r.status_code, attempt)
                continue
            r.raise_for_status()
        except requests.RequestException as e:
            last_err = e
            log.warning("Request error on attempt %s: %s", attempt, e)
    raise RuntimeError(f"Failed after retries: {last_err}")


# ---------------------------------------------------------------------------
# Snowflake load
# ---------------------------------------------------------------------------

def load_to_snowflake(rows: list[tuple[str, str, datetime, str]]) -> None:
    """Insert rows into RAW_EVENTS. payload is passed as JSON string and
    parsed server-side via PARSE_JSON."""
    if not rows:
        log.info("No rows to load.")
        return

    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "TICKETMASTER_WH"),
        database=os.environ.get("SNOWFLAKE_DATABASE", "TICKETMASTER"),
        schema=os.environ.get("SNOWFLAKE_SCHEMA", "RAW"),
        role=os.environ.get("SNOWFLAKE_ROLE", "ACCOUNTADMIN"),
    )
    try:
        cur = conn.cursor()
        cur.executemany(
            """
            INSERT INTO RAW_EVENTS (event_id, fetched_city, ingested_at, payload)
            SELECT column1, column2, column3, PARSE_JSON(column4)
            FROM VALUES (%s, %s, %s, %s)
            """,
            rows,
        )
        conn.commit()
        log.info("Inserted %d rows into RAW_EVENTS.", len(rows))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    api_key = os.environ["TICKETMASTER_API_KEY"]
    ingested_at = datetime.now(timezone.utc).replace(tzinfo=None)

    rows: list[tuple[str, str, datetime, str]] = []
    seen_keys: set[tuple[str, str]] = set()  # (event_id, city) within this run

    for city_params in CITIES:
        city_label = city_params["city"]
        log.info("Fetching events for %s ...", city_label)
        count = 0
        for event in fetch_events_for_city(api_key, city_params):
            event_id = event.get("id")
            if not event_id:
                continue
            key = (event_id, city_label)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            rows.append((event_id, city_label, ingested_at, json.dumps(event)))
            count += 1
        log.info("  %s: %d events", city_label, count)

    log.info("Total events to load: %d", len(rows))
    load_to_snowflake(rows)


if __name__ == "__main__":
    main()
