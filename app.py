from __future__ import annotations

import base64

import streamlit as st
import pandas as pd
import plotly.express as px
import snowflake.connector
from cryptography.hazmat.primitives.serialization import (
    load_der_private_key,
    load_pem_private_key,
    Encoding,
    PrivateFormat,
    NoEncryption,
)

st.set_page_config(
    page_title="Ticketmaster Concert Radar",
    page_icon="🎵",
    layout="wide",
)


# ── Connection ────────────────────────────────────────────────────────────────

def _private_key_der(key_str: str) -> bytes:
    """Accept either base64-encoded DER or PEM and return DER bytes."""
    key_str = key_str.strip()
    if key_str.startswith("-----"):
        # PEM format — reconstruct proper newlines in case TOML mangled them
        private_key = load_pem_private_key(key_str.encode(), password=None)
    else:
        # base64-encoded DER (recommended format for secrets.toml)
        # Add padding if stripped (safe — extra = chars are ignored)
        private_key = load_der_private_key(
            base64.b64decode(key_str + "=="), password=None
        )
    return private_key.private_bytes(
        encoding=Encoding.DER,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    )


@st.cache_resource
def get_connection() -> snowflake.connector.SnowflakeConnection:
    """Create a Snowflake connection using key-pair auth from st.secrets."""
    private_key_der = _private_key_der(st.secrets["snowflake"]["private_key"])
    return snowflake.connector.connect(
        account=st.secrets["snowflake"]["account"],
        user=st.secrets["snowflake"]["user"],
        private_key=private_key_der,
        role=st.secrets["snowflake"]["role"],
        warehouse=st.secrets["snowflake"]["warehouse"],
        database=st.secrets["snowflake"]["database"],
        schema="MARTS",
    )


def _query(sql: str) -> pd.DataFrame:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(sql)
    return cur.fetch_pandas_all()


# ── Data loading ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=3600)
def load_fct_events() -> pd.DataFrame:
    return _query("""
        SELECT
            event_id,
            fetched_city,
            event_name,
            event_url,
            event_date,
            event_status,
            genre,
            sub_genre,
            venue_id,
            venue_name,
            venue_city,
            venue_state_code,
            artist_id,
            artist_name,
            price_min,
            price_max,
            price_currency
        FROM TICKETMASTER.RAW_MARTS.FCT_EVENTS
        WHERE is_current = TRUE
        ORDER BY event_date
    """)


@st.cache_data(ttl=3600)
def load_fct_events_by_city() -> pd.DataFrame:
    return _query("""
        SELECT *
        FROM TICKETMASTER.RAW_MARTS.FCT_EVENTS_BY_CITY
        ORDER BY event_date
    """)


@st.cache_data(ttl=3600)
def load_dim_venues() -> pd.DataFrame:
    return _query("""
        SELECT *
        FROM TICKETMASTER.RAW_MARTS.DIM_VENUES
        WHERE venue_latitude IS NOT NULL
          AND venue_longitude IS NOT NULL
          AND is_current = TRUE
    """)


# ── App ───────────────────────────────────────────────────────────────────────

st.title("Concert Radar")
st.caption("Live music events across major U.S. cities · powered by Ticketmaster API")

with st.spinner("Loading data..."):
    try:
        fct = load_fct_events()
        agg = load_fct_events_by_city()
        venues = load_dim_venues()
    except Exception as e:
        st.error(f"Could not connect to Snowflake: {e}")
        st.stop()

# Snowflake returns uppercase column names
fct.columns = fct.columns.str.upper()
agg.columns = agg.columns.str.upper()
venues.columns = venues.columns.str.upper()

# Ensure date types
fct["EVENT_DATE"] = pd.to_datetime(fct["EVENT_DATE"])
agg["EVENT_DATE"] = pd.to_datetime(agg["EVENT_DATE"])


# ── Sidebar filters ───────────────────────────────────────────────────────────

st.sidebar.header("Filters")

cities = sorted(fct["FETCHED_CITY"].dropna().unique())
selected_cities = st.sidebar.multiselect("City", cities, default=cities)

genres = sorted(fct["GENRE"].dropna().unique())
selected_genres = st.sidebar.multiselect("Genre", genres, default=genres)

min_date = fct["EVENT_DATE"].min().date()
max_date = fct["EVENT_DATE"].max().date()
date_range = st.sidebar.date_input(
    "Date range",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date,
)

# Apply filters
start_date = pd.Timestamp(date_range[0])
end_date = pd.Timestamp(date_range[1]) if len(date_range) > 1 else pd.Timestamp(max_date)

mask = (
    fct["FETCHED_CITY"].isin(selected_cities)
    & fct["GENRE"].isin(selected_genres)
    & (fct["EVENT_DATE"] >= start_date)
    & (fct["EVENT_DATE"] <= end_date)
)
filtered = fct[mask]

agg_mask = (
    agg["FETCHED_CITY"].isin(selected_cities)
    & agg["GENRE"].isin(selected_genres)
    & (agg["EVENT_DATE"] >= start_date)
    & (agg["EVENT_DATE"] <= end_date)
)
filtered_agg = agg[agg_mask]


# ── KPI cards ─────────────────────────────────────────────────────────────────

