"""
Makisushi synthetic dataset generator - VERSION 2.

Same model as makisushi_datagen.py, which is left unchanged so that generated/
(v1) and generated_v2/ (this file) can be compared. Section 1 (reference tables
and cleaned recipes) still comes from makisushi_generator.build_dimensions, so
every dimension and the recipe bridge are identical to v1.

Changes, each tied to a finding in audit/DATA_AUDIT_REPORT.md:
  A1/B4  Expiry: the receipt date is usable day 1, so the last usable day is
         received + shelf_life_days - 1 and the batch is expired from the day
         after. Expired batches are binned at the start of the day, BEFORE any
         consumption, and consumption draws usable batches FIFO (earliest
         received first). Every batch lives exactly shelf_life_days: the random
         batch-quality life of v1 is gone (BAT-01, WST-01, BAT-02, BAT-03).
  A2/B1  A double-logged POS line copies its original's channel; the copy is
         kept in sales.csv and flagged, never used as a separate sale (SAL-02).
  A3     Synthetic is_complimentary uses the real-line rule:
         category MANAGEMENT or net_sales <= 0 (SAL-03).
  A4     Complimentary MANAGEMENT lines are Dine-in (SAL-04).
  A5     A short delivery of a piece/serving item is a whole number of units
         (INV-02).
  A6     A bought-to-order (slow perishable) item is re-bought only when there
         has been demand since its last delivery (INV-01).
  A7     Superseded by A1/B4: no batch outlives its stated shelf life.
  A8     Parquet twins are rewritten every run and a failure raises (FILE-01).
  A9     Lineage and calendar columns: data_source on every fact, is_synthetic
         on the supplier tables, iso_year / week_start_date on the calendar.
  B2     POS artifacts stay in sales.csv, flagged; sales_artifact_log.csv lists
         every artifact, including the POS lines the export lost (those sales
         happened, so their ingredients are consumed).
  B3     Synthetic sales on restaurant closure days stay in sales.csv, flagged
         with the reason, and are excluded from facts and consumption.
         Closure days = real-window days with no POS line at all, and the same
         public holidays in the backfill years.
  B5     lead_time_days >= 1 (external suppliers). Orders are placed only on
         days when order date + lead_time_days is a supplier delivery day, so an
         on-time receipt arrives exactly lead_time_days after the order.
  B6     The last two months (2026-07-09 .. 2026-09-08) are an untouched
         forecast test period: the backfill's item rates, weekday profile and
         prices are calibrated on real sales before it only, and items first
         sold inside it get no synthetic history.

No parameter was changed to move waste, stockout or forecast KPIs.
Run:  python makisushi_datagen_v2.py        (writes generated_v2/)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

import makisushi_generator as s1   # Section 1: reference tables (same folder, unchanged)

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------


@dataclass
class Config:
    seed: int = 42
    start: str = "2021-01-01"
    seam: str = "2025-12-01"
    end: str = "2026-09-08"

    src_dir: Path = field(default_factory=s1._find_src_dir)
    sales_file: str = "makisushi_Jan_2026.xlsx"
    # opt-in (used by makisushi_datagen_v3.py; False keeps generated_v2 byte-identical):
    # closure days carry no sales lines, no orders and no deliveries
    remove_closure_days: bool = False
    sales_sheet: str = "SALES'26"
    out_dir: Path = Path("generated_v2")      # v2: never writes into generated/

    # B6: the most recent months are a test period nothing may be calibrated on
    forecast_test_months: int = 2

    # 8.1 trend: monotonic growth, no COVID dip, normalized to 1.0 at the seam
    trend_2021: float = 0.48

    # 8.4 calendar multipliers (literature-imposed; in-window totals are flat)
    ber_month_lift: float = 0.14          # Sep-Dec
    december_extra: float = 0.10          # 13th-month pay on top of ber-month
    q3_dip: float = -0.10                 # Jun-Aug
    payday_lift: float = 0.11             # 15th & month-end
    holiday_lift: float = -0.05           # PH holidays: office district goes quiet

    # 7.3 latent processes
    rho_u: float = 0.70
    sigma_u: float = 0.25
    rho_w: float = 0.55
    sigma_w: float = 0.80
    w_season_amp: float = 0.70            # wet season Jun-Oct
    mgr_bias_0: float = 0.18              # initial over-ordering
    mgr_tau_days: float = 3 * 365.0       # learning decay
    sigma_m: float = 0.010

    # 7.4 demand
    gamma_mu: float = 0.25                # sensitivity to area activity
    gamma_sd: float = 0.08
    delta_mu: float = 0.12                # sensitivity to bad weather
    delta_sd: float = 0.05
    eps_early_2021: float = 0.55          # day-level noise, wider in early years
    eps_early_2025: float = 0.40          # matches the real slice's daily CV ~0.45
    p_catering: float = 0.010             # heavy-tail platter days (max ~PHP 55k)

    # channel
    deliv_alpha: float = -2.6
    deliv_beta_w: float = 0.55            # rain => more GrabFood
    deliv_2021: float = 1.9               # high delivery share in 2021 ...
    deliv_decay_days: float = 420.0       # ... decaying to today's low share

    # 7.9 financials
    p_discount: float = 0.26
    disc_beta_a: float = 1.6
    disc_beta_b: float = 18.0
    p_tax_nonzero: float = 0.004
    p_dup_row: float = 0.003
    p_missing_row: float = 0.002
    p_label_noise: float = 0.005

    # 7.7 inventory / ordering
    service_z: float = 1.41               # ~92% service level
    lead_weather_kappa: float = 0.35
    review_fresh_days: int = 1
    review_dry_days: int = 7
    supplier_override: dict = field(default_factory=dict)
    terms_override: dict = field(default_factory=dict)
    # opt-in (generated_v4): items bought only in whole units (whole fish). When their stock runs
    # out, the emergency buy is whole packs too; what the day does not use is stocked as a batch.
    # Empty keeps generated_v2 / v3 byte-identical.
    whole_unit_emergency: tuple = ()
    whole_unit_emergency_premium: float = 0.0
    # opt-in (generated_v4, round 6): walk-in suppliers (a nearby store bought from with petty cash). A same-day
    # emergency run there costs the regular price, not emergency_premium. Empty = v2 / v3 unchanged.
    walk_in_suppliers: tuple = ()
    # opt-in (generated_v4, issue I20): items whose one pack outlasts its shelf life never fall below the
    # reorder point by use, so the old trigger only reacted after the pack expired. These items are checked
    # daily and a replacement is planned to arrive the morning the old pack is binned. Empty = v2 / v3 unchanged.
    planned_replacement: tuple = ()
    # opt-in (generated_v4, issue I07): use outside the POS (staff meals, specials, comps, trimming), as a ratio
    # to the item's POS use, spread over the open days of each month. Empty = v2 / v3 unchanged.
    off_pos_use_ratio: dict = field(default_factory=dict)
    # opt-in (generated_v4, issue I12): a fixed use outside the POS (staff meals), base units per open day, for
    # items with no POS use to scale a ratio from. Empty = v2 / v3 unchanged.
    off_pos_use_daily: dict = field(default_factory=dict)
    # opt-in (generated_v4 seed sensitivity): a separate seed for the inventory simulation only (ordering,
    # lead times, fill rates, prices); sales and latents keep `seed`. None = v2 / v3 unchanged.
    inventory_seed: int | None = None

    # 7.8 spoilage (v2: expiry is deterministic, see A1/B4; the v1 batch-quality
    # parameters sigma_batch and shelf_weather_phi no longer exist)
    sparse_pack_frac: float = 0.50        # below this, a line is bought to order
    perish_cover_frac: float = 0.70       # order-up-to cap, as a share of shelf life
    cover_floor_days: float = 0.5         # ...but never below lead time + this many days
    emergency_premium: float = 0.25

    volume_multiplier: float = 1.0
    branch_id: int = 1

    write_parquet: bool = True

    def __post_init__(self) -> None:
        self.src_dir = Path(self.src_dir)
        self.out_dir = Path(self.out_dir)
        if not self.out_dir.is_absolute():
            self.out_dir = self.src_dir / self.out_dir


CATEGORY_TYPOS = {       # real messiness: inconsistent category labels
    "ALL TIME FAVORITES": "ALL TIME FAVORITE",
    "DON BURI (BEEF)": "DONBURI (BEEF)",
    "DON BURI (PORK)": "DONBURI (PORK)",
    "GRAB FOOD": "GRABFOOD",
    "MAKI ROLLS": "MAKI ROLL",
}


def _dates(cfg: Config):
    idx = pd.date_range(cfg.start, cfg.end, freq="D")
    seam = pd.Timestamp(cfg.seam)
    return idx, seam


def forecast_test_start(cfg: Config) -> pd.Timestamp:
    """First day of the untouched test period: the last forecast_test_months months."""
    return pd.Timestamp(cfg.end) - pd.DateOffset(months=cfg.forecast_test_months) + pd.Timedelta(days=1)


# --------------------------------------------------------------------------
# Section 1 outputs (fixed inputs)
# --------------------------------------------------------------------------


def load_dimensions(cfg: Config) -> dict:
    D = s1.build_dimensions(
        s1.Config(src_dir=cfg.src_dir, sales_file=cfg.sales_file, seed=cfg.seed),
        np.random.default_rng(cfg.seed),
    )
    cal = D["dim_date"].copy()
    menu = D["dim_menu_item"].copy()
    ing = D["dim_ingredient"].copy()
    sup = D["dim_supplier"].copy()
    bom = D["bom"].copy()
    supply_ref = D["supply_ref"].copy()

    bom = bom.dropna(subset=["item_id", "ingredient_id"]).copy()
    bom["item_id"] = bom["item_id"].astype(int)
    bom["ingredient_id"] = bom["ingredient_id"].astype(int)
    menu["item_id"] = menu["item_id"].astype(int)
    ing["unit_cost"] = ing["unit_cost"].astype(float)
    bom = bom[bom["qty_base"] > 0].copy()
    return dict(
        calendar=cal, menu=menu, ingredients=ing, suppliers=sup,
        terms=D["supplier_item_terms"].copy(), bom=bom, supply_ref=supply_ref, recipe_review=D["recipe_review"],
    )


def load_real_sales(cfg: Config, menu: pd.DataFrame) -> pd.DataFrame:
    """The kept-real slice: 2025-12-01 -> 2026-09-08, never resampled."""
    raw = pd.read_excel(cfg.src_dir / cfg.sales_file, sheet_name=cfg.sales_sheet)
    raw = raw.rename(
        columns={
            "Item name": "item_name", "SKU": "sku", "Category": "category",
            "Items sold": "quantity_sold", "Gross sales": "gross_sales",
            "Discounts": "discount", "Net sales": "net_sales",
            "Taxes": "taxes", "DATE": "date",
        }
    )
    raw["date"] = pd.to_datetime(raw["date"])
    ids = menu[["item_id", "item_name"]].drop_duplicates("item_name")
    df = raw.merge(ids, on="item_name", how="left")
    df = df.dropna(subset=["item_id"]).copy()
    df["item_id"] = df["item_id"].astype(int)
    df["unit_price"] = np.where(
        df["quantity_sold"] > 0, df["gross_sales"] / df["quantity_sold"], 0.0
    )
    df["is_complimentary"] = (df["category"].astype(str).str.upper() == "MANAGEMENT") | (
        df["net_sales"] <= 0
    )
    df["is_real"] = True
    keep = [
        "date", "item_id", "sku", "category", "quantity_sold", "unit_price",
        "gross_sales", "discount", "net_sales", "taxes", "is_complimentary", "is_real",
    ]
    return df[keep].reset_index(drop=True)


def closure_calendar(cfg: Config, real: pd.DataFrame) -> dict:
    """B3: restaurant closure days -> basis.

    Real window: a day with no POS line at all is an observed closure. Backfill
    years: the same public holidays (matched by name), because the real POS
    shows the restaurant closed on each of them. Owner confirmation is still
    recommended for the backfill years."""
    import holidays

    idx, seam = _dates(cfg)
    ph = holidays.Philippines(years=range(idx.min().year, idx.max().year + 1))
    parts = lambda d: set((ph.get(d.date()) or "").split("; ")) - {""}   # same-day holidays are joined by "; "
    sold = set(pd.to_datetime(real["date"]).dt.normalize())
    observed = [d for d in pd.date_range(seam, cfg.end, freq="D") if d not in sold]
    names = set().union(*(parts(d) for d in observed)) if observed else set()
    out = {d: "observed: no POS line in SALES'26" for d in observed}
    for d in idx[idx < seam]:
        hit = sorted(parts(d) & names)
        if hit:
            out[d] = f"inferred: {hit[0]} (closed on {hit[0]} in the real POS window)"
    return out


# --------------------------------------------------------------------------
# Section 2 - latents (7.3) - generated, then STRIPPED at export (9)
# --------------------------------------------------------------------------


def draw_latents(cfg: Config, rng: np.random.Generator) -> pd.DataFrame:
    idx, _ = _dates(cfg)
    n = len(idx)
    t = np.arange(n)

    u = np.zeros(n)
    eta = rng.normal(0.0, cfg.sigma_u, n)
    for i in range(1, n):
        u[i] = cfg.rho_u * u[i - 1] + eta[i]

    doy = idx.dayofyear.to_numpy()
    seas = cfg.w_season_amp * np.sin(2 * np.pi * (doy - 100) / 365.25)  # wet Jun-Oct
    resid = np.zeros(n)
    etw = rng.normal(0.0, cfg.sigma_w * math.sqrt(1 - cfg.rho_w ** 2), n)
    for i in range(1, n):
        resid[i] = cfg.rho_w * resid[i - 1] + etw[i]
    w = seas + resid
    w = (w - w.mean()) / w.std()

    drift = np.cumsum(rng.normal(0.0, cfg.sigma_m, n))
    m = cfg.mgr_bias_0 * np.exp(-t / cfg.mgr_tau_days) + drift
    m = np.clip(m, -0.15, 0.80)

    return pd.DataFrame({"date": idx, "u_t": u, "w_t": w, "m_t": m})


# --------------------------------------------------------------------------
# Section 2 - calendar / trend / weekly shape (B6: calibration slice only)
# --------------------------------------------------------------------------


def build_time_factors(cfg: Config, calendar: pd.DataFrame,
                       real_calib: pd.DataFrame) -> pd.DataFrame:
    idx, seam = _dates(cfg)
    cal = calendar.set_index("date").reindex(idx)

    span = (seam - pd.Timestamp(cfg.start)).days
    elapsed = (seam - idx).days.to_numpy().astype(float)
    trend = np.power(cfg.trend_2021, np.clip(elapsed, 0, None) / span)  # T(t*)=1

    # Wk(dow): from the real calibration slice only (B6)
    r = real_calib.copy()
    r["dow"] = r["date"].dt.dayofweek
    per_day = r.groupby(["date", "dow"], as_index=False)["net_sales"].sum()
    wk = per_day.groupby("dow")["net_sales"].mean()
    wk = wk / wk.mean()
    wk_vec = wk.reindex(range(7)).to_numpy()

    month = idx.month.to_numpy()
    cal_f = np.ones(len(idx))
    cal_f *= np.where(np.isin(month, [9, 10, 11, 12]), 1 + cfg.ber_month_lift, 1.0)
    cal_f *= np.where(month == 12, 1 + cfg.december_extra, 1.0)
    cal_f *= np.where(np.isin(month, [6, 7, 8]), 1 + cfg.q3_dip, 1.0)
    cal_f *= np.where(cal["is_payday"].to_numpy(dtype=bool), 1 + cfg.payday_lift, 1.0)
    cal_f *= np.where(cal["is_holiday"].to_numpy(dtype=bool), 1 + cfg.holiday_lift, 1.0)

    years = (idx - pd.Timestamp(cfg.start)).days.to_numpy() / 365.25
    eps_sd = np.interp(years, [0, 5], [cfg.eps_early_2021, cfg.eps_early_2025])

    return pd.DataFrame(
        {
            "date": idx,
            "dow": idx.dayofweek,
            "trend": trend,
            "wk": wk_vec[idx.dayofweek.to_numpy()],
            "cal": cal_f,
            "eps_sd": eps_sd,
        }
    )


def calibrate_base(cfg: Config, real_calib: pd.DataFrame, menu: pd.DataFrame,
                   tf: pd.DataFrame, test_start: pd.Timestamp) -> pd.DataFrame:
    """base_i such that the model reproduces the calibration slice's item mix at T=1.

    B6: exposure and units come from seam <= date < test_start only. An item
    with no sale in that slice was first sold inside the test period, so it
    gets no synthetic history (base 0) - v1 gave it a faint tail rate, which
    leaked the test period's menu into the training years."""
    _, seam = _dates(cfg)
    tf_cal = tf[(tf["date"] >= seam) & (tf["date"] < test_start)]
    exposure = float((tf_cal["trend"] * tf_cal["wk"] * tf_cal["cal"]).sum())

    units = real_calib.groupby("item_id")["quantity_sold"].sum()
    base = (units / exposure).rename("base_i").reset_index()

    out = menu[["item_id"]].merge(base, on="item_id", how="left")
    out["base_i"] = out["base_i"].fillna(0.0) * cfg.volume_multiplier
    return out


