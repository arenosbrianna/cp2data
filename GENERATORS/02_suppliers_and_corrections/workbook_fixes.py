"""Corrections that make generated_v4 agree with the owner's workbooks, cell by cell (audit 2026-10-07).

makisushi_Jan_2026.xlsx
  MENU2 lists some platters as one line per component, with the component named in column F
  ("[PL] Medium Party Tray" KNI 2 KANI + KNI 2 CRAZY KANI ROLL + KNI 1 CALIFORNIA MAKI). The generator
  de-duplicated (dish, code) pairs keeping the last row, so a platter kept one component only. Here the
  components are summed. Rows that repeat the same quantity without naming a component ([MR] California
  Maki SUS 100 twice) stay one line: SUM-SALES25 (the owner's own calculator, 2026-08-31) books 3
  California maki as 300 g of rice, i.e. 100 g a roll.
  MENU2 has two "Katsudon" dishes: ANNIVERSARY PROMO 2025 (row 808, PL_060 x 1) and MANAGEMENT (row 867,
  PL_060 x 2). The promo POS items took the MANAGEMENT pork line; they get the promo row's.
MAKISUSHI-MENU.xlsx
  printed_menu_price is set from an explicit map of every price cell to the POS items of the same dish and
  variant; the generator's parser misread slash prices (88/150), SMALL/LARGE, the Mix & Match tempura
  columns and 4/8-piece sizes (gyoza 8 pcs got the 4-piece 238).
POS export text
  'Lemonadeüçã' is the lemon emoji mis-decoded in the SALES'26 export, like '3pcs K√†ni Tempura'.
"""
import pandas as pd

MENU2 = "makisushi_Jan_2026.xlsx MENU2"

# POS item name -> {raw code: (qty in the raw base unit, MENU2 rows and reason)}
MENU2_COMPONENTS = {
    '[PL] Medium Party Tray': {'KNI': (5.0, 'rows 636 / 638 / 640: KNI 2 (KANI) + 2 (CRAZY KANI ROLL) + 1 (CALIFORNIA MAKI)')},
    '[PL] Seafood Platter Maki Rolls': {'SAL': (80.0, 'rows 670 / 674: SAL 50 (Crunchy Salmon Aburi) + 30 (Phila Salmon)')},
    'Super supreme': {'KNI': (3.0, 'rows 887 / 889: KNI 2 (CRUNCHY KANI) + 1 (PHILA)')},
    'supreme': {'KNI': (3.0, 'copy of Super supreme; rows 887 / 889: KNI 2 (CRUNCHY KANI) + 1 (PHILA)')},
    '[PL] Super Supreme Mixed Maki': {'KNI': (3.0, 'rows 643 / 645: KNI 2 (CRUNCHY KANI) + 1 (PHILA)')},
    '[HS] Mixed Maki Rolls': {'KNI': (0.75, 'rows 599 / 601: KNI 0.25 (CALIFORNIA MAKI) + 0.5 (KANI)')},
    '[PL] Special Mixed Sushi Maki Salmon & Tuna Sashimi': {
        'KNI': (9.0, 'rows 664 / 669: KNI 6 + 3 (CALIFORNIA MAKI)')},
    '[PL] Small Party Tray': {'KNI': (4.0, 'row 629: KNI 4 as written; row 631 (CALI MAKI) has no quantity, '
                                           'so the median imputation (2) that replaced it is dropped')},
    '[HS] Mixed Sushi & Sashimi': {'KNI': (1.5, 'rows 610 / 612: KNI 1 + 0.5 (SUSHI); the printed menu lists 2 pcs '
                                                'kani sushi and 4 pcs california')},
    'Mixed sushi and sashimi': {'KNI': (1.5, 'rows 604 / 606: KNI 1 + 0.5 (SUSHI); the printed menu lists 2 pcs kani '
                                             'sushi and 4 pcs california')},
    'Katsudon': {'PL': (60.0, 'row 808 (ANNIVERSARY PROMO 2025 section): PL_060 x 1; row 867 (PL_060 x 2) is the '
                              'MANAGEMENT dish of the same name')},
    '[PR] Katsudon': {'PL': (60.0, 'row 808 (ANNIVERSARY PROMO 2025 section): PL_060 x 1')},
}
ADJUSTED_BY = 'workbook:menu2_components'