k1, k2, k3, k4 = st.columns(4)
k1.metric("Total Events", f"{len(filtered):,}")
k2.metric("Unique Artists", f"{filtered['ARTIST_NAME'].nunique():,}")
k3.metric("Unique Venues", f"{filtered['VENUE_ID'].nunique():,}")
prices = filtered["PRICE_MIN"].dropna()
avg_price = f"${prices.mean():.2f}" if not prices.empty else "N/A"
k4.metric("Avg Min Ticket Price", avg_price)

st.divider()


# ── Charts row 1: Events by city + Top genres ─────────────────────────────────

col1, col2 = st.columns(2)

with col1:
    st.subheader("Events by City")
    city_counts = (
        filtered.groupby("FETCHED_CITY")
        .size()
        .reset_index(name="total_events")
        .sort_values("total_events", ascending=True)
    )
    fig = px.bar(
        city_counts,
        x="total_events",
        y="FETCHED_CITY",
        orientation="h",
        labels={"total_events": "Events", "FETCHED_CITY": "City"},
        color="total_events",
        color_continuous_scale="Blues",
    )
    fig.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=0))
    st.plotly_chart(fig, use_container_width=True)

with col2:
    st.subheader("Top Genres")
    genre_counts = (
        filtered.groupby("GENRE")
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
        .head(10)
    )
    fig2 = px.bar(
        genre_counts,
        x="GENRE",
        y="count",
        labels={"count": "Events", "GENRE": "Genre"},
        color="count",
        color_continuous_scale="Purples",
    )
    fig2.update_layout(coloraxis_showscale=False, margin=dict(l=0, r=0))
    st.plotly_chart(fig2, use_container_width=True)


# ── Charts row 2: Events over time + Ticket price distribution ────────────────

col3, col4 = st.columns(2)

with col3:
    st.subheader("Events Over Time (Next 30 Days)")
    next_30_days = pd.Timestamp.today().normalize()
    time_series = (
        filtered_agg[
            (filtered_agg["EVENT_DATE"] <= next_30_days + pd.Timedelta(days=30))
        ]
        .groupby(["EVENT_DATE", "FETCHED_CITY"])["TOTAL_EVENTS"]
        .sum()
        .reset_index()
    )
    fig3 = px.line(
        time_series,
        x="EVENT_DATE",
        y="TOTAL_EVENTS",
        color="FETCHED_CITY",
        labels={
            "TOTAL_EVENTS": "Events",
            "EVENT_DATE": "Date",
            "FETCHED_CITY": "City",
        },
    )
    fig3.update_layout(margin=dict(l=0, r=0))
    st.plotly_chart(fig3, use_container_width=True)

with col4:
    st.subheader("Ticket Price Distribution")
    price_data = filtered[filtered["PRICE_MIN"].notna()].copy()
    if not price_data.empty:
        fig4 = px.box(
            price_data,
            x="FETCHED_CITY",
            y="PRICE_MIN",
            color="FETCHED_CITY",
            labels={"PRICE_MIN": "Min Ticket Price (USD)", "FETCHED_CITY": "City"},
        )
        fig4.update_layout(showlegend=False, margin=dict(l=0, r=0))
        st.plotly_chart(fig4, use_container_width=True)
    else:
        st.info("No ticket price data available for selected filters.")

st.divider()


# ── Venue map ─────────────────────────────────────────────────────────────────

st.subheader("Venue Map")

venue_event_counts = (
    filtered.groupby("VENUE_ID")
    .size()
    .reset_index(name="event_count")
)
map_data = venues.merge(venue_event_counts, on="VENUE_ID", how="inner")

if not map_data.empty:
    fig5 = px.scatter_mapbox(
        map_data,
        lat="VENUE_LATITUDE",
        lon="VENUE_LONGITUDE",
        hover_name="VENUE_NAME",
        hover_data={
            "VENUE_CITY": True,
            "VENUE_STATE_CODE": True,
            "event_count": True,
            "VENUE_LATITUDE": False,
            "VENUE_LONGITUDE": False,
        },
        size="event_count",
        color="event_count",
        color_continuous_scale="Viridis",
        mapbox_style="carto-positron",
        zoom=3,
        center={"lat": 37.5, "lon": -96},
        labels={"event_count": "Events"},
    )
    fig5.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=450)
    st.plotly_chart(fig5, use_container_width=True)
else:
    st.info("No venue data for selected filters.")

st.divider()


# ── Upcoming events table ─────────────────────────────────────────────────────

st.subheader("Upcoming Events")

display_cols = {
    "EVENT_NAME": "Event",
    "FETCHED_CITY": "City",
    "EVENT_DATE": "Date",
    "ARTIST_NAME": "Artist",
    "VENUE_NAME": "Venue",
    "GENRE": "Genre",
    "PRICE_MIN": "Min Price",
    "PRICE_MAX": "Max Price",
    "EVENT_URL": "Ticket Link",
}
table = filtered[list(display_cols.keys())].rename(columns=display_cols).head(200)

st.dataframe(
    table,
    column_config={
        "Ticket Link": st.column_config.LinkColumn("Ticket Link"),
        "Min Price": st.column_config.NumberColumn("Min Price", format="$%.2f"),
        "Max Price": st.column_config.NumberColumn("Max Price", format="$%.2f"),
    },
    use_container_width=True,
    hide_index=True,
)

st.caption(
    f"Showing {len(table):,} of {len(filtered):,} upcoming events · "
    "Data refreshes every hour"
)
