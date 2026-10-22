"""Makisushi DSS — interactive dashboard over the generated dataset.

Run:  streamlit run app.py

Reads the eight exports in generated/ and puts a filter layer over them, so the
same questions the EDA notebook answers once can be re-asked for any date range,
category, channel, supplier or ingredient.
"""

from __future__ import annotations

from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

DATA = Path(__file__).parent / "generated"
SEAM = pd.Timestamp("2025-12-01")          # real records begin here

st.set_page_config(page_title="Makisushi DSS", page_icon="🍣", layout="wide")

# --- palette ---------------------------------------------------------------
# Categorical hues assigned in fixed order, never cycled; magnitude gets a
# single-hue ramp; polarity a two-hue diverging pair with a neutral midpoint.
S1, S2, S3 = "#2a78d6", "#eb6834", "#1baf7a"
S4, S5, S6 = "#eda100", "#e87ba4", "#008300"
S7, S8 = "#4a3aa7", "#e34948"
CAT = [S1, S2, S3, S4, S5, S6, S7, S8]
INK, INK2, MUTED, SURFACE = "#0b0b0b", "#52514e", "#b8b7b0", "#fcfcfb"
SEQ = "blues"


def style(chart: alt.Chart, height: int = 260) -> alt.Chart:
    """House style: recessive grid and axes, no chart-junk border."""
    return (
        chart.properties(height=height)
        .configure_view(stroke=None)
        .configure_axis(
            grid=True, gridColor="#e9e8e3", gridWidth=0.8,
            domainColor=MUTED, tickColor=MUTED,
            labelColor=INK2, titleColor=INK2, labelFontSize=11, titleFontSize=11,
        )
        .configure_legend(labelColor=INK2, titleColor=INK2, orient="top",
                          direction="horizontal", offset=6)
        .configure_title(color=INK, fontSize=13, anchor="start", dy=-6)
    )


def hover_line(df, x, y, colour=S1, y_title="", x_title="", tooltip=None):
    """Line + crosshair rule + nearest-point tooltip (hover layer by default)."""
    base = alt.Chart(df)
    sel = alt.selection_point(nearest=True, on="mouseover", fields=[x], empty=False)
    line = base.mark_line(color=colour, strokeWidth=2).encode(
        x=alt.X(f"{x}:T", title=x_title),
        y=alt.Y(f"{y}:Q", title=y_title),
    )
    pts = base.mark_point(color=colour, size=70, filled=True).encode(
        x=f"{x}:T", y=f"{y}:Q", opacity=alt.condition(sel, alt.value(1), alt.value(0)),
        tooltip=tooltip or [alt.Tooltip(f"{x}:T", title="date"),
                            alt.Tooltip(f"{y}:Q", title=y_title or y, format=",.0f")],
    ).add_params(sel)
    rule = base.mark_rule(color=MUTED).encode(
        x=f"{x}:T", opacity=alt.condition(sel, alt.value(0.6), alt.value(0)),
    )
    return line + rule + pts


def peso(v: float) -> str:
    if abs(v) >= 1e6:
        return f"₱{v/1e6:,.2f}M"
    if abs(v) >= 1e3:
        return f"₱{v/1e3:,.0f}k"
    return f"₱{v:,.0f}"


# ===========================================================================
# Data
# ===========================================================================


@st.cache_data(show_spinner="Loading the dataset…")
def load():
    cal = pd.read_csv(DATA / "calendar.csv", parse_dates=["date"])
    keys = cal[["date_id", "date", "day_of_week", "dow", "month", "year",
                "is_weekend", "is_holiday", "is_payday", "is_ber_month"]]

    sales = pd.read_csv(DATA / "sales.csv").merge(keys, on="date_id", how="left")
    sales["is_real"] = sales["date"] >= SEAM

    ingr = pd.read_csv(DATA / "ingredients.csv")
    sup = pd.read_csv(DATA / "suppliers.csv")

    inv = (pd.read_csv(DATA / "inventory.csv")
           .merge(keys[["date_id", "date", "dow", "year"]], on="date_id", how="left")
           .merge(ingr[["ingredient_id", "ingredient_name", "ingredient_code",
                        "category", "storage_type", "uom", "shelf_life_days",
                        "is_perishable", "unit_cost", "pack_size"]],
                  on="ingredient_id", how="left")
           .merge(sup[["supplier_id", "supplier_name"]], on="supplier_id", how="left"))

    waste = (pd.read_csv(DATA / "waste.csv",
                         parse_dates=["received_date", "expiry_date"])
             .merge(keys[["date_id", "date", "year"]], on="date_id", how="left")
             .merge(ingr[["ingredient_id", "ingredient_name", "storage_type",
                          "is_perishable", "shelf_life_days"]],
                    on="ingredient_id", how="left")
             .merge(sup[["supplier_id", "supplier_name"]], on="supplier_id", how="left"))

    menu = pd.read_csv(DATA / "menu_items.csv")
    recipes = pd.read_csv(DATA / "recipes.csv")
    return sales, inv, waste, sup, menu, ingr, recipes, cal


