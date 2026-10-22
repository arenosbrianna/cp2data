"""
Makisushi synthetic dataset generator - Sections 2-6 of MAKISUSHI_SPEC.md.

Section 1 (reference tables + cleaned recipes) is built in memory on every run by
``makisushi_generator.build_dimensions`` - keep makisushi_generator.py in the same
folder as this file. No intermediate CSVs are needed.

This module adds:
  Section 2  latent states + demand backfill + real-slice stitch + KS seam gate
  Section 3  sales financials, discounts/comps/taxes, logging artifacts
  Section 4  recipe disaggregation -> consumption -> (R,s,S) inventory ledger
  Section 5  per-batch FEFO spoilage -> waste event log
  Section 6  strip latents, export the 8 files, validation report

Golden rule: every number comes from math (numpy), never from an LLM.
Run:  python makisushi_datagen.py
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

import makisushi_generator as s1   # Section 1: reference tables (same folder)

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------


@dataclass
class Config:
    seed: int = 42
    start: str = "2021-01-01"
    seam: str = "2025-12-01"
    end: str = "2026-09-08"

    # folder holding the three Excel files - found automatically
    # (see SOURCE_DIR_CANDIDATES in makisushi_generator.py)
    src_dir: Path = field(default_factory=s1._find_src_dir)
    sales_file: str = "makisushi_Jan_2026.xlsx"
    sales_sheet: str = "SALES'26"
    out_dir: Path = Path("generated")     # relative paths resolve inside src_dir

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
    sigma_batch: float = 0.18             # LogNormal batch quality

    # 7.4 demand
    gamma_mu: float = 0.25                # sensitivity to area activity
    gamma_sd: float = 0.08
    delta_mu: float = 0.12                # sensitivity to bad weather
    delta_sd: float = 0.05
    eps_early_2021: float = 0.55          # day-level noise, wider in early years
    eps_early_2025: float = 0.40          # matches the real slice's daily CV ~0.45
    p_catering: float = 0.010             # heavy-tail platter days (max ~PHP 55k)
    tail_floor_frac: float = 0.20         # faint rate for items never sold in-window

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
    # sensitivity scenarios only; the baseline uses the synthetic supplier
    # tables as defined in Section 1.
    #   supplier_override: {supplier_name: {column: value}}, e.g.
    #       {"UMA'I JAPANESE GROCERY": {"lead_time_days": 3, "delivery_interval_days": 3}}
    #   terms_override: {ingredient_code: {column: value}}, e.g.
    #       {"SAL": {"pack_size": 1, "pack_unit": "kg", "pack_size_base": 1000}}
    supplier_override: dict = field(default_factory=dict)
    terms_override: dict = field(default_factory=dict)

    # 7.8 spoilage
    # waste is spoilage only (expiry / overstock); prep trim is not modelled, so
    # the kitchen draws exactly what the recipes call for
    shelf_weather_phi: float = 0.06
    sparse_pack_frac: float = 0.50        # below this, a line is bought to order
    perish_cover_frac: float = 0.70       # order-up-to cap, as a share of shelf
                                          # life: lower = less waste, worse service
    cover_floor_days: float = 0.5         # ...but never below lead time + this many
                                          # days, or 1-2 day lines can't cover a day
    # a dish that sold was cooked, so a shortfall is never a lost sale: the kitchen
    # buys the missing quantity the same day (market run) at a premium. That keeps
    # sales and ingredient usage consistent and gives the LP a shortage cost.
    emergency_premium: float = 0.25

    # scale knobs (8.8)
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


# --------------------------------------------------------------------------
# Section 1 outputs (fixed inputs)
# --------------------------------------------------------------------------


def load_dimensions(cfg: Config) -> dict:
    # Section 1 is built fresh in memory from the source Excel files every run,
    # so this always uses the CLEANED recipes (no duplicate or conflicting
    # recipe lines, median-imputed blanks). No intermediate CSVs are needed.
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

    # bom["qty_base"] is already in each raw ingredient's base unit (g / pc /
    # serving): Section 1 converts MENU2's portions, servings and vegetable
    # portions and records how in bom["derivation"]
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
# Section 2 - calendar / trend / weekly shape
# --------------------------------------------------------------------------


def build_time_factors(cfg: Config, calendar: pd.DataFrame,
                       real: pd.DataFrame) -> pd.DataFrame:
    idx, seam = _dates(cfg)
    cal = calendar.set_index("date").reindex(idx)

    span = (seam - pd.Timestamp(cfg.start)).days
    elapsed = (seam - idx).days.to_numpy().astype(float)
    trend = np.power(cfg.trend_2021, np.clip(elapsed, 0, None) / span)  # T(t*)=1

    # Wk(dow): recomputed from the real slice (8.3 gives the target values)
    r = real.copy()
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


def calibrate_base(cfg: Config, real: pd.DataFrame, menu: pd.DataFrame,
                   tf: pd.DataFrame) -> pd.DataFrame:
    """base_i such that the model reproduces the real slice's item mix at T=1."""
    _, seam = _dates(cfg)
    tf_real = tf[tf["date"] >= seam]
    exposure = float((tf_real["trend"] * tf_real["wk"] * tf_real["cal"]).sum())

    units = real.groupby("item_id")["quantity_sold"].sum()
    base = (units / exposure).rename("base_i").reset_index()

    out = menu[["item_id"]].merge(base, on="item_id", how="left")
    # items never sold in the real window still get a faint rate (long sparse tail)
    floor = float(base["base_i"].quantile(0.05)) * cfg.tail_floor_frac if len(base) else 1e-4
    out["base_i"] = out["base_i"].fillna(max(floor, 1e-5)) * cfg.volume_multiplier
    return out


