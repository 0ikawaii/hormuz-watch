"""
hormuz_watch/dashboard/app.py

HormuzWatch — Streamlit Dashboard MVP
Visualises oil prices, geopolitical risk, and country impact.

Run with:
    streamlit run dashboard/app.py
"""

import sys
from pathlib import Path
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent / "genai"))

# -------------------------------------------------------------------
# Page config
# -------------------------------------------------------------------
st.set_page_config(
    page_title="HormuzWatch",
    page_icon="🛢️",
    layout="wide",
    initial_sidebar_state="expanded",
)

DATA_DIR = Path(__file__).parent.parent / "data" / "raw"

# -------------------------------------------------------------------
# Data loaders (cached)
# -------------------------------------------------------------------

@st.cache_data(ttl=3600)
def load_oil_prices():
    p = DATA_DIR / "eia_oil_prices.csv"
    if p.exists():
        df = pd.read_csv(p, parse_dates=["date"])
        return df.sort_values("date")
    return pd.DataFrame()

@st.cache_data(ttl=3600)
def load_gdelt():
    p = DATA_DIR / "gdelt_daily_risk_timeline.csv"
    if p.exists():
        df = pd.read_csv(p, parse_dates=["date"])
        return df.sort_values("date")
    return pd.DataFrame()

@st.cache_data(ttl=86400)
def load_worldbank():
    # Use the most recent available file
    files = sorted(DATA_DIR.glob("worldbank_latest_*.csv"))
    if files:
        return pd.read_csv(files[-1])
    p = DATA_DIR / "worldbank_country_indicators.csv"
    if p.exists():
        df = pd.read_csv(p)
        if not df.empty:
            return df[df["year"] == df["year"].max()]
    return pd.DataFrame()

@st.cache_data(ttl=3600)
def load_fred():
    p = DATA_DIR / "fred_economic_indicators.csv"
    if p.exists():
        df = pd.read_csv(p, parse_dates=["date"])
        return df.sort_values("date")
    return pd.DataFrame()

@st.cache_data(ttl=3600)
def load_alphavantage_commodities():
    p = DATA_DIR / "alphavantage_commodities.csv"
    if p.exists():
        df = pd.read_csv(p, parse_dates=["date"])
        return df.sort_values("date")
    return pd.DataFrame()

@st.cache_data(ttl=3600)
def load_alphavantage_fx():
    p = DATA_DIR / "alphavantage_fx.csv"
    if p.exists():
        df = pd.read_csv(p, parse_dates=["date"])
        return df.sort_values("date")
    return pd.DataFrame()

PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"

@st.cache_data(ttl=3600)
def load_risk_index():
    p = PROCESSED_DIR / "hormuz_risk_index.csv"
    if p.exists():
        df = pd.read_csv(p, parse_dates=["date"])
        return df.sort_values("date")
    return pd.DataFrame()

@st.cache_data(ttl=3600)
def load_price_model_results():
    p = PROCESSED_DIR / "price_impact_results.json"
    if p.exists():
        import json
        with open(p) as f:
            return json.load(f)
    return None

@st.cache_data(ttl=3600)
def load_ml_price_model_results():
    p = PROCESSED_DIR / "ml_price_model_results.json"
    if p.exists():
        import json
        with open(p) as f:
            return json.load(f)
    return None

@st.cache_data(ttl=3600)
def load_backtest_results():
    p = PROCESSED_DIR / "backtest_results.json"
    if p.exists():
        import json
        with open(p) as f:
            return json.load(f)
    return None

@st.cache_data(ttl=1800)
def load_daily_briefing():
    p = PROCESSED_DIR / "daily_briefing.json"
    if p.exists():
        import json
        with open(p) as f:
            return json.load(f)
    return None

@st.cache_data(ttl=1800)
def load_data_quality_report():
    p = PROCESSED_DIR / "data_quality_report.json"
    if p.exists():
        import json
        with open(p) as f:
            return json.load(f)
    return None

LINEAGE_DATASETS = [
    "eia_oil_prices.csv", "eia_natgas_prices.csv", "eia_gulf_imports.csv",
    "gdelt_daily_risk_timeline.csv", "gdelt_hormuz_events.csv", "gdelt_hormuz_news.csv",
    "worldbank_country_indicators.csv", "fred_economic_indicators.csv",
    "newsapi_hormuz_articles.csv", "alphavantage_commodities.csv", "alphavantage_fx.csv",
]

# Collectors treat these as best-effort (non-fatal try/except around a
# frequently-rate-limited endpoint — see eia_collector.py's Gulf imports/
# natgas fetches and gdelt_collector.py's fetch_hormuz_news). A missing file
# here is expected pipeline behavior, not a broken dataset, so it's surfaced
# separately from real gaps in the lineage panel below.
OPTIONAL_LINEAGE_DATASETS = {"eia_gulf_imports.csv", "eia_natgas_prices.csv", "gdelt_hormuz_news.csv"}