try:
    sales, inventory, waste, suppliers, menu, ingr, recipes, calendar = load()
except FileNotFoundError as exc:
    st.error(f"Could not find the exports in `{DATA}`. Run `python makisushi_datagen.py` "
             f"first.\n\n{exc}")
    st.stop()


# ===========================================================================
# Filters
# ===========================================================================

st.sidebar.title("🍣 Filters")
st.sidebar.caption("Everything below cascades into every tab.")

lo, hi = sales.date.min().date(), sales.date.max().date()
d1, d2 = st.sidebar.slider("Date range", min_value=lo, max_value=hi, value=(lo, hi),
                           format="MMM YYYY")
d1, d2 = pd.Timestamp(d1), pd.Timestamp(d2)

source = st.sidebar.radio("Sales source", ["Everything", "Real only (Dec 2025 →)",
                                           "Generated only (→ Nov 2025)"],
                          help="The history before 2025-12-01 is synthetic; "
                               "from the seam onward it is the owner's own records.")

with st.sidebar.expander("Menu & channel", expanded=False):
    cats = sorted(sales.category.dropna().unique())
    pick_cat = st.multiselect("Category", cats, default=[],
                              help="Empty = all categories.")
    chans = sorted(sales.channel.dropna().unique())
    pick_chan = st.multiselect("Channel", chans, default=[])

with st.sidebar.expander("Ingredients & suppliers", expanded=False):
    stores = sorted(ingr.storage_type.dropna().unique())
    pick_store = st.multiselect("Storage type", stores, default=[])
    only_perish = st.checkbox("Perishable only", value=False)
    sup_names = sorted(suppliers.supplier_name.unique())
    pick_sup = st.multiselect("Supplier", sup_names, default=[])
    ing_names = sorted(ingr.ingredient_name.unique())
    pick_ing = st.multiselect("Ingredient", ing_names, default=[])

# --- apply -----------------------------------------------------------------
s = sales[(sales.date >= d1) & (sales.date <= d2)]
if source.startswith("Real"):
    s = s[s.is_real]
elif source.startswith("Generated"):
    s = s[~s.is_real]
if pick_cat:
    s = s[s.category.isin(pick_cat)]
if pick_chan:
    s = s[s.channel.isin(pick_chan)]

inv = inventory[(inventory.date >= d1) & (inventory.date <= d2)]
w = waste[(waste.date >= d1) & (waste.date <= d2)]
if pick_store:
    inv = inv[inv.storage_type.isin(pick_store)]
    w = w[w.storage_type.isin(pick_store)]
if only_perish:
    inv, w = inv[inv.is_perishable], w[w.is_perishable]
if pick_sup:
    inv = inv[inv.supplier_name.isin(pick_sup)]
    w = w[w.supplier_name.isin(pick_sup)]
if pick_ing:
    inv = inv[inv.ingredient_name.isin(pick_ing)]
    w = w[w.ingredient_name.isin(pick_ing)]

menu_filtered = bool(pick_cat or pick_chan) or not source.startswith("Every")

if s.empty or inv.empty:
    st.warning("Nothing matches these filters. Widen the date range or clear a filter.")
    st.stop()

st.sidebar.divider()
st.sidebar.metric("Sales rows in view", f"{len(s):,}")
st.sidebar.metric("Ingredient-days in view", f"{len(inv):,}")


# ===========================================================================
# Header
# ===========================================================================

st.title("Makisushi — inventory & waste DSS")
st.caption(
    f"{d1:%d %b %Y} → {d2:%d %b %Y}  ·  {s.date.nunique():,} trading days  ·  "
    f"perishable raw-material decision support, Panay Ave × EDSA"
)

thr = inv.qty_consumed.sum() + inv.qty_wasted.sum()
k = st.columns(5)
k[0].metric("Net sales", peso(s.net_sales.sum()))
k[1].metric("Units sold", f"{s.quantity_sold.sum():,.0f}")
k[2].metric("Waste value", peso(w.waste_value_php.sum()),
            help="Capital thrown away over the window in view.")