# --------------------------------------------------------------------------
# Section 2 - demand backfill (7.4)
# --------------------------------------------------------------------------


def build_backfill(cfg: Config, rng: np.random.Generator, menu: pd.DataFrame,
                   base: pd.DataFrame, tf: pd.DataFrame,
                   latents: pd.DataFrame) -> pd.DataFrame:
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

    # log-lambda decomposition, items x days
    loglam = (
        np.log(b)[:, None]
        + np.log(day_f)[None, :]
        + gamma[:, None] * u[None, :]
        - delta[:, None] * w[None, :]
        + eps[None, :]
    )
    lam = np.exp(loglam) * active

    # catering blow-outs: a handful of items get a large platter draw (7.4)
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
    out = out.merge(
        items[["item_id", "sku", "category", "price"]], on="item_id", how="left"
    )
    out = out.rename(columns={"price": "unit_price"})
    out["is_real"] = False
    return out


def stitch(cfg: Config, rng: np.random.Generator, backfill: pd.DataFrame,
           real: pd.DataFrame) -> pd.DataFrame:
    """Section 3: financials + artifacts on the backfill; real rows pass through."""
    b = backfill.copy()
    n = len(b)

    b["gross_sales"] = (b["unit_price"] * b["quantity_sold"]).round(2)
    disc_hit = rng.random(n) < cfg.p_discount
    disc_frac = rng.beta(cfg.disc_beta_a, cfg.disc_beta_b, n)
    b["discount"] = (disc_hit * disc_frac * b["gross_sales"]).round(2)

    comp = b["category"].astype(str).str.upper() == "MANAGEMENT"
    b.loc[comp, "discount"] = b.loc[comp, "gross_sales"]
    b["is_complimentary"] = comp
    b["net_sales"] = (b["gross_sales"] - b["discount"]).round(2)

    tax_hit = rng.random(n) < cfg.p_tax_nonzero
    b["taxes"] = np.where(tax_hit, (b["net_sales"] * 0.12).round(2), 0.0)

    sales = pd.concat([b, real], ignore_index=True, sort=False)
    sales = sales.sort_values(["date", "item_id"]).reset_index(drop=True)

    # --- logging artifacts (7.9 / 10) - applied to synthetic rows only ---------
    syn = ~sales["is_real"].to_numpy(dtype=bool)
    m = len(sales)

    typo = syn & (rng.random(m) < cfg.p_label_noise)
    sales.loc[typo, "category"] = (
        sales.loc[typo, "category"].map(CATEGORY_TYPOS).fillna(
            sales.loc[typo, "category"]
        )
    )

    drop = syn & (rng.random(m) < cfg.p_missing_row)
    sales = sales[~drop].copy()

    syn2 = ~sales["is_real"].to_numpy(dtype=bool)
    dup = syn2 & (rng.random(len(sales)) < cfg.p_dup_row)
    sales = pd.concat([sales, sales[dup]], ignore_index=True, sort=False)

    sales = sales.sort_values(["date", "item_id"]).reset_index(drop=True)
    sales["cost_of_goods"] = pd.NA            # real artifact: empty on 100% of rows
    sales["sale_id"] = np.arange(1, len(sales) + 1)
    return sales


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
    # real SALES'26 lines are not simulated: the POS export has no channel column,
    # so it is read from the category (GRAB FOOD lines were GrabFood orders)
    real = sales["is_real"].astype(bool).to_numpy()
    sales.loc[real, "channel"] = np.where(forced.to_numpy()[real], "GrabFood", "Dine-in")
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