@st.cache_data(ttl=1800)
def load_lineage_summary():
    """Per raw dataset: row count, latest source/run_id/fetched_at, staleness — computed
    directly from the _source/_fetched_at/_run_id columns BaseCollector.save_csv() stamps
    on every row (ingestion/base_collector.py), no Supabase/dbt connection required."""
    rows = []
    for filename in LINEAGE_DATASETS:
        p = DATA_DIR / filename
        if not p.exists():
            if filename in OPTIONAL_LINEAGE_DATASETS:
                rows.append({"dataset": filename, "status": "optional — not fetched this run"})
            else:
                rows.append({"dataset": filename, "status": "missing"})
            continue
        df = pd.read_csv(p)
        if "_run_id" not in df.columns:
            rows.append({"dataset": filename, "status": "no lineage columns (pre-Layer-1 file?)",
                        "row_count": len(df)})
            continue

        fetched = pd.to_datetime(df["_fetched_at"], errors="coerce", utc=True)
        latest_idx = fetched.idxmax() if fetched.notna().any() else df.index[-1]
        latest = df.loc[latest_idx]
        staleness_days = None
        if pd.notna(fetched.max()):
            staleness_days = (pd.Timestamp.now(tz="UTC") - fetched.max()).days

        rows.append({
            "dataset": filename,
            "status": "ok",
            "row_count": len(df),
            "source": latest.get("_source"),
            "latest_run_id": latest.get("_run_id"),
            "latest_fetched_at": str(fetched.max()) if pd.notna(fetched.max()) else None,
            "staleness_days": staleness_days,
        })
    return rows

# -------------------------------------------------------------------
# Sidebar
# -------------------------------------------------------------------

with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/8/8d/Hormuz_strait_en.svg/300px-Hormuz_strait_en.svg.png",
             use_column_width=True)
    st.title("🛢️ HormuzWatch")
    st.caption("Geopolitical & Economic Risk Monitor")
    st.divider()

    page = st.radio("Navigate", [
        "📊 Overview",
        "🛢️ Energy Markets",
        "⚠️ Geopolitical Risk",
        "📈 Risk Index (HRI)",
        "🔮 Price Forecast",
        "🧪 Backtest",
        "🌍 Country Impact",
        "📰 News Feed",
        "🤖 Ask HormuzWatch",
        "🔍 Data Lineage",
    ])

    st.divider()
    st.caption("Data sources: EIA · GDELT · World Bank · FRED")
    st.caption("Updated daily · Free tier")

# -------------------------------------------------------------------
# Load all data
# -------------------------------------------------------------------
df_prices  = load_oil_prices()
df_gdelt   = load_gdelt()
df_wb      = load_worldbank()
df_fred    = load_fred()
df_hri     = load_risk_index()
price_model_results = load_price_model_results()
ml_model_results = load_ml_price_model_results()
backtest_results  = load_backtest_results()
df_av_commodities = load_alphavantage_commodities()
df_av_fx          = load_alphavantage_fx()
daily_briefing     = load_daily_briefing()
data_quality_report = load_data_quality_report()
lineage_summary    = load_lineage_summary()

# -------------------------------------------------------------------
# Helper: data availability notice
# -------------------------------------------------------------------

def no_data_notice(source: str, instructions: str = ""):
    st.info(
        f"**No data yet for {source}.**\n\n"
        f"Run the ingestion pipeline first:\n"
        f"```bash\npython ingestion/run_pipeline.py\n```\n"
        + instructions,
        icon="ℹ️"
    )

# -------------------------------------------------------------------
# PAGE: Overview
# -------------------------------------------------------------------

if page == "📊 Overview":
    st.title("Strait of Hormuz — Global Risk Monitor")
    st.caption("Tracking the world's most critical energy chokepoint")

    if daily_briefing:
        st.info(
            f"**🤖 Daily Briefing** ({daily_briefing['hri_date']}) — "
            f"{daily_briefing['briefing']}",
            icon="🤖",
        )

    # KPI row
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if not df_prices.empty and "brent_usd" in df_prices.columns:
            latest = df_prices.dropna(subset=["brent_usd"]).iloc[-1]
            prev   = df_prices.dropna(subset=["brent_usd"]).iloc[-2] if len(df_prices) > 1 else latest
            delta  = float(latest["brent_usd"]) - float(prev["brent_usd"])
            st.metric("Brent Crude", f"${latest['brent_usd']:.2f}/bbl", f"{delta:+.2f}")
        else:
            st.metric("Brent Crude", "—", "No data")

    with col2:
        if not df_prices.empty and "wti_usd" in df_prices.columns:
            latest = df_prices.dropna(subset=["wti_usd"]).iloc[-1]
            prev   = df_prices.dropna(subset=["wti_usd"]).iloc[-2] if len(df_prices) > 1 else latest
            delta  = float(latest["wti_usd"]) - float(prev["wti_usd"])
            st.metric("WTI Crude", f"${latest['wti_usd']:.2f}/bbl", f"{delta:+.2f}")
        else:
            st.metric("WTI Crude", "—", "No data")

    with col3:
        if not df_gdelt.empty and "risk_signal" in df_gdelt.columns:
            latest_risk = df_gdelt["risk_signal"].iloc[-1]
            prev_risk   = df_gdelt["risk_signal"].iloc[-7] if len(df_gdelt) > 7 else latest_risk
            delta_risk  = latest_risk - prev_risk
            level = "🔴 High" if latest_risk > 0.6 else ("🟡 Moderate" if latest_risk > 0.3 else "🟢 Low")
            st.metric("Geopolitical Risk", level, f"{delta_risk:+.3f} vs 7d ago")
        else:
            st.metric("Geopolitical Risk", "—", "No data")

    with col4:
        if not df_gdelt.empty and "article_count" in df_gdelt.columns:
            last_7d = df_gdelt.tail(7)["article_count"].sum()
            st.metric("News Volume (7d)", f"{int(last_7d):,}", "articles")
        else:
            st.metric("News Volume (7d)", "—", "No data")

    st.divider()

    # Charts
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Oil Price Trend")
        if not df_prices.empty:
            fig = go.Figure()
            if "brent_usd" in df_prices.columns:
                fig.add_trace(go.Scatter(
                    x=df_prices["date"], y=df_prices["brent_usd"],
                    name="Brent", line=dict(color="#E8593C", width=2)
                ))
            if "wti_usd" in df_prices.columns:
                fig.add_trace(go.Scatter(
                    x=df_prices["date"], y=df_prices["wti_usd"],
                    name="WTI", line=dict(color="#3B8BD4", width=2)
                ))
            fig.update_layout(
                height=300, margin=dict(l=0, r=0, t=10, b=0),
                yaxis_title="USD / barrel", xaxis_title="",
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)"
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            no_data_notice("EIA oil prices")

    with col_right:
        st.subheader("Geopolitical Risk Signal")
        if not df_gdelt.empty and "risk_signal" in df_gdelt.columns:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df_gdelt["date"], y=df_gdelt["risk_signal"],
                fill="tozeroy", fillcolor="rgba(232,89,60,0.15)",
                line=dict(color="#E8593C", width=2),
                name="Risk signal"
            ))
            fig.update_layout(
                height=300, margin=dict(l=0, r=0, t=10, b=0),
                yaxis_title="Risk (0–1)", yaxis=dict(range=[0, 1]),
                xaxis_title="",
                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)"
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            no_data_notice("GDELT risk signal")

    # Country dependency table
    st.subheader("Hormuz Dependency by Country (latest year)")
    if not df_wb.empty and "hormuz_dependency_score" in df_wb.columns:
        display_cols = ["country_name", "hormuz_dependency_score",
                        "energy_imports_pct", "gdp_growth_pct", "inflation_pct"]
        display_cols = [c for c in display_cols if c in df_wb.columns]
        table = df_wb[display_cols].dropna(subset=["hormuz_dependency_score"])
        table = table.sort_values("hormuz_dependency_score", ascending=False).head(15)
        table.columns = [c.replace("_", " ").title() for c in table.columns]
        st.dataframe(table, use_container_width=True, hide_index=True)
    else:
        no_data_notice("World Bank indicators")