k[3].metric("Waste share", f"{(inv.qty_wasted.sum()/thr if thr else 0):.1%}",
            help="Quantity wasted as a share of everything bought.")
k[4].metric("Stockout rate", f"{inv.stockout_flag.mean():.1%}",
            help="Ingredient-days where demand could not be met in full.")

tabs = st.tabs(["Overview", "Sales", "Inventory", "Waste", "Sales ↔ Inventory",
                "Data"])

# ===========================================================================
# 1 — Overview
# ===========================================================================
with tabs[0]:
    daily = (s.groupby("date", as_index=False)
             .agg(net=("net_sales", "sum"), units=("quantity_sold", "sum"),
                  lines=("sale_id", "count")))
    daily["roll"] = daily.net.rolling(28, center=True, min_periods=7).mean()

    st.subheader("Net sales per day")
    st.caption("28-day rolling mean. The dashed rule is the handover from generated "
               "history to the owner's real records.")
    ch = hover_line(daily, "date", "roll", S1, "₱ per day",
                    tooltip=[alt.Tooltip("date:T", title="date"),
                             alt.Tooltip("roll:Q", title="₱/day (28d mean)", format=",.0f"),
                             alt.Tooltip("net:Q", title="₱ that day", format=",.0f")])
    if d1 <= SEAM <= d2:
        seam_rule = (alt.Chart(pd.DataFrame({"d": [SEAM]}))
                     .mark_rule(color=INK2, strokeDash=[5, 4]).encode(x="d:T"))
        ch = ch + seam_rule
    st.altair_chart(style(ch, 300), width="stretch")

    c1, c2 = st.columns([1, 1])
    with c1:
        st.subheader("Day of week")
        st.caption("Index against the window's own mean. This is an office district — "
                   "Wednesday peaks, Sunday troughs.")
        pd_ = s.groupby(["date", "dow"], as_index=False).net_sales.sum()
        prof = pd_.groupby("dow", as_index=False).net_sales.mean()
        prof["idx"] = prof.net_sales / prof.net_sales.mean()
        prof["day"] = prof.dow.map(dict(enumerate(
            ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])))
        bar = alt.Chart(prof).mark_bar(color=S1, cornerRadiusEnd=4, size=26).encode(
            x=alt.X("day:N", sort=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                    title=None),
            y=alt.Y("idx:Q", title="index (1.00 = mean)",
                    scale=alt.Scale(zero=True)),
            tooltip=[alt.Tooltip("day:N", title="day"),
                     alt.Tooltip("idx:Q", title="index", format=".2f"),
                     alt.Tooltip("net_sales:Q", title="₱/day", format=",.0f")],
        )
        st.altair_chart(style(bar, 260), width="stretch")
    with c2:
        st.subheader("Monthly net sales")
        st.caption("Ber-months (Sep–Dec) run hot; the rainy quarter runs cold.")
        m = (s.assign(m=s.date.values.astype("datetime64[M]"))
             .groupby("m", as_index=False).net_sales.sum())
        ch = hover_line(m, "m", "net_sales", S1, "₱",
                        tooltip=[alt.Tooltip("m:T", title="month", format="%b %Y"),
                                 alt.Tooltip("net_sales:Q", title="₱", format=",.0f")])
        st.altair_chart(style(ch, 260), width="stretch")

    st.subheader("The two ways to be wrong")
    st.caption("Days sorted into quintiles by how busy they were. Quiet days spoil "
               "stock; busy days run short. Any policy has to be scored on both.")
    day = (daily.set_index("date")
           .join(inv.groupby("date").agg(waste=("qty_wasted", "sum"),
                                         cons=("qty_consumed", "sum"),
                                         short=("stockout_flag", "mean")))
           .dropna())
    if len(day) >= 10:
        day["waste_rate"] = day.waste / (day.waste + day.cons).replace(0, np.nan) * 100
        day["q"] = pd.qcut(day.net, 5, labels=["quietest", "2nd", "middle", "4th",
                                               "busiest"], duplicates="drop")
        agg = (day.groupby("q", observed=True)
               .agg(spoilage=("waste_rate", "mean"), stockout=("short", "mean"))
               .reset_index())
        agg["stockout"] *= 100
        long = agg.melt("q", var_name="measure", value_name="pct")
        long["measure"] = long.measure.map({"spoilage": "spoilage rate",
                                            "stockout": "stockout rate"})
        bars = alt.Chart(long).mark_bar(cornerRadiusEnd=4).encode(
            x=alt.X("q:N", title="how busy the day was", sort=list(agg.q)),
            y=alt.Y("pct:Q", title="% "),
            color=alt.Color("measure:N", title=None,
                            scale=alt.Scale(range=[S8, S2])),
            xOffset="measure:N",
            tooltip=[alt.Tooltip("q:N", title="quintile"),
                     alt.Tooltip("measure:N", title=None),
                     alt.Tooltip("pct:Q", format=".1f", title="%")],
        )
        st.altair_chart(style(bars, 260), width="stretch")
    else:
        st.info("Widen the date range to see the quintile breakdown.")

