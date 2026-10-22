# ================================================================
# Makisushi Synthetic Generator  —  SECTION 1: Dimensions & BOM
# Reproducible (seeded). Reads the real project files, emits clean
# dim_* tables + a tidy long-format `bom` bridge (from MENU2).
# No random demand yet — that's Section 2.
#   NB: install prerequisites once (Jupyter):  %pip install holidays --break-system-packages
# ================================================================
import numpy as np, pandas as pd, re
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------- config
# Where the three source Excel files live. The first folder that actually
# contains makisushi_Jan_2026.xlsx wins, so the same file runs on Gab's PC
# and in the Claude project sandbox without edits.
SOURCE_DIR_CANDIDATES = [
    Path(r"C:\Users\gabbm\Documents\capstone - maki"),   # local Windows folder
    Path("/mnt/project"),                                # Claude project sandbox
    Path.cwd(),                                          # wherever the notebook runs
]
SALES_FILE = "makisushi_Jan_2026.xlsx"

def _find_src_dir() -> Path:
    for d in SOURCE_DIR_CANDIDATES:
        if (d / SALES_FILE).exists():
            return d
    raise FileNotFoundError(
        f"Could not find {SALES_FILE} in any of: "
        + ", ".join(str(d) for d in SOURCE_DIR_CANDIDATES)
        + ". Put the three Excel files in one of these folders or edit SOURCE_DIR_CANDIDATES.")

@dataclass
class Config:
    seed: int = 42
    start: str = "2021-01-01"          # backfill begins
    seam:  str = "2025-12-01"          # real data begins here (kept as-is)
    end:   str = "2026-09-08"          # last real day
    src_dir: Path = field(default_factory=_find_src_dir)
    sales_file: str = SALES_FILE
    out_dir: Path = Path("generated")  # where makisushi_datagen.py writes the 8 exports (inside src_dir)
    # locked trend (used in Section 2) ------------------------------
    trend_2021: float = 0.48
    annual_growth: float = 0.16
    service_level_z: float = 1.41       # ~92%

CFG = Config()
RNG = np.random.default_rng(CFG.seed)

# ---------------------------------------------------------------- stable surrogate keys
def stable_ids(natural_keys, cfg, table, key_col, id_col):
    """Reuse the id each natural key already has in the last export; new keys get
    max(id)+1 in sorted order. Adding a menu item never renumbers existing ones."""
    path = Path(cfg.src_dir) / cfg.out_dir / f"{table}.csv"
    known = {}
    if path.exists():
        prev = pd.read_csv(path, usecols=[key_col, id_col])
        known = dict(zip(prev[key_col], prev[id_col].astype(int)))
    nxt = max(known.values(), default=0) + 1
    ids = {}
    for k in sorted(set(natural_keys), key=str):
        if k in known:
            ids[k] = known[k]
        else:
            ids[k] = nxt; nxt += 1
    return [ids[k] for k in natural_keys]

# ---------------------------------------------------------------- dim_date
def build_dim_date(cfg):
    idx = pd.date_range(cfg.start, cfg.end, freq="D")
    try:
        import holidays
        yrs = range(idx.min().year, idx.max().year + 1)
        ph = set(pd.to_datetime(list(holidays.Philippines(years=yrs).keys())))
    except Exception:
        ph = set()
    d = pd.DataFrame({"date": idx})
    d["date_id"]      = d["date"].dt.strftime("%Y%m%d").astype(int)
    d["day_of_week"]  = d["date"].dt.day_name()
    d["dow"]          = d["date"].dt.dayofweek
    d["week"]         = d["date"].dt.isocalendar().week.astype(int)
    d["month"]        = d["date"].dt.month
    d["quarter"]      = d["date"].dt.quarter
    d["year"]         = d["date"].dt.year
    d["is_weekend"]   = d["dow"] >= 5
    d["is_holiday"]   = d["date"].isin(ph)
    d["is_payday"]    = (d["date"].dt.day == 15) | d["date"].dt.is_month_end
    d["is_ber_month"] = d["month"].isin([9, 10, 11, 12])
    return d

# ---------------------------------------------------------------- dim_menu_item (from SALES'26)
def build_dim_menu_item(cfg):
    s = pd.read_excel(cfg.src_dir / cfg.sales_file, sheet_name="SALES'26")
    s["unit_price"] = s["Gross sales"] / s["Items sold"].replace(0, np.nan)
    valid = s[(s["Items sold"] > 0) & (s["Gross sales"] > 0)]
    mode1 = lambda x: x.round(0).mode().iloc[0] if len(x.mode()) else np.nan
    price = valid.groupby("Item name")["unit_price"].agg(mode1).rename("price")
    cat   = s.groupby("Item name")["Category"].agg(lambda x: x.mode().iloc[0]).rename("category")
    sku   = s.groupby("Item name")["SKU"].first().rename("sku")
    m = pd.concat([cat, sku, price], axis=1).reset_index().rename(columns={"Item name": "item_name"})
    m["price"] = m["price"].fillna(0.0)
    m.insert(0, "item_id", stable_ids(m["item_name"], cfg, "menu_items", "item_name", "item_id"))
    m = m.sort_values("item_id").reset_index(drop=True)
    m["is_promo"] = m["category"].str.contains(r"PROMO|STARDEAL|VALUE|GRAB", case=False, na=False)
    m["is_complimentary"]  = m["category"].str.upper().eq("MANAGEMENT")
    # A+ time-honest menu evolution
    m["date_introduced"] = pd.Timestamp(cfg.start)
    m["date_retired"]    = pd.NaT
    yr = m["category"].str.extract(r"(20\d{2})")[0]
    m.loc[yr.notna(), "date_introduced"] = pd.to_datetime(yr[yr.notna()] + "-01-01")
    m.loc[m["category"].str.contains("GRAB", case=False, na=False),
          "date_introduced"] = pd.Timestamp("2022-01-01")
    m["is_active"] = True
    # item_name stays exactly as the POS wrote it (it must match SALES'26);
    # display_name fixes POS typing glitches for dashboards
    m["display_name"] = m["item_name"].map(clean_display_name)
    return m


# POS section tags. Most only repeat the category and are dropped; a few carry the
# kind of dish, which is added to the name when the name doesn't already say it.
_NAME_TAG = re.compile(r"^\s*[\[\(]?\s*(DB|MR|ATF|ST|PR|SM|MM|M/M|VM|SB|BSP|BS|SH|SL|PL|RM|DS|D|ALC|HS|TM|"
                  r"EXTRA|UPGRADE|BAKED SUSHI)\s*[\]\)]\s*|^\s*(BSP)\s+", re.I)
_NAME_SPELLING = [
    (r"\bterriyaki\b", "Teriyaki"), (r"\bshoyo\b", "Shoyu"), (r"\bchicekn\b", "Chicken"),
    (r"\bgyosa\b", "Gyoza"), (r"\bburito\b", "Burrito"), (r"\bleche plan\b", "Leche Flan"),
    (r"\bmushroomc\b", "Mushroom"), (r"\bmushrooms\b", "Mushroom"), (r"\bsoftdrinks\b", "Soft Drinks"),
    (r"\bcali maki\b", "California Maki"), (r"\bteppan\b(?!yaki)", "Teppanyaki"),
    (r"\b4\s*in\s*1\b", "4-in-1"), (r"\bm\s*&\s*m\b|\bmm\b|\bmix\s*&\s*match\b|\bm/m\b", "Mix & Match"),
    (r"\bsfr?\b", "Seafood Fried Rice"), (r"\bjr\b", "Japanese Rice"), (r"\bala carte\b", "a la Carte"),
    (r"\bupgrade to\b", "Upgrade to"), (r"\s+and\s+", " & "), (r"(?<=\s)w(?=\s)", "w/"),
    (r"\brice/", "Rice w/ "),
]
_NAME_LOWER = {"w/", "&", "with", "to", "of", "a", "la", "for", "or"}
_NAME_KEEP = {"BBQ", "4-in-1"}


