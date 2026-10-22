"""
Makisushi synthetic dataset generator - Sections 2-6 of MAKISUSHI_SPEC.md.

Section 1 (reference tables) was already built and verified; its outputs live in
``generated/`` (dim_date, dim_menu_item, dim_ingredient, dim_supplier, bom,
supply_ref) and are consumed here as fixed inputs.

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
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------


@dataclass
class Config:
    seed: int = 42
    start: str = "2021-01-01"
    seam: str = "2025-12-01"
    end: str = "2026-09-08"

    src_dir: Path = Path(".")
    sales_file: str = "makisushi_Jan_2026.xlsx"
    sales_sheet: str = "SALES'26"
    dim_dir: Path = Path("generated")
    out_dir: Path = Path("generated")

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

    # 7.8 spoilage
    shelf_weather_phi: float = 0.06
    prep_waste_lo: float = 0.04
    prep_waste_hi: float = 0.06
    prep_waste_trim_bonus: float = 0.02   # trim-heavy proteins & leafy veg
    sparse_pack_frac: float = 0.50        # below this, a line is bought to order
    perish_cover_frac: float = 0.70       # order-up-to cap, as a share of shelf
                                          # life: lower = less waste, worse service

    # scale knobs (8.8)
    volume_multiplier: float = 1.0
    branch_id: int = 1

    write_parquet: bool = True

    def __post_init__(self) -> None:
        self.src_dir = Path(self.src_dir)
        self.dim_dir = Path(self.dim_dir)
        self.out_dir = Path(self.out_dir)


PACK_RULES = {           # pack size per uom/storage, for ceil-to-pack ordering
    ("g", "frozen"): 1000.0,
    ("g", "chilled"): 1000.0,
    ("g", "ambient"): 500.0,
    ("ml", "ambient"): 1000.0,
    ("ml", "chilled"): 1000.0,
    ("pc", "chilled"): 30.0,
    ("pc", "ambient"): 50.0,
    ("pcs", "chilled"): 30.0,
    ("pcs", "ambient"): 50.0,
}
PACK_LADDER = {                      # purchasable sub-packs, smallest first
    "g": [50.0, 100.0, 250.0, 500.0, 1000.0],
    "ml": [250.0, 500.0, 1000.0],
    "pc": [1.0, 5.0, 10.0, 30.0],
    "pcs": [1.0, 5.0, 10.0, 30.0],
}
TRIM_HEAVY = {"seafood", "meat", "vegetable", "produce", "veg", "beef", "pork",
              "chicken", "veg_portion"}

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


def _date_id(s: pd.Series) -> pd.Series:
    return (s.dt.year * 10000 + s.dt.month * 100 + s.dt.day).astype("int64")


# --------------------------------------------------------------------------
# Section 1 outputs (fixed inputs)
# --------------------------------------------------------------------------


def load_dimensions(cfg: Config) -> dict:
    d = cfg.dim_dir
    cal = pd.read_csv(d / "dim_date.csv", parse_dates=["date"])
    menu = pd.read_csv(
        d / "dim_menu_item.csv", parse_dates=["date_introduced", "date_retired"]
    )
    ing = pd.read_csv(d / "dim_ingredient.csv")
    sup = pd.read_csv(d / "dim_supplier.csv")
    bom = pd.read_csv(d / "bom.csv")
    supply_ref = pd.read_csv(d / "supply_ref.csv")

    bom = bom.dropna(subset=["item_id", "ingredient_id"]).copy()
    bom["item_id"] = bom["item_id"].astype(int)
    bom["ingredient_id"] = bom["ingredient_id"].astype(int)
    menu["item_id"] = menu["item_id"].astype(int)

    # pack size (D1: needed for ceil-to-pack ordering; not in the S1 export)
    ing["pack_size"] = [
        PACK_RULES.get((str(u).lower(), str(s).lower()), 1.0)
        for u, s in zip(ing["uom"], ing["storage_type"])
    ]
    ing["unit_cost"] = ing["unit_cost"].astype(float)

    # MENU2 mixes units: portion-coded lines (CF_060, CT_120, GP_050 ...) state
    # qty in PORTIONS, bulk lines (TUN, SAL, SUS) state it in grams, yet every
    # row is labelled "g". Normalise to a base unit so consumption is comparable
    # with pack sizes; the owner's original number is kept as qty_per_unit.
    pg = ing.set_index("ingredient_id")["portion_g"]
    bom["portion_g"] = bom["ingredient_id"].map(pg)
    bom["qty_base"] = np.where(
        bom["portion_g"].notna(),
        bom["qty_per_unit"] * bom["portion_g"].fillna(1.0),
        bom["qty_per_unit"],
    )
    return dict(
        calendar=cal, menu=menu, ingredients=ing, suppliers=sup,
        bom=bom, supply_ref=supply_ref,
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
    df["is_comp"] = (df["category"].astype(str).str.upper() == "MANAGEMENT") | (
        df["net_sales"] <= 0
    )
    df["is_real"] = True
    keep = [
        "date", "item_id", "sku", "category", "quantity_sold", "unit_price",
        "gross_sales", "discount", "net_sales", "taxes", "is_comp", "is_real",
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
    b["is_comp"] = comp
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
    sales["date_id"] = _date_id(sales["date"])
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
    sales["channel"] = np.where(is_deliv | forced.to_numpy(), "GrabFood", "dine-in")
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


def resolve_pack_sizes(ing: pd.DataFrame, cons: pd.DataFrame,
                       n_days: int) -> pd.DataFrame:
    """Demand-aware purchase pack (D1 / S 10 pack rounding).

    The catalog pack (PACK_RULES) is the ceiling: a 1 kg tray. A kitchen buying a
    2-day-shelf-life ingredient it uses 1 g of per day does not buy a kilo of it,
    so short-shelf-life items step down the ladder to the smallest pack that still
    covers about one review cycle. Long-life dry/frozen goods keep the full pack.
    """
    # average over the whole panel, not just days with demand: a pack has to
    # match everyday usage, otherwise slow lines buy more than they can use
    mu = cons.groupby("ingredient_id")["qty"].sum() / max(n_days, 1)
    packs = []
    for r in ing.itertuples():
        cap = float(r.pack_size)
        d = float(mu.get(int(r.ingredient_id), 0.0))
        shelf = float(r.shelf_life_days)
        if shelf > 90 or d <= 0:                      # dry goods: catalog pack
            packs.append(cap)
            continue
        cover = 1.0 if shelf <= 2 else (2.0 if shelf <= 7 else min(shelf * 0.5, 21.0))
        target = max(d * cover, 1e-6)                 # a pack is a few days of cover
        ladder = [p for p in PACK_LADDER.get(str(r.uom).lower(), [cap]) if p <= cap]
        pick = next((p for p in ladder if p >= target), ladder[-1] if ladder else cap)
        packs.append(float(pick))
    out = ing.copy()
    out["pack_size"] = packs
    return out


def build_consumption(sales: pd.DataFrame, bom: pd.DataFrame) -> pd.DataFrame:
    j = sales[["date", "item_id", "quantity_sold"]].merge(
        bom[["item_id", "ingredient_id", "qty_base"]], on="item_id", how="inner"
    )
    j["qty"] = j["quantity_sold"] * j["qty_base"]
    return j.groupby(["date", "ingredient_id"], as_index=False)["qty"].sum()


def _assign_suppliers(ing: pd.DataFrame, sup: pd.DataFrame,
                      rng: np.random.Generator) -> dict:
    served = {int(r.supplier_id): str(r.category_served).lower()
              for r in sup.itertuples()}
    out = {}
    sids = list(served)
    for r in ing.itertuples():
        cat = f"{str(r.category).lower()} {str(r.storage_type).lower()}"
        hit = [sid for sid, cs in served.items()
               if any(tok and tok in cat for tok in cs.replace("/", " ").split())]
        out[int(r.ingredient_id)] = int(hit[0]) if hit else int(rng.choice(sids))
    return out


def simulate_inventory(cfg: Config, rng: np.random.Generator, cons: pd.DataFrame,
                       ing: pd.DataFrame, sup: pd.DataFrame,
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
    pack = ing["pack_size"].to_numpy(dtype=float)
    fresh = (ing["is_perishable"].to_numpy(dtype=bool)) & (shelf <= 7)
    review_n = np.where(fresh, cfg.review_fresh_days, cfg.review_dry_days)
    omega = rng.uniform(cfg.prep_waste_lo, cfg.prep_waste_hi, ng) + np.where(
        ing["category"].str.lower().isin(TRIM_HEAVY), cfg.prep_waste_trim_bonus, 0.0
    )

    sup_of = _assign_suppliers(ing, sup, rng)
    sup_idx = sup.set_index("supplier_id")
    lt_mean = np.array([sup_idx.loc[sup_of[int(g)], "lead_time_mean"] for g in gids],
                       dtype=float)
    # a perishable cannot be ordered on a lead time longer than it survives:
    # fresh lines ride the supplier's daily run (8.7: fresh lead time 1-3 d)
    perish = ing["is_perishable"].to_numpy(dtype=bool)
    lt_mean = np.where(perish, np.clip(lt_mean, 1.0, np.maximum(shelf - 1.0, 1.0)),
                       lt_mean)
    lt_sd = np.array([sup_idx.loc[sup_of[int(g)], "lead_time_sd"] for g in gids],
                     dtype=float)
    fill = np.array([sup_idx.loc[sup_of[int(g)], "fill_rate"] for g in gids],
                    dtype=float)
    moq = np.array([sup_idx.loc[sup_of[int(g)], "min_order_qty"] for g in gids],
                   dtype=float)

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
    inv_rows, waste_rows = [], []
    waste_id = 1
    date_ids = _date_id(pd.Series(idx)).to_numpy()

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
        prep = omega * need
        draw = need + prep
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

        for k in range(ng):
            if draw[k] <= 0:
                continue
            # the dish comes first; trim loss is whatever the prep also burns through
            consumed[k] = _fefo_draw(k, need[k])
            if consumed[k] < need[k] - 1e-6:
                stockout[k] = True                          # unmet => lost sale
            prep_used = _fefo_draw(k, prep[k] * (consumed[k] / max(need[k], 1e-9)))
            if prep_used > 0:
                wasted[k] += prep_used
                waste_rows.append(
                    {"waste_id": waste_id, "date": day,
                     "ingredient_id": int(gids[k]), "supplier_id": sup_of[int(gids[k])],
                     "batch_id": 0, "waste_quantity": round(prep_used, 4),
                     "waste_reason": "prep-trim", "unit_cost": cost[k],
                     "received_date": day, "expiry_date": day, "days_held": 0}
                )
                waste_id += 1

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

        # --- review & order: (R,s,S) with manager-bias distortion ------------
        due = (ti % review_n) == 0
        mu = np.maximum(mean_dem, 0.0)
        sd = demand[max(0, ti - 27): ti + 1, :].std(axis=0)
        mu_ltd = mu * lt_mean
        sd_ltd = np.sqrt(np.maximum(lt_mean, 1) * sd ** 2 + (mu * lt_sd) ** 2)
        s_lvl = mu_ltd + cfg.service_z * sd_ltd
        S_lvl = s_lvl + mu * review_n
        # no kitchen orders three days of tuna when tuna keeps for two: the
        # order-up-to level is capped at what can be used before it expires
        S_lvl = np.where(perish,
                         np.minimum(S_lvl, mu * np.maximum(shelf, 1.0)
                                    * cfg.perish_cover_frac),
                         S_lvl)
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
                    q = pack[k]
                    order_qty[k] = q
                    on_order[k] += q
                    lt = int(max(1, round(lt_mean[k])))
                    pipeline.setdefault(ti + lt, []).append(
                        (k, q, q, sup_of[int(gids[k])], round(cost[k], 4))
                    )
                continue
            if not due[k] or position[k] > s_lvl[k]:
                continue
            raw_q = max(S_lvl[k] - position[k], 0.0) * (1 + m_t)
            q = float(np.ceil(max(raw_q, moq[k]) / pack[k]) * pack[k])
            if q <= 0:
                continue
            order_qty[k] = q
            on_order[k] += q
            lt = int(max(1, round(lt_mean[k] * (1 + cfg.lead_weather_kappa * w_t)
                                  + rng.normal(0, lt_sd[k]))))
            got = q if rng.random() < fill[k] else q * rng.uniform(0.60, 0.95)
            ucost = cost[k] * rng.uniform(0.94, 1.08)      # SUPPLY-UR fluctuation %
            pipeline.setdefault(ti + lt, []).append(
                (k, q, got, sup_of[int(gids[k])], round(ucost, 4))
            )

        did = int(date_ids[ti])
        for k in range(ng):
            inv_rows.append(
                (did, int(gids[k]), sup_of[int(gids[k])], round(opening[k], 4),
                 round(received[k], 4), round(consumed[k], 4), round(wasted[k], 4),
                 round(closing[k], 4), round(s_lvl[k], 4), round(order_qty[k], 4),
                 round(on_order[k], 4), bool(stockout[k]))
            )

    inv = pd.DataFrame(
        inv_rows,
        columns=["date_id", "ingredient_id", "supplier_id", "opening_stock",
                 "qty_received", "qty_consumed", "qty_wasted", "closing_stock",
                 "reorder_level", "order_qty", "on_order_qty", "stockout_flag"],
    )
    inv.insert(0, "inventory_id", np.arange(1, len(inv) + 1))

    waste = pd.DataFrame(waste_rows)
    if len(waste):
        waste["date_id"] = _date_id(waste["date"])
        waste = waste.merge(ing[["ingredient_id", "uom"]], on="ingredient_id",
                            how="left")
        waste["waste_value_php"] = (waste["waste_quantity"] *
                                    waste["unit_cost"]).round(2)
        waste = waste[
            ["waste_id", "date_id", "ingredient_id", "supplier_id", "batch_id",
             "waste_quantity", "uom", "waste_reason", "unit_cost",
             "waste_value_php", "received_date", "expiry_date", "days_held"]
        ]
    return inv, waste


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
    dims["ingredients"] = resolve_pack_sizes(dims["ingredients"], cons,
                                             len(_dates(cfg)[0]))
    inv, waste = simulate_inventory(cfg, rng, cons, dims["ingredients"],
                                    dims["suppliers"], latents)

    sales_out = sales[
        ["sale_id", "date_id", "item_id", "sku", "category", "quantity_sold",
         "unit_price", "gross_sales", "discount", "net_sales", "cost_of_goods",
         "taxes", "channel", "is_comp"]
    ].copy()                                    # latents u/w/m never exported (9)

    ing_out = dims["ingredients"][
        ["ingredient_id", "ingredient_code", "ingredient_name", "category",
         "storage_type", "uom", "portion_g", "pack_size", "shelf_life_days",
         "is_perishable", "unit_cost", "name_inferred"]
    ]
    menu_out = dims["menu"][
        ["item_id", "sku", "item_name", "category", "price", "is_promo", "is_comp",
         "is_active", "date_introduced", "date_retired"]
    ]
    recipes = dims["bom"][["item_id", "ingredient_id", "ingredient_code",
                           "qty_per_unit", "qty_base"]].copy()
    recipes = recipes.merge(ing_out[["ingredient_id", "uom"]], on="ingredient_id",
                            how="left")

    tables = {
        "sales": sales_out,
        "inventory": inv,
        "waste": waste,
        "suppliers": dims["suppliers"],
        "menu_items": menu_out,
        "ingredients": ing_out,
        "recipes": recipes,
        "calendar": dims["calendar"],
    }
    export(cfg, tables)
    validate(cfg, tables, report)
    return tables


def validate(cfg: Config, t: dict, seam: dict) -> None:
    s, inv, w = t["sales"], t["inventory"], t["waste"]
    bal = (inv["opening_stock"] + inv["qty_received"] - inv["qty_consumed"]
           - inv["qty_wasted"] - inv["closing_stock"]).abs().max()
    wpct = w["waste_quantity"].sum() / max(
        inv["qty_consumed"].sum() + w["waste_quantity"].sum(), 1)
    print("\n--- validation report ---")
    print(f"sales rows       {len(s):>9,}   net PHP {s['net_sales'].sum():,.0f}")
    print(f"inventory rows   {len(inv):>9,}   ledger max imbalance {bal:.6f}")
    print(f"waste rows       {len(w):>9,}   waste share {wpct:.1%} (target 4-10%)")
    print(f"waste value      PHP {w['waste_value_php'].sum():,.0f}")
    print(f"stockout rate    {inv['stockout_flag'].mean():.2%} of panel rows")
    print(f"qty/row mean     {s['quantity_sold'].mean():.2f} (real 1.41)")
    print(f"discounted rows  {(s['discount'] > 0).mean():.1%} (real 26%)")
    print(f"comp rows        {s['is_comp'].mean():.1%} (real ~5%)")
    print(f"seam KS p        {seam['ks_p']}  pass={seam['pass']}")
    print(f"files written to {cfg.out_dir.resolve()}")


if __name__ == "__main__":
    run()
