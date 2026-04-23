# dashboard.py
# Run with: streamlit run dashboard.py

import datetime

import pandas as pd
# Set this to the cutoff date — data before this date is excluded from the dashboard
DATA_START_DATE = datetime.date(2026, 4, 15)

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from supabase import create_client

from config import SUPABASE_URL, SUPABASE_KEY
from eval_logger import submit_label

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Trading Dashboard",
    page_icon="📈",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Supabase client
# ---------------------------------------------------------------------------
@st.cache_resource
def get_client():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
@st.cache_data(ttl=30)
def load_trades() -> pd.DataFrame:
    client = get_client()
    response = client.table("trades").select("*").order("timestamp", desc=False).execute()
    if not response.data:
        return pd.DataFrame()
    df = pd.DataFrame(response.data)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce")
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    df["total_value"] = pd.to_numeric(df["total_value"], errors="coerce")
    if "source" not in df.columns:
        df["source"] = "unknown"
    return df


@st.cache_data(ttl=15)
def load_evals() -> pd.DataFrame:
    client = get_client()
    response = client.table("parser_evals").select("*").order("timestamp", desc=False).execute()
    if not response.data:
        return pd.DataFrame()
    df = pd.DataFrame(response.data)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["parsed_price"] = pd.to_numeric(df["parsed_price"], errors="coerce")
    df["human_price"] = pd.to_numeric(df["human_price"], errors="coerce")
    return df


# ---------------------------------------------------------------------------
# Helpers — Trading tab
# ---------------------------------------------------------------------------
def get_closed_trades(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["type"].isin(["EXIT_ALL", "EXIT_PARTIAL", "EXIT_STOP_LOSS"]) & df["pnl"].notna()].copy()


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


TYPE_COLORS = {
    "ENTRY": "#1565c0",
    "ADD": "#f57c00",
    "EXIT_PARTIAL": "#fdd835",
    "EXIT_ALL": "#6a1b9a",
    "EXIT_STOP_LOSS": "#d50000",
}

CHART_LAYOUT = dict(
    margin=dict(t=10, b=10),
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
)


# ---------------------------------------------------------------------------
# Main layout
# ---------------------------------------------------------------------------
st.title("📈 Options Trading Dashboard")
st.caption("Auto-refreshes every 30 seconds. Hit R to force refresh.")

# --- Sidebar source filter ---
with st.sidebar:
    st.header("Filters")
    source_options = ["All Sources", "waxui", "zabes"]
    selected_source = st.selectbox("Signal Source", source_options, index=0)

tab_trading, tab_parser = st.tabs(["Trading", "Parser Accuracy"])