# ===========================================================================
# 2 — Sales
# ===========================================================================
with tabs[1]:
    c1, c2 = st.columns([1.1, 1])
    with c1:
        st.subheader("Best sellers")
        n_top = st.slider("How many items", 5, 30, 12, key="ntop")
        top = (s.groupby("item_id", as_index=False)
               .agg(units=("quantity_sold", "sum"), net=("net_sales", "sum"))
               .merge(menu[["item_id", "item_name", "category"]], on="item_id")
               .nlargest(n_top, "units"))
        bar = alt.Chart(top).mark_bar(color=S1, cornerRadiusEnd=4).encode(
            y=alt.Y("item_name:N", sort="-x", title=None,
                    axis=alt.Axis(labelLimit=220)),
            x=alt.X("units:Q", title="units sold"),
            tooltip=[alt.Tooltip("item_name:N", title="item"),
                     alt.Tooltip("category:N", title="category"),
                     alt.Tooltip("units:Q", title="units", format=",.0f"),
                     alt.Tooltip("net:Q", title="₱ net", format=",.0f")],
        )
        st.altair_chart(style(bar, 26 * n_top + 40), width="stretch")
    with c2:
        st.subheader("Where the money comes from")
        bycat = (s.groupby("category", as_index=False).net_sales.sum()
                 .nlargest(12, "net_sales"))
        bar = alt.Chart(bycat).mark_bar(color=S3, cornerRadiusEnd=4).encode(
            y=alt.Y("category:N", sort="-x", title=None,
                    axis=alt.Axis(labelLimit=220)),
            x=alt.X("net_sales:Q", title="₱ net"),
            tooltip=[alt.Tooltip("category:N", title="category"),
                     alt.Tooltip("net_sales:Q", title="₱", format=",.0f")],
        )
        st.altair_chart(style(bar, 26 * len(bycat) + 40), width="stretch")

        st.subheader("Concentration")
        by_item = s.groupby("item_id").quantity_sold.sum().sort_values(ascending=False)
        cum = pd.DataFrame({
            "pct_items": np.arange(1, len(by_item) + 1) / len(by_item) * 100,
            "pct_units": by_item.cumsum().values / by_item.sum() * 100,
        })
        at10 = float(np.interp(10, cum.pct_items, cum.pct_units))
        st.caption(f"The top 10% of items account for **{at10:.0f}%** of units sold.")
        area = alt.Chart(cum).mark_area(color=S1, opacity=0.18, line={"color": S1}).encode(
            x=alt.X("pct_items:Q", title="% of menu items (ranked)"),
            y=alt.Y("pct_units:Q", title="% of units"),
            tooltip=[alt.Tooltip("pct_items:Q", format=".0f", title="% of items"),
                     alt.Tooltip("pct_units:Q", format=".0f", title="% of units")],
        )
        st.altair_chart(style(area, 220), width="stretch")

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Channel mix over time")
        q = (s.assign(q=s.date.dt.to_period("Q").dt.to_timestamp())
             .groupby(["q", "channel"], as_index=False).net_sales.sum())
        area = alt.Chart(q).mark_area(opacity=0.9).encode(
            x=alt.X("q:T", title=None),
            y=alt.Y("net_sales:Q", stack="normalize", title="share of ₱",
                    axis=alt.Axis(format="%")),
            color=alt.Color("channel:N", title=None,
                            scale=alt.Scale(domain=["dine-in", "GrabFood"],
                                            range=[S1, S2])),
            tooltip=[alt.Tooltip("q:T", title="quarter", format="%b %Y"),
                     alt.Tooltip("channel:N", title="channel"),
                     alt.Tooltip("net_sales:Q", title="₱", format=",.0f")],
        )
        st.altair_chart(style(area, 260), width="stretch")
    with c2:
        st.subheader("Discounts, comps and other quirks")
        st.caption("Reproduced from the owner's export rather than scrubbed — a DSS "
                   "that only works on clean data will not survive the POS.")
        quirks = pd.DataFrame({
            "artifact": ["cost_of_goods empty", "net ≤ 0 (comps)", "discounted",
                         "taxed"],
            "pct": [s.cost_of_goods.isna().mean() * 100,
                    (s.net_sales <= 0).mean() * 100,
                    (s.discount > 0).mean() * 100,
                    (s.taxes > 0).mean() * 100],
        })
        bar = alt.Chart(quirks).mark_bar(color=S2, cornerRadiusEnd=4).encode(
            y=alt.Y("artifact:N", sort="-x", title=None),
            x=alt.X("pct:Q", title="% of sales lines"),
            tooltip=[alt.Tooltip("artifact:N", title=None),
                     alt.Tooltip("pct:Q", format=".1f", title="% of rows")],
        )
        st.altair_chart(style(bar, 200), width="stretch")
        st.caption(f"Median discount, when given: "
                   f"**{(s.loc[s.discount>0, 'discount'] / s.loc[s.discount>0, 'gross_sales'].replace(0, np.nan) * 100).median():.1f}%** "
                   f"of gross · duplicate (item, date) pairs in view: "
                   f"**{int(s.duplicated(['date_id','item_id']).sum())}**")