def calibration_attributes(real_calib: pd.DataFrame) -> pd.DataFrame:
    """sku / category / price the backfill writes on its lines, from the
    calibration slice only (B6) - same rules as makisushi_generator's
    dim_menu_item (first SKU, modal category, modal rounded unit price)."""
    r = real_calib.copy()
    valid = r[(r["quantity_sold"] > 0) & (r["gross_sales"] > 0)]
    price = (valid.assign(p=(valid["gross_sales"] / valid["quantity_sold"]).round(0))
             .groupby("item_id")["p"].agg(lambda x: x.mode().iloc[0]))
    cat = r.groupby("item_id")["category"].agg(lambda x: x.mode().iloc[0])
    sku = r.groupby("item_id")["sku"].first()
    out = pd.concat([sku.rename("sku"), cat.rename("category"), price.rename("price")], axis=1)
    out["price"] = out["price"].fillna(0.0)
    return out.reset_index()


# --------------------------------------------------------------------------
# Section 2 - demand backfill (7.4)
# --------------------------------------------------------------------------


def build_backfill(cfg: Config, rng: np.random.Generator, menu: pd.DataFrame,
                   base: pd.DataFrame, tf: pd.DataFrame,
                   latents: pd.DataFrame, attrs: pd.DataFrame) -> pd.DataFrame:
    _, seam = _dates(cfg)
    days = tf[tf["date"] < seam].reset_index(drop=True)
    nd = len(days)

    items = menu.sort_values("item_id").reset_index(drop=True)
    b = base.set_index("item_id").loc[items["item_id"]]["base_i"].to_numpy()
    ni = len(items)

    gamma = np.clip(rng.normal(cfg.gamma_mu, cfg.gamma_sd, ni), 0.0, None)
    delta = np.clip(rng.normal(cfg.delta_mu, cfg.delta_sd, ni), 0.0, None)
    r_i = np.clip(0.8 + 0.8 * np.sqrt(b), 0.4, 3.0)       # NB size; overdispersion

    lat = latents.set_index("date").loc[days["date"]]
    u = lat["u_t"].to_numpy()
    w = lat["w_t"].to_numpy()

    day_f = (days["trend"] * days["wk"] * days["cal"]).to_numpy()
    eps = rng.normal(0.0, 1.0, nd) * days["eps_sd"].to_numpy()

    intro = items["date_introduced"].fillna(pd.Timestamp(cfg.start)).to_numpy()
    retire = items["date_retired"].fillna(pd.Timestamp("2100-01-01")).to_numpy()
    dvals = days["date"].to_numpy()
    active = (dvals[None, :] >= intro[:, None]) & (dvals[None, :] <= retire[:, None])
    active &= (b > 0)[:, None]                               # B6: no history for test-period-only items

    loglam = (
        np.log(np.maximum(b, 1e-12))[:, None]
        + np.log(day_f)[None, :]
        + gamma[:, None] * u[None, :]
        - delta[:, None] * w[None, :]
        + eps[None, :]
    )
    lam = np.exp(loglam) * active

    cater_days = rng.random(nd) < cfg.p_catering
    if cater_days.any():
        for j in np.where(cater_days)[0]:
            pick = rng.choice(ni, size=min(12, ni), replace=False)
            lam[pick, j] *= rng.uniform(8.0, 25.0, size=len(pick))

    p = r_i[:, None] / (r_i[:, None] + np.maximum(lam, 1e-9))
    qty = rng.negative_binomial(r_i[:, None] * np.ones_like(lam), p)
    qty = np.where(lam > 0, qty, 0)

    ii, jj = np.nonzero(qty)
    out = pd.DataFrame(
        {
            "date": days["date"].to_numpy()[jj],
            "item_id": items["item_id"].to_numpy()[ii],
            "quantity_sold": qty[ii, jj].astype(int),
        }
    )
    out = out.merge(attrs[["item_id", "sku", "category", "price"]], on="item_id", how="left")
    out = out.rename(columns={"price": "unit_price"})
    out["is_real"] = False
    return out