def _title(word, first):
    lead = re.match(r"^[(\[]*", word).group(0)
    trail = re.search(r"[)\],:]*$", word).group(0)
    core = word[len(lead):len(word) - len(trail)] if trail else word[len(lead):]
    if not core:
        return word
    if core.upper() in _NAME_KEEP or core in _NAME_KEEP or re.fullmatch(r"\d+(pcs|g)?", core):
        out = core.upper() if core.upper() in _NAME_KEEP else core
    elif "/" in core and core != "w/":
        out = "/".join(_title(w, False) for w in core.split("/"))
    elif not first and not lead and core.lower() in _NAME_LOWER:
        out = core.lower()
    elif core.lower() in ("pcs", "pc"):
        out = core.lower()
    else:
        out = core[:1].upper() + core[1:].lower()
    return lead + out + trail


def _insert_kind(s, kind):
    """'Salmon (Sake)' + 'Sashimi' -> 'Salmon Sashimi (Sake)'."""
    k = s.find(" (")
    return (s[:k] + " " + kind + s[k:]) if k > 0 else s + " " + kind


def clean_display_name(name):
    """Standardised dashboard name: POS section tags dropped (the category says it),
    spelling fixed, Title Case, and size / pieces / grams / Set A-B written one way."""
    return standardize_name(name)


def standardize_name(name):
    s = str(name).replace("K\u221a\u2020ni", "Kani")
    s = re.sub(r"[^\x20-\x7E]+", "", s).strip().rstrip(",:")
    tag = None
    m = _NAME_TAG.match(s)
    if m:
        tag = (m.group(1) or m.group(2)).upper()
        s = s[m.end():]
    s = s.replace("Baked Sushi]", "")
    # set A / B
    m = re.search(r"\(\s*set\s*([ab])\s*\)|\bset\s*([ab])\b|\(([ab])\)", s, re.I)
    set_ = (m.group(1) or m.group(2) or m.group(3)).upper() if m else None
    s = re.sub(r"\(\s*set\s*[ab]\s*\)|\bset\s*[ab]\b|\([ab]\)", " ", s, flags=re.I)
    # regular / sharing
    size = None
    if re.search(r"\bsharing\b", s, re.I):
        size = "Sharing"
        s = re.sub(r"\(?\s*(for\s+)?sharing\s*\)?", " ", s, flags=re.I)
    m = re.search(r"\(?\b(small|large)\b\)?", s, re.I)
    if m:
        size = m.group(1).capitalize()
        s = s[:m.start()] + " " + s[m.end():]
    if re.search(r"\(?\breg(ular)?\b\)?", s, re.I):
        size = "Regular"
        s = re.sub(r"\(?\breg(ular)?\b\)?", " ", s, flags=re.I)
    # pieces: moved to the end when leading or in brackets, normalised in place otherwise
    pcs = None
    m = re.match(r"^\s*(\d+)\s*pcs?\b", s, re.I) or re.search(r"\(\s*(\d+)\s*pcs?\s*\)", s, re.I)
    if m:
        pcs = m.group(1)
        s = s[:m.start()] + " " + s[m.end():]
    elif re.search(r"(\d+)\s*pcs?\s*$", s, re.I):
        m = re.search(r"(\d+)\s*pcs?\s*$", s, re.I); pcs = m.group(1); s = s[:m.start()]
    s = re.sub(r"(\d+)\s*pcs?\b", r"\1 pcs", s, flags=re.I)
    # grams
    grams = None
    m = re.search(r"\(?\s*(\d+)\s*(grams?|gms?|g)\s*\)?(?=\s|$)", s, re.I)
    if m:
        grams = m.group(1)
        s = s[:m.start()] + " " + s[m.end():]
    for pat, rep in _NAME_SPELLING:
        s = re.sub(pat, rep, s, flags=re.I)
    s = re.sub(r"\s*&\s*", " & ", s)
    s = re.sub(r"\bw/\s*", "w/ ", s, flags=re.I)
    s = re.sub(r"\s*/\s*(?=[A-Za-z])", "/", s).replace("w/", "w/ ")
    s = re.sub(r"\s+", " ", s).strip(" ,:-")
    s = re.sub(r"(okonomiyaki)\s*\(([^)]+)\)", lambda m: m.group(1) + " " + m.group(2), s, flags=re.I)
    if tag == "UPGRADE" and not s.lower().startswith("upgrade"):
        s = "Upgrade " + s
    elif tag == "EXTRA" and not s.lower().startswith("extra"):
        s = "Extra " + s
    elif tag in ("MM", "M/M") and "rice" not in s.lower() and not s.lower().startswith("mix"):
        s = "Mix & Match " + s
    words = s.split(" ")
    s = " ".join(_title(w, k == 0) for k, w in enumerate(words) if w)
    s = s.replace("W/ ", "w/ ")
    low = s.lower()
    # add the kind of dish when only the tag said it
    if tag == "BSP" and "baked" not in low:
        s += " Baked Sushi Pie"
    elif tag in ("BS", "BAKED SUSHI") or (tag is None and low.endswith(" baked")):
        if "baked sushi" not in low:
            s = s + " Sushi" if low.endswith("baked") else s + " Baked Sushi"
    elif tag == "SH" and "sashimi" not in low:
        s = _insert_kind(s, "Sashimi")
    elif tag == "RM" and "ramen" not in low and "tantanmen" not in low:
        s = _insert_kind(s, "Ramen")
    elif tag == "MR" and not re.search(r"maki|roll", low):
        s = _insert_kind(s, "Roll")
    if size:
        s += f" ({size})"
    if pcs:
        s += f" ({pcs} pc)" if pcs == "1" else f" ({pcs} pcs)"
    if grams:
        s += f" ({grams} g)"
    if set_:
        s += f" (Set {set_})"
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------- raw ingredient master
# One row per thing the restaurant BUYS and STORES. MENU2 writes some ingredients as
# fixed portions (CF_060 = one 60 g chicken fillet portion) or as premixed vegetable
# portions (VDB = cabbage + carrot + togue + onion + bell pepper). Those are recipe
# notation, not separate stock, so they roll up to the raw material (MENU2_TO_RAW).
# The owner's own SUM-SALES25 calculator rolls portions up the same way (PL, SB, CF...).
#
# Meat and most seafood are bought FROZEN: the meat-and-seafood supplier is "Frozen
# seafood and meat", REFERENCES logs pork belly "FROZEN -> DEFROZED -> COOKED", and
# INGREDIENTS.xlsx sells kani, squid tubes and shrimp as boxed frozen stock (30 days  [v1-v3; SUPERSEDED in v4: 28 d]
# is a conservative frozen life; confirm with owner). Salmon, tuna and sashimi trim
# are served raw, so they stay chilled 2-day perishables.  [v1-v3; SUPERSEDED in v4: frozen 28 d, client Q1]
# generated_v4 overrides these values in client_answers.py (client Q1: frozen goods keep "up to 4 weeks+").
#
# base_uom: g = grams, pc = pieces (egg, kani stick, nori sheet, tofu piece...),
# serving = a kitchen serving the owner never weighed (MENU2 books it as "1").
# code: (name, category, storage, base_uom, shelf_life_days, name_source)
RAW_INGREDIENTS = {
    "CF":   ("Chicken Fillet",            "chicken",   "frozen",  "g",       30,  "SUM-SALES25"),
    "CT":   ("Chicken Thigh",             "chicken",   "frozen",  "g",       30,  "SUM-SALES25"),
    "PB":   ("Pork Belly",                "pork",      "frozen",  "g",       30,  "SUM-SALES25"),
    "PL":   ("Pork Loin",                 "pork",      "frozen",  "g",       30,  "SUM-SALES25"),
    "GP":   ("Ground Pork",               "pork",      "frozen",  "g",       30,  "SUPPLY-UR"),
    "SB":   ("Sukiyaki Beef",             "beef",      "frozen",  "g",       30,  "SUM-SALES25"),
    "GB":   ("Ground Beef",               "beef",      "frozen",  "g",       30,  "SUM-SALES25"),
    "SQD":  ("Squid",                     "seafood",   "frozen",  "g",       30,  "SUM-SALES25"),
    "TUN":  ("Tuna",                      "seafood",   "chilled", "g",       2,   "SUM-SALES25"),
    "SAL":  ("Salmon",                    "seafood",   "chilled", "g",       2,   "SUM-SALES25"),
    "SAS":  ("Sashimi Trim",              "seafood",   "chilled", "g",       2,   "inferred"),
    "KNI":  ("Kani (Crab Stick)",         "seafood",   "frozen",  "pc",      30,  "SUM-SALES25"),
    "EBI":  ("Nobashi Shrimp",            "seafood",   "frozen",  "pc",      90,  "SUM-SALES25"),
    "PDT":  ("Peeled Deveined Shrimp",    "seafood",   "frozen",  "pc",      30,  "SUM-SALES25"),
    "EBK":  ("Ebiko (Fish Roe)",          "seafood",   "frozen",  "g",       30,  "SUPPLY-UR"),
    "GZA":  ("Gyoza",                     "prepared",  "frozen",  "pc",      30,  "SUM-SALES25"),
    # SUS: SUPPLY-UR buys "Sushi Rice" by the kg and COSTING prices 100 g of it at that
    # kg rate, so the stocked item is the rice grain (cooked in-house daily)
    "SUS":  ("Sushi Rice",                "rice",      "ambient", "g",       365, "SUM-SALES25"),
    "EGG":  ("Egg",                       "egg",       "chilled", "pc",      21,  "SUM-SALES25"),
    "TAM":  ("Tamago (Japanese Omelette)", "egg",      "chilled", "g",       3,   "inferred"),
    "TUF":  ("Tofu",                      "tofu",      "chilled", "pc",      5,   "SUM-SALES25"),
    "CHE":  ("Cheese",                    "dairy",     "chilled", "pc",      14,  "inferred"),
    "NOD":  ("Ramen Noodles",             "noodle",    "chilled", "g",       3,   "SUM-SALES25"),
    "ENOD": ("Egg Noodles",               "noodle",    "chilled", "serving", 3,   "SUM-SALES25"),
    "SOT":  ("Sotanghon (Glass Noodles)", "noodle",    "ambient", "serving", 180, "inferred"),
    "MUS":  ("Mushroom",                  "vegetable", "chilled", "g",       5,   "SUM-SALES25"),
    "CUC":  ("Cucumber",                  "vegetable", "chilled", "g",       5,   "SUM-SALES25"),
    "CAR":  ("Carrot",                    "vegetable", "chilled", "g",       7,   "EGG+VEG"),
    "CAB":  ("Cabbage",                   "vegetable", "chilled", "g",       7,   "EGG+VEG"),
    "TOG":  ("Togue (Bean Sprouts)",      "vegetable", "chilled", "g",       3,   "EGG+VEG"),
    "ONI":  ("White Onion",               "vegetable", "ambient", "g",       30,  "EGG+VEG"),
    "BEL":  ("Bell Pepper",               "vegetable", "chilled", "g",       7,   "EGG+VEG"),
    "KAL":  ("Kalabasa (Squash)",         "vegetable", "chilled", "g",       7,   "inferred"),  # v1-v3 name; SUPERSEDED in v4: "Kalamansi" (owner O4)
    "VMO":  ("Moyashi Portion",           "vegetable", "chilled", "serving", 3,   "SUM-SALES25"),
    "BSG":  ("Benishoga (Pickled Ginger)", "condiment", "ambient", "serving", 90, "SUM-SALES25"),
    "MAY":  ("Japanese Mayonnaise",       "condiment", "chilled", "g",       30,  "SUPPLY-UR"),
    "WAS":  ("Wasabi",                    "condiment", "chilled", "g",       30,  "SUPPLY-UR"),
    "NOR":  ("Nori Sheet",                "dry goods", "ambient", "pc",      180, "SUPPLY-UR"),
    "TEM":  ("Tempura Flakes",            "dry goods", "ambient", "g",       90,  "inferred"),
    "B+B":  ("Breading and Batter Mix",   "dry goods", "ambient", "serving", 180, "SUM-SALES25"),
    "TSS":  ("Tempura Sauce",             "sauce",     "ambient", "g",       90,  "SUM-SALES25"),
    "TEP":  ("Teppanyaki Sauce",          "sauce",     "ambient", "g",       90,  "SUM-SALES25"),
    "TER":  ("Teriyaki Sauce",            "sauce",     "ambient", "serving", 90,  "SUM-SALES25"),
    "MZN":  ("Maruzen Ramen Soup Base",   "sauce",     "ambient", "g",       90,  "SUPPLY-UR"),
    "SHO":  ("Shoyu (Soy Sauce)",         "sauce",     "ambient", "g",       180, "SUM-SALES25"),
    "OKO":  ("Okonomiyaki Sauce",         "sauce",     "ambient", "g",       90,  "SUM-SALES25"),
    "ICT":  ("Iced Tea",                  "beverage",  "ambient", "pc",      180, "SUM-SALES25"),
    # BAR is not food: SUPPLY-UR lists "Baran", the plastic grass divider in sushi packs
    "BAR":  ("Baran (Sushi Grass Divider)", "packaging", "ambient", "pc",    365, "SUPPLY-UR"),
}