# -------------------------------------------------------------------
# PAGE: Energy Markets
# -------------------------------------------------------------------

elif page == "🛢️ Energy Markets":
    st.title("Energy Markets")

    if df_prices.empty and df_fred.empty:
        no_data_notice("energy prices", "Register free EIA and FRED keys in your .env file.")
        st.stop()

    # Date range filter
    col1, col2 = st.columns(2)
    with col1:
        date_from = st.date_input("From", value=pd.Timestamp("2022-01-01"))
    with col2:
        date_to = st.date_input("To", value=pd.Timestamp.today())

    if not df_prices.empty:
        mask = (df_prices["date"] >= pd.Timestamp(date_from)) & \
               (df_prices["date"] <= pd.Timestamp(date_to))
        df_filtered = df_prices[mask]

        fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                            subplot_titles=["Crude Oil Prices (USD/bbl)", "Price Spread (Brent – WTI)"],
                            vertical_spacing=0.12)

        if "brent_usd" in df_filtered.columns:
            fig.add_trace(go.Scatter(
                x=df_filtered["date"], y=df_filtered["brent_usd"],
                name="Brent", line=dict(color="#E8593C")), row=1, col=1)

        if "wti_usd" in df_filtered.columns:
            fig.add_trace(go.Scatter(
                x=df_filtered["date"], y=df_filtered["wti_usd"],
                name="WTI", line=dict(color="#3B8BD4")), row=1, col=1)

        if "brent_usd" in df_filtered.columns and "wti_usd" in df_filtered.columns:
            spread = df_filtered["brent_usd"] - df_filtered["wti_usd"]
            fig.add_trace(go.Bar(
                x=df_filtered["date"], y=spread, name="Spread",
                marker_color=spread.apply(lambda x: "#E8593C" if x > 0 else "#3B8BD4")
            ), row=2, col=1)

        fig.update_layout(height=500, margin=dict(l=0, r=0, t=40, b=0),
                          plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, use_container_width=True)

    # Gulf state import shares
    p = DATA_DIR / "eia_gulf_imports.csv"
    if p.exists():
        df_imp = pd.read_csv(p, parse_dates=["date"])
        st.subheader("U.S. Crude Imports from Gulf States")
        fig2 = px.area(df_imp, x="date", y="imports_mb", color="country",
                       title="Thousand Barrels Imported Monthly")
        fig2.update_layout(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig2, use_container_width=True)

    # Alpha Vantage: independent second price source (cross-check vs EIA)
    if not df_av_commodities.empty and "brent_usd" in df_prices.columns:
        st.divider()
        st.subheader("Cross-Source Price Check (EIA vs. Alpha Vantage)")
        st.caption("Same commodity, two independent providers — divergence is worth investigating "
                   "before trusting either source blindly.")
        merged_check = pd.merge(
            df_prices[["date", "brent_usd"]], df_av_commodities[["date", "brent_usd_av"]],
            on="date", how="inner",
        )
        if not merged_check.empty:
            fig_check = go.Figure()
            fig_check.add_trace(go.Scatter(x=merged_check["date"], y=merged_check["brent_usd"],
                                           name="Brent (EIA)", line=dict(color="#E8593C")))
            fig_check.add_trace(go.Scatter(x=merged_check["date"], y=merged_check["brent_usd_av"],
                                           name="Brent (Alpha Vantage)",
                                           line=dict(color="#1D9E75", dash="dot")))
            fig_check.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0),
                                    yaxis_title="USD / barrel",
                                    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(fig_check, use_container_width=True)
        else:
            st.caption("No overlapping dates between EIA and Alpha Vantage data yet.")

    # Alpha Vantage: FX exposure for the two largest Hormuz-dependent importers
    if not df_av_fx.empty:
        st.divider()
        st.subheader("Currency Exposure — Japan & China")
        st.caption("A weaker yen/yuan raises the real cost of imported oil independent of the "
                   "dollar price of crude. Japan (~87% of imports via Hormuz) and China (~40%) are "
                   "this project's two largest Hormuz-dependent importers.")
        fig_fx = make_subplots(rows=1, cols=2, subplot_titles=["USD/JPY", "USD/CNY"])
        if "usd_jpy" in df_av_fx.columns:
            fig_fx.add_trace(go.Scatter(x=df_av_fx["date"], y=df_av_fx["usd_jpy"],
                                        line=dict(color="#3B8BD4"), name="USD/JPY"), row=1, col=1)
        if "usd_cny" in df_av_fx.columns:
            fig_fx.add_trace(go.Scatter(x=df_av_fx["date"], y=df_av_fx["usd_cny"],
                                        line=dict(color="#7F77DD"), name="USD/CNY"), row=1, col=2)
        fig_fx.update_layout(height=280, showlegend=False, margin=dict(l=0, r=0, t=30, b=0),
                             plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig_fx, use_container_width=True)