def apply_menu2_components(df, qty, names):
    """Set the summed / promo quantities on the matching recipe lines (bom or recipes.csv layout)."""
    df = df.copy()
    hits = 0
    for item, lines in MENU2_COMPONENTS.items():
        ids = names[names == item].index
        assert len(ids) == 1, f'{item}: {len(ids)} menu items'
        for code, (q, why) in lines.items():
            k = (df['item_id'] == ids[0]) & (df['ingredient_code'] == code)
            assert k.sum() == 1, f'{item} {code}: {k.sum()} lines'
            df.loc[k, qty] = q
            df.loc[k, 'qty_adjusted_by'] = ADJUSTED_BY
            df.loc[k, 'derivation'] = f'{MENU2} {why} = {q:g}'
            hits += 1
    return df, hits


# ---- MAKISUSHI-MENU.xlsx Sheet1: price cell -> POS item ids (same dish and variant) ------------------------
# (cell, printed price, item ids). Promo, GrabFood and MANAGEMENT listings of the same dish carry the printed
# price of that dish, as before; the POS price stays in menu_items.price.
PRINTED = [
    # DON BURI, SET A (column I) / SET B (column K)
    ('I5', 255, [235, 56]), ('K5', 315, [237, 236]),
    ('I7', 255, [262]), ('K7', 315, [263]),
    ('I8', 260, [267, 147]), ('K8', 340, [268]),
    ('I9', 260, [246, 245, 81]), ('K9', 340, [247]),
    ('I10', 260, [275, 163, 169]), ('K10', 355, [276]),
    ('I11', 275, [282, 172, 170, 381]), ('K11', 355, [283]),
    ('I12', 275, [285, 284]), ('K12', 355, [286]),
    ('I13', 275, [240, 242, 239, 50]), ('K13', 355, [234, 241]),
    ('I14', 275, [232, 46, 43, 42, 376]), ('K14', 355, [233]),
    ('I15', 275, [277, 166, 168]), ('K15', 355, [278]),
    ('I16', 315, [280, 279]), ('K16', 385, [281]),
    ('I20', 260, [273, 157]), ('K20', 355, [274]),
    ('I22', 275, [258, 257, 85, 377]), ('K22', 355, [259]),
    ('I23', 275, [269]), ('K23', 355, [270]),
    ('I24', 275, [223, 224, 266]), ('K24', 355, [221, 222]),
    ('I25', 275, [264, 126, 380, 127, 128]), ('K25', 355, [265]),
    ('I26', 275, [248, 250]), ('K26', 355, [249, 251]),
    ('I27', 315, [252, 253]), ('K27', 385, [254]),
    ('I31', 310, [271, 154]), ('K31', 350, [272]),
    ('I32', 340, [243]), ('K32', 370, [244]),
    ('I33', 350, [225, 28]), ('K33', 385, [226]),
    ('I34', 350, [230]), ('K34', 385, [231]),
    ('I35', 350, [228, 227]), ('K35', 385, [229]),
    ('I38', 335, [260, 104]), ('K38', 375, [261]),
    ('I39', 335, [255, 84, 83]), ('K39', 375, [256]),
    # RAMEN (column I)
    ('I44', 310, [387, 145, 148]), ('I45', 340, [394, 167]), ('I46', 350, [385, 82]), ('I47', 350, [386, 143]),
    ('I48', 350, [388, 144, 146]), ('I49', 360, [393, 161, 162]), ('I50', 360, [384]), ('I51', 385, [383, 382]),
    ('I52', 385, [390, 391, 152]), ('I53', 385, [389]), ('I54', 385, [392]),
    # MIX & MATCH: KANI TEMPURA (column H) / EBI TEMPURA (column J)
    ('H60', 225, [330, 90, 98]), ('J60', 245, [329, 103, 333]),
    ('H61', 225, [326, 334]), ('J61', 245, [325]),
    ('H62', 225, [324, 332]), ('J62', 255, [323]),
    ('H63', 245, [320, 92]), ('J63', 265, [319, 91]),
    ('H64', 245, [322, 97]), ('J64', 265, [321, 96]),
    ('H65', 255, [328, 93, 94, 95]), ('J65', 275, [327, 331, 318]),
    # TEMPURA MEALS (column H)
    ('H70', 285, [437]), ('H71', 335, [436, 142, 141]), ('H72', 355, [438]),
    # VALUE MEALS (column I; I77 reads "695/ 715": chicken / pork)
    ('I77', 695, [442]), ('I77', 715, [443]), ('I79', 795, [445]), ('I81', 1825, [444]),
    # SNACK MEALS (column I)
    ('I85', 325, [410]), ('I86', 275, [414, 413]), ('I87', 335, [412]), ('I88', 395, [415, 182]), ('I89', 395, [411]),
    # STARTERS: REGULAR (column H) / FOR SHARING (column K)
    ('H93', 270, [421]), ('K93', 420, [422]),
    ('H94', 195, [416, 20]), ('K94', 375, [417]),
    ('H95', 238, [418, 420, 6, 22, 374]), ('K95', 448, [419]),
    ('H98', 280, [423, 430, 119, 118, 378]), ('K98', 485, [424, 431]),
    ('H99', 280, [427, 115, 121, 379]),
    ('H100', 280, [425, 432, 111, 114]), ('K100', 485, [426, 112]),
    ('H101', 320, [428, 434, 122]), ('K101', 525, [429, 435, 113]),
    # ALL TIME FAVORITES: REGULAR (H) / FOR SHARING (K) / 12 pcs (L). Row 108 repeats the EBI TEMPURA label but
    # its 210 / 370 / 720 are the POS kani tempura prices (3 / 6 / 12 pcs), so it is read as KANI TEMPURA.
    ('H107', 260, [190]), ('K107', 470, [191]), ('L107', 895, [189]),
    ('H108', 210, [193]), ('K108', 370, [194]), ('L108', 720, [192]),
    ('H110', 285, [187]), ('K110', 430, [188]),
    ('H111', 310, [202, 153]), ('K111', 465, [203]),
    ('H112', 275, [205, 181]), ('K112', 410, [206, 180]),
    ('H113', 365, [201]), ('H114', 535, [204, 176]), ('H115', 558, [199, 200]),
    ('H117', 58, [308, 68]), ('H118', 95, [198, 106]),
    # HOUSE SPECIALTY (column H)
    ('H122', 250, [315]), ('H125', 468, [317, 105]), ('H129', 625, [316]), ('H133', 395, [314]),
    # SUSHI BURRITO (column H)
    ('H137', 325, [396, 395]), ('H138', 315, [397, 40]), ('H139', 315, [398]), ('H140', 335, [399]), ('H141', 345, [401]),
    # BAKED SUSHI: LARGE (column I); the POS [BS] items are the large size, SMALL (column G) has no POS item
    ('I146', 560, [213, 54, 55]), ('I147', 555, [210, 36, 35, 218, 219]), ('I148', 570, [211, 212, 220]),
    ('I149', 615, [214, 215]), ('I150', 615, [216, 217]), ('I151', 1315, [209, 17]),
    # MAKI ROLLS (column E)
    ('E156', 190, [335, 31, 34]), ('E157', 210, [351, 133]), ('E158', 190, [358]), ('E159', 310, [346, 73]),
    ('E160', 250, [350, 125]), ('E161', 235, [349, 124]), ('E162', 225, [343, 344]), ('E163', 225, [338, 57]),
    ('E164', 330, [354, 136, 138]), ('E165', 310, [353, 135]), ('E166', 345, [341, 59]), ('E167', 320, [342, 61]),
    ('E168', 275, [339, 58]), ('E169', 230, [340]), ('E170', 250, [337, 53]), ('E171', 255, [336, 39]),
    ('E172', 245, [357, 185, 156]), ('E173', 250, [352]), ('E174', 255, [361, 184]), ('E175', 330, [360]),
    ('E176', 260, [345, 62]), ('E177', 285, [348, 29]),
    # SASHIMI (column E)
    ('E181', 335, [404, 403, 134]), ('E182', 310, [406, 175]), ('E183', 255, [402]), ('E184', 255, [405]),
    # SALAD (column E; E189 reads "275/390": regular / sharing)
    ('E188', 495, [407]), ('E189', 275, [408, 150, 79]), ('E189', 390, [409]),
    # DESSERT, DRINKS & SHAKES (column E; E205 reads "88/  150": regular / bottomless)
    ('E194', 75, [87, 86]),
    ('E199', 45, [300]), ('E200', 95, [302]), ('E201', 95, [305]), ('E202', 110, [297]), ('E204', 85, [288]),
    ('E205', 88, [292, 76]), ('E205', 150, [75]), ('E207', 75, [290]), ('E208', 85, [287]),
    ('E209', 135, [291, 294]), ('E212', 195, [298]), ('E213', 195, [289]), ('E214', 195, [304]),
]