# MENU2 code -> [(raw code, factor, how)]: qty in raw base unit = MENU2 qty x factor.
# Portion codes (XX_NNN) are handled by rule in _to_raw: NNN grams of raw XX per portion.
# Vegetable portions (VDB/VRG/VMM/VOK) come from the EGG+VEG sheet at run time.
MENU2_TO_RAW = {
    "NOD": [("NOD", 100, "1 serving = 100 g (COSTING ramen: Ramen Noodles 100 g)")],
    "TEP": [("TEP", 45, "1 serving = 45 g (COSTING: PHP 9.86 per serving / PHP 0.219 per g)")],
    "MUS": [("MUS", 30, "1 serving = 30 g (MENU2 books mushroom as 30 g on its MUO line)")],
    "MUO": [("MUS", 1, "grams")],
    "CAR": [("CAR", 30, "1 portion = 30 g (EGG+VEG carrot portion)")],
}
VEG_PORTION_TO_RAW = {"Cabbage": "CAB", "Carrots": "CAR", "Togue": "TOG",
                      "WOnion": "ONI", "Bell Pepper": "BEL"}

# Owner's own unit rates -> PHP per base unit. SUPPLY-UR's "Unit Rate per gms" is price
# / usable qty after wastage: PHP per g for kg lines, PHP per piece for counted packs
# (Nobashi 25 pc, Kani 30 pc, Nori 100 sheets, Egg 30 pc) - COSTING's own basis.
SUPPLY_UR_COST = {
    "CF": "Chicken Fillet - leg", "CT": "Chicken Legs - boneless", "PB": "Pork Belly",
    "PL": "Porkloin", "GP": "Ground Pork", "SB": "Beef", "GB": "Ground Beef",
    "SQD": "Squid Tube", "TUN": "Tuna Steak", "SAL": "Salmon", "KNI": "Kani",
    "EBI": "Nobashi", "PDT": "PDT - shrimp", "EBK": "Ebiko", "SUS": "Sushi Rice",
    "EGG": "Egg", "MUS": "Mushroom", "CUC": "Cucumber", "CAR": "Carrots",
    "CAB": "Cabbage", "TOG": "Togue", "ONI": "White Onion", "BEL": "Bell Pepper",
    "MAY": "Mayonaise", "WAS": "Wasabi", "NOR": "Nori sheet", "MZN": "Maruzen",
    "SHO": "Shoyo Soy Sauce", "OKO": "Okonomiyaki", "NOD": "Ramen Noodles",
}
GRAMS_PER_EGG = 50.0     # TAM (tamago, g) priced from the per-egg rate; assumption
# unit costs the owner worked out on the COSTING sheet (row label -> amount)
COSTING_COST = {"TEP": "Teppanyaki Sauce - Grams",   # per g
                "TER": "Teriyaki Sauce",             # per serving (PHP 709.57 / 45 servings)
                "B+B": "Batter"}                     # per serving: egg+panko+flour+starch+oil