# ===========================================================================
# 3 — Inventory
# ===========================================================================
with tabs[2]:
    st.subheader("Ledger explorer")
    st.caption("Pick an ingredient and watch the stock sawtooth: deliveries land, "
               "consumption draws it down, the reorder point triggers the next order.")

    ranked = (inv.groupby("ingredient_name").qty_consumed.sum()
              .sort_values(ascending=False))
    choice = st.selectbox("Ingredient", ranked.index.tolist(), index=0)
    one = inv[inv.ingredient_name == choice].sort_values("date")
    meta = ingr[ingr.ingredient_name == choice].iloc[0]

    m = st.columns(5)
    m[0].metric("Shelf life", f"{int(meta.shelf_life_days)} d")
    m[1].metric("Pack size", f"{meta.pack_size:,.0f} {meta.uom}")
    m[2].metric("Consumed", f"{one.qty_consumed.sum():,.0f} {meta.uom}")
    m[3].metric("Wasted", f"{one.qty_wasted.sum():,.0f} {meta.uom}",
                delta=f"{one.qty_wasted.sum()/max(one.qty_consumed.sum()+one.qty_wasted.sum(),1):.1%} of throughput",
                delta_color="inverse")
    m[4].metric("Out of stock", f"{one.stockout_flag.mean():.1%} of days")

    span = one.date.max() - one.date.min()
    if span > pd.Timedelta(days=120):
        st.caption("Showing the last 120 days of the selected range so the sawtooth "
                   "stays legible.")
        one_v = one[one.date >= one.date.max() - pd.Timedelta(days=120)]
    else:
        one_v = one

    base = alt.Chart(one_v)
    stock = base.mark_line(color=S1, strokeWidth=2).encode(
        x=alt.X("date:T", title=None), y=alt.Y("closing_stock:Q", title=f"{meta.uom} on hand"),
        tooltip=[alt.Tooltip("date:T", title="date"),
                 alt.Tooltip("closing_stock:Q", title="on hand", format=",.0f"),
                 alt.Tooltip("qty_consumed:Q", title="consumed", format=",.0f"),
                 alt.Tooltip("qty_wasted:Q", title="wasted", format=",.0f"),
                 alt.Tooltip("reorder_level:Q", title="reorder point", format=",.0f")])
    reorder = base.mark_line(color=MUTED, strokeWidth=1.4, strokeDash=[4, 3]).encode(
        x="date:T", y="reorder_level:Q")
    deliveries = base.transform_filter(alt.datum.qty_received > 0).mark_point(
        color=S3, size=70, filled=True, stroke=SURFACE, strokeWidth=1.5).encode(
        x="date:T", y="closing_stock:Q",
        tooltip=[alt.Tooltip("date:T", title="delivered"),
                 alt.Tooltip("qty_received:Q", title="qty received", format=",.0f"),
                 alt.Tooltip("supplier_name:N", title="supplier")])
    st.altair_chart(style(stock + reorder + deliveries, 300), width="stretch")
    st.caption("Blue = stock on hand · dashed grey = reorder point · green dots = "
               "deliveries arriving.")

    flow = one_v.melt("date", ["qty_consumed", "qty_wasted"],
                      var_name="flow", value_name="qty")
    flow["flow"] = flow.flow.map({"qty_consumed": "consumed", "qty_wasted": "wasted"})
    bars = alt.Chart(flow).mark_bar().encode(
        x=alt.X("date:T", title=None), y=alt.Y("qty:Q", title=f"{meta.uom}/day"),
        color=alt.Color("flow:N", title=None,
                        scale=alt.Scale(domain=["consumed", "wasted"], range=[S1, S8])),
        tooltip=[alt.Tooltip("date:T", title="date"),
                 alt.Tooltip("flow:N", title=None),
                 alt.Tooltip("qty:Q", format=",.1f", title="qty")])
    st.altair_chart(style(bars, 200), width="stretch")

    st.divider()
    st.subheader("Which lines run short")
    per = (inv.groupby("ingredient_name")
           .agg(stockout=("stockout_flag", "mean"),
                consumed=("qty_consumed", "sum"),
                wasted=("qty_wasted", "sum"))
           .reset_index())
    per["waste_pct"] = per.wasted / (per.consumed + per.wasted).replace(0, np.nan) * 100
    per["stockout"] *= 100
    top_so = per.nlargest(12, "stockout")
    bar = alt.Chart(top_so).mark_bar(color=S2, cornerRadiusEnd=4).encode(
        y=alt.Y("ingredient_name:N", sort="-x", title=None,
                axis=alt.Axis(labelLimit=220)),
        x=alt.X("stockout:Q", title="% of days short"),
        tooltip=[alt.Tooltip("ingredient_name:N", title="ingredient"),
                 alt.Tooltip("stockout:Q", format=".1f", title="% days short"),
                 alt.Tooltip("waste_pct:Q", format=".1f", title="% wasted")])
    st.altair_chart(style(bar, 26 * len(top_so) + 40), width="stretch")