def build_consumption(sales: pd.DataFrame, bom: pd.DataFrame) -> pd.DataFrame:
    # a POS line logged twice (the duplicate-row artifact, synthetic rows only)
    # was cooked once; the real SALES'26 lines are never touched
    syn = ~sales["is_real"].astype(bool)
    cols = [c for c in sales.columns if c != "sale_id"]
    sales = pd.concat([sales[syn].drop_duplicates(subset=cols), sales[~syn]])
    j = sales[["date", "item_id", "quantity_sold"]].merge(
        bom[["item_id", "ingredient_id", "qty_base"]], on="item_id", how="inner"
    )
    j["qty"] = j["quantity_sold"] * j["qty_base"]
    return j.groupby(["date", "ingredient_id"], as_index=False)["qty"].sum()


def simulate_inventory(cfg: Config, rng: np.random.Generator, cons: pd.DataFrame,
                       ing: pd.DataFrame, sup: pd.DataFrame, terms: pd.DataFrame,
                       latents: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(R,s,S) ordering + manager-bias distortion + FEFO batches + spoilage."""
    idx, _ = _dates(cfg)
    # B1: every ingredient gets a row every day. Two codes (PB_120, TEM) appear in
    # no recipe line, so they simply sit at zero - the panel stays rectangular.
    ing = ing.reset_index(drop=True)
    gids = ing["ingredient_id"].to_numpy()
    ng = len(gids)

    demand = (cons.pivot_table(index="date", columns="ingredient_id", values="qty",
                               aggfunc="sum")
              .reindex(idx).reindex(columns=gids).fillna(0.0).to_numpy())

    shelf = ing["shelf_life_days"].to_numpy(dtype=float)
    cost = ing["unit_cost"].to_numpy(dtype=float)
    # pack and minimum order come from each ingredient's supplier_item_terms
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
    #   review_n  - how often the kitchen decides whether to order (fresh daily,
    #               dry weekly: the kitchen's own policy)
    #   interval  - how often the supplier delivers (delivery_interval_days);
    #               an order can only arrive on one of the supplier's delivery days
    #   lt_mean   - order-to-arrival delay (lead_time_days), kept as the supplier
    #               states it, even when it is long for a short-life ingredient
    lt_mean = per_ing("lead_time_days")
    lt_sd = per_ing("lead_time_sd_days")
    fill = per_ing("fill_rate")
    interval = per_ing("delivery_interval_days").astype(int)
    # each supplier delivers on its own fixed days (staggered by supplier_id)
    offset = np.array([sup_of[int(g)] for g in gids]) % np.maximum(interval, 1)
    # minimum order is counted in packs: MOQ in base units = packs x pack size
    moq_base = t_of["min_order_packs"].to_numpy(dtype=float) * pack

    def arrival_day(ti_order: int, lt: int, k: int) -> int:
        """First supplier delivery day on or after order day + lead time."""
        t = ti_order + lt
        while (t - offset[k]) % interval[k] != 0:
            t += 1
        return t

    lat = latents.set_index("date").reindex(idx)
    w_all = lat["w_t"].to_numpy()
    m_all = lat["m_t"].to_numpy()

    # warm start: one review cycle of demand on hand
    warm = np.maximum(demand[:28].mean(axis=0), 0.0)
    batches: dict[int, list[dict]] = {k: [] for k in range(ng)}   # FEFO queues
    next_batch_id = 1
    for k in range(ng):
        if warm[k] <= 0:                                   # never used: no opening stock
            continue
        q = float(np.ceil(max(warm[k] * review_n[k] * 1.5, pack[k]) / pack[k]) * pack[k])
        batches[k].append(
            {"id": next_batch_id, "qty": q, "recv": idx[0], "cost": cost[k],
             "sup": sup_of[int(gids[k])],
             "exp": idx[0] + pd.Timedelta(days=int(max(shelf[k], 1)))}
        )
        next_batch_id += 1

    pipeline: dict[int, list[tuple[int, float, int, float]]] = {}
    on_order = np.zeros(ng)
    inv_rows, waste_rows, batch_rows = [], [], []
    waste_id = 1

    for ti, day in enumerate(idx):
        w_t, m_t = w_all[ti], m_all[ti]
        opening = np.array([sum(b["qty"] for b in batches[k]) for k in range(ng)])

        # --- receipts ------------------------------------------------------
        received = np.zeros(ng)
        for k, ordered, qty, sid, ucost in pipeline.pop(ti, []):
            eff = max(1, int(round(shelf[k] * rng.lognormal(0.0, cfg.sigma_batch)
                                   * (1 - cfg.shelf_weather_phi * w_t))))
            batches[k].append(
                {"id": next_batch_id, "qty": qty, "recv": day, "cost": ucost,
                 "sup": sid, "exp": day + pd.Timedelta(days=eff)}
            )
            next_batch_id += 1
            received[k] += qty
            # release the full ordered amount: a short delivery closes the PO too,
            # otherwise the position carries a phantom that blocks the next order
            on_order[k] = max(0.0, on_order[k] - ordered)

        # --- consumption, FEFO ---------------------------------------------
        need = demand[ti].copy()
        consumed = np.zeros(ng)
        wasted = np.zeros(ng)
        stockout = np.zeros(ng, dtype=bool)

        def _fefo_draw(k: int, want: float) -> float:
            """Pull `want` from ingredient k's batches, oldest expiry first."""
            batches[k].sort(key=lambda b: b["exp"])
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

        emergency = np.zeros(ng)
        for k in range(ng):
            if need[k] <= 0:
                continue
            consumed[k] = _fefo_draw(k, need[k])
            if consumed[k] < need[k] - 1e-6:
                stockout[k] = True                          # planned stock ran out ...
                emergency[k] = need[k] - consumed[k]        # ... so buy the gap today
                consumed[k] = need[k]                       # and it is used at once

        # --- expiry / overstock spoilage ------------------------------------
        mean_dem = demand[max(0, ti - 27): ti + 1, :].mean(axis=0)
        for k in range(ng):
            keep = []
            for b in batches[k]:
                if day > b["exp"]:
                    held = int((day - b["recv"]).days)
                    on_hand = sum(x["qty"] for x in batches[k])
                    reason = ("overstock"
                              if on_hand > 3 * max(mean_dem[k], 1e-6) else "expiry")
                    wasted[k] += b["qty"]
                    waste_rows.append(
                        {"waste_id": waste_id, "date": day,
                         "ingredient_id": int(gids[k]), "supplier_id": b["sup"],
                         "batch_id": b["id"], "waste_quantity": round(b["qty"], 4),
                         "waste_reason": reason, "unit_cost": b["cost"],
                         "received_date": b["recv"], "expiry_date": b["exp"],
                         "days_held": held}
                    )
                    waste_id += 1
                else:
                    keep.append(b)
            batches[k] = keep

        closing = np.array([sum(b["qty"] for b in batches[k]) for k in range(ng)])

        # --- end-of-day batch stock: what is on the shelf and when it expires
        for k in range(ng):
            for b in batches[k]:
                if b["qty"] > 1e-9:
                    batch_rows.append((day, b["id"], int(gids[k]), b["sup"], b["recv"],
                                       b["exp"], round(b["qty"], 4), b["cost"]))

        # --- review & order: (R,s,S) with manager-bias distortion ------------
        due = (ti % review_n) == 0
        mu = np.maximum(mean_dem, 0.0)
        sd = demand[max(0, ti - 27): ti + 1, :].std(axis=0)
        # periodic review: stock ordered today must last until the NEXT order
        # can arrive. That gap is the longer of the kitchen's review period and
        # the supplier's delivery interval, so the reorder point protects lead
        # time + that gap (L+R), not lead time alone.
        gap = np.maximum(review_n, interval)
        prot = lt_mean + gap
        mu_ltd = mu * prot
        sd_ltd = np.sqrt(np.maximum(prot, 1) * sd ** 2 + (mu * lt_sd) ** 2)
        s_lvl = mu_ltd + cfg.service_z * sd_ltd
        S_lvl = s_lvl + mu * gap
        # no kitchen orders three days of tuna when tuna keeps for two: the
        # order-up-to level is capped near what can be used before it expires.
        # When deliveries are further apart than the shelf life (salmon: 2-day  [v1-v3; SUPERSEDED in v4: frozen 28 d]
        # life, 3-day delivery interval) the cap still allows cover up to the
        # shelf life + a fraction of a day, so the gap shows up as waste and
        # emergency buys rather than being hidden.
        # The cap applies to the inventory position (on hand + on order), so it
        # includes the lead-time demand still in the pipeline; what it limits is
        # the stock left on the shelf once a delivery has arrived.
        cap_days = lt_mean + np.maximum(np.maximum(shelf, 1.0) * cfg.perish_cover_frac,
                                        np.minimum(gap, np.maximum(shelf, 1.0)) + cfg.cover_floor_days)
        S_lvl = np.where(perish, np.minimum(S_lvl, mu * cap_days), S_lvl)
        s_lvl = np.minimum(s_lvl, S_lvl)
        position = closing + on_order

        # a line so slow that one pack outlives its shelf life is not held in
        # stock at all: the kitchen buys it only when an order actually comes in
        recent = demand[max(0, ti - 6): ti + 1, :].sum(axis=0)
        sparse = perish & (mu * np.maximum(shelf, 1.0) < cfg.sparse_pack_frac * pack)

        order_qty = np.zeros(ng)
        for k in range(ng):
            if sparse[k]:
                if recent[k] > 0 and position[k] <= 1e-6:
                    q = float(np.ceil(max(pack[k], moq_base[k]) / pack[k]) * pack[k])
                    order_qty[k] = q
                    on_order[k] += q
                    lt = int(max(1, round(lt_mean[k])))
                    pipeline.setdefault(arrival_day(ti, lt, k), []).append(
                        (k, q, q, sup_of[int(gids[k])], round(cost[k], 4))
                    )
                continue
            # no usage in the last 28 days => nothing to replenish; without this
            # the min-order-qty floor buys a pack every review and bins it
            if not due[k] or mu[k] <= 0 or position[k] > s_lvl[k]:
                continue
            raw_q = max(S_lvl[k] - position[k], 0.0) * (1 + m_t)
            q = float(np.ceil(max(raw_q, moq_base[k]) / pack[k]) * pack[k])
            if q <= 0:
                continue
            order_qty[k] = q
            on_order[k] += q
            lt = int(max(1, round(lt_mean[k] * (1 + cfg.lead_weather_kappa * w_t)
                                  + rng.normal(0, lt_sd[k]))))
            got = q if rng.random() < fill[k] else q * rng.uniform(0.60, 0.95)
            ucost = cost[k] * rng.uniform(0.94, 1.08)      # SUPPLY-UR fluctuation %
            pipeline.setdefault(arrival_day(ti, lt, k), []).append(
                (k, q, got, sup_of[int(gids[k])], round(ucost, 4))
            )

        for k in range(ng):
            inv_rows.append(
                (day, int(gids[k]), sup_of[int(gids[k])], round(opening[k], 4),
                 round(received[k], 4), round(emergency[k], 4), round(consumed[k], 4),
                 round(wasted[k], 4), round(closing[k], 4), round(s_lvl[k], 4),
                 round(order_qty[k], 4), round(on_order[k], 4), bool(stockout[k]),
                 round(emergency[k] * cost[k] * (1 + cfg.emergency_premium), 2))
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
        waste = waste.merge(ing[["ingredient_id", "uom"]], on="ingredient_id",
                            how="left")
        waste["waste_value_php"] = (waste["waste_quantity"] *
                                    waste["unit_cost"]).round(2)
        waste = waste[
            ["waste_id", "waste_date", "ingredient_id", "supplier_id", "batch_id",
             "waste_quantity", "uom", "waste_reason", "unit_cost",
             "waste_value_php", "received_date", "expiry_date", "days_held"]
        ]

    bat = pd.DataFrame(batch_rows, columns=["snapshot_date", "batch_id", "ingredient_id",
                                            "supplier_id", "received_date", "expiry_date",
                                            "qty_on_hand", "unit_cost"])
    # 0 = last usable day (the batch is binned the day after its expiry date)
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
            try:
                df.to_parquet(cfg.out_dir / f"{name}.parquet", index=False)
            except Exception:
                pass


def run(cfg: Config | None = None) -> dict:
    cfg = cfg or Config()
    rng = np.random.default_rng(cfg.seed)
    dims = load_dimensions(cfg)
    sup, terms = dims["suppliers"], dims["terms"]
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
    latents = draw_latents(cfg, rng)
    tf = build_time_factors(cfg, dims["calendar"], real)
    base = calibrate_base(cfg, real, dims["menu"], tf)

    backfill = build_backfill(cfg, rng, dims["menu"], base, tf, latents)
    sales = stitch(cfg, rng, backfill, real)
    sales = assign_channel(cfg, rng, sales, latents)

    report = seam_report(cfg, sales)
    print("seam gate (E3):", report)
    if not report["pass"]:
        print("  WARNING: KS gate not passed at p>0.05 - inspect trend/calibration.")

    cons = build_consumption(sales, dims["bom"])
    inv, waste, batches = simulate_inventory(cfg, rng, cons, dims["ingredients"],
                                             dims["suppliers"], dims["terms"], latents)

    # generated/sales.csv = synthetic backfill (2021-01-01 -> 2025-11-30) followed
    # by the real SALES'26 lines (2025-12-01 -> 2026-09-08), built straight from the
    # sheet so every real value is exactly what the POS recorded.
    syn_out = synthetic_sales_rows(sales, dims["menu"])     # latents never exported (9)
    real_out = real_sales_rows(cfg, dims["menu"], first_id=int(syn_out["sale_id"].max()) + 1)
    sales_out = pd.concat([syn_out, real_out], ignore_index=True)

    # one row per raw material the restaurant buys and stores; unit_cost is PHP per uom
    ing_out = dims["ingredients"][
        ["ingredient_id", "ingredient_code", "ingredient_name", "category",
         "storage_type", "uom", "shelf_life_days", "is_perishable",
         "unit_cost", "catalog_unit_cost", "menu2_codes"]
    ]
    # date_introduced / date_retired stay internal: the generator uses them to keep
    # a dish out of the backfill before it existed, but they are not exported
    menu_out = dims["menu"][
        ["item_id", "sku", "item_name", "display_name", "category", "price",
         "printed_menu_price", "is_promo", "is_complimentary", "is_active"]
    ]
    # the BOM bridge: how much of each raw ingredient ONE unit of a menu item uses,
    # in that ingredient's uom; derivation shows the MENU2 line(s) it came from.
    # Which recipes were borrowed from a similarly named dish is listed in
    # recipe_review.csv, not repeated on every recipe line.
    recipes = (dims["bom"].rename(columns={"qty_base": "qty_per_item"})
               .merge(ing_out[["ingredient_id", "uom"]], on="ingredient_id", how="left")
               .sort_values(["item_id", "ingredient_id"]))
    recipes = recipes[["item_id", "ingredient_id", "ingredient_code", "qty_per_item",
                       "uom", "derivation"]]

    tables = {
        "sales": sales_out,
        "inventory": inv,
        "inventory_batches": batches,
        "waste": waste,
        "suppliers": dims["suppliers"],
        "supplier_item_terms": dims["terms"],
        "menu_items": menu_out,
        "ingredients": ing_out,
        "recipes": recipes,
        "recipe_review": dims["recipe_review"],   # for the owner; not loaded
        "calendar": dims["calendar"].drop(columns="date_id"),
    }
    export(cfg, tables)
    validate(cfg, tables, report)
    return tables


# sales.csv columns. Each SALES'26 column has a counterpart (renamed to snake_case):
#   DATE->sale_date  Item name->item_name  SKU->sku  Category->category
#   Items sold->quantity_sold  Gross sales->gross_sales  Items refunded->items_refunded
#   Refunds->refunds  Discounts->discount  Net sales->net_sales
#   Cost of goods->cost_of_goods  Gross profit->gross_profit  Margin->margin  Taxes->taxes
# plus keys and flags: sale_id, item_id, unit_price, channel, is_complimentary.
# Lines dated before 2025-12-01 are synthetic; from 2025-12-01 on they are the
# SALES'26 lines, in sheet order (sale_id 42685 = sheet row 2, and so on).
SALES_COLUMNS = ["sale_id", "sale_date", "item_id", "item_name", "sku", "category",
                 "quantity_sold", "gross_sales", "items_refunded", "refunds", "discount",
                 "net_sales", "cost_of_goods", "gross_profit", "margin", "taxes",
                 "unit_price", "channel", "is_complimentary"]
SHEET_TO_SALES = {"DATE": "sale_date", "Item name": "item_name", "SKU": "sku",
                  "Category": "category", "Items sold": "quantity_sold",
                  "Gross sales": "gross_sales", "Items refunded": "items_refunded",
                  "Refunds": "refunds", "Discounts": "discount", "Net sales": "net_sales",
                  "Cost of goods": "cost_of_goods", "Gross profit": "gross_profit",
                  "Margin": "margin", "Taxes": "taxes"}


def synthetic_sales_rows(sales: pd.DataFrame, menu: pd.DataFrame) -> pd.DataFrame:
    """Backfill lines, filled in the POS's own way: the POS records no refunds and
    no cost of goods (0 on every SALES'26 line), so gross profit = net sales and
    margin = 1, or 0 on a zero-net (complimentary) line."""
    s = sales.loc[~sales["is_real"].astype(bool)].rename(columns={"date": "sale_date"}).copy()
    s["item_name"] = s["item_id"].map(menu.set_index("item_id")["item_name"])
    s["items_refunded"], s["refunds"], s["cost_of_goods"] = 0, 0, 0
    s["gross_profit"] = s["net_sales"]
    s["margin"] = (s["net_sales"] > 0).astype(int)
    s["sale_date"] = s["sale_date"].dt.date
    return s[SALES_COLUMNS]


def real_sales_rows(cfg: Config, menu: pd.DataFrame, first_id: int) -> pd.DataFrame:
    """SALES'26 line for line, in sheet order, every value exactly as recorded.
    SKU is read as text because a few POS lines store it as "00" / "000000"."""
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
    return r[SALES_COLUMNS]


def check_real_rows_match_sheet(cfg: Config, sales: pd.DataFrame) -> int:
    """Independent cell-by-cell check (openpyxl, not pandas) of every real line in
    sales.csv against SALES'26. Returns the number of cells compared."""
    import datetime
    import openpyxl
    ws = openpyxl.load_workbook(cfg.src_dir / cfg.sales_file, read_only=True,
                                data_only=True)[cfg.sales_sheet]
    rows = ws.iter_rows(values_only=True)
    header = next(rows)
    # real lines = everything from the seam on, stored in sheet order
    real = sales[pd.to_datetime(sales["sale_date"]) >= pd.Timestamp(cfg.seam)]
    real = real.sort_values("sale_id").reset_index(drop=True)
    cells, sheet_row = 0, 1
    for sheet_row, values in enumerate(rows, start=2):
        if sheet_row - 2 >= len(real):
            raise ValueError(f"sales.csv has fewer real lines than SALES'26 ({len(real)})")
        line = real.loc[sheet_row - 2]
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
    seam_day = pd.Timestamp(cfg.seam)
    real_mask = pd.to_datetime(s["sale_date"]) >= seam_day
    syn, r = s[~real_mask], s[real_mask]
    last_syn = pd.to_datetime(syn["sale_date"]).max()
    if r["sale_id"].min() <= syn["sale_id"].max():
        raise ValueError("real SALES'26 lines must follow the synthetic lines")
    cells = check_real_rows_match_sheet(cfg, s)
    bal = (inv["opening_stock"] + inv["qty_received"] + inv["qty_emergency"]
           - inv["qty_consumed"] - inv["qty_wasted"] - inv["closing_stock"]).abs().max()
    # by value: grams, pieces and servings can't be added together
    cost = t["ingredients"].set_index("ingredient_id")["unit_cost"]
    used_php = (inv["qty_consumed"] * inv["ingredient_id"].map(cost)).sum()
    wpct = w["waste_value_php"].sum() / max(used_php + w["waste_value_php"].sum(), 1)
    print("\n--- validation report ---")
    print(f"sales.csv        {len(s):>9,} lines")
    print(f"  synthetic      {len(syn):>9,}   net PHP {syn['net_sales'].sum():,.2f}   "
          f"{pd.to_datetime(syn['sale_date']).min().date()} -> {last_syn.date()}")
    print(f"  real SALES'26  {len(r):>9,}   net PHP {r['net_sales'].sum():,.2f}   "
          f"{min(r['sale_date'])} -> {max(r['sale_date'])}   "
          f"{cells:,} cells identical to the sheet")
    print(f"inventory rows   {len(inv):>9,}   ledger max imbalance {bal:.6f}")
    print(f"waste rows       {len(w):>9,}   waste {wpct:.1%} of usage by value (target 4-10%)")
    print(f"waste value      PHP {w['waste_value_php'].sum():,.0f}")
    print(f"stockout rate    {inv['stockout_flag'].mean():.2%} of panel rows "
          f"(covered by emergency buys: PHP {inv['emergency_cost_php'].sum():,.0f})")
    print(f"batch snapshot   {len(t['inventory_batches']):>9,} rows")
    print(f"qty/row mean     {syn['quantity_sold'].mean():.2f} synthetic vs "
          f"{r['quantity_sold'].mean():.2f} real")
    print(f"discounted rows  {(syn['discount'] > 0).mean():.1%} synthetic vs "
          f"{(r['discount'] > 0).mean():.1%} real")
    print(f"comp rows        {syn['is_complimentary'].mean():.1%} synthetic vs {r['is_complimentary'].mean():.1%} real")
    print(f"seam KS p        {seam['ks_p']}  pass={seam['pass']}")
    print(f"files written to {cfg.out_dir.resolve()}")


if __name__ == "__main__":
    run()