# No owner price exists for these; a rough market estimate per base unit keeps the
# LP budget complete.
ESTIMATED_COST = {"SAS": 0.40, "TUF": 6.25, "CHE": 10.0, "ENOD": 15.0, "SOT": 10.0,
                  "KAL": 0.10, "VMO": 10.0, "BSG": 3.0, "TEM": 0.10, "TSS": 0.15,
                  "GZA": 15.0, "ICT": 15.0, "BAR": 0.50}

# in MENU2 only on dishes that were never sold (no POS item), so never stocked
UNUSED_INGREDIENTS = {"TEM"}

# MENU2 lines that are clearly mistyped, fixed with the evidence noted.
# (dish, MENU2 code): (corrected MENU2 qty, reason)
MENU2_CORRECTIONS = {
    ("[MM] JR w/ Beef Misono & Kani Tempura", "KNI"):
        (2.0, "typed 60; every Mix & Match kani tempura is 2 kani (COSTING 'Mix&Match - 2Kani')"),
    ("[MM] JR w/ Beef Misono & Kani Tempura", "SB_050"):
        (1.2, "typed 60 (grams) under a 50 g portion code; 60 g = 1.2 portions"),
    ("[DB] Tonkatsu (Set B)", "ICT"):
        (1.0, "typed 0; Set B includes 1 iced tea (21 of 23 MENU2 Set B pairs, printed menu)"),
}
# second opinion from the supplier catalogue INGREDIENTS.xlsx (sheet "Squid" = fish
# price list, PHP per kg). Kept alongside unit_cost, not instead of it: the catalogue
# is a list price before trimming, SUPPLY-UR is the owner's usable-yield rate.
CATALOG_FILE = "INGREDIENTS.xlsx"
CATALOG_COST = {"TUN": "Tuna Loin", "SAL": "Salmon Fillet", "SQD": "Squid Tube"}
PRINTED_MENU_FILE = "MAKISUSHI-MENU.xlsx"
# column headers on the printed menu -> the suffix the POS uses for that variant
PRINTED_VARIANTS = {"SET A": " (Set A)", "SET B": " (Set B)", "REGULAR": " (Regular)",
                    "FOR SHARING": " (Sharing)", "KANI TEMPURA": " & Kani Tempura",
                    "EBI TEMPURA": " & Ebi Tempura"}
# dairy spoils like a perishable even though its nominal shelf life (14 d) is
# past the <=7-day cutoff
PERISHABLE_CATEGORIES = {"dairy"}


def _to_raw(code, veg_portions):
    """MENU2 code -> [(raw code, factor, how)]."""
    if code in MENU2_TO_RAW:
        return MENU2_TO_RAW[code]
    if code in veg_portions:                             # VDB / VRG / VMM / VOK
        return [(VEG_PORTION_TO_RAW[v], g, f"{code} portion = {g:g} g {v.lower()} (EGG+VEG)")
                for v, g in veg_portions[code].items()]
    m = re.fullmatch(r"([A-Z]+)_(\d+)", code)
    if m:                                                # portion code, e.g. CF_060
        return [(m.group(1), float(m.group(2)), f"{code} = {int(m.group(2))} g portion")]
    return [(code, 1.0, None)]


def _attrs(code):
    """(category, uom) of the raw material a MENU2 code rolls up to."""
    raw = _to_raw(code, {})[0][0]
    name, cat, storage, uom, shelf, src = RAW_INGREDIENTS.get(raw, (raw, "other", "ambient", "g", 30, "inferred"))
    return cat, uom

# ---------------------------------------------------------------- recipe cleaning
# MENU2 is a real but unvalidated spreadsheet: it contains (a) blank quantities,
# (b) rows logged twice with identical qty (harmless), (c) rows logged twice with
# DIFFERENT qty for the same dish-ingredient pair (edit history, not noise), and
# (d) a few mistyped quantities. Every resolution is logged to recipe_review.csv.
def _clean_recipe_rows(bom_raw: pd.DataFrame):
    bom_raw = bom_raw.copy()
    bom_raw["_row"] = np.arange(len(bom_raw))            # preserve original sheet order
    bom_raw["note"] = None

    # (d) documented corrections first, so they are not mistaken for conflicts
    for (dish, code), (qty, why) in MENU2_CORRECTIONS.items():
        hit = (bom_raw["item_name"] == dish) & (bom_raw["ingredient_code"] == code)
        bom_raw.loc[hit, "qty_per_unit"] = qty
        bom_raw.loc[hit, "note"] = f"corrected: {why}"

    # (a) impute blanks: same-ingredient-code median first; if an ingredient has
    #     NO real value anywhere, fall back to the median of other codes that share
    #     its category AND unit of measure.
    med_by_code = bom_raw.groupby("ingredient_code")["qty_per_unit"].median()
    blank = bom_raw["qty_per_unit"].isna()
    n_blank = int(blank.sum())
    bom_raw.loc[blank, "note"] = "imputed: blank in MENU2, median of the same code"
    bom_raw.loc[blank, "qty_per_unit"] = bom_raw.loc[blank, "ingredient_code"].map(med_by_code)
    still_blank = bom_raw["qty_per_unit"].isna()
    for code in bom_raw.loc[still_blank, "ingredient_code"].unique():
        peers = [c for c in bom_raw["ingredient_code"].unique() if _attrs(c) == _attrs(code)]
        fb = bom_raw.loc[bom_raw["ingredient_code"].isin(peers), "qty_per_unit"].median()
        hit = still_blank & (bom_raw["ingredient_code"] == code)
        bom_raw.loc[hit, "qty_per_unit"] = fb
        bom_raw.loc[hit, "note"] = "imputed: blank in MENU2, median of same-category codes"

    # (b)+(c) de-duplicate on (item_name, ingredient_code); when qty disagrees,
    #     keep the LAST row as written in the sheet (documented rule -- matches
    #     the dominant kani portion-standardization pattern found in the data).
    conflicts = (bom_raw.groupby(["item_name", "ingredient_code"])
                 .filter(lambda d: d["qty_per_unit"].nunique() > 1))
    conflict_log = (conflicts.groupby(["item_name", "ingredient_code"])["qty_per_unit"]
                     .agg(observed_values=lambda s: sorted(set(s)), resolved_value="last")
                     .reset_index())
    clean = (bom_raw.sort_values("_row")
             .drop_duplicates(subset=["item_name", "ingredient_code"], keep="last")
             .drop(columns="_row").reset_index(drop=True))

    # a line still at 0 after all of the above is a recipe gap, not a recipe fact
    zero = clean["qty_per_unit"] <= 0
    zero_log = clean.loc[zero, ["item_name", "ingredient_code"]].copy()
    clean = clean.loc[~zero].reset_index(drop=True)
    return clean, conflict_log, zero_log, n_blank