def stitch(cfg: Config, rng: np.random.Generator, backfill: pd.DataFrame,
           real: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Section 3: financials + artifacts on the backfill; real rows pass through.

    B2: every artifact is recorded. A dropped (lost) POS line is returned
    separately; a double-logged line is appended as a flagged copy of its
    original; a label typo keeps the label it replaced."""
    b = backfill.copy()
    n = len(b)

    b["gross_sales"] = (b["unit_price"] * b["quantity_sold"]).round(2)
    disc_hit = rng.random(n) < cfg.p_discount
    disc_frac = rng.beta(cfg.disc_beta_a, cfg.disc_beta_b, n)
    b["discount"] = (disc_hit * disc_frac * b["gross_sales"]).round(2)

    comp = b["category"].astype(str).str.upper() == "MANAGEMENT"
    b.loc[comp, "discount"] = b.loc[comp, "gross_sales"]
    b["net_sales"] = (b["gross_sales"] - b["discount"]).round(2)
    # A3: the same rule as the real SALES'26 lines
    b["is_complimentary"] = comp | (b["net_sales"] <= 0)

    tax_hit = rng.random(n) < cfg.p_tax_nonzero
    b["taxes"] = np.where(tax_hit, (b["net_sales"] * 0.12).round(2), 0.0)

    sales = pd.concat([b, real], ignore_index=True, sort=False)
    sales = sales.sort_values(["date", "item_id"]).reset_index(drop=True)

    # --- logging artifacts (7.9 / 10) - applied to synthetic rows only ---------
    syn = ~sales["is_real"].to_numpy(dtype=bool)
    m = len(sales)

    typo = syn & (rng.random(m) < cfg.p_label_noise)
    before = sales["category"].copy()
    sales.loc[typo, "category"] = (
        sales.loc[typo, "category"].map(CATEGORY_TYPOS).fillna(
            sales.loc[typo, "category"]
        )
    )
    sales["_label_artifact"] = (sales["category"] != before).to_numpy()
    sales["_category_before"] = before.where(sales["_label_artifact"])

    drop = syn & (rng.random(m) < cfg.p_missing_row)
    dropped = sales[drop].copy()                       # sold, but missing from the POS export
    sales = sales[~drop].copy()

    syn2 = ~sales["is_real"].to_numpy(dtype=bool)
    dup = syn2 & (rng.random(len(sales)) < cfg.p_dup_row)
    sales["_orig_key"] = np.arange(len(sales))
    sales["_dup_copy"] = False
    copies = sales[dup].copy()
    copies["_dup_copy"] = True
    sales = pd.concat([sales, copies], ignore_index=True, sort=False)

    sales = sales.sort_values(["date", "item_id"]).reset_index(drop=True)
    sales["cost_of_goods"] = pd.NA            # real artifact: empty on 100% of rows
    sales["sale_id"] = np.arange(1, len(sales) + 1)
    orig_sid = sales.loc[~sales["_dup_copy"]].set_index("_orig_key")["sale_id"]
    sales["_duplicate_of"] = sales["_orig_key"].map(orig_sid).where(sales["_dup_copy"])
    return sales, dropped


def assign_channel(cfg: Config, rng: np.random.Generator, sales: pd.DataFrame,
                   latents: pd.DataFrame) -> pd.DataFrame:
    lat = latents.set_index("date")
    w = lat["w_t"].reindex(sales["date"]).to_numpy()
    age = (sales["date"] - pd.Timestamp(cfg.start)).dt.days.to_numpy()
    s_deliv = cfg.deliv_2021 * np.exp(-age / cfg.deliv_decay_days)
    z = cfg.deliv_alpha + cfg.deliv_beta_w * w + s_deliv
    p = 1 / (1 + np.exp(-z))
    is_deliv = rng.random(len(sales)) < p
    forced = (sales["category"].astype(str).str.upper()
              .str.replace(" ", "", regex=False).eq("GRABFOOD"))
    sales["channel"] = np.where(is_deliv | forced.to_numpy(), "GrabFood", "Dine-in")
    real = sales["is_real"].astype(bool).to_numpy()
    sales.loc[real, "channel"] = np.where(forced.to_numpy()[real], "GrabFood", "Dine-in")
    # A4: a complimentary MANAGEMENT line is a staff/owner meal, never a delivery
    mgmt = ~real & sales["category"].astype(str).str.upper().eq("MANAGEMENT").to_numpy()
    sales.loc[mgmt, "channel"] = "Dine-in"
    # A2/B1: a double-logged line is the same sale, so it carries its original's channel
    orig_ch = sales.loc[~sales["_dup_copy"]].set_index("_orig_key")["channel"]
    cp = sales["_dup_copy"].to_numpy(dtype=bool)
    sales.loc[cp, "channel"] = sales.loc[cp, "_orig_key"].map(orig_ch).to_numpy()
    return sales


# --------------------------------------------------------------------------
# Section 2 - seam validation gate (E3)
# --------------------------------------------------------------------------


def _ks_2samp(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    a = np.sort(np.asarray(a, dtype=float))
    b = np.sort(np.asarray(b, dtype=float))
    n, m = len(a), len(b)
    allv = np.concatenate([a, b])
    cdf_a = np.searchsorted(a, allv, side="right") / n
    cdf_b = np.searchsorted(b, allv, side="right") / m
    d = float(np.max(np.abs(cdf_a - cdf_b)))
    en = math.sqrt(n * m / (n + m))
    lam = (en + 0.12 + 0.11 / en) * d
    p = 2 * sum((-1) ** (k - 1) * math.exp(-2 * k * k * lam * lam)
                for k in range(1, 101))
    return d, float(min(max(p, 0.0), 1.0))


def seam_report(cfg: Config, sales: pd.DataFrame) -> dict:
    _, seam = _dates(cfg)
    daily = sales.groupby("date", as_index=False)["net_sales"].sum()
    pre = daily[(daily["date"] >= seam - pd.Timedelta(days=30)) &
                (daily["date"] < seam)]["net_sales"].to_numpy()
    post = daily[(daily["date"] >= seam) &
                 (daily["date"] < seam + pd.Timedelta(days=31))]["net_sales"].to_numpy()
    d, p = _ks_2samp(pre, post)

    s = sales.copy()
    s["dow"] = s["date"].dt.dayofweek
    pre_dow = (s[s["date"] < seam].groupby(["date", "dow"])["net_sales"].sum()
               .groupby("dow").mean())
    post_dow = (s[s["date"] >= seam].groupby(["date", "dow"])["net_sales"].sum()
                .groupby("dow").mean())
    corr = float(np.corrcoef(pre_dow / pre_dow.mean(), post_dow / post_dow.mean())[0, 1])

    return {
        "ks_D": round(d, 4),
        "ks_p": round(p, 4),
        "pass": bool(p > 0.05),
        "nov25_mean_net": round(float(pre.mean()), 2),
        "dec25_mean_net": round(float(post.mean()), 2),
        "dow_profile_corr": round(corr, 4),
    }


# --------------------------------------------------------------------------
# Section 4 - consumption (7.6) + inventory ledger (7.7)
# --------------------------------------------------------------------------


def build_consumption(sales: pd.DataFrame, dropped: pd.DataFrame, bom: pd.DataFrame,
                      closed: set) -> pd.DataFrame:
    """What the kitchen actually used.

    Recorded sales that happened (no double-log copies, no closure-day lines)
    plus the lines the POS export lost (B2: those dishes were cooked). Real
    SALES'26 lines are all recorded sales."""
    happened = sales.loc[~sales["_dup_copy"] & ~sales["_closure_adjusted"],
                         ["date", "item_id", "quantity_sold"]]
    lost = dropped.loc[~dropped["date"].isin(closed), ["date", "item_id", "quantity_sold"]]
    j = pd.concat([happened, lost], ignore_index=True).merge(
        bom[["item_id", "ingredient_id", "qty_base"]], on="item_id", how="inner"
    )
    j["qty"] = j["quantity_sold"] * j["qty_base"]
    return j.groupby(["date", "ingredient_id"], as_index=False)["qty"].sum()


def simulate_inventory(cfg: Config, rng: np.random.Generator, cons: pd.DataFrame,
                       ing: pd.DataFrame, sup: pd.DataFrame, terms: pd.DataFrame,
                       latents: pd.DataFrame, closed=frozenset()) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(R,s,S) ordering + manager-bias distortion + FIFO batches + expiry.
    `closed`: dates the restaurant is shut - no order is placed and nothing is delivered
    on them (a delivery due that day moves to the supplier's next delivery day)."""
    idx, _ = _dates(cfg)
    closed_t = {i for i, d in enumerate(idx) if d in closed}
    ing = ing.reset_index(drop=True)
    gids = ing["ingredient_id"].to_numpy()
    ng = len(gids)

    demand = (cons.pivot_table(index="date", columns="ingredient_id", values="qty",
                               aggfunc="sum")
              .reindex(idx).reindex(columns=gids).fillna(0.0).to_numpy())

    # opt-in: off-POS use = ratio x the month's POS use, spread evenly over the month's open days
    if cfg.off_pos_use_ratio or cfg.off_pos_use_daily:
        demand = demand.copy()
    is_open = np.array([t not in closed_t for t in range(len(idx))])
    for c, per_day in cfg.off_pos_use_daily.items():
        k = int(np.flatnonzero(ing["ingredient_code"].to_numpy() == c)[0])
        demand[is_open, k] += per_day
    for c, ratio in cfg.off_pos_use_ratio.items():
        k = int(np.flatnonzero(ing["ingredient_code"].to_numpy() == c)[0])
        month = idx.to_period("M")
        for mo in month.unique():
            sel = (month == mo) & is_open
            if sel.any():
                demand[sel, k] += ratio * demand[month == mo, k].sum() / sel.sum()

    shelf = ing["shelf_life_days"].to_numpy(dtype=float)
    life = np.maximum(ing["shelf_life_days"].to_numpy(dtype=int), 1)   # usable days, receipt day = day 1
    cost = ing["unit_cost"].to_numpy(dtype=float)
    count_unit = ing["uom"].isin(["pc", "serving"]).to_numpy()
    t_of = terms.set_index("ingredient_id").reindex(gids)
    if t_of["supplier_id"].isna().any():
        raise ValueError("ingredient without supplier_item_terms")
    pack = t_of["pack_size_base"].to_numpy(dtype=float)
    fresh = (ing["is_perishable"].to_numpy(dtype=bool)) & (shelf <= 7)
    review_n = np.where(fresh, cfg.review_fresh_days, cfg.review_dry_days)

    sup_of = {int(g): int(t_of.loc[g, "supplier_id"]) for g in gids}
    sup_idx = sup.set_index("supplier_id")
    per_ing = lambda col: np.array([sup_idx.loc[sup_of[int(g)], col] for g in gids], dtype=float)
    perish = ing["is_perishable"].to_numpy(dtype=bool)
    # Three separate supplier/kitchen concepts, never collapsed into one:
    #   review_n  - how often the kitchen reviews the item (fresh daily, dry weekly)
    #   interval  - how often the supplier delivers (delivery_interval_days)
    #   lt_nom    - order-to-receipt days (lead_time_days, >= 1 - B5)
    lt_mean = per_ing("lead_time_days")
    lt_nom = np.maximum(1, np.round(lt_mean)).astype(int)
    lt_sd = per_ing("lead_time_sd_days")
    fill = per_ing("fill_rate")
    interval = per_ing("delivery_interval_days").astype(int)
    offset = np.array([sup_of[int(g)] for g in gids]) % np.maximum(interval, 1)
    moq_base = t_of["min_order_packs"].to_numpy(dtype=float) * pack
    whole_k = {k for k, c in enumerate(ing["ingredient_code"]) if c in cfg.whole_unit_emergency}
    walk_in = set(cfg.walk_in_suppliers)
    replace_k = sorted(k for k, c in enumerate(ing["ingredient_code"]) if c in cfg.planned_replacement)

    def delivery_day(t: int, k: int) -> bool:
        return (t - offset[k]) % interval[k] == 0 and t not in closed_t

    def arrival_day(ti_order: int, lt: int, k: int) -> int:
        """First supplier delivery day on or after order day + lead time."""
        t = ti_order + lt
        while not delivery_day(t, k):
            t += 1
        return t

    def order_day(ti: int, k: int) -> bool:
        """B5: an order placed today is due exactly lead_time_days later, on a delivery day."""
        return ti not in closed_t and delivery_day(ti + lt_nom[k], k)

    lat = latents.set_index("date").reindex(idx)
    w_all = lat["w_t"].to_numpy()
    m_all = lat["m_t"].to_numpy()

    # warm start: one review cycle of demand on hand (received on day 0)
    warm = np.maximum(demand[:28].mean(axis=0), 0.0)
    batches: dict[int, list[dict]] = {k: [] for k in range(ng)}
    next_batch_id = 1
    for k in range(ng):
        if warm[k] <= 0:
            continue
        q = float(np.ceil(max(warm[k] * review_n[k] * 1.5, pack[k]) / pack[k]) * pack[k])
        batches[k].append(
            {"id": next_batch_id, "qty": q, "recv": idx[0], "cost": cost[k],
             "sup": sup_of[int(gids[k])],
             "exp": idx[0] + pd.Timedelta(days=int(life[k]) - 1)}     # A1/B4: last usable day
        )
        next_batch_id += 1

    pipeline: dict[int, list[tuple[int, float, float, int, float]]] = {}
    on_order = np.zeros(ng)
    next_review = np.zeros(ng, dtype=int)     # first day the item may be reviewed again
    since_recv = np.zeros(ng)                 # A6: demand since the last delivery (day 0 counts as one)
    inv_rows, waste_rows, batch_rows = [], [], []
    waste_id = 1

    def _fifo_draw(k: int, want: float) -> float:
        """Pull `want` from ingredient k's usable batches, earliest received first."""
        batches[k].sort(key=lambda b: (b["recv"], b["id"]))
        taken = 0.0
        for b in batches[k]:
            if want <= 1e-9:
                break
            t_ = min(b["qty"], want)
            b["qty"] -= t_
            want -= t_
            taken += t_
        batches[k] = [b for b in batches[k] if b["qty"] > 1e-9]
        return taken

    for ti, day in enumerate(idx):
        w_t, m_t = w_all[ti], m_all[ti]
        opening = np.array([sum(b["qty"] for b in batches[k]) for k in range(ng)])

        # --- receipts (start of day) ----------------------------------------
        received = np.zeros(ng)
        for k, ordered, qty, sid, ucost in pipeline.pop(ti, []):
            batches[k].append(
                {"id": next_batch_id, "qty": qty, "recv": day, "cost": ucost,
                 "sup": sid, "exp": day + pd.Timedelta(days=int(life[k]) - 1)}
            )
            next_batch_id += 1
            received[k] += qty
            # a short delivery closes the PO too
            on_order[k] = max(0.0, on_order[k] - ordered)
        since_recv[received > 0] = 0.0

        # --- A1/B4: bin expired batches before anything is drawn -------------
        wasted = np.zeros(ng)
        prev = demand[max(0, ti - 28): ti, :]
        mean_prev = prev.mean(axis=0) if len(prev) else np.zeros(ng)
        for k in range(ng):
            expired = [b for b in batches[k] if day > b["exp"]]
            if not expired:
                continue
            on_hand = sum(x["qty"] for x in batches[k])
            reason = "overstock" if on_hand > 3 * max(mean_prev[k], 1e-6) else "expiry"
            for b in expired:
                wasted[k] += b["qty"]
                waste_rows.append(
                    {"waste_id": waste_id, "date": day,
                     "ingredient_id": int(gids[k]), "supplier_id": b["sup"],
                     "batch_id": b["id"], "waste_quantity": round(b["qty"], 4),
                     "waste_reason": reason, "unit_cost": b["cost"],
                     "received_date": b["recv"], "expiry_date": b["exp"],
                     "days_held": int((day - b["recv"]).days)}
                )
                waste_id += 1
            batches[k] = [b for b in batches[k] if day <= b["exp"]]

        # --- consumption, FIFO over usable batches ----------------------------
        need = demand[ti].copy()
        consumed = np.zeros(ng)
        stockout = np.zeros(ng, dtype=bool)
        emergency = np.zeros(ng)
        for k in range(ng):
            if need[k] <= 0:
                continue
            consumed[k] = _fifo_draw(k, need[k])
            if consumed[k] < need[k] - 1e-6:
                stockout[k] = True                          # planned stock ran out ...
                if k in whole_k:
                    # ... so buy whole packs today; the rest goes into stock like any delivery
                    n = math.ceil((need[k] - consumed[k]) / pack[k] - 1e-9)
                    batches[k].append(
                        {"id": next_batch_id, "qty": n * pack[k], "recv": day, "cost": cost[k],
                         "sup": sup_of[int(gids[k])], "exp": day + pd.Timedelta(days=int(life[k]) - 1)}
                    )
                    next_batch_id += 1
                    emergency[k] = n * pack[k]
                    consumed[k] += _fifo_draw(k, need[k] - consumed[k])
                    continue
                emergency[k] = need[k] - consumed[k]        # ... so buy the gap today
                consumed[k] = need[k]                       # and it is used at once
        since_recv += need

        closing = np.array([sum(b["qty"] for b in batches[k]) for k in range(ng)])

        # --- end-of-day batch stock: what is on the shelf and when it expires
        for k in range(ng):
            for b in batches[k]:
                if b["qty"] > 1e-9:
                    batch_rows.append((day, b["id"], int(gids[k]), b["sup"], b["recv"],
                                       b["exp"], round(b["qty"], 4), b["cost"]))

        # --- review & order: (R,s,S) with manager-bias distortion ------------
        mean_dem = demand[max(0, ti - 27): ti + 1, :].mean(axis=0)
        mu = np.maximum(mean_dem, 0.0)
        sd = demand[max(0, ti - 27): ti + 1, :].std(axis=0)
        gap = np.maximum(review_n, interval)
        prot = lt_mean + gap
        mu_ltd = mu * prot
        sd_ltd = np.sqrt(np.maximum(prot, 1) * sd ** 2 + (mu * lt_sd) ** 2)
        s_lvl = mu_ltd + cfg.service_z * sd_ltd
        S_lvl = s_lvl + mu * gap
        cap_days = lt_mean + np.maximum(np.maximum(shelf, 1.0) * cfg.perish_cover_frac,
                                        np.minimum(gap, np.maximum(shelf, 1.0)) + cfg.cover_floor_days)
        S_lvl = np.where(perish, np.minimum(S_lvl, mu * cap_days), S_lvl)
        s_lvl = np.minimum(s_lvl, S_lvl)
        position = closing + on_order

        sparse = perish & (mu * np.maximum(shelf, 1.0) < cfg.sparse_pack_frac * pack)

        order_qty = np.zeros(ng)
        # I20 (opt-in): when today is the last order day whose delivery arrives by the morning after a pack's
        # last usable day (closure days take no orders or deliveries, so before a closure the last chance comes
        # earlier) and the stock left after that pack is below the reorder point, plan one pack (no RNG draw of
        # its own; a regular order it pre-empts skips its draws, so later random draws of other items shift)
        for k in replace_k:
            if not order_day(ti, k) or on_order[k] > 1e-9:
                continue
            arr = ti + int(lt_nom[k])
            if arr >= len(idx):
                continue
            nxt = next((t for t in range(ti + 1, len(idx) - int(lt_nom[k])) if order_day(t, k)), None)
            if nxt is None:
                continue
            first_day = idx[arr] - pd.Timedelta(days=1)                       # expiring today-arrival eve ...
            last_day = idx[nxt + int(lt_nom[k])] - pd.Timedelta(days=2)       # ... up to the next chance's
            keep = sum(b["qty"] for b in batches[k] if b["exp"] > last_day)
            if any(first_day <= b["exp"] <= last_day for b in batches[k]) and keep - mu[k] * lt_nom[k] <= s_lvl[k]:
                q = float(pack[k])
                order_qty[k] = q
                on_order[k] += q
                pipeline.setdefault(arr, []).append((k, q, q, sup_of[int(gids[k])], round(cost[k], 4)))
        for k in range(ng):
            if not order_day(ti, k):                        # B5
                continue
            if sparse[k]:
                # A6: re-buy a slow perishable only if it was wanted since the last delivery
                if since_recv[k] > 1e-9 and position[k] <= 1e-6:
                    q = float(np.ceil(max(pack[k], moq_base[k]) / pack[k]) * pack[k])
                    order_qty[k] = q
                    on_order[k] += q
                    pipeline.setdefault(arrival_day(ti, int(lt_nom[k]), k), []).append(
                        (k, q, q, sup_of[int(gids[k])], round(cost[k], 4))
                    )
                continue
            if ti < next_review[k]:
                continue
            # keep the review on its own grid (weekly stays weekly on average)
            next_review[k] = max(next_review[k] + review_n[k], ti + 1)
            # no usage in the last 28 days => nothing to replenish
            if mu[k] <= 0 or position[k] > s_lvl[k]:
                continue
            raw_q = max(S_lvl[k] - position[k], 0.0) * (1 + m_t)
            q = float(np.ceil(max(raw_q, moq_base[k]) / pack[k]) * pack[k])
            if q <= 0:
                continue
            order_qty[k] = q
            on_order[k] += q
            # late deliveries come from the supplier's own variability
            # (lead_time_sd_days, weather); never earlier than lead_time_days
            lt = int(max(lt_nom[k], round(lt_mean[k] * (1 + cfg.lead_weather_kappa * w_t)
                                          + rng.normal(0, lt_sd[k]))))
            got = q if rng.random() < fill[k] else q * rng.uniform(0.60, 0.95)
            if count_unit[k] and got < q:
                got = max(1.0, float(np.floor(got)))            # A5: whole pieces / servings
            ucost = cost[k] * rng.uniform(0.94, 1.08)          # SUPPLY-UR fluctuation %
            pipeline.setdefault(arrival_day(ti, lt, k), []).append(
                (k, q, got, sup_of[int(gids[k])], round(ucost, 4))
            )

        for k in range(ng):
            inv_rows.append(
                (day, int(gids[k]), sup_of[int(gids[k])], round(opening[k], 4),
                 round(received[k], 4), round(emergency[k], 4), round(consumed[k], 4),
                 round(wasted[k], 4), round(closing[k], 4), round(s_lvl[k], 4),
                 round(order_qty[k], 4), round(on_order[k], 4), bool(stockout[k]),
                 round(emergency[k] * cost[k] * (1 + (cfg.whole_unit_emergency_premium if k in whole_k
                                                      else 0.0 if sup_of[int(gids[k])] in walk_in
                                                      else cfg.emergency_premium)), 2))
            )

    inv = pd.DataFrame(
        inv_rows,
        columns=["inventory_date", "ingredient_id", "supplier_id", "opening_stock",
                 "qty_received", "qty_emergency", "qty_consumed", "qty_wasted",
                 "closing_stock", "reorder_level", "order_qty", "on_order_qty",
                 "stockout_flag", "emergency_cost_php"],
    )

    waste = pd.DataFrame(waste_rows)
    if len(waste):
        waste = waste.rename(columns={"date": "waste_date"})
        waste = waste.merge(ing[["ingredient_id", "uom"]], on="ingredient_id", how="left")
        waste["waste_value_php"] = (waste["waste_quantity"] * waste["unit_cost"]).round(2)
        waste = waste[
            ["waste_id", "waste_date", "ingredient_id", "supplier_id", "batch_id",
             "waste_quantity", "uom", "waste_reason", "unit_cost",
             "waste_value_php", "received_date", "expiry_date", "days_held"]
        ]

    bat = pd.DataFrame(batch_rows, columns=["snapshot_date", "batch_id", "ingredient_id",
                                            "supplier_id", "received_date", "expiry_date",
                                            "qty_on_hand", "unit_cost"])
    # 0 = last usable day (the batch is binned the next morning, before any use)
    bat["days_to_expiry"] = (bat["expiry_date"] - bat["snapshot_date"]).dt.days
    return inv, waste, bat


# --------------------------------------------------------------------------
# Section 6 - export
# --------------------------------------------------------------------------


def export(cfg: Config, tables: dict) -> None:
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_csv(cfg.out_dir / f"{name}.csv", index=False)
        if cfg.write_parquet:
            df.to_parquet(cfg.out_dir / f"{name}.parquet", index=False)   # A8: fail loudly


# sales.csv columns. The first 19 are v1's (each SALES'26 column plus keys and
# flags); v2 adds lineage and artifact columns after them.
SALES_COLUMNS = ["sale_id", "sale_date", "item_id", "item_name", "sku", "category",
                 "quantity_sold", "gross_sales", "items_refunded", "refunds", "discount",
                 "net_sales", "cost_of_goods", "gross_profit", "margin", "taxes",
                 "unit_price", "channel", "is_complimentary"]
LINEAGE_COLUMNS = ["data_source", "source_row", "is_duplicate_artifact", "duplicate_of_sale_id",
                   "is_label_artifact", "is_closure_adjusted", "include_in_fact", "adjustment_reason"]
SHEET_TO_SALES = {"DATE": "sale_date", "Item name": "item_name", "SKU": "sku",
                  "Category": "category", "Items sold": "quantity_sold",
                  "Gross sales": "gross_sales", "Items refunded": "items_refunded",
                  "Refunds": "refunds", "Discounts": "discount", "Net sales": "net_sales",
                  "Cost of goods": "cost_of_goods", "Gross profit": "gross_profit",
                  "Margin": "margin", "Taxes": "taxes"}


def _reason(row, closures: dict) -> str:
    parts = []
    if row["_dup_copy"]:
        parts.append(f"duplicate POS log of sale_id {int(row['_duplicate_of'])} (same sale recorded twice); "
                     "kept here, excluded from facts and consumption")
    if row["_closure_adjusted"]:
        parts.append(f"restaurant closed - {closures[row['date']]}; synthetic sale excluded from facts and consumption")
    if row["_label_artifact"]:
        parts.append(f"category label typo (was '{row['_category_before']}'); kept, resolved by the category alias table")
    return "; ".join(parts)


def synthetic_sales_rows(sales: pd.DataFrame, menu: pd.DataFrame, closures: dict) -> pd.DataFrame:
    """Backfill lines, filled in the POS's own way, plus v2 lineage/artifact flags."""
    s = sales.loc[~sales["is_real"].astype(bool)].copy()
    s["item_name"] = s["item_id"].map(menu.set_index("item_id")["item_name"])
    s["items_refunded"], s["refunds"], s["cost_of_goods"] = 0, 0, 0
    s["gross_profit"] = s["net_sales"]
    s["margin"] = (s["net_sales"] > 0).astype(int)
    s["sku"] = s["sku"].map(lambda v: str(int(v)) if pd.notna(v) else "")
    s["data_source"] = "synthetic_backfill"
    s["source_row"] = pd.array([pd.NA] * len(s), dtype="Int64")
    s["is_duplicate_artifact"] = s["_dup_copy"].astype(bool)
    s["duplicate_of_sale_id"] = s["_duplicate_of"].astype("Int64")
    s["is_label_artifact"] = s["_label_artifact"].astype(bool)
    s["is_closure_adjusted"] = s["_closure_adjusted"].astype(bool)
    s["include_in_fact"] = ~(s["is_duplicate_artifact"] | s["is_closure_adjusted"])
    s["adjustment_reason"] = s.apply(_reason, axis=1, closures=closures)
    s["sale_date"] = s["date"].dt.date
    return s[SALES_COLUMNS + LINEAGE_COLUMNS]


def real_sales_rows(cfg: Config, menu: pd.DataFrame, first_id: int) -> pd.DataFrame:
    """SALES'26 line for line, in sheet order, every value exactly as recorded."""
    raw = pd.read_excel(cfg.src_dir / cfg.sales_file, sheet_name=cfg.sales_sheet,
                        dtype={"SKU": str})
    r = raw.rename(columns=SHEET_TO_SALES)
    ids = menu.drop_duplicates("item_name").set_index("item_name")["item_id"]
    r["item_id"] = r["item_name"].map(ids)
    if r["item_id"].isna().any():
        raise ValueError("SALES'26 items missing from the menu: "
                         f"{sorted(r.loc[r['item_id'].isna(), 'item_name'].unique())[:5]}")
    r["item_id"] = r["item_id"].astype(int)
    r["sale_date"] = pd.to_datetime(r["sale_date"]).dt.date
    r["sale_id"] = first_id + np.arange(len(r))
    r["unit_price"] = np.where(r["quantity_sold"] > 0,
                               r["gross_sales"] / r["quantity_sold"].where(r["quantity_sold"] > 0, 1),
                               0.0)
    cat = r["category"].astype(str).str.upper()
    r["channel"] = np.where(cat.str.replace(" ", "", regex=False).eq("GRABFOOD"),
                            "GrabFood", "Dine-in")
    r["is_complimentary"] = cat.eq("MANAGEMENT") | (r["net_sales"] <= 0)
    r["data_source"] = "real_pos"
    r["source_row"] = pd.array(np.arange(2, len(r) + 2), dtype="Int64")   # SALES'26 sheet row
    r["is_duplicate_artifact"] = False
    r["duplicate_of_sale_id"] = pd.array([pd.NA] * len(r), dtype="Int64")
    r["is_label_artifact"] = False
    r["is_closure_adjusted"] = False
    r["include_in_fact"] = True
    r["adjustment_reason"] = ""
    return r[SALES_COLUMNS + LINEAGE_COLUMNS]


def artifact_log(sales_out: pd.DataFrame, sales: pd.DataFrame, dropped: pd.DataFrame,
                 closures: dict) -> pd.DataFrame:
    """B2: one row per artifact or adjustment, including POS lines the export lost."""
    rows = []
    syn = sales_out[sales_out["data_source"] == "synthetic_backfill"]
    before = sales.set_index("sale_id")["_category_before"]
    for r in syn[syn["is_duplicate_artifact"]].itertuples():
        rows.append(("duplicate_pos_line", r.sale_date, r.item_id, r.sale_id, r.duplicate_of_sale_id,
                     r.quantity_sold, r.net_sales, r.category, None, True, False, False,
                     "same sale logged twice; the copy is not demand"))
    for r in syn[syn["is_label_artifact"]].itertuples():
        rows.append(("category_label_typo", r.sale_date, r.item_id, r.sale_id, None,
                     r.quantity_sold, r.net_sales, r.category, before.get(r.sale_id), True,
                     bool(r.include_in_fact), bool(r.include_in_fact),
                     "real demand under a mistyped label; resolved by the category alias table"))
    for r in syn[syn["is_closure_adjusted"]].itertuples():
        rows.append(("closure_day_adjustment", r.sale_date, r.item_id, r.sale_id, None,
                     r.quantity_sold, r.net_sales, r.category, None, True, False, False,
                     closures[pd.Timestamp(r.sale_date)]))
    for r in dropped.itertuples():
        on_closed = r.date in closures
        rows.append(("dropped_pos_line", r.date.date(), r.item_id, None, None,
                     r.quantity_sold, r.net_sales, r.category, None, False, False, not on_closed,
                     "sold but missing from the POS export (simulated logging gap); ingredients consumed"
                     if not on_closed else "lost line on a closure day; no demand, no consumption"))
    log = pd.DataFrame(rows, columns=["artifact_type", "sale_date", "item_id", "sale_id", "related_sale_id",
                                      "quantity_sold", "net_sales", "category_recorded", "category_original",
                                      "in_pos_export", "in_analytical_fact", "in_consumption", "detail"])
    log = log.sort_values(["sale_date", "artifact_type", "item_id"]).reset_index(drop=True)
    log.insert(0, "artifact_id", np.arange(1, len(log) + 1))
    for c in ("sale_id", "related_sale_id"):
        log[c] = log[c].astype("Int64")
    return log


def calendar_rows(cfg: Config, cal: pd.DataFrame, closures: dict) -> pd.DataFrame:
    c = cal.drop(columns="date_id").copy()
    iso = c["date"].dt.isocalendar()
    c["iso_year"] = iso["year"].astype(int)                       # A9: week belongs to this year
    c["week_start_date"] = (c["date"] - pd.to_timedelta(c["dow"], unit="D")).dt.date
    c["is_open"] = ~c["date"].isin(set(closures))                 # B3
    c["closure_basis"] = c["date"].map(closures).fillna("")
    c["forecast_split"] = np.where(c["date"] >= forecast_test_start(cfg), "test", "train")   # B6
    return c


def run(cfg: Config | None = None) -> dict:
    cfg = cfg or Config()
    rng = np.random.default_rng(cfg.seed)
    dims = load_dimensions(cfg)
    sup, terms = dims["suppliers"], dims["terms"]
    # B5: lead_time_days counts calendar days from order to receipt; an external
    # supplier cannot deliver an order on the day it is placed
    sup["lead_time_days"] = sup["lead_time_days"].clip(lower=1)
    for name, cols in cfg.supplier_override.items():
        hit = sup["supplier_name"] == name
        if not hit.any():
            raise ValueError(f"unknown supplier in override: {name}")
        for col, value in cols.items():
            sup.loc[hit, col] = value
    code_id = dict(zip(dims["ingredients"]["ingredient_code"], dims["ingredients"]["ingredient_id"]))
    for code, cols in cfg.terms_override.items():
        hit = terms["ingredient_id"] == code_id[code]
        for col, value in cols.items():
            terms.loc[hit, col] = value

    real = load_real_sales(cfg, dims["menu"])
    t_start = forecast_test_start(cfg)
    real_calib = real[real["date"] < t_start]                     # B6: never the test period
    latents = draw_latents(cfg, rng)
    tf = build_time_factors(cfg, dims["calendar"], real_calib)
    base = calibrate_base(cfg, real_calib, dims["menu"], tf, t_start)
    attrs = calibration_attributes(real_calib)

    backfill = build_backfill(cfg, rng, dims["menu"], base, tf, latents, attrs)
    sales, dropped = stitch(cfg, rng, backfill, real)
    sales = assign_channel(cfg, rng, sales, latents)

    closures = closure_calendar(cfg, real)
    closed = set(closures)
    sales["_closure_adjusted"] = (~sales["is_real"].astype(bool) & sales["date"].isin(closed)).to_numpy()

    fact_view = sales[~sales["_dup_copy"] & ~sales["_closure_adjusted"]]
    report = seam_report(cfg, fact_view)
    print("seam gate (E3):", report)
    if not report["pass"]:
        print("  WARNING: KS gate not passed at p>0.05 - reported as is (no re-tuning).")

    cons = build_consumption(sales, dropped, dims["bom"], closed)
    if cfg.inventory_seed is not None:
        rng = np.random.default_rng(cfg.inventory_seed)
    inv, waste, batches = simulate_inventory(cfg, rng, cons, dims["ingredients"],
                                             sup, terms, latents,
                                             closed=closed if cfg.remove_closure_days else frozenset())

    syn_out = synthetic_sales_rows(sales, dims["menu"], closures)
    real_out = real_sales_rows(cfg, dims["menu"], first_id=int(syn_out["sale_id"].max()) + 1)
    sales_out = pd.concat([syn_out, real_out], ignore_index=True)
    sales_out["sku"] = sales_out["sku"].astype(str)

    ing_out = dims["ingredients"][
        ["ingredient_id", "ingredient_code", "ingredient_name", "category",
         "storage_type", "uom", "shelf_life_days", "is_perishable",
         "unit_cost", "catalog_unit_cost", "menu2_codes"]
    ]
    menu_out = dims["menu"][
        ["item_id", "sku", "item_name", "display_name", "category", "price",
         "printed_menu_price", "is_promo", "is_complimentary", "is_active"]
    ]
    recipes = (dims["bom"].rename(columns={"qty_base": "qty_per_item"})
               .merge(ing_out[["ingredient_id", "uom"]], on="ingredient_id", how="left")
               .sort_values(["item_id", "ingredient_id"]))
    recipes = recipes[["item_id", "ingredient_id", "ingredient_code", "qty_per_item",
                       "uom", "derivation"]]

    for t in (inv, batches, waste):
        t["data_source"] = "simulated"                             # A9: lineage on the fact itself
    sup_out = sup.assign(is_synthetic=True)                        # A9
    terms_out = terms.assign(is_synthetic=True)

    tables = {
        "sales": sales_out,
        "sales_artifact_log": artifact_log(sales_out, sales, dropped, closures),
        "inventory": inv,
        "inventory_batches": batches,
        "waste": waste,
        "suppliers": sup_out,
        "supplier_item_terms": terms_out,
        "menu_items": menu_out,
        "ingredients": ing_out,
        "recipes": recipes,
        "recipe_review": dims["recipe_review"],   # for the owner; not loaded
        "calendar": calendar_rows(cfg, dims["calendar"], closures),
    }
    if cfg.remove_closure_days:
        # closure-day synthetic lines leave the dataset entirely (kept aside as a record)
        s_ = tables["sales"]
        on_closed = s_["is_closure_adjusted"].astype(bool)
        tables["closure_day_sales_removed"] = s_[on_closed].reset_index(drop=True)
        s_ = s_[~on_closed].reset_index(drop=True)
        # keep sale_id contiguous: renumber and remap every reference to it
        new_id = dict(zip(s_["sale_id"], np.arange(1, len(s_) + 1)))
        s_["sale_id"] = s_["sale_id"].map(new_id)
        s_["duplicate_of_sale_id"] = s_["duplicate_of_sale_id"].map(new_id).astype("Int64")
        tables["sales"] = s_
        log = tables["sales_artifact_log"]
        keep = ~pd.to_datetime(log["sale_date"]).isin(closed)
        log = log[keep].reset_index(drop=True)
        for c in ("sale_id", "related_sale_id"):
            log[c] = log[c].map(new_id).astype("Int64")
        log["artifact_id"] = np.arange(1, len(log) + 1)
        tables["sales_artifact_log"] = log
        # Expiry during closure: shelf life still runs while the restaurant is shut.
        #   expiry_date     = last usable day (unchanged, B4)
        #   expired_on_date = day the batch became unusable = expiry_date + 1; it leaves
        #                     usable stock that day (inventory.qty_wasted is booked then)
        #   waste_date      = day it is physically disposed of and recorded = the next
        #                     operating day when expired_on_date is a closure day
        w = tables["waste"]
        w.insert(w.columns.get_loc("expiry_date") + 1, "expired_on_date", w["waste_date"])
        open_days = np.array(sorted(set(pd.to_datetime(dims["calendar"]["date"])) - set(closed)), dtype="datetime64[ns]")
        during = w["expired_on_date"].isin(closed)
        nxt = open_days[np.searchsorted(open_days, w.loc[during, "expired_on_date"].to_numpy(dtype="datetime64[ns]"))]
        w.loc[during, "waste_date"] = pd.to_datetime(nxt)
        w.loc[during, "waste_reason"] = "EXPIRED_DURING_CLOSURE"
        w["days_held"] = (w["waste_date"] - w["received_date"]).dt.days
        tables["waste"] = w
    export(cfg, tables)
    validate(cfg, tables, report)
    return tables


def check_real_rows_match_sheet(cfg: Config, sales: pd.DataFrame) -> int:
    """Independent cell-by-cell check (openpyxl, not pandas) of every real line in
    sales.csv against SALES'26. Returns the number of cells compared."""
    import datetime
    import openpyxl
    ws = openpyxl.load_workbook(cfg.src_dir / cfg.sales_file, read_only=True,
                                data_only=True)[cfg.sales_sheet]
    rows = ws.iter_rows(values_only=True)
    header = next(rows)
    real = sales[sales["data_source"] == "real_pos"].sort_values("source_row").reset_index(drop=True)
    cells, sheet_row = 0, 1
    for sheet_row, values in enumerate(rows, start=2):
        if sheet_row - 2 >= len(real):
            raise ValueError(f"sales.csv has fewer real lines than SALES'26 ({len(real)})")
        line = real.loc[sheet_row - 2]
        if int(line["source_row"]) != sheet_row:
            raise ValueError(f"source_row {line['source_row']} is not sheet row {sheet_row}")
        for col, xv in zip(header, values):
            cv = line[SHEET_TO_SALES[col]]
            if isinstance(xv, datetime.datetime):
                ok = xv.date() == cv
            elif isinstance(xv, (int, float)):
                ok = pd.notna(cv) and abs(float(cv) - xv) < 1e-9
            elif xv is None:
                ok = pd.isna(cv)
            else:
                ok = str(xv) == str(cv)
            if not ok:
                raise ValueError(f"sales.csv differs from SALES'26 at sheet row {sheet_row}, "
                                 f"column {col!r}: sheet {xv!r} vs csv {cv!r}")
            cells += 1
    if len(real) != sheet_row - 1:
        raise ValueError(f"sales.csv has {len(real)} real lines, SALES'26 has {sheet_row - 1}")
    return cells


def validate(cfg: Config, t: dict, seam: dict) -> None:
    s, inv, w = t["sales"], t["inventory"], t["waste"]
    real_mask = s["data_source"] == "real_pos"
    syn, r = s[~real_mask], s[real_mask]
    if r["sale_id"].min() <= syn["sale_id"].max():
        raise ValueError("real SALES'26 lines must follow the synthetic lines")
    cells = check_real_rows_match_sheet(cfg, s)
    bal = (inv["opening_stock"] + inv["qty_received"] + inv["qty_emergency"]
           - inv["qty_consumed"] - inv["qty_wasted"] - inv["closing_stock"]).abs().max()
    cost = t["ingredients"].set_index("ingredient_id")["unit_cost"]
    used_php = (inv["qty_consumed"] * inv["ingredient_id"].map(cost)).sum()
    wpct = w["waste_value_php"].sum() / max(used_php + w["waste_value_php"].sum(), 1)
    fact = s[s["include_in_fact"]]
    print("\n--- validation report (v2) ---")
    print(f"sales.csv        {len(s):>9,} lines   in fact {len(fact):,}   "
          f"duplicate copies {int(s['is_duplicate_artifact'].sum())}   closure-day lines {int(s['is_closure_adjusted'].sum())}")
    print(f"  synthetic      {len(syn):>9,}   net PHP {syn.loc[syn['include_in_fact'], 'net_sales'].sum():,.2f} (in fact)")
    print(f"  real SALES'26  {len(r):>9,}   net PHP {r['net_sales'].sum():,.2f}   {cells:,} cells identical to the sheet")
    print(f"artifact log     {len(t['sales_artifact_log']):>9,} rows")
    print(f"inventory rows   {len(inv):>9,}   ledger max imbalance {bal:.6f}")
    print(f"waste rows       {len(w):>9,}   waste {wpct:.1%} of usage by value")
    print(f"waste value      PHP {w['waste_value_php'].sum():,.0f}")
    print(f"stockout rate    {inv['stockout_flag'].mean():.2%} of panel rows "
          f"(covered by emergency buys: PHP {inv['emergency_cost_php'].sum():,.0f})")
    print(f"batch snapshot   {len(t['inventory_batches']):>9,} rows")
    print(f"seam KS p        {seam['ks_p']}  pass={seam['pass']}")
    print(f"files written to {cfg.out_dir.resolve()}")


if __name__ == "__main__":
    run()