# ===========================================================================
# 4 — Waste
# ===========================================================================
with tabs[3]:
    if w.empty:
        st.info("No waste events under these filters.")
    else:
        c1, c2 = st.columns([1, 1.4])
        with c1:
            st.subheader("Why it was binned")
            rs = w.groupby("waste_reason", as_index=False).waste_value_php.sum()
            bar = alt.Chart(rs).mark_bar(cornerRadiusEnd=4).encode(
                y=alt.Y("waste_reason:N", sort="-x", title=None),
                x=alt.X("waste_value_php:Q", title="₱"),
                color=alt.Color("waste_reason:N", legend=None,
                                scale=alt.Scale(range=[S1, S2, S8])),
                tooltip=[alt.Tooltip("waste_reason:N", title="reason"),
                         alt.Tooltip("waste_value_php:Q", title="₱", format=",.0f")])
            st.altair_chart(style(bar, 200), width="stretch")
            st.caption("**prep-trim** is unavoidable kitchen loss. **expiry** and "
                       "**overstock** are the controllable share — what the DSS is for.")
        with c2:
            st.subheader("Costliest ingredients to throw away")
            tw = (w.groupby("ingredient_name", as_index=False)
                  .agg(value=("waste_value_php", "sum"), qty=("waste_quantity", "sum"))
                  .nlargest(10, "value"))
            bar = alt.Chart(tw).mark_bar(color=S8, cornerRadiusEnd=4).encode(
                y=alt.Y("ingredient_name:N", sort="-x", title=None,
                        axis=alt.Axis(labelLimit=220)),
                x=alt.X("value:Q", title="₱ binned"),
                tooltip=[alt.Tooltip("ingredient_name:N", title="ingredient"),
                         alt.Tooltip("value:Q", title="₱", format=",.0f"),
                         alt.Tooltip("qty:Q", title="quantity", format=",.0f")])
            st.altair_chart(style(bar, 280), width="stretch")

        st.divider()
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Waste value per month")
            mw = (w.assign(m=w.date.dt.to_period("M").dt.to_timestamp())
                  .groupby("m", as_index=False).waste_value_php.sum())
            ch = hover_line(mw, "m", "waste_value_php", S8, "₱",
                            tooltip=[alt.Tooltip("m:T", title="month", format="%b %Y"),
                                     alt.Tooltip("waste_value_php:Q", title="₱",
                                                 format=",.0f")])
            st.altair_chart(style(ch, 260), width="stretch")
        with c2:
            st.subheader("Shelf life is destiny")
            st.caption("Each bubble is an ingredient; size = ₱ value consumed.")
            per_i = (inv.groupby("ingredient_name")
                     .agg(cons=("qty_consumed", "sum"), wst=("qty_wasted", "sum"),
                          shelf=("shelf_life_days", "first"),
                          perish=("is_perishable", "first"),
                          cost=("unit_cost", "first")).reset_index())
            per_i = per_i[per_i.cons > 0]
            per_i["waste_pct"] = per_i.wst / (per_i.cons + per_i.wst) * 100
            per_i["value"] = per_i.cons * per_i.cost
            per_i["keeps"] = np.where(per_i.perish, "perishable", "keeps well")
            pts = alt.Chart(per_i).mark_circle(opacity=0.6).encode(
                x=alt.X("shelf:Q", title="shelf life (days, log)",
                        scale=alt.Scale(type="log")),
                y=alt.Y("waste_pct:Q", title="% of throughput wasted"),
                size=alt.Size("value:Q", legend=None, scale=alt.Scale(range=[40, 700])),
                color=alt.Color("keeps:N", title=None,
                                scale=alt.Scale(domain=["perishable", "keeps well"],
                                                range=[S1, S2])),
                tooltip=[alt.Tooltip("ingredient_name:N", title="ingredient"),
                         alt.Tooltip("shelf:Q", title="shelf life (d)"),
                         alt.Tooltip("waste_pct:Q", format=".1f", title="% wasted"),
                         alt.Tooltip("value:Q", format=",.0f", title="₱ consumed")])
            st.altair_chart(style(pts, 260), width="stretch")

        st.subheader("Traced back to the delivering supplier")
        st.caption("Every waste event carries the batch it came from, so spoilage "
                   "attributes to a supplier and a lead time.")
        sw = (w.groupby("supplier_name", as_index=False)
              .agg(value=("waste_value_php", "sum"), events=("waste_id", "count"))
              .merge(suppliers[["supplier_name", "lead_time_mean", "fill_rate"]],
                     on="supplier_name", how="left")
              .sort_values("value", ascending=False))
        st.dataframe(
            sw.rename(columns={"supplier_name": "supplier", "value": "₱ wasted",
                               "events": "events", "lead_time_mean": "lead time (d)",
                               "fill_rate": "fill rate"}),
            hide_index=True, width="stretch",
            column_config={"₱ wasted": st.column_config.NumberColumn(format="%.0f"),
                           "fill rate": st.column_config.ProgressColumn(
                               min_value=0, max_value=1, format="%.3f")})