# ---------------------------------------------------------------- bom (from MENU2) + ingredient master
def build_bom_and_ingredients(cfg, supply_ref, veg_portions, costing=None, catalog=None):
    raw = pd.read_excel(cfg.src_dir / cfg.sales_file, sheet_name="MENU2", header=None)
    code_re = re.compile(r"^[A-Z+]{2,4}(_\d+)?$")    # "+" for B+B (breading + batter)
    rows = []
    for r in range(raw.shape[0]):
        c0, c1, cq = raw.iat[r, 0], raw.iat[r, 1], raw.iat[r, 4]
        if isinstance(c0, str) and code_re.match(c0.strip()) and \
           isinstance(c1, str) and c1.strip() and c1.strip() != "DESCRIPTION":
            rows.append((c1.strip(), c0.strip(), cq if isinstance(cq, (int, float)) else np.nan))
    bom_raw = pd.DataFrame(rows, columns=["item_name", "ingredient_code", "qty_per_unit"])
    m2, conflict_log, zero_log, n_blank_imputed = _clean_recipe_rows(bom_raw)

    # --- MENU2 code -> raw material, quantity in the raw material's base unit -----
    # Confirmed against dish names that state their own gram amount:
    #   "Baked Sushi Chicken 30 grams" -> CF_060 x 0.5 -> 0.5 x 60 g = 30 g (exact)
    out = []
    for r in m2.itertuples():
        for raw_code, factor, how in _to_raw(r.ingredient_code, veg_portions):
            qty = float(r.qty_per_unit) * factor
            text = f"{r.ingredient_code} x {r.qty_per_unit:g}"
            if how:
                text += f" ({how})"
            if r.note:
                text += f" [{r.note}]"
            out.append((r.item_name, raw_code, qty, r.ingredient_code, text))
    bom = pd.DataFrame(out, columns=["item_name", "ingredient_code", "qty_base",
                                     "menu2_code", "derivation"])
    # one dish can reach the same raw material twice (a VDB portion and a CAR line)
    bom = (bom.groupby(["item_name", "ingredient_code"], as_index=False, sort=False)
              .agg(qty_base=("qty_base", "sum"),
                   menu2_code=("menu2_code", lambda s: ", ".join(dict.fromkeys(s))),
                   derivation=("derivation", " + ".join)))
    bom["qty_base"] = bom["qty_base"].round(4)

    # --- ingredient master: every raw material that some recipe uses -----------
    codes = sorted(bom["ingredient_code"].unique())
    codes = [c for c in codes if c not in UNUSED_INGREDIENTS]
    bom = bom[bom["ingredient_code"].isin(codes)].reset_index(drop=True)
    unknown = [c for c in codes if c not in RAW_INGREDIENTS]
    if unknown:
        raise ValueError(f"MENU2 codes with no raw-ingredient entry: {unknown}")
    im = pd.DataFrame({"ingredient_code": codes})
    attrs = im["ingredient_code"].map(RAW_INGREDIENTS)
    im["ingredient_name"] = attrs.str[0]
    im["category"] = attrs.str[1]
    im["storage_type"] = attrs.str[2]
    im["uom"] = attrs.str[3]
    im["shelf_life_days"] = attrs.str[4].astype(int)
    im["is_perishable"] = (im["shelf_life_days"] <= 7) | im["category"].isin(PERISHABLE_CATEGORIES)
    im["unit_cost"], im["cost_source"] = price_ingredients(im, supply_ref, costing)
    catalog = catalog or {}
    im["catalog_unit_cost"] = [round(catalog[CATALOG_COST[c]] / 1000, 4)
                               if CATALOG_COST.get(c) in catalog else np.nan
                               for c in im["ingredient_code"]]
    im["name_source"] = attrs.str[5]
    used = bom.groupby("ingredient_code")["menu2_code"].agg(
        lambda s: ", ".join(sorted(set(", ".join(s).split(", ")))))
    im["menu2_codes"] = im["ingredient_code"].map(used)
    im.insert(0, "ingredient_id", stable_ids(im["ingredient_code"], cfg, "ingredients",
                                             "ingredient_code", "ingredient_id"))
    im = im.sort_values("ingredient_id").reset_index(drop=True)

    bom.attrs["conflict_log"] = conflict_log
    bom.attrs["zero_log"] = zero_log
    bom.attrs["n_blank_imputed"] = n_blank_imputed
    return bom, im

# ---------------------------------------------------------------- real supplier rates (SUPPLY-UR) — reference only
def build_supply_ref(cfg):
    su = pd.read_excel(cfg.src_dir / cfg.sales_file, sheet_name="SUPPLY-UR", header=None)
    num = lambda v: float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else np.nan
    out = []
    for r in range(su.shape[0]):
        p = su.iat[r, 2]
        if isinstance(p, str) and p.strip() and p.strip().upper() != "PRODUCT":
            unit = su.iat[r, 5]
            out.append((p.strip(), str(unit).strip().lower() if isinstance(unit, str) else None,
                        num(su.iat[r, 6]), num(su.iat[r, 7]), num(su.iat[r, 10]),
                        num(su.iat[r, 12])))
    ref = pd.DataFrame(out, columns=["product", "unit", "detailed_qty", "unit_rate_php",
                                     "fluctuation_pct", "rate_per_base"])
    # a kg line with no "Detailed Quantity" (Benishoga, Wasabi) has rate_per_base 0 in
    # the sheet; rebuild it the sheet's own way: price / (1000 g x (1 - wastage))
    fix = (ref["rate_per_base"].fillna(0) <= 0) & (ref["unit"] == "kg") & ref["unit_rate_php"].gt(0)
    ref.loc[fix, "rate_per_base"] = (ref.loc[fix, "unit_rate_php"]
                                     / (1000 * (1 - ref.loc[fix, "fluctuation_pct"].fillna(0))))
    return ref.drop_duplicates("product", keep="last").reset_index(drop=True)

def build_veg_portions(cfg):
    """EGG+VEG sheet: grams of each vegetable in one VMM/VDB/VRG/VOK portion."""
    ev = pd.read_excel(cfg.src_dir / cfg.sales_file, sheet_name="EGG+VEG", header=None)
    hdr = next(r for r in range(ev.shape[0]) if "Cabbage" in list(ev.iloc[r].astype(str)))
    cols = {str(ev.iat[hdr, c]).strip(): c for c in range(ev.shape[1]) if isinstance(ev.iat[hdr, c], str)}
    out = {}
    for r in range(hdr + 1, ev.shape[0]):
        code = ev.iat[r, 0]
        if isinstance(code, str) and code.strip() and code.strip() not in out:
            g = {veg: ev.iat[r, c] for veg, c in cols.items() if veg in VEG_PORTION_TO_RAW}
            out[code.strip()] = {v: float(q) for v, q in g.items() if isinstance(q, (int, float)) and q > 0}
    return out

def build_costing_rates(cfg):
    """COSTING sheet: label in column B -> amount in column F."""
    cs = pd.read_excel(cfg.src_dir / cfg.sales_file, sheet_name="COSTING", header=None)
    # labels sit in column B, except block totals ("Batter", "Tempura Bater") in D
    out = {}
    for r in range(cs.shape[0]):
        amt = cs.iat[r, 5]
        for lab in (cs.iat[r, 1], cs.iat[r, 3]):
            if isinstance(lab, str) and isinstance(amt, (int, float)) and amt > 0:
                out.setdefault(lab.strip(), float(amt))
    return out

def build_catalog_prices(cfg):
    """INGREDIENTS.xlsx fish list: product -> PHP per kg (column C of sheet 'Squid')."""
    path = cfg.src_dir / CATALOG_FILE
    if not path.exists():
        return {}
    sq = pd.read_excel(path, sheet_name="Squid", header=None)
    return {str(sq.iat[r, 0]).strip(): float(sq.iat[r, 2]) for r in range(sq.shape[0])
            if isinstance(sq.iat[r, 0], str) and isinstance(sq.iat[r, 2], (int, float))}