# -------------------------------------------------------------------
# PAGE: Geopolitical Risk
# -------------------------------------------------------------------

elif page == "⚠️ Geopolitical Risk":
    st.title("Geopolitical Risk Monitor")

    if df_gdelt.empty:
        no_data_notice("GDELT events", "No API key needed — just run the pipeline.")
        st.stop()

    st.subheader("Risk Signal vs. News Volume")
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(
        x=df_gdelt["date"], y=df_gdelt["risk_signal"],
        name="Risk signal", fill="tozeroy",
        fillcolor="rgba(232,89,60,0.15)",
        line=dict(color="#E8593C", width=2)
    ), secondary_y=False)
    if "article_count" in df_gdelt.columns:
        fig.add_trace(go.Bar(
            x=df_gdelt["date"], y=df_gdelt["article_count"],
            name="Article count", opacity=0.3,
            marker_color="#3B8BD4"
        ), secondary_y=True)
    fig.update_layout(height=400, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    fig.update_yaxes(title_text="Risk (0–1)", range=[0, 1], secondary_y=False)
    fig.update_yaxes(title_text="Articles / day", secondary_y=True)
    st.plotly_chart(fig, use_container_width=True)

    if "avg_tone" in df_gdelt.columns:
        st.subheader("Average News Tone (negative = hostile)")
        fig2 = go.Figure(go.Scatter(
            x=df_gdelt["date"], y=df_gdelt["avg_tone"],
            fill="tozeroy",
            fillcolor="rgba(59,139,212,0.1)",
            line=dict(color="#3B8BD4", width=1.5)
        ))
        fig2.add_hline(y=0, line_dash="dash", line_color="gray")
        fig2.update_layout(height=280, plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                           yaxis_title="Tone score")
        st.plotly_chart(fig2, use_container_width=True)

# -------------------------------------------------------------------
# PAGE: Risk Index (HRI) — Phase 2
# -------------------------------------------------------------------

elif page == "📈 Risk Index (HRI)":
    st.title("Hormuz Risk Index (HRI)")
    st.caption("Composite 0–100 score combining news volume, news tone, "
               "price volatility, and price deviation from trend")

    if df_hri.empty:
        no_data_notice("Hormuz Risk Index", "Run `python analytics/risk_index.py` after the main pipeline.")
        st.stop()

    latest = df_hri.iloc[-1]

    # KPI row
    col1, col2, col3 = st.columns(3)
    with col1:
        color = {"Critical": "🔴", "High": "🟠", "Elevated": "🟡", "Moderate": "🔵", "Low": "🟢"}
        emoji = color.get(latest["risk_level"], "⚪")
        st.metric("Current HRI Score", f"{latest['hri_score']:.1f} / 100", f"{emoji} {latest['risk_level']}")
    with col2:
        if len(df_hri) > 7:
            delta = latest["hri_score"] - df_hri.iloc[-8]["hri_score"]
            st.metric("7-Day Change", f"{delta:+.1f}")
    with col3:
        st.metric("Days of History", f"{len(df_hri)}")

    st.divider()

    # Main HRI chart with risk level bands
    st.subheader("Risk Index Over Time")
    fig = go.Figure()

    # Risk level background bands
    bands = [(0, 20, "rgba(29,158,117,0.08)"), (20, 40, "rgba(59,139,212,0.08)"),
             (40, 60, "rgba(239,159,39,0.08)"), (60, 75, "rgba(232,89,60,0.10)"),
             (75, 100, "rgba(180,30,30,0.12)")]
    for y0, y1, color_band in bands:
        fig.add_hrect(y0=y0, y1=y1, fillcolor=color_band, line_width=0)

    fig.add_trace(go.Scatter(
        x=df_hri["date"], y=df_hri["hri_score"],
        line=dict(color="#1a1a1a", width=2.5),
        name="HRI Score"
    ))
    fig.update_layout(height=400, yaxis=dict(range=[0, 100], title="HRI Score"),
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                      margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)

    # Component breakdown
    st.subheader("Component Breakdown")
    component_cols = [c for c in ["news_component", "tone_component",
                                   "volatility_component", "price_dev_component"]
                      if c in df_hri.columns]

    if component_cols:
        fig2 = go.Figure()
        labels = {
            "news_component": "News Volume", "tone_component": "News Tone (hostility)",
            "volatility_component": "Price Volatility", "price_dev_component": "Price Deviation"
        }
        colors_map = {
            "news_component": "#3B8BD4", "tone_component": "#E8593C",
            "volatility_component": "#EF9F27", "price_dev_component": "#7F77DD"
        }
        for col in component_cols:
            fig2.add_trace(go.Scatter(
                x=df_hri["date"], y=df_hri[col],
                name=labels.get(col, col), line=dict(color=colors_map.get(col)),
                stackgroup=None
            ))
        fig2.update_layout(height=350, yaxis=dict(range=[0, 100], title="Component score (0–100)"),
                           plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                           legend=dict(orientation="h", yanchor="bottom", y=1.02),
                           margin=dict(l=0, r=0, t=30, b=0))
        st.plotly_chart(fig2, use_container_width=True)

        with st.expander("How is the HRI calculated?"):
            st.markdown("""
The **Hormuz Risk Index** is a weighted composite of four signals:

| Component | Weight | What it measures |
|---|---|---|
| News Volume | 35% | Spike in news coverage about Hormuz vs. 30-day baseline |
| News Tone | 25% | How hostile/negative the coverage is (GDELT tone score) |
| Price Volatility | 25% | 7-day rolling volatility of Brent returns, percentile-ranked |
| Price Deviation | 15% | Current Brent price vs. its 90-day moving average |

Each component is scaled to 0–100. If a data source is unavailable,
weights are automatically redistributed across the remaining components.

**Risk levels:** Low (0–20) · Moderate (20–40) · Elevated (40–60) · High (60–75) · Critical (75–100)
            """)

# -------------------------------------------------------------------
# PAGE: Price Forecast (VAR model) — Phase 2
# -------------------------------------------------------------------

elif page == "🔮 Price Forecast":
    st.title("Price Impact Model")
    st.caption("Vector Autoregression (VAR) — how Hormuz risk shocks propagate to oil prices")

    if price_model_results is None:
        no_data_notice("price impact model", "Run `python analytics/price_model.py` after building the risk index.")
        st.stop()

    info = price_model_results["model_info"]
    st.write(f"**Model:** VAR(lag={info['lag_order']}) · "
             f"**Observations:** {info['n_observations']} days · "
             f"**Range:** {info['date_range'][0]} to {info['date_range'][1]}")

    col1, col2 = st.columns(2)

    # Impulse Response Function
    with col1:
        st.subheader("Impulse Response")
        st.caption("Expected % change in Brent returns after a 1-unit HRI shock")
        irf = price_model_results["impulse_response"]
        fig = go.Figure(go.Bar(
            x=irf["period"], y=irf["brent_response_to_hri_shock"],
            marker_color=["#E8593C" if v > 0 else "#3B8BD4" for v in irf["brent_response_to_hri_shock"]]
        ))
        fig.update_layout(height=320, xaxis_title="Days after shock", yaxis_title="Brent return %",
                          plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                          margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

    # Variance Decomposition
    with col2:
        st.subheader("Variance Decomposition")
        st.caption("What explains Brent price movement variance?")
        fevd = price_model_results["variance_decomposition"]
        fig2 = go.Figure()
        fig2.add_trace(go.Bar(x=fevd["period"], y=fevd["pct_explained_by_hri_shocks"],
                              name="HRI shocks", marker_color="#E8593C"))
        fig2.add_trace(go.Bar(x=fevd["period"], y=fevd["pct_explained_by_own_past"],
                              name="Own momentum", marker_color="#3B8BD4"))
        fig2.update_layout(height=320, barmode="stack", xaxis_title="Days ahead", yaxis_title="Fraction of variance",
                           plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                           legend=dict(orientation="h", yanchor="bottom", y=1.02),
                           margin=dict(l=0, r=0, t=30, b=0))
        st.plotly_chart(fig2, use_container_width=True)

    # Forecast
    st.subheader("7-Day Price Forecast")
    fc = price_model_results["forecast"]
    fig3 = go.Figure()
    fig3.add_trace(go.Scatter(
        x=[fc["last_observed_date"]] + fc["forecast_dates"],
        y=[fc["last_observed_price"]] + fc["forecast_prices_usd"],
        mode="lines+markers", line=dict(color="#E8593C", dash="dot"),
        name="Forecast"
    ))
    fig3.update_layout(height=300, yaxis_title="Brent USD/bbl",
                       plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                       margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig3, use_container_width=True)
    st.caption(f"⚠️ {fc['note']}")

    # -------------------------------------------------------------------
    # Model Validation: Granger causality, out-of-sample RMSE, XGBoost comparison
    # -------------------------------------------------------------------
    st.divider()
    st.subheader("Model Validation")
    st.caption("Does this model actually add value, or is it just fitting noise?")

    gc = price_model_results.get("granger_causality", {})
    oos = price_model_results.get("out_of_sample_validation", {})

    col1, col2, col3 = st.columns(3)

    with col1:
        if gc and "error" not in gc:
            st.metric(
                "Granger Causality (HRI → Brent)",
                "Significant" if gc["significant_at_5pct"] else "Not significant",
                f"p={gc['min_p_value']:.4f} @ lag {gc['most_significant_lag']}",
            )
        else:
            st.metric("Granger Causality", "—", "Not enough data")

    with col2:
        if oos:
            st.metric(
                "VAR Out-of-Sample RMSE",
                f"{oos['var_rmse']:.4f}",
                f"{'beats' if oos['var_beats_baseline'] else 'worse than'} baseline "
                f"({oos['baseline_rmse']:.4f})",
            )
        else:
            st.metric("VAR Out-of-Sample RMSE", "—", "Not enough data")

    with col3:
        if ml_model_results:
            st.metric(
                "XGBoost vs. Naive Baseline (RMSE)",
                f"{ml_model_results['xgboost_rmse']:.4f}",
                f"{'beats' if ml_model_results['xgboost_beats_baseline'] else 'worse than'} baseline "
                f"({ml_model_results['baseline_rmse']:.4f})",
            )
        else:
            no_data_notice("XGBoost comparison model",
                            "Run `python analytics/ml_price_model.py`.")

    with st.expander("How to read these numbers"):
        if gc and "error" not in gc:
            st.markdown(f"**Granger causality:** {gc['interpretation']}")
        if oos:
            st.markdown(f"**VAR out-of-sample validation:** {oos['interpretation']}")
        if ml_model_results:
            st.markdown(f"**XGBoost comparison:** {ml_model_results['interpretation']}")
            st.caption(ml_model_results.get("note", ""))
            if ml_model_results.get("top_feature_importances"):
                st.markdown("**Top XGBoost features:**")
                st.json(ml_model_results["top_feature_importances"])

# -------------------------------------------------------------------
# PAGE: Backtest — Layer 4
# -------------------------------------------------------------------

elif page == "🧪 Backtest":
    st.title("HRI Backtest — Historical Events")
    st.caption("Sanity-checking the Risk Index against real Gulf-region disruption events")

    if backtest_results is None:
        no_data_notice("backtest results", "Run `python analytics/backtest.py` "
                        "(takes several minutes — it fetches historical GDELT data per event).")
        st.stop()

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Events Scored", f"{backtest_results['n_scored']} / {backtest_results['n_events']}")
    with col2:
        hit_rate = backtest_results.get("hri_rose_hit_rate")
        st.metric("HRI Rose Above Baseline", f"{hit_rate:.0%}" if hit_rate is not None else "—")

    st.divider()

    for ev in backtest_results["events"]:
        if ev["status"] != "ok":
            with st.expander(f"⚪ {ev['name']} — {ev['date']} (no data)"):
                st.write(ev.get("note", ""))
            continue

        rose = ev.get("hri_rose_at_event")
        icon = "🔴" if rose else "🟢"
        with st.expander(f"{icon} {ev['name']} — {ev['date']}"):
            st.write(ev.get("note", ""))
            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("HRI at Event", f"{ev.get('hri_at_event', '—')}",
                          f"baseline {ev.get('hri_baseline_mean', '—')}")
            with c2:
                st.metric("HRI Z-Score at Event", f"{ev.get('hri_zscore_at_event', '—')}")
            with c3:
                move = ev.get("brent_pct_move")
                st.metric("Brent Move (peak, following 14d)", f"{move:+.2f}%" if move is not None else "—")

    st.divider()
    with st.expander("Methodology & limitations"):
        st.markdown(backtest_results.get("methodology", ""))

# -------------------------------------------------------------------
# PAGE: Country Impact
# -------------------------------------------------------------------

elif page == "🌍 Country Impact":
    st.title("Country-Level Economic Impact")

    if df_wb.empty:
        no_data_notice("World Bank country data")
        st.stop()

    st.caption(
        "Showing each country's most recent year with complete data. "
        "World Bank indicators are typically published with a 1-3 year lag, "
        "so different countries may show slightly different reference years."
    )
    if "year" in df_wb.columns:
        with st.expander("Reference years per country"):
            year_table = df_wb[["country_name", "year"]].sort_values("country_name")
            st.dataframe(year_table, use_container_width=True, hide_index=True)

    # Choropleth map of dependency score
    if "hormuz_dependency_score" in df_wb.columns and "country_code" in df_wb.columns:
        st.subheader("Hormuz Dependency Score (higher = more exposed)")
        fig = px.choropleth(
            df_wb.dropna(subset=["hormuz_dependency_score"]),
            locations="country_code",
            locationmode="ISO-3",
            color="hormuz_dependency_score",
            hover_name="country_name",
            color_continuous_scale="Reds",
            title="Economic exposure to a Hormuz disruption",
        )
        fig.update_layout(height=450, margin=dict(l=0, r=0, t=40, b=0))
        st.plotly_chart(fig, use_container_width=True)

    # Country detail
    st.subheader("Country Deep Dive")
    countries = sorted(df_wb["country_name"].dropna().unique().tolist())
    selected = st.selectbox("Select a country", countries, index=countries.index("Japan") if "Japan" in countries else 0)

    df_country_all_years_path = DATA_DIR / "worldbank_country_indicators.csv"
    if df_country_all_years_path.exists():
        df_all = pd.read_csv(df_country_all_years_path)
        df_sel = df_all[df_all["country_name"] == selected].sort_values("year")

        metric_cols = [c for c in ["gdp_growth_pct", "inflation_pct", "energy_imports_pct",
                                    "current_account_pct", "fuel_imports_pct"] if c in df_sel.columns]
        if metric_cols:
            fig3 = make_subplots(rows=len(metric_cols), cols=1,
                                  subplot_titles=[c.replace("_", " ").title() for c in metric_cols],
                                  shared_xaxes=True, vertical_spacing=0.07)
            colors = ["#E8593C", "#3B8BD4", "#1D9E75", "#EF9F27", "#7F77DD"]
            for i, col in enumerate(metric_cols, 1):
                fig3.add_trace(go.Scatter(
                    x=df_sel["year"], y=df_sel[col],
                    mode="lines+markers", name=col,
                    line=dict(color=colors[(i-1) % len(colors)])
                ), row=i, col=1)

            fig3.update_layout(height=200 * len(metric_cols), showlegend=False,
                                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                                margin=dict(l=0, r=0, t=40, b=0))
            st.plotly_chart(fig3, use_container_width=True)

# -------------------------------------------------------------------
# PAGE: News Feed
# -------------------------------------------------------------------

elif page == "📰 News Feed":
    st.title("Hormuz News Feed")

    newsapi_path = DATA_DIR / "newsapi_hormuz_articles.csv"
    news_path    = DATA_DIR / "gdelt_hormuz_news.csv"
    events_path  = DATA_DIR / "gdelt_hormuz_events.csv"

    has_newsapi = newsapi_path.exists()
    has_news    = news_path.exists()
    has_events  = events_path.exists()

    if not has_newsapi and not has_news and not has_events:
        no_data_notice("news/events", "No API key needed for GDELT events; "
                        "set NEWS_API_KEY in .env for real article text via NewsAPI.")
        st.stop()

    # ---- NewsAPI articles (real article text, second source alongside GDELT) ----
    if has_newsapi:
        df_newsapi = pd.read_csv(newsapi_path, parse_dates=["date"])
        st.subheader("News Articles (NewsAPI)")
        st.caption(f"{len(df_newsapi)} articles collected — last {'29' } days (NewsAPI free-tier limit)")

        for _, row in df_newsapi.head(50).iterrows():
            date_str = row["date"].strftime("%Y-%m-%d") if pd.notna(row["date"]) else ""
            with st.expander(f"📰 {row.get('title', 'No title')} — {date_str}"):
                st.write(f"**Source:** {row.get('domain', 'Unknown')}")
                if pd.notna(row.get("author")):
                    st.write(f"**Author:** {row['author']}")
                if pd.notna(row.get("description")):
                    st.write(row["description"])
                if row.get("url"):
                    st.write(f"**URL:** {row['url']}")
        st.divider()

    # ---- Real news articles (best-effort, may not exist) ----
    if has_news:
        df_news = pd.read_csv(news_path, parse_dates=["date"])
        if "tone" in df_news.columns:
            df_news = df_news.sort_values("date", ascending=False)
            st.subheader("News Articles")
            st.caption(f"{len(df_news)} articles collected")

            tone_filter = st.slider("Tone filter (negative = hostile)", -10.0, 10.0, (-10.0, 10.0), 0.5)
            df_news = df_news[df_news["tone"].between(*tone_filter)]

            for _, row in df_news.head(50).iterrows():
                tone_color = "🔴" if row["tone"] < -2 else ("🟡" if row["tone"] < 0 else "🟢")
                with st.expander(f"{tone_color} {row.get('title', 'No title')} — {row['date'].strftime('%Y-%m-%d') if pd.notna(row['date']) else ''}"):
                    st.write(f"**Source:** {row.get('domain', 'Unknown')}")
                    st.write(f"**Tone score:** {row.get('tone', 0):.2f}")
                    if row.get("url"):
                        st.write(f"**URL:** {row['url']}")
            st.divider()
        else:
            st.caption("News article file exists but has an unexpected format — skipping.")

    # ---- Raw events table (always available from CSV fallback) ----
    if has_events:
        df_events = pd.read_csv(events_path, parse_dates=["date"])
        st.subheader("Recent Geopolitical Events (raw GDELT data)")
        st.caption(
            f"{len(df_events)} events involving Iran/Gulf states in the last 30 days. "
            "Each row is one coded event (not a full article) — "
            "`avg_tone` is the tone of the source coverage (negative = hostile)."
        )

        tone_filter2 = st.slider("Event tone filter (negative = hostile)",
                                  -10.0, 10.0, (-10.0, 10.0), 0.5, key="event_tone")
        df_events_f = df_events[df_events["avg_tone"].between(*tone_filter2)]

        display_cols = [c for c in ["date", "actor1_country", "actor2_country",
                                     "event_code", "action_country", "avg_tone"]
                        if c in df_events_f.columns]
        table = df_events_f[display_cols].sort_values("date", ascending=False).head(200)
        table.columns = [c.replace("_", " ").title() for c in table.columns]
        st.dataframe(table, use_container_width=True, hide_index=True)

        with st.expander("What do these columns mean?"):
            st.markdown("""
- **Actor1/Actor2 Country** — the countries of the two parties involved in the event
  (3-letter CAMEO codes, e.g. IRN = Iran, SAU = Saudi Arabia, USA = United States)
- **Event Code** — GDELT's CAMEO action classification (e.g. 04 = consult, 17 = coerce, 19 = fight)
- **Action Country** — where the event geographically took place
- **Avg Tone** — sentiment of the news coverage describing this event (negative = hostile framing)
            """)
    elif not has_news:
        no_data_notice("GDELT news/events")

# -------------------------------------------------------------------
# PAGE: Ask HormuzWatch — Layer 6 RAG assistant
# -------------------------------------------------------------------

elif page == "🤖 Ask HormuzWatch":
    st.title("Ask HormuzWatch")
    st.caption("Ask a question in plain English — answers are grounded in the project's actual "
               "GDELT events, news articles, risk index history, and model results, with citations.")

    from llm_client import is_configured as llm_is_configured
    from llm_client import SECRETS_LOOKUP_DETAIL as llm_secrets_detail

    if not llm_is_configured():
        no_data_notice(
            "the Ask HormuzWatch assistant",
            "Add `GEMINI_API_KEY` to your `.env` file (free tier: https://aistudio.google.com/apikey).",
        )
        st.caption(f"Diagnostic: {llm_secrets_detail}")
        st.stop()

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    for turn in st.session_state.chat_history:
        with st.chat_message("user"):
            st.write(turn["question"])
        with st.chat_message("assistant"):
            st.write(turn["answer"])
            if turn["sources"]:
                with st.expander(f"Sources ({len(turn['sources'])})"):
                    for s in turn["sources"]:
                        line = f"**{s['source']}**"
                        if s.get("date"):
                            line += f" · {s['date']}"
                        line += f" · similarity {s['similarity']:.2f}"
                        st.markdown(f"- {line}")
                        if s.get("url"):
                            st.caption(s["url"])

    question = st.chat_input("Ask about Hormuz risk, recent events, or the models...")
    if question:
        with st.chat_message("user"):
            st.write(question)
        with st.chat_message("assistant"):
            with st.spinner("Retrieving context and generating an answer..."):
                from rag import answer as rag_answer
                result = rag_answer(question)
            st.write(result["answer"])
            sources = [
                {"source": d["source"], "date": d.get("date"), "url": d.get("url"), "similarity": d["similarity"]}
                for d in result["retrieved_documents"]
            ]
            if sources:
                with st.expander(f"Sources ({len(sources)})"):
                    for s in sources:
                        line = f"**{s['source']}**"
                        if s.get("date"):
                            line += f" · {s['date']}"
                        line += f" · similarity {s['similarity']:.2f}"
                        st.markdown(f"- {line}")
                        if s.get("url"):
                            st.caption(s["url"])
        st.session_state.chat_history.append({
            "question": question, "answer": result["answer"], "sources": sources,
        })

# -------------------------------------------------------------------
# PAGE: Data Lineage — Layer 8 governance
# -------------------------------------------------------------------

elif page == "🔍 Data Lineage":
    st.title("Data Lineage & Quality")
    st.caption("Every row in this project is traceable to a source, a pipeline run, and a "
               "fetch timestamp (ingestion/base_collector.py) — this page surfaces that "
               "directly from the raw files, no warehouse connection required.")

    st.subheader("Ingestion Lineage")
    ok_rows = [r for r in lineage_summary if r.get("status") == "ok"]
    other_rows = [r for r in lineage_summary if r.get("status") != "ok"]

    if ok_rows:
        table = pd.DataFrame(ok_rows)[
            ["dataset", "source", "row_count", "latest_run_id", "latest_fetched_at", "staleness_days"]
        ]
        table.columns = ["Dataset", "Source", "Rows", "Latest Run ID", "Last Fetched", "Days Stale"]
        st.dataframe(table, use_container_width=True, hide_index=True)
    else:
        st.info("No lineage-stamped datasets found yet — run `python ingestion/run_pipeline.py`.")

    optional_absent = [r for r in other_rows if r["dataset"] in OPTIONAL_LINEAGE_DATASETS]
    real_gaps = [r for r in other_rows if r["dataset"] not in OPTIONAL_LINEAGE_DATASETS]

    if real_gaps:
        with st.expander(f"⚠️ {len(real_gaps)} dataset(s) missing or without lineage columns", expanded=True):
            for r in real_gaps:
                st.write(f"- **{r['dataset']}**: {r['status']}")

    if optional_absent:
        with st.expander(f"{len(optional_absent)} optional dataset(s) not fetched this run"):
            st.caption("These sources are best-effort (rate-limited APIs or non-critical "
                       "supplements) — the pipeline runs fine without them.")
            for r in optional_absent:
                st.write(f"- **{r['dataset']}**: {r['status']}")

    st.divider()

    st.subheader("Latest Data Quality Report")
    if data_quality_report:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Run ID", data_quality_report["run_id"][:12])
        with col2:
            st.metric("Checks Passed", f"{data_quality_report['passed']}/{data_quality_report['total_checks']}")
        with col3:
            st.metric("Checks Failed", data_quality_report["failed"])
        with col4:
            st.metric("Generated", data_quality_report["generated_at"][:10])

        if data_quality_report["failures"]:
            with st.expander(f"⚠️ {len(data_quality_report['failures'])} failing check(s)"):
                fail_table = pd.DataFrame(data_quality_report["failures"])[["dataset", "check", "detail"]]
                fail_table.columns = ["Dataset", "Check", "Detail"]
                st.dataframe(fail_table, use_container_width=True, hide_index=True)
        else:
            st.success("All data quality checks passed on the latest run.")
    else:
        no_data_notice("data quality report")

    st.divider()
    st.caption(
        "Governance artifacts: `dbt/models/marts/lineage_log.sql` and the `data_lineage_log` "
        "view in `supabase_schema.sql` expose this same information as queryable warehouse "
        "tables once dbt has been run. See `docs/MODEL_RISK_MEMO.md` for model assumptions, "
        "limitations, and do-not-use boundaries, and `CHANGELOG.md` for schema/model history."
    )