# ===========================================================================
# 5 — the linkage
# ===========================================================================
with tabs[4]:
    st.subheader("Stock moves because dishes were sold")
    st.markdown(
        "The claim the whole DSS rests on. Recompute ingredient demand **from the "
        "sales table alone**, by exploding every dish through its recipe, then "
        "compare against what the inventory ledger independently recorded as "
        "consumed."
    )
    st.code("qty_consumed[ingredient, day]  =  Σ  units_sold[dish, day] × recipe_qty[dish, ingredient]",
            language="text")

    link = (s[["date", "item_id", "quantity_sold"]]
            .merge(recipes[["item_id", "ingredient_id", "qty_base"]], on="item_id")
            .assign(demand=lambda d: d.quantity_sold * d.qty_base)
            .groupby(["date", "ingredient_id"], as_index=False).demand.sum())
    chk = (inv[["date", "ingredient_id", "ingredient_name", "qty_consumed",
                "stockout_flag"]]
           .merge(link, on=["date", "ingredient_id"], how="left")
           .fillna({"demand": 0.0}))

    if menu_filtered:
        st.info(
            "**Attribution mode.** A category, channel or source filter is active, so "
            "the recomputed demand covers only the dishes in view — it is a *share* of "
            "ledger consumption, not the whole of it. Clear those filters to see the "
            "exact identity check.", icon="ℹ️")
        att = (chk.groupby("ingredient_name", as_index=False)
               .agg(attributed=("demand", "sum"), ledger=("qty_consumed", "sum")))
        att = att[att.ledger > 0].nlargest(15, "attributed")
        att["share"] = att.attributed / att.ledger * 100
        bar = alt.Chart(att).mark_bar(color=S3, cornerRadiusEnd=4).encode(
            y=alt.Y("ingredient_name:N", sort="-x", title=None,
                    axis=alt.Axis(labelLimit=220)),
            x=alt.X("attributed:Q", title="quantity drawn by the dishes in view"),
            tooltip=[alt.Tooltip("ingredient_name:N", title="ingredient"),
                     alt.Tooltip("attributed:Q", format=",.0f", title="attributed"),
                     alt.Tooltip("ledger:Q", format=",.0f", title="ledger total"),
                     alt.Tooltip("share:Q", format=".1f", title="% of ledger")])
        st.altair_chart(style(bar, 26 * len(att) + 40), width="stretch")
        st.caption("Which ingredients the selected part of the menu is actually "
                   "responsible for — the ordering consequence of a menu decision.")
    else:
        served = chk[~chk.stockout_flag]
        r_all = chk.demand.corr(chk.qty_consumed)
        r_ok = served.demand.corr(served.qty_consumed)
        gap = float((served.demand - served.qty_consumed).abs().max())

        c = st.columns(3)
        c[0].metric("r, all ingredient-days", f"{r_all:.4f}")
        c[1].metric("r, fully-stocked days", f"{r_ok:.6f}")
        c[2].metric("Largest gap when in stock", f"{gap:.6f}")
        st.success(
            "On any day the kitchen was in stock, consumption equals recipe-implied "
            "demand to floating-point precision. The ledger is not a table that merely "
            "correlates with sales — it is their arithmetic consequence. Where the two "
            "come apart is exactly where stock ran out, and that gap **is** the lost "
            "sale.", icon="✅")

        samp = chk[chk.demand > 0]
        if len(samp) > 4000:
            samp = samp.sample(4000, random_state=0)
        lim = float(np.percentile(samp.demand, 99)) if len(samp) else 1.0
        samp = samp.assign(status=np.where(samp.stockout_flag, "stocked out", "in stock"))
        pts = alt.Chart(samp).mark_circle(size=22, opacity=0.45).encode(
            x=alt.X("demand:Q", title="demand implied by sales × recipes",
                    scale=alt.Scale(domain=[0, lim], clamp=True)),
            y=alt.Y("qty_consumed:Q", title="qty_consumed in the ledger",
                    scale=alt.Scale(domain=[0, lim], clamp=True)),
            color=alt.Color("status:N", title=None,
                            scale=alt.Scale(domain=["in stock", "stocked out"],
                                            range=[S1, S2])),
            tooltip=[alt.Tooltip("ingredient_name:N", title="ingredient"),
                     alt.Tooltip("date:T", title="date"),
                     alt.Tooltip("demand:Q", format=",.1f", title="demanded"),
                     alt.Tooltip("qty_consumed:Q", format=",.1f", title="consumed")])
        diag = (alt.Chart(pd.DataFrame({"x": [0, lim]}))
                .mark_line(color=INK2, strokeDash=[5, 4], strokeWidth=1.2)
                .encode(x="x:Q", y="x:Q"))
        st.altair_chart(style(pts + diag, 420), width="stretch")
        st.caption("Points on the dashed line: everything the recipes asked for was "
                   "served. Points below it: demand the kitchen could not meet.")

    st.divider()
    st.subheader("Deliveries follow usage")
    st.caption("Cross-correlating daily consumption against daily receipts recovers "
               "the replenishment lead time without being told it.")
    dc = inv.groupby("date").qty_consumed.sum()
    dr = inv.groupby("date").qty_received.sum()
    if len(dc) > 30 and dc.std() and dr.std():
        a = (dc - dc.mean()) / dc.std()
        b = (dr - dr.mean()) / dr.std()
        ccf = pd.DataFrame({"lag": range(-7, 8),
                            "corr": [a.corr(b.shift(-L)) for L in range(-7, 8)]})
        best = int(ccf.loc[ccf["corr"].idxmax(), "lag"])
        bar = alt.Chart(ccf).mark_bar(cornerRadiusEnd=3).encode(
            x=alt.X("lag:O", title="lag (days)"),
            y=alt.Y("corr:Q", title="correlation"),
            color=alt.condition(alt.datum.lag == best, alt.value(S2), alt.value(MUTED)),
            tooltip=[alt.Tooltip("lag:O", title="lag (days)"),
                     alt.Tooltip("corr:Q", format=".3f", title="corr")])
        st.altair_chart(style(bar, 240), width="stretch")
        st.caption(f"Peak at lag **{best:+d} day(s)** — usage first, delivery after.")
    else:
        st.info("Widen the date range to compute the lag.")

# ===========================================================================
# 6 — Data
# ===========================================================================
with tabs[5]:
    st.subheader("The filtered rows")
    st.caption("Everything the filters produced, ready to pull into Excel or Power BI.")
    which = st.radio("Table", ["sales", "inventory", "waste", "suppliers",
                               "menu_items", "ingredients", "recipes"],
                     horizontal=True)
    frames = {"sales": s, "inventory": inv, "waste": w, "suppliers": suppliers,
              "menu_items": menu, "ingredients": ingr, "recipes": recipes}
    df = frames[which]
    st.caption(f"{len(df):,} rows × {df.shape[1]} columns"
               + ("  ·  filters apply to this table" if which in
                  ("sales", "inventory", "waste") else "  ·  reference table, unfiltered"))
    st.dataframe(df.head(2000), width="stretch", hide_index=True)
    st.download_button(f"Download {which}.csv", df.to_csv(index=False).encode("utf-8"),
                       file_name=f"{which}_filtered.csv", mime="text/csv")