def build_printed_prices(cfg):
    """MAKISUSHI-MENU.xlsx: (dish name + variant suffix, price) for every numeric price."""
    path = cfg.src_dir / PRINTED_MENU_FILE
    if not path.exists():
        return pd.DataFrame(columns=["printed_name", "printed_price"])
    pm = pd.read_excel(path, header=None)
    labels, rows = {}, []
    for r in range(pm.shape[0]):
        cells = {c: pm.iat[r, c] for c in range(2, pm.shape[1]) if pd.notna(pm.iat[r, c])}
        heads = {c: str(v).strip().upper() for c, v in cells.items()
                 if isinstance(v, str) and str(v).strip().upper() in PRINTED_VARIANTS}
        if heads:
            labels = heads
            continue
        name = pm.iat[r, 1]
        if not isinstance(name, str) or not name.strip():
            continue
        for c, v in cells.items():
            if isinstance(v, (int, float)) and v > 0:
                rows.append((name.strip() + PRINTED_VARIANTS.get(labels.get(c), ""), float(v)))
    return pd.DataFrame(rows, columns=["printed_name", "printed_price"])

def attach_printed_prices(dim_menu, printed):
    """printed_menu_price: the printed-menu price of the same dish and variant, if any."""
    # a name printed in two sections at two prices ("CHEESY BEEF" okonomiyaki 280 vs
    # baked sushi 285) can't be told apart without the section, so it is dropped
    by_key = {}
    for n, p in zip(printed["printed_name"], printed["printed_price"]):
        by_key.setdefault(_recipe_key(n), set()).add(p)
    keyed = {k: next(iter(v)) for k, v in by_key.items() if len(v) == 1}
    def look(name):
        k = _recipe_key(name)
        if k in keyed:
            return keyed[k]
        if k[0] is None:                    # POS name without a set = the Set A price
            return keyed.get(("A",) + k[1:])
        return np.nan
    dim_menu["printed_menu_price"] = [look(n) for n in dim_menu["item_name"]]
    return dim_menu

def price_ingredients(im, supply_ref, costing=None):
    """unit_cost (PHP per base unit) + cost_source for every raw ingredient,
    owner sources first, a labelled estimate only where the owner has no price."""
    rate = supply_ref.set_index("product")["rate_per_base"]
    costing = costing or {}
    costs, sources = [], []
    for code in im["ingredient_code"]:
        prod = SUPPLY_UR_COST.get(code)
        if prod and rate.get(prod, 0) > 0:
            costs.append(float(rate[prod])); sources.append(f"SUPPLY-UR: {prod}")
        elif COSTING_COST.get(code) in costing:
            costs.append(costing[COSTING_COST[code]]); sources.append(f"COSTING: {COSTING_COST[code]}")
        elif code == "TAM" and rate.get("Egg", 0) > 0:
            costs.append(float(rate["Egg"]) / GRAMS_PER_EGG)
            sources.append(f"SUPPLY-UR: Egg / {GRAMS_PER_EGG:.0f} g per egg")
        elif code in ESTIMATED_COST:
            costs.append(ESTIMATED_COST[code]); sources.append("estimate (no owner price)")
        else:
            raise ValueError(f"no price rule for ingredient {code}")
    return np.round(costs, 4), sources

# ---------------------------------------------------------------- dim_supplier (SYNTHETIC)
# Makisushi has no supplier records, so the supply side is a synthetic scenario
# built for simulation and LP testing. The four names are the team's chosen
# supplier names; what each supplies, and on what terms, is a modelling
# assumption and is not claimed to describe the real businesses. The values are
# modelled on how Metro Manila food suppliers publicly operate (next-day / daily
# seafood and produce delivery, weekly dry-goods runs). No contact details are
# stored.
#   lead_time_days         - order placed -> order received (0 = same day)
#   delivery_interval_days - how often the supplier can deliver (1 = daily)
#   lead_time_sd_days, fill_rate - delivery noise used by the simulation and for
#                            safety stock; not part of the LP's hard constraints
# name : (supplier_type, service_area, lead_time_days, lead_time_sd_days,
#         fill_rate, delivery_interval_days)
SUPPLIERS = {
    "FUJI MART JAPANESE FOOD STORE": ("Japanese ingredients, sauces & condiments", "Quezon City / Metro Manila", 1, 0.4, 0.96, 2),
    "UMA'I JAPANESE GROCERY":        ("Seafood, meat & poultry",                   "Metro Manila",               1, 0.3, 0.97, 1),
    "KYOTO MART":                    ("Fresh produce, eggs, dairy & tofu",         "Quezon City",                0, 0.2, 0.97, 1),
    "HI-TOP":                        ("Rice & dry staples",                        "Quezon City / Manila",       1, 0.5, 0.95, 7),
}
FUJI, UMAI, KYOTO, HITOP = SUPPLIERS

# ---------------------------------------------------------------- supplier_item_terms (SYNTHETIC)
# How each ingredient is packed and sold by its (synthetic) supplier: supplier
# information, not purchase history. pack_size is in pack_unit as a buyer would
# read it (1 kg, 1.8 L, 50 sheets); pack_size_base is the same pack in the
# ingredient's own base unit (g / pc / serving), which the model uses.
# Minimum order = min_order_packs x pack_size_base. Perishables are sized to what
# the kitchen can use before they expire, and every minimum is 1 pack except
# where a case is the normal selling unit. Conversions: sauces at ~1 g per ml;   [v1-v3; SUPERSEDED in v4: cited densities]
# kani and peeled shrimp at ~20 g a piece.
# generated_v4 replaces the salmon / tuna packs (whole fish, client Q4) and converts the litre sauces at cited
# densities (client_answers.SAUCE_DENSITY); every pack also carries a usable fraction (owner O2).
# code : (supplier, order_unit, pack_size, pack_unit, pack_size_base, min_order_packs)
SUPPLIER_ITEM_TERMS = {
    # UMA'I - seafood. Salmon and tuna come as ~250 g saku blocks (sashimi-grade
    # loin cut to order): a 1 kg pack is ~6 days of salmon against a 2-day life.  [v1-v3; SUPERSEDED in v4: whole fish]
    "SAL":  (UMAI,   "saku block", 250,  "g",       250,   1),
    "TUN":  (UMAI,   "saku block", 250,  "g",       250,   1),
    "SAS":  (UMAI,   "pack",       250,  "g",       250,   1),
    "EBK":  (UMAI,   "tub",        500,  "g",       500,   1),
    "SQD":  (UMAI,   "pack",       1,    "kg",      1000,  1),
    "EBI":  (UMAI,   "tray",       30,   "pc",      30,    1),
    "PDT":  (UMAI,   "pack",       1,    "kg",      50,    1),
    "KNI":  (UMAI,   "pack",       1,    "kg",      50,    1),
    # FUJI MART - Japanese ingredients
    "NOR":  (FUJI,   "pack",       50,   "sheets",  50,    1),
    "NOD":  (FUJI,   "pack",       1,    "kg",      1000,  1),
    "ENOD": (FUJI,   "pack",       5,    "serving", 5,     1),
    "SOT":  (FUJI,   "pack",       10,   "serving", 10,    1),
    "MZN":  (FUJI,   "pack",       1,    "kg",      1000,  1),
    "TAM":  (FUJI,   "block",      250,  "g",       250,   1),
    # KYOTO MART - produce, sold loose by weight; also dairy, tofu and eggs
    "CUC":  (KYOTO,  "kg",         1,    "kg",      1000,  1),
    "CAB":  (KYOTO,  "kg",         1,    "kg",      1000,  1),
    "CAR":  (KYOTO,  "kg",         0.5,  "kg",      500,   1),
    "ONI":  (KYOTO,  "kg",         0.5,  "kg",      500,   1),
    "KAL":  (KYOTO,  "kg",         0.5,  "kg",      500,   1),
    "BEL":  (KYOTO,  "kg",         0.25, "kg",      250,   1),
    "TOG":  (KYOTO,  "kg",         0.25, "kg",      250,   1),
    "MUS":  (KYOTO,  "pack",       100,  "g",       100,   1),
    "TUF":  (KYOTO,  "block",      1,    "pc",      1,     1),
    "VMO":  (KYOTO,  "portion",    1,    "serving", 1,     1),
    "CHE":  (KYOTO,  "pack",       10,   "slices",  10,    1),
    "EGG":  (KYOTO,  "tray",       30,   "pc",      30,    1),
    # HI-TOP - rice and dry staples
    "SUS":  (HITOP,  "sack",       25,   "kg",      25000, 1),
    "B+B":  (HITOP,  "bag",        50,   "serving", 50,    1),
    "BAR":  (HITOP,  "pack",       100,  "pc",      100,   1),
    "ICT":  (HITOP,  "case",       24,   "pc",      24,    1),
    # UMA'I - meat and poultry (frozen)
    "CF":   (UMAI,   "pack",       2,    "kg",      2000,  1),
    "CT":   (UMAI,   "pack",       2,    "kg",      2000,  1),
    "PL":   (UMAI,   "pack",       2,    "kg",      2000,  1),
    "PB":   (UMAI,   "pack",       1,    "kg",      1000,  1),
    "GP":   (UMAI,   "pack",       1,    "kg",      1000,  1),
    "SB":   (UMAI,   "pack",       1,    "kg",      1000,  1),
    "GZA":  (UMAI,   "pack",       50,   "pc",      50,    1),
    # FUJI MART - sauces and condiments
    "SHO":  (FUJI,   "bottle",     1.8,  "L",       1800,  2),
    "TSS":  (FUJI,   "bottle",     1.8,  "L",       1800,  1),
    "TEP":  (FUJI,   "bottle",     1,    "L",       1000,  1),
    "OKO":  (FUJI,   "bottle",     500,  "g",       500,   1),
    "MAY":  (FUJI,   "pouch",      500,  "g",       500,   1),
    "WAS":  (FUJI,   "pack",       500,  "g",       500,   1),
    "BSG":  (FUJI,   "tub",        50,   "serving", 50,    1),
    "TER":  (FUJI,   "pack",       10,   "serving", 10,    1),
}
_TO_BASE = {"kg": 1000, "g": 1, "L": 1000}     # checked where the conversion is plain


