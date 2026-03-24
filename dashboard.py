# dashboard.py
# Run with: streamlit run dashboard.py

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from supabase import create_client

from config import SUPABASE_URL, SUPABASE_KEY

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Trading Dashboard",
    page_icon="📈",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
@st.cache_data(ttl=30)  # Refresh every 30 seconds
def load_trades() -> pd.DataFrame:
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    response = client.table("trades").select("*").order("timestamp", desc=False).execute()
    if not response.data:
        return pd.DataFrame()
    df = pd.DataFrame(response.data)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    df["total_value"] = pd.to_numeric(df["total_value"], errors="coerce")
    return df


# ---------------------------------------------------------------------------
# Derived data helpers
# ---------------------------------------------------------------------------
def get_closed_trades(df: pd.DataFrame) -> pd.DataFrame:
    """Rows that represent a closed position with a known P&L."""
    return df[df["type"].isin(["EXIT_ALL", "EXIT_PARTIAL"]) & df["pnl"].notna()].copy()


def get_summary(closed: pd.DataFrame) -> dict:
    if closed.empty:
        return {"total_pnl": 0, "win_rate": 0, "num_trades": 0, "avg_pnl": 0, "best": 0, "worst": 0}
    wins = closed[closed["pnl"] > 0]
    return {
        "total_pnl": closed["pnl"].sum(),
        "win_rate": len(wins) / len(closed) * 100,
        "num_trades": len(closed),
        "avg_pnl": closed["pnl"].mean(),
        "best": closed["pnl"].max(),
        "worst": closed["pnl"].min(),
    }


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
st.title("📈 Options Trading Dashboard")
st.caption("Auto-refreshes every 30 seconds. Hit R to force refresh.")

df = load_trades()

if df.empty:
    st.info("No trades logged yet. Send a signal to get started.")
    st.stop()

closed = get_closed_trades(df)
summary = get_summary(closed)

# ---------------------------------------------------------------------------
# Summary metrics row
# ---------------------------------------------------------------------------
c1, c2, c3, c4, c5, c6 = st.columns(6)

c1.metric(
    "Total P&L",
    f"${summary['total_pnl']:,.2f}",
    delta=f"${summary['total_pnl']:,.2f}",
    delta_color="normal",
)
c2.metric("Win Rate", f"{summary['win_rate']:.1f}%")
c3.metric("Closed Trades", summary["num_trades"])
c4.metric("Avg P&L / Trade", f"${summary['avg_pnl']:,.2f}")
c5.metric("Best Trade", f"${summary['best']:,.2f}")
c6.metric("Worst Trade", f"${summary['worst']:,.2f}")

st.divider()

# ---------------------------------------------------------------------------
# Row 1: Cumulative P&L | Win/Loss breakdown
# ---------------------------------------------------------------------------
col_left, col_right = st.columns([3, 1])

with col_left:
    st.subheader("Cumulative P&L Over Time")
    if closed.empty:
        st.info("No closed trades with P&L data yet.")
    else:
        cum_df = closed.sort_values("timestamp").copy()
        cum_df["cumulative_pnl"] = cum_df["pnl"].cumsum()
        # Color the line green/red based on whether we're up or down
        final_pnl = cum_df["cumulative_pnl"].iloc[-1]
        line_color = "#00c853" if final_pnl >= 0 else "#d50000"

        fig_cum = go.Figure()
        fig_cum.add_trace(go.Scatter(
            x=cum_df["timestamp"],
            y=cum_df["cumulative_pnl"],
            mode="lines+markers",
            line=dict(color=line_color, width=2),
            marker=dict(size=6),
            hovertemplate="<b>%{x|%b %d %H:%M}</b><br>Cumulative P&L: $%{y:,.2f}<extra></extra>",
        ))
        fig_cum.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
        fig_cum.update_layout(
            margin=dict(t=10, b=10),
            yaxis_tickprefix="$",
            xaxis_title=None,
            yaxis_title="P&L ($)",
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_cum, use_container_width=True)

with col_right:
    st.subheader("Win / Loss")
    if closed.empty:
        st.info("No data.")
    else:
        wins = len(closed[closed["pnl"] > 0])
        losses = len(closed[closed["pnl"] <= 0])
        fig_pie = px.pie(
            values=[wins, losses],
            names=["Wins", "Losses"],
            color_discrete_sequence=["#00c853", "#d50000"],
            hole=0.5,
        )
        fig_pie.update_traces(textinfo="label+percent")
        fig_pie.update_layout(
            margin=dict(t=10, b=10),
            showlegend=False,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_pie, use_container_width=True)