def printed_prices(menu):
    """menu_items with printed_menu_price and printed_menu_cell from PRINTED (items not on it: empty)."""
    rows = [(i, p, c) for c, p, ids in PRINTED for i in ids]
    t = pd.DataFrame(rows, columns=['item_id', 'printed_menu_price', 'printed_menu_cell'])
    assert t['item_id'].is_unique, t[t['item_id'].duplicated(keep=False)]
    assert set(t['item_id']) <= set(menu['item_id'])
    out = menu.drop(columns=['printed_menu_price', 'printed_menu_cell'], errors='ignore').merge(t, on='item_id', how='left')
    out['printed_menu_cell'] = out['printed_menu_cell'].map(lambda c: f'MAKISUSHI-MENU.xlsx Sheet1!{c}' if isinstance(c, str) else c)
    pos = list(menu.columns).index('printed_menu_price')
    cols = [c for c in out.columns if c not in ('printed_menu_price', 'printed_menu_cell')]
    return out[cols[:pos] + ['printed_menu_price', 'printed_menu_cell'] + cols[pos:]]


# SALES'26 row 4138: the lemon emoji (UTF-8 F0 9F 8D 8B) decoded as Mac Roman (U+F8FF, u-umlaut, c-cedilla, a-tilde)
NAME_FIXES = {'Lemonadeüçã': 'Lemonade🍋'}