def build_dim_supplier(cfg, rng=None):
    rows = [dict(supplier_id=i, supplier_name=n, supplier_type=t, service_area=a,
                 lead_time_days=lt, lead_time_sd_days=sd, fill_rate=fr,
                 delivery_interval_days=di)
            for i, (n, (t, a, lt, sd, fr, di)) in enumerate(SUPPLIERS.items(), 1)]
    return pd.DataFrame(rows)


def build_supplier_item_terms(dim_ing, dim_sup):
    sid = dict(zip(dim_sup["supplier_name"], dim_sup["supplier_id"]))
    missing = sorted(set(dim_ing["ingredient_code"]) - set(SUPPLIER_ITEM_TERMS))
    if missing:
        raise ValueError(f"no supplier_item_terms for: {missing}")
    rows = []
    for r in dim_ing.itertuples():
        sup, unit, size, pu, base, moq = SUPPLIER_ITEM_TERMS[r.ingredient_code]
        if pu in _TO_BASE and r.uom == "g" and abs(size * _TO_BASE[pu] - base) > 1e-9:
            raise ValueError(f"{r.ingredient_code}: {size} {pu} is not {base} g")
        rows.append(dict(supplier_id=sid[sup], ingredient_id=r.ingredient_id,
                         order_unit=unit, pack_size=size, pack_unit=pu,
                         pack_size_base=base, min_order_packs=moq))
    return pd.DataFrame(rows).sort_values(["supplier_id", "ingredient_id"]).reset_index(drop=True)

# ---------------------------------------------------------------- link + build all
def _norm(s):
    s = re.sub(r"\[[A-Za-z]+\)?", "", str(s)).replace("(", " ").replace(")", " ").replace("/", " ")
    s = re.sub(r"\bset\b", "", s, flags=re.I); s = re.sub(r"\bw/\b", " ", s, flags=re.I)
    return re.sub(r"\s+", " ", s).upper().strip()

# ---------------------------------------------------------------- recipe linking
# MENU2 names a dish one way ("Gyoza 4pcs"), the POS another ("[ST] Gyoza (4pcs)",
# "[PR] 4pcs Gyoza", GrabFood "TONKATSU set A"). A menu item with no exact recipe
# borrows the recipe of the MENU2 dish with the same normalised name, provided set
# (A/B), piece count and regular/sharing size all agree. Every link is exported to
# recipe_links.csv so the owner can confirm or reject it.
SET_B_ADDONS = {"ICT": 1.0, "KNI": 0.25}   # modal Set B - Set A difference across MENU2's
                                           # 23 A/B pairs; printed menu: "kani salad & iced tea"
LINK_THRESHOLD = 0.90
_SPELLING = [("terriyaki", "teriyaki"), ("chicekn", "chicken"), ("shoyo", "shoyu"),
             ("gyosa", "gyoza"), ("calfornia", "california"), ("cali ", "california "),
             ("phildelphia", "philadelphia"), ("tonkots ", "tonkotsu "), ("donburi", "don buri")]
_FILLER = r"\b(regular|reg|for|the|with|w|and|a la carte|ala carte|order|orders|of)\b"

def _recipe_key(name):
    """(set, piece sizes, sharing?, gram portion, normalised name) for recipe matching."""
    s = " " + str(name).lower() + " "
    s = re.sub(r"[\[\(]rm[\]\)]", " ramen ", s)          # a ramen is never a rice bowl
    s = re.sub(r"[\[\(](db|mr|atf|st|pr|sm|mm|vm|sb|bs|bsp|sh|sl|pl|ds|d|alc|extra|baked sushi)[\]\)]", " ", s)
    s = s.replace("baked sushi]", "baked sushi ")
    m = re.search(r"\bset\s*([ab])\b|\(([ab])\)", s)
    set_ = (m.group(1) or m.group(2)).upper() if m else None
    s = re.sub(r"\bset\s*[ab]\b|\([ab]\)", " ", s)
    sizes = tuple(sorted(re.findall(r"(\d+)\s*(?:pcs?|pieces?)\b", s)))
    sharing = "sharing" in s
    grams = re.search(r"(\d+)\s*(?:grams?|gms?|g)\b", s)
    grams = grams.group(1) if grams else None
    s = s.replace("&", " and ").replace("w/", " with ").replace("/", " ")
    for a, b in _SPELLING:
        s = s.replace(a, b)
    s = re.sub(r"\d+\s*(pcs?|pieces?|grams?|gms?|g)\b", " ", s)
    s = re.sub(r"sharing", " ", s)
    s = re.sub(_FILLER, " ", s)
    s = re.sub(r"[^a-z ]", " ", s)
    return set_, sizes, sharing, grams, " ".join(sorted(s.split()))