# ===========================================================================
# TAB 1 — TRADING
# ===========================================================================
with tab_trading:
    df = load_trades()

    if df.empty:
        st.info("No trades logged yet. Send a signal to get started.")
        st.stop()

    # Apply date cutoff
    df = df[df["timestamp"].dt.date >= DATA_START_DATE]
    if df.empty:
        st.info(f"No trades on or after {DATA_START_DATE}.")
        st.stop()

    # Apply source filter from sidebar
    if selected_source != "All Sources":
        df = df[df["source"] == selected_source]
        if df.empty:
            st.info(f"No trades logged for source: {selected_source}")
            st.stop()

    closed = get_closed_trades(df)
    summary = get_summary(closed)

    # --- Summary metrics ---
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Total P&L", f"${summary['total_pnl']:,.2f}",
              delta=f"${summary['total_pnl']:,.2f}", delta_color="normal")
    c2.metric("Win Rate", f"{summary['win_rate']:.1f}%")
    c3.metric("Closed Trades", summary["num_trades"])
    c4.metric("Avg P&L / Trade", f"${summary['avg_pnl']:,.2f}")
    c5.metric("Best Trade", f"${summary['best']:,.2f}")
    c6.metric("Worst Trade", f"${summary['worst']:,.2f}")

    st.divider()

    # --- Row 1: Cumulative P&L | Win/Loss ---
    col_left, col_right = st.columns([3, 1])

    with col_left:
        st.subheader("Cumulative P&L Over Time")
        if closed.empty:
            st.info("No closed trades with P&L data yet.")
        else:
            cum_df = closed.sort_values("timestamp").copy()
            cum_df["cumulative_pnl"] = cum_df["pnl"].cumsum()
            line_color = "#00c853" if cum_df["cumulative_pnl"].iloc[-1] >= 0 else "#d50000"
            fig_cum = go.Figure()
            fig_cum.add_trace(go.Scatter(
                x=cum_df["timestamp"], y=cum_df["cumulative_pnl"],
                mode="lines+markers",
                line=dict(color=line_color, width=2), marker=dict(size=6),
                hovertemplate="<b>%{x|%b %d %H:%M}</b><br>Cumulative P&L: $%{y:,.2f}<extra></extra>",
            ))
            fig_cum.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
            fig_cum.update_layout(yaxis_tickprefix="$", xaxis_title=None,
                                  yaxis_title="P&L ($)", **CHART_LAYOUT)
            st.plotly_chart(fig_cum, use_container_width=True)

    with col_right:
        st.subheader("Win / Loss")
        if closed.empty:
            st.info("No data.")
        else:
            wins = len(closed[closed["pnl"] > 0])
            losses = len(closed[closed["pnl"] <= 0])
            fig_pie = px.pie(values=[wins, losses], names=["Wins", "Losses"],
                             color_discrete_sequence=["#00c853", "#d50000"], hole=0.5)
            fig_pie.update_traces(textinfo="label+percent")
            fig_pie.update_layout(showlegend=False, **CHART_LAYOUT)
            st.plotly_chart(fig_pie, use_container_width=True)

    # --- Row 2: P&L by ticker | Activity by ticker ---
    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("P&L by Ticker")
        if closed.empty:
            st.info("No data.")
        else:
            ticker_pnl = (closed.groupby("ticker")["pnl"].sum()
                          .reset_index().sort_values("pnl", ascending=False))
            ticker_pnl["color"] = ticker_pnl["pnl"].apply(
                lambda x: "#00c853" if x >= 0 else "#d50000")
            fig_ticker = px.bar(ticker_pnl, x="ticker", y="pnl",
                                color="color", color_discrete_map="identity",
                                text=ticker_pnl["pnl"].apply(lambda x: f"${x:,.2f}"))
            fig_ticker.update_layout(showlegend=False, yaxis_tickprefix="$",
                                     xaxis_title=None, yaxis_title="Total P&L ($)",
                                     **CHART_LAYOUT)
            st.plotly_chart(fig_ticker, use_container_width=True)

    with col_b:
        st.subheader("Trade Activity by Ticker")
        ticker_counts = df.groupby(["ticker", "type"]).size().reset_index(name="count")
        fig_count = px.bar(ticker_counts, x="ticker", y="count", color="type",
                           barmode="stack", color_discrete_map=TYPE_COLORS)
        fig_count.update_layout(xaxis_title=None, yaxis_title="Number of Orders",
                                legend_title="Type", **CHART_LAYOUT)
        st.plotly_chart(fig_count, use_container_width=True)

    # --- Row 3: P&L distribution ---
    if not closed.empty and len(closed) >= 3:
        st.subheader("P&L Distribution")
        fig_hist = px.histogram(closed, x="pnl", nbins=20,
                                color_discrete_sequence=["#1565c0"])
        fig_hist.add_vline(x=0, line_dash="dash", line_color="gray", opacity=0.6)
        fig_hist.update_layout(xaxis_tickprefix="$", xaxis_title="P&L per Trade ($)",
                               yaxis_title="Count", **CHART_LAYOUT)
        st.plotly_chart(fig_hist, use_container_width=True)

    # --- Trade log ---
    st.subheader("Trade Log")
    display_df = df.copy().sort_values("timestamp", ascending=False)
    display_df["timestamp"] = display_df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
    display_df["price"] = display_df["price"].apply(lambda x: f"${x:.2f}" if pd.notna(x) else "—")
    display_df["total_value"] = display_df["total_value"].apply(lambda x: f"${x:,.2f}" if pd.notna(x) else "—")
    display_df["pnl"] = display_df["pnl"].apply(lambda x: f"${x:+,.2f}" if pd.notna(x) else "—")
    display_df["quantity"] = display_df["quantity"].apply(lambda x: int(x) if pd.notna(x) else "—")
    display_df = display_df.rename(columns={
        "timestamp": "Time", "ticker": "Ticker", "occ_symbol": "Contract",
        "type": "Type", "price": "Price", "quantity": "Qty",
        "total_value": "Value", "pnl": "P&L", "source": "Source",
    })

    def _color_type(val):
        colors = {
            "ENTRY": "color: #1565c0", "ADD": "color: #f57c00",
            "EXIT_PARTIAL": "color: #f9a825", "EXIT_ALL": "color: #6a1b9a",
            "EXIT_STOP_LOSS": "color: #d50000; font-weight: bold",
        }
        return colors.get(val, "")

    def _color_pnl(val):
        if isinstance(val, str) and val.startswith("$+"):
            return "color: #00c853; font-weight: bold"
        if isinstance(val, str) and val.startswith("$-"):
            return "color: #d50000; font-weight: bold"
        return ""

    styled = (
        display_df[["Time", "Source", "Ticker", "Contract", "Type", "Price", "Qty", "Value", "P&L"]]
        .style.applymap(_color_type, subset=["Type"])
              .applymap(_color_pnl, subset=["P&L"])
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)