def fix_menu(menu):
    """menu_items: export-encoding name fix, printed-menu prices from PRINTED."""
    menu = menu.assign(item_name=menu['item_name'].replace(NAME_FIXES))
    if 'display_name' in menu:
        menu['display_name'] = menu['display_name'].replace(NAME_FIXES)
    return printed_prices(menu)


def fix_sales(v4, v3):
    """sales: the name fix, plus pos_sku and taxes as recorded (SALES'26 columns B and M for real lines; the
    synthetic backfill's own values otherwise). clean_sales_v4 replaced 146 real SKUs with the item's menu SKU and
    dropped taxes (3 real lines carry tax); both stay available here. sale_id joins to generated_v3."""
    v4 = v4.drop(columns=['pos_sku', 'taxes'], errors='ignore')
    v4['item_name'] = v4['item_name'].replace(NAME_FIXES)
    src = v3.set_index('sale_id')
    v4.insert(v4.columns.get_loc('sku') + 1, 'pos_sku', v4['sale_id'].map(src['sku']))
    v4.insert(v4.columns.get_loc('net_sales') + 1, 'taxes', v4['sale_id'].map(src['taxes']))
    assert v4['pos_sku'].notna().all()
    return v4


def fix_split_review(rv):
    return rv.assign(pos_item_name=rv['pos_item_name'].replace(NAME_FIXES), item_name=rv['item_name'].replace(NAME_FIXES))


def recipe_review_v4(rv):
    """recipe_review (generated_v3's log) with how v4 treats each line (v4_status)."""
    rv = rv.drop(columns='v4_status', errors='ignore')
    fixed = {(d, c) for d, lines in MENU2_COMPONENTS.items() for c in lines}
    pos_name = {'Mixed Sushi & Sashimi': 'Mixed sushi and sashimi'}      # MENU2 dish -> its POS item
    code = rv['menu2_code'].str.replace(r'_\d+$', '', regex=True)
    status = []
    for t, d, c in zip(rv['review_type'], rv['dish'], code):
        d = pos_name.get(d, d)
        if (d, c) in fixed:
            status.append(f'superseded in v4: {MENU2_COMPONENTS[d][c][1]} (workbook_fixes.MENU2_COMPONENTS)')
        elif t == 'IMPUTED_BLANK':
            status.append('kept; qty_provenance SYNTHETIC_ASSUMPTION in v4 (a median, not a workbook quantity)')
        elif t == 'CONFLICT_RESOLVED' and d == 'Seafood Platter':
            status.append('components (rows 987 / 991: Crunchy Salmon Aburi + Phila Salmon), but no POS item uses this '
                          'MENU2 dish; [PL] Seafood Platter Maki Rolls carries the sum')
        elif t == 'CONFLICT_RESOLVED':
            status.append('last row kept, the other row hidden (team decision 2026-10-07, issue I23): the rows name no '
                          'separate components')
        else:
            status.append('kept')
    return rv.assign(v4_status=status)