def link_recipes(bom, dim_menu):
    """Give menu items without a recipe the recipe of their matching MENU2 dish."""
    from difflib import SequenceMatcher
    have = set(bom["item_id"].dropna().astype(int))
    dishes = {d: _recipe_key(d) for d in bom["item_name"].unique()}
    links, extra = [], []
    for item_id, name in zip(dim_menu["item_id"], dim_menu["item_name"]):
        if item_id in have:
            continue
        t_set, t_size, t_share, t_g, t_key = _recipe_key(name)
        if not t_key:
            continue
        best = None
        for dish, (c_set, c_size, c_share, c_g, c_key) in dishes.items():
            if c_size != t_size or c_share != t_share or not c_key:
                continue
            if t_g != c_g:                  # a 50 g portion never borrows a 30 g recipe
                continue
            if not (c_set == t_set or (t_set == "B" and c_set == "A")
                    or (t_set is None and c_set in (None, "A"))):
                continue
            score = 1.0 if c_key == t_key else SequenceMatcher(None, t_key, c_key).ratio()
            # same set beats the Set-A fallback; then higher score
            rank = (score, c_set == t_set)
            if score >= LINK_THRESHOLD and (best is None or rank > best[0]):
                best = (rank, dish, c_set)
        if best is None:
            continue
        (score, _), dish, c_set = best
        rows = bom[bom["item_name"] == dish][["ingredient_code", "qty_base", "menu2_code",
                                              "derivation"]].copy()
        rule = "NAME_MATCH"
        if t_set == "B" and c_set == "A":
            rule = "NAME_MATCH+SET_B"
            for code, q in SET_B_ADDONS.items():
                if code not in set(rows["ingredient_code"]):
                    rows.loc[len(rows)] = [code, q, code,
                                           f"{code} x {q:g} (Set B rule: Set A + iced tea + kani salad)"]
        rows["item_name"], rows["item_id"] = dish, item_id
        rows["recipe_source"], rows["source_dish"] = rule, dish
        extra.append(rows)
        links.append(dict(item_id=item_id, item_name=name, menu2_dish=dish,
                          score=round(score, 3), rule=rule))
    attrs, bom.attrs = bom.attrs, {}           # concat can't compare DataFrame-valued attrs
    linked = pd.concat([bom] + extra, ignore_index=True) if extra else bom
    linked.attrs = attrs
    return linked, pd.DataFrame(links, columns=["item_id", "item_name", "menu2_dish", "score", "rule"])

def build_dimensions(cfg=CFG, rng=RNG):
    dim_date = build_dim_date(cfg)
    dim_menu = attach_printed_prices(build_dim_menu_item(cfg), build_printed_prices(cfg))
    supply_ref = build_supply_ref(cfg)
    bom, dim_ing = build_bom_and_ingredients(cfg, supply_ref, build_veg_portions(cfg),
                                             build_costing_rates(cfg), build_catalog_prices(cfg))
    dim_sup = build_dim_supplier(cfg, rng)
    imap = {_norm(n): i for n, i in zip(dim_menu["item_name"], dim_menu["item_id"])}
    cmap = {c: i for c, i in zip(dim_ing["ingredient_code"], dim_ing["ingredient_id"])}
    bom["item_id"]       = bom["item_name"].map(lambda n: imap.get(_norm(n)))
    bom["recipe_source"] = "MENU2"
    bom["source_dish"]   = bom["item_name"]
    bom, recipe_links = link_recipes(bom, dim_menu)
    bom["ingredient_id"] = bom["ingredient_code"].map(cmap)
    # some dishes are logged under 2+ spelling variants in MENU2 (e.g. "Yakisoba
    # (for sharing)" / "Yakisoba For Sharing") that both resolve to the same
    # item_id; once linked, collapse any resulting (item_id, ingredient_id)
    # duplicates the same way as the name-level cleaning above.
    linked_dup = bom["item_id"].notna() & bom.duplicated(subset=["item_id", "ingredient_id"], keep="last")
    bom = bom.loc[~linked_dup].reset_index(drop=True)
    return dict(dim_date=dim_date, dim_menu_item=dim_menu, dim_ingredient=dim_ing,
                dim_supplier=dim_sup, bom=bom, supply_ref=supply_ref,
                supplier_item_terms=build_supplier_item_terms(dim_ing, dim_sup),
                recipe_review=build_recipe_review(bom, recipe_links))


def build_recipe_review(bom, links):
    """Everything done to the owner's recipes, one line each, for the owner to
    confirm: corrections, imputed blanks, conflicting duplicates, dropped zero
    lines, and recipes borrowed by name."""
    out = []
    corrected = bom[bom["derivation"].str.contains(r"\[corrected", regex=True)]
    for r in corrected.drop_duplicates(["source_dish", "menu2_code"]).itertuples():
        out.append(("CORRECTION", r.source_dish, r.menu2_code, r.derivation))
    imputed = bom[bom["derivation"].str.contains(r"\[imputed", regex=True)]
    for r in imputed.drop_duplicates(["source_dish", "menu2_code"]).itertuples():
        out.append(("IMPUTED_BLANK", r.source_dish, r.menu2_code, r.derivation))
    for r in bom.attrs.get("conflict_log", pd.DataFrame()).itertuples():
        out.append(("CONFLICT_RESOLVED", r.item_name, r.ingredient_code,
                    f"MENU2 lists {r.observed_values}; the last one ({r.resolved_value:g}) is kept"))
    for r in bom.attrs.get("zero_log", pd.DataFrame()).itertuples():
        out.append(("DROPPED_ZERO", r.item_name, r.ingredient_code,
                    "quantity is 0 in MENU2; line left out until the owner gives the amount"))
    for r in links.itertuples():
        out.append((r.rule, r.item_name, None,
                    f"POS item has no MENU2 recipe of its own; uses '{r.menu2_dish}' "
                    f"(name similarity {r.score:.2f})"))
    return pd.DataFrame(out, columns=["review_type", "dish", "menu2_code", "detail"])

# ================================================================ verify
if __name__ == "__main__":
    D = build_dimensions()
    print("="*62, "\nSHAPES")
    for k, v in D.items():
        print(f"  {k:16s} {v.shape}")
    dd, dm, di, bom = D["dim_date"], D["dim_menu_item"], D["dim_ingredient"], D["bom"]
    print("\ndim_date:", dd['date'].min().date(), "->", dd['date'].max().date(),
          "| PH holidays:", int(dd['is_holiday'].sum()), "| paydays:", int(dd['is_payday'].sum()))
    print("\ndim_ingredient: n=%d  perishable=%d  names inferred=%d" %
          (len(di), int(di['is_perishable'].sum()), int((di['name_source'] == 'inferred').sum())))
    print(di[["ingredient_code","ingredient_name","category","storage_type","shelf_life_days","uom","is_perishable","unit_cost"]].head(10).to_string(index=False))

    # BOM coverage, volume-weighted
    s = pd.read_excel(CFG.src_dir/CFG.sales_file, sheet_name="SALES'26")
    units = s.groupby("Item name")["Items sold"].sum()
    have = {_norm(n) for n in bom["item_name"].unique()}
    cov = units[[_norm(i) in have for i in units.index]].sum()
    print("\nbom: rows=%d  dishes=%d  ingredient links complete=%s" %
          (len(bom), bom["item_name"].nunique(), bom["ingredient_id"].notna().all()))
    print("  menu items linked to an item_id: %d/%d  (bom rows with no item_id: %d)" %
          (bom["item_id"].dropna().nunique(), len(dm), int(bom["item_id"].isna().sum())))
    print("  VOLUME-weighted recipe coverage: %.1f%% of units sold (uncovered = mostly drinks)" % (cov/units.sum()*100))

    print("\n--- recipe cleaning results ---")
    print("  blank quantities imputed (median-based, not a flat constant):", bom.attrs.get("n_blank_imputed"))
    dup_check = bom.duplicated(subset=["item_id", "ingredient_id"], keep=False)
    print("  duplicate (item,ingredient) rows remaining:", int(dup_check.sum()), "(should be 0)")
    clog = bom.attrs.get("conflict_log")
    print(f"  conflicting pairs resolved (last-occurrence rule): {len(clog)}")
    print(clog.to_string(index=False))

    print("\n  sample recipe [MR] California Maki (MENU2 code -> raw ingredient):")
    print(bom.loc[bom.item_name == "[MR] California Maki",
                   ["ingredient_code", "qty_base", "derivation"]].to_string(index=False))
    print("\nrecipe review lines:", D["recipe_review"]["review_type"].value_counts().to_dict())
    print("\nsupply_ref (real rates for later cost/yield merge): rows=%d, with fluctuation%%=%d" %
          (len(D["supply_ref"]), int(D["supply_ref"]["fluctuation_pct"].notna().sum())))
    print(D["supply_ref"].dropna(subset=["unit_rate_php"]).head(5).to_string(index=False))
    print("\ndim_supplier:")
    print(D["dim_supplier"].to_string(index=False))