# ===========================================================================
# TAB 2 — PARSER ACCURACY
# ===========================================================================
with tab_parser:
    eval_df = load_evals()

    if eval_df.empty:
        st.info("No parser evaluations logged yet.")
        st.stop()

    eval_df = eval_df[eval_df["timestamp"].dt.date >= DATA_START_DATE]
    if eval_df.empty:
        st.info(f"No parser evaluations on or after {DATA_START_DATE}.")
        st.stop()

    labeled_df   = eval_df[eval_df["is_correct"].notna()].copy()
    unlabeled_df = eval_df[eval_df["human_type"].isna()].copy()
    accuracy     = (labeled_df["is_correct"].sum() / len(labeled_df) * 100
                    if not labeled_df.empty else 0.0)

    # --- Summary metrics ---
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Messages", len(eval_df))
    m2.metric("Labeled", len(labeled_df))
    m3.metric("Awaiting Labels", len(unlabeled_df))
    m4.metric("Accuracy", f"{accuracy:.1f}%",
              delta=f"{accuracy:.1f}%" if not labeled_df.empty else None,
              delta_color="normal")

    st.divider()

    # --- Accuracy charts (only if we have labeled data) ---
    if not labeled_df.empty:
        chart_col, field_col = st.columns(2)

        with chart_col:
            st.subheader("Accuracy by Message Type")
            type_acc = (
                labeled_df.groupby("parsed_type")["is_correct"]
                .agg(correct="sum", total="count")
                .reset_index()
            )
            type_acc["accuracy_pct"] = type_acc["correct"] / type_acc["total"] * 100
            fig_type = px.bar(type_acc, x="parsed_type", y="accuracy_pct",
                              text=type_acc["accuracy_pct"].apply(lambda x: f"{x:.0f}%"),
                              color_discrete_sequence=["#1565c0"])
            fig_type.add_hline(y=100, line_dash="dash", line_color="gray", opacity=0.4)
            fig_type.update_layout(xaxis_title=None, yaxis_title="Accuracy (%)",
                                   yaxis_range=[0, 105], **CHART_LAYOUT)
            st.plotly_chart(fig_type, use_container_width=True)

        with field_col:
            st.subheader("Per-Field Accuracy")
            fields = ["type", "ticker", "exp_date", "strike", "opt_type", "price"]
            field_acc = []
            for f in fields:
                pcol, hcol = f"parsed_{f}", f"human_{f}"
                if hcol not in labeled_df.columns:
                    continue
                both = labeled_df[[pcol, hcol]].dropna(subset=[hcol])
                if both.empty:
                    continue
                if f == "price":
                    match = (both[pcol] - both[hcol]).abs() <= 0.01
                else:
                    match = both[pcol].str.lower() == both[hcol].str.lower()
                field_acc.append({"field": f, "accuracy_pct": match.mean() * 100,
                                  "n": len(both)})
            if field_acc:
                field_acc_df = pd.DataFrame(field_acc)
                fig_field = px.bar(field_acc_df, x="field", y="accuracy_pct",
                                   text=field_acc_df["accuracy_pct"].apply(lambda x: f"{x:.0f}%"),
                                   color_discrete_sequence=["#00897b"])
                fig_field.add_hline(y=100, line_dash="dash", line_color="gray", opacity=0.4)
                fig_field.update_layout(xaxis_title=None, yaxis_title="Accuracy (%)",
                                        yaxis_range=[0, 105], **CHART_LAYOUT)
                st.plotly_chart(fig_field, use_container_width=True)

        # Incorrect rows table
        incorrect = labeled_df[labeled_df["is_correct"] == False].copy()
        if not incorrect.empty:
            with st.expander(f"View {len(incorrect)} incorrect parse(s)"):
                cols = ["timestamp", "source", "raw_message",
                        "parsed_type", "parsed_ticker", "parsed_price",
                        "human_type",  "human_ticker",  "human_price", "notes"]
                cols = [c for c in cols if c in incorrect.columns]
                st.dataframe(incorrect[cols].sort_values("timestamp", ascending=False),
                             use_container_width=True, hide_index=True)

    st.divider()

    # --- Labeling UI ---
    st.subheader("Label Messages")

    if unlabeled_df.empty:
        st.success("All messages have been labeled.")
    else:
        # Reset index so iloc works cleanly after cache reload
        unlabeled_df = unlabeled_df.reset_index(drop=True)

        if "eval_idx" not in st.session_state:
            st.session_state.eval_idx = 0

        # Clamp index if rows were labeled since last load
        st.session_state.eval_idx = min(st.session_state.eval_idx, len(unlabeled_df) - 1)
        idx = st.session_state.eval_idx

        # Navigation
        nav_left, nav_mid, nav_right = st.columns([1, 4, 1])
        if nav_left.button("← Prev", disabled=(idx == 0)):
            st.session_state.eval_idx -= 1
            st.rerun()
        nav_mid.caption(f"Message {idx + 1} of {len(unlabeled_df)} unlabeled")
        if nav_right.button("Next →", disabled=(idx >= len(unlabeled_df) - 1)):
            st.session_state.eval_idx += 1
            st.rerun()

        row = unlabeled_df.iloc[idx]

        # Raw message + parsed output side by side
        msg_col, parsed_col = st.columns(2)

        with msg_col:
            st.markdown("**Raw Message**")
            st.text_area("raw", value=row["raw_message"], height=160,
                         disabled=True, label_visibility="collapsed")
            st.caption(f"Source: {row.get('source', '—')}  |  {row['timestamp'].strftime('%Y-%m-%d %H:%M')}")

        with parsed_col:
            st.markdown("**Parser Output**")
            parsed_display = {
                "Type":     row.get("parsed_type")     or "—",
                "Ticker":   row.get("parsed_ticker")   or "—",
                "Exp Date": row.get("parsed_exp_date") or "—",
                "Strike":   row.get("parsed_strike")   or "—",
                "Opt Type": row.get("parsed_opt_type") or "—",
                "Price":    f"${row['parsed_price']:.2f}" if pd.notna(row.get("parsed_price")) else "—",
            }
            for label, val in parsed_display.items():
                st.markdown(f"**{label}:** {val}")

        st.markdown("---")

        # Label form
        ALL_TYPES = ["ENTRY", "ADD", "EXIT_ALL", "EXIT_PARTIAL", "EXIT_STOP_LOSS", "IGNORE"]
        parsed_type = row.get("parsed_type") or "IGNORE"
        default_type_idx = ALL_TYPES.index(parsed_type) if parsed_type in ALL_TYPES else 0

        with st.form(key=f"label_form_{row['id']}"):
            st.markdown("**Your Label**")

            form_left, form_right = st.columns(2)

            with form_left:
                human_type = st.selectbox("Type", ALL_TYPES, index=default_type_idx)
                human_ticker = st.text_input("Ticker",
                    value=row.get("parsed_ticker") or "")
                human_price_raw = st.text_input("Price",
                    value=str(row["parsed_price"]) if pd.notna(row.get("parsed_price")) else "")

            with form_right:
                human_exp_date = st.text_input("Exp Date (MM/DD)",
                    value=row.get("parsed_exp_date") or "")
                human_strike = st.text_input("Strike",
                    value=row.get("parsed_strike") or "")
                human_opt_type = st.selectbox("Opt Type", ["", "C", "P"],
                    index=["", "C", "P"].index(row.get("parsed_opt_type") or "")
                    if row.get("parsed_opt_type") in ["", "C", "P"] else 0)

            notes = st.text_input("Notes (optional)", placeholder="e.g. ambiguous message, slang not caught")

            btn_correct, btn_submit = st.columns(2)
            mark_correct   = btn_correct.form_submit_button("✅ Mark Correct")
            submit_label_btn = btn_submit.form_submit_button("📝 Submit Label")

            if mark_correct or submit_label_btn:
                if mark_correct:
                    # Use parsed values as the human labels
                    human_fields = {
                        "type":     parsed_type,
                        "ticker":   row.get("parsed_ticker"),
                        "exp_date": row.get("parsed_exp_date"),
                        "strike":   row.get("parsed_strike"),
                        "opt_type": row.get("parsed_opt_type"),
                        "price":    row.get("parsed_price"),
                    }
                else:
                    human_price = float(human_price_raw) if human_price_raw.strip() else None
                    human_fields = {
                        "type":     human_type,
                        "ticker":   human_ticker.strip().upper() or None,
                        "exp_date": human_exp_date.strip() or None,
                        "strike":   human_strike.strip() or None,
                        "opt_type": human_opt_type or None,
                        "price":    human_price,
                    }

                parsed_fields = {
                    "type":     row.get("parsed_type"),
                    "ticker":   row.get("parsed_ticker"),
                    "exp_date": row.get("parsed_exp_date"),
                    "strike":   row.get("parsed_strike"),
                    "opt_type": row.get("parsed_opt_type"),
                    "price":    row.get("parsed_price"),
                }

                submit_label(int(row["id"]), human_fields, parsed_fields, notes)
                load_evals.clear()  # Bust cache so next load reflects the new label

                # Advance to next unlabeled message
                st.session_state.eval_idx = min(idx, len(unlabeled_df) - 2)
                st.rerun()