# ---------------------------------------------------------------------------
# Row 2: P&L by ticker | Trade count by ticker
# ---------------------------------------------------------------------------
col_a, col_b = st.columns(2)

with col_a:
    st.subheader("P&L by Ticker")
    if closed.empty:
        st.info("No data.")
    else:
        ticker_pnl = (
            closed.groupby("ticker")["pnl"]
            .sum()
            .reset_index()
            .sort_values("pnl", ascending=False)
        )
        ticker_pnl["color"] = ticker_pnl["pnl"].apply(lambda x: "#00c853" if x >= 0 else "#d50000")
        fig_ticker = px.bar(
            ticker_pnl,
            x="ticker",
            y="pnl",
            color="color",
            color_discrete_map="identity",
            text=ticker_pnl["pnl"].apply(lambda x: f"${x:,.2f}"),
        )
        fig_ticker.update_layout(
            showlegend=False,
            margin=dict(t=10, b=10),
            yaxis_tickprefix="$",
            xaxis_title=None,
            yaxis_title="Total P&L ($)",
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_ticker, use_container_width=True)

with col_b:
    st.subheader("Trade Activity by Ticker")
    ticker_counts = df.groupby(["ticker", "type"]).size().reset_index(name="count")
    fig_count = px.bar(
        ticker_counts,
        x="ticker",
        y="count",
        color="type",
        barmode="stack",
        color_discrete_map={
            "ENTRY": "#1565c0",
            "ADD": "#f57c00",
            "EXIT_PARTIAL": "#fdd835",
            "EXIT_ALL": "#6a1b9a",
        },
    )
    fig_count.update_layout(
        margin=dict(t=10, b=10),
        xaxis_title=None,
        yaxis_title="Number of Orders",
        legend_title="Type",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig_count, use_container_width=True)

# ---------------------------------------------------------------------------
# Row 3: P&L distribution histogram
# ---------------------------------------------------------------------------
if not closed.empty and len(closed) >= 3:
    st.subheader("P&L Distribution")
    fig_hist = px.histogram(
        closed,
        x="pnl",
        nbins=20,
        color_discrete_sequence=["#1565c0"],
    )
    fig_hist.add_vline(x=0, line_dash="dash", line_color="gray", opacity=0.6)
    fig_hist.update_layout(
        margin=dict(t=10, b=10),
        xaxis_tickprefix="$",
        xaxis_title="P&L per Trade ($)",
        yaxis_title="Count",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig_hist, use_container_width=True)

# ---------------------------------------------------------------------------
# Trade log table
# ---------------------------------------------------------------------------
st.subheader("Trade Log")

display_df = df.copy().sort_values("timestamp", ascending=False)
display_df["timestamp"] = display_df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
display_df["price"] = display_df["price"].apply(lambda x: f"${x:.2f}" if pd.notna(x) else "—")
display_df["total_value"] = display_df["total_value"].apply(lambda x: f"${x:,.2f}" if pd.notna(x) else "—")
display_df["pnl"] = display_df["pnl"].apply(lambda x: f"${x:+,.2f}" if pd.notna(x) else "—")
display_df["quantity"] = display_df["quantity"].apply(lambda x: int(x) if pd.notna(x) else "—")

display_df = display_df.rename(columns={
    "timestamp": "Time",
    "ticker": "Ticker",
    "occ_symbol": "Contract",
    "type": "Type",
    "price": "Price",
    "quantity": "Qty",
    "total_value": "Value",
    "pnl": "P&L",
})

def _color_type(val):
    colors = {
        "ENTRY": "color: #1565c0",
        "ADD": "color: #f57c00",
        "EXIT_PARTIAL": "color: #f9a825",
        "EXIT_ALL": "color: #6a1b9a",
    }
    return colors.get(val, "")

def _color_pnl(val):
    if isinstance(val, str) and val.startswith("$+"):
        return "color: #00c853; font-weight: bold"
    if isinstance(val, str) and val.startswith("$-"):
        return "color: #d50000; font-weight: bold"
    return ""

styled = (
    display_df[["Time", "Ticker", "Contract", "Type", "Price", "Qty", "Value", "P&L"]]
    .style
    .applymap(_color_type, subset=["Type"])
    .applymap(_color_pnl, subset=["P&L"])
)

st.dataframe(styled, use_container_width=True, hide_index=True)
