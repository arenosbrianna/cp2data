"""Reorganises the anniversary-promotion sales (team instruction 2026-10-10).

Reads the PRISTINE sales source (generated_v4_pre_promo_reorg/generated_v4_pre_stg_trim/sales.csv, copied once before
the first run), applies the campaign plan in anniversary_promo_rules.py and writes generated_v4_pre_stg_trim/sales.csv:

  * a synthetic-period line that qualifies for a campaign keeps its item, date, quantity and price; its discount becomes
    the campaign rate (10 % / 25 %) and net_sales = gross_sales - discount;
  * the client's real POS lines (SALES'26, 2025-12-01 on) are never changed and nothing is added on or after that date;
  * missing campaign volume is ADDED as synthetic lines only inside the synthetic part of a window, at the item's
    observed rate (no uplift except the documented Baked Sushi pair assumption);
  * 2024 Offer B: every paid Maki Rolls line with quantity >= 2 earns floor(quantity / 2) complimentary
    Crunchy Veggie Salad Rolls on the same date and channel, rung at list price with a 100 % discount (the convention the
    project already uses for complimentary lines of priced items, e.g. items 7 and 125);
  * no line is deleted; no unrelated line is touched.

There is no promotion column anywhere: the register generated_v4_audit/anniversary_promo_changes.csv records every
touched line, and anniversary_promo_schedule.md (build_promo_schedule.py) documents the campaigns.

Stock: added lines consume ingredients, so resimulate_inventory.py must be run next (it regenerates inventory,
batches and waste from the new consumption; the simulation is deterministic and was verified to reproduce the old files).
Run:  py reorganize_anniversary_promos.py  ->  py resimulate_inventory.py  ->  py build_stg_extract.py  ->  py clean_sales.py
"""
import json
import shutil
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

import anniversary_promo_rules as R

ROOT = Path(__file__).resolve().parent
PRE = ROOT / 'generated_v4_pre_stg_trim'
BACKUP = ROOT / 'generated_v4_pre_promo_reorg'
AUDIT = ROOT / 'generated_v4_audit'
SEED = 20261010
# what the reorganisation (and the pipeline run after it) rewrites; copied once, never overwritten
BACKUP_ITEMS = ['generated_v4_pre_stg_trim', 'generated_v4', 'cleaned', 'supabase_final', 'erd', 'generated_v4_audit',
                'clean_sales.py', 'sku_line_overrides.csv']
MONEY = ['gross_sales', 'discount', 'net_sales', 'unit_price']


def backup():
    BACKUP.mkdir(exist_ok=True)
    for name in BACKUP_ITEMS:
        src, dst = ROOT / name, BACKUP / name
        if dst.exists():
            continue
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)


def fmt(x):
    """Money as the CSV writes it ('159.0', '22.12')."""
    return str(float(round(x, 2)))


def daterange(a, b):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def main():
    backup()
    raw = pd.read_csv(BACKUP / 'generated_v4_pre_stg_trim' / 'sales.csv', dtype=str, keep_default_na=False)
    menu = pd.read_csv(BACKUP / 'generated_v4_pre_stg_trim' / 'menu_items.csv')
    cal = pd.read_csv(BACKUP / 'generated_v4_pre_stg_trim' / 'calendar.csv', parse_dates=['date'])
    R.verify_catalogue(menu)
    price = menu.set_index('item_id')['price'].to_dict()
    sku = menu.set_index('item_id')['sku'].to_dict()
    open_day = {d.date(): bool(o) for d, o in zip(cal['date'], cal['is_open'])}

    t = raw.copy()
    for c in ('sale_id', 'item_id', 'quantity_sold'):
        t[c] = t[c].astype(int)
    for c in MONEY:
        t[c] = t[c].astype(float)
    t['day'] = pd.to_datetime(t['sale_date']).dt.date
    t['is_comp'] = t['is_complimentary'].eq('True')
    t['paying'] = (t['gross_sales'] > 0) & ~t['is_comp']
    t['real'] = t['day'] >= R.REAL_POS_START
    assert t['sale_id'].is_unique
    n_real_src = int(t['real'].sum())

    cls = R.classify(t, menu, t['paying'])
    t['cp_year'], t['cp_window'], t['cp_offer'], t['cp_rate'] = cls['cp_year'], cls['cp_window'], cls['cp_offer'], cls['cp_rate']
    offers = {o.key: (y, name, o, ids) for y, name, o, ids in R.offer_table(menu)}

    changes, targets = [], []        # register rows / volume model rows
    out = raw.copy()
    idx_of = {sid: i for i, sid in enumerate(t['sale_id'])}

    # ------------------------------------------------------------------ 1. existing qualifying lines
    n_reused = n_modified = n_real_kept = 0
    for r in t[t['cp_offer'].notna()].itertuples():
        y, _n, o, _ids = offers[r.cp_offer]
        base = dict(sale_id_source=r.sale_id, sale_date=r.sale_date, item_id=r.item_id, campaign_year=y,
                    window=r.cp_window, offer=o.key, quantity_sold=r.quantity_sold, unit_price=r.unit_price,
                    channel=r.channel, gross_sales=r.gross_sales)
        if r.real:
            n_real_kept += 1
            changes.append({**base, 'action': 'REAL_POS_KEPT_AS_RECORDED', 'discount_before': r.discount,
                            'discount_after': r.discount, 'net_before': r.net_sales, 'net_after': r.net_sales,
                            'provenance': 'CLIENT_PROVIDED (SALES\'26)',
                            'note': 'real POS line inside the window: recorded discount kept, not set to the campaign rate'})
            continue
        if o.kind == 'pair_free_item':          # Offer B changes nothing on the paid line; the comp line is added below
            n_reused += 1
            changes.append({**base, 'action': 'REUSED_PAID_LINE_UNCHANGED', 'discount_before': r.discount,
                            'discount_after': r.discount, 'net_before': r.net_sales, 'net_after': r.net_sales,
                            'provenance': 'SYNTHETIC_BACKFILL', 'note': 'qualifying paid Maki Rolls line; earns free Veggie Salad Roll line(s)'})
            continue
        disc = R.promo_discount(r.gross_sales, o.rate)
        net = R.money(r.gross_sales - disc)
        action = 'REUSED_DISCOUNT_UNCHANGED' if abs(disc - r.discount) < 0.005 else 'REUSED_DISCOUNT_SET'
        n_reused += 1
        if action == 'REUSED_DISCOUNT_SET':
            n_modified += 1
            i = idx_of[r.sale_id]
            out.at[i, 'discount'], out.at[i, 'net_sales'] = fmt(disc), fmt(net)
        changes.append({**base, 'action': action, 'discount_before': r.discount, 'discount_after': disc,
                        'net_before': r.net_sales, 'net_after': net, 'provenance': 'SYNTHETIC_BACKFILL',
                        'note': f'campaign discount {o.rate:.0%} of gross'})

    # ------------------------------------------------------------------ 2. volume model for ADDED lines
    synth = t[~t['real']]
    # restaurant-wide day-of-week profile of the synthetic period (lines per weekday), used to place new lines
    dow_w = synth[synth['gross_sales'] > 0].groupby(pd.to_datetime(synth['sale_date']).dt.weekday).size()
    dow_w = (dow_w / dow_w.sum()).reindex(range(7)).fillna(0).to_numpy()
    # observed promo-dish rate from the client's real export: paid lines / days between first and last real sale
    real_paid = t[t['real'] & t['paying']]
    lam = {}
    for iid, g in real_paid.groupby('item_id'):
        span = (g['day'].max() - g['day'].min()).days + 1
        lam[iid] = (len(g), span, len(g) / max(span, R.MIN_SPAN_DAYS))
    # item descriptors for new rows: the item's most common existing synthetic row (real row if it has none)
    def template(iid):
        g = t[(t['item_id'] == iid) & t['paying']]
        s = g[~g['real']]
        g = s if len(s) else g
        key = g[['item_code', 'item_name', 'portion_qty', 'portion_unit', 'category']].astype(str).agg('|'.join, axis=1)
        return raw.loc[g.index[key == key.mode().iloc[0]][0]]

    occupied = {(r.day, r.item_id, r.channel) for r in t[['day', 'item_id', 'channel']].itertuples()}
    grab_share_default = float((synth['channel'] == 'GrabFood').mean())
    new_rows, new_meta = [], []

    def item_stats(iid):
        g = t[(t['item_id'] == iid) & t['paying']]
        qty = g['quantity_sold'].to_numpy() if len(g) else np.array([1])
        s = g[~g['real']]
        gs = float((s['channel'] == 'GrabFood').mean()) if len(s) >= 20 else grab_share_default
        return qty, gs

    def add_line(rng, year, win, offer, iid, qty_pool, grab_p, days, w, kind='ADDED_PAID_LINE', qty=None):
        for _ in range(200):
            d = days[rng.choice(len(days), p=w)]
            ch = 'GrabFood' if rng.random() < grab_p else 'Dine-in'
            if (d, iid, ch) not in occupied:
                break
        else:
            raise SystemExit(f'no free slot for item {iid} in {win} {year}')
        occupied.add((d, iid, ch))
        q = int(qty if qty is not None else rng.choice(qty_pool))
        up = float(price[iid]) if ch == 'Dine-in' else R.grab_price(price[iid])
        new_rows.append(dict(day=d, item_id=iid, qty=q, unit_price=up, channel=ch, offer=offer, year=year, win=win, kind=kind))

    for year, win, start, end in R.all_windows():
        if end >= R.REAL_POS_START:
            continue                                   # real window: no synthetic line is ever added
        days = [d for d in daterange(start, end) if open_day.get(d, False)]
        w = dow_w[[d.weekday() for d in days]]
        w = w / w.sum()
        for o in R.CAMPAIGNS[year][1]:
            ids = offers[o.key][3]
            if o.kind == 'percent_off':
                for iid in ids:
                    rng = np.random.default_rng(np.random.SeedSequence([SEED, year, 6 if win == 'Jun' else 11, iid]))
                    n_obs, span, rate = lam.get(iid, (0, 0, 0.0))
                    e = rate * len(days) * o.uplift
                    drawn = int(rng.poisson(e))
                    existing = int(((t['cp_offer'] == o.key) & (t['item_id'] == iid) & (t['cp_window'] == win)).sum())
                    add = max(0, drawn - existing)
                    qty_pool, grab_p = item_stats(iid)
                    for _ in range(add):
                        add_line(rng, year, win, o.key, iid, qty_pool, grab_p, days, w)
                    targets.append(dict(campaign_year=year, window=win, offer=o.key, item_id=iid, real_lines=n_obs,
                                        real_span_days=span, rate_per_day=round(rate, 4), window_days=len(days),
                                        expected_lines=round(e, 2), drawn_target=drawn, existing_qualifying=existing,
                                        added=add))
            elif o.kind == 'pair_percent_off':
                # natural rate of paid Baked Sushi lines with quantity >= 2 on synthetic non-window days, x the pair uplift
                base_days = [d for d in daterange(date(2022, 1, 1), date(2025, 11, 30)) if open_day.get(d, False)
                             and R.window_of(d) is None]
                g = synth[synth['paying'] & synth['item_id'].isin(ids) & (synth['quantity_sold'] >= o.min_qty)]
                g = g[g['day'].isin(set(base_days))]
                rate = len(g) / len(base_days)
                e = rate * len(days) * o.uplift
                rng = np.random.default_rng(np.random.SeedSequence([SEED, year, 6 if win == 'Jun' else 11, 9000]))
                drawn = int(rng.poisson(e))
                existing = int(((t['cp_offer'] == o.key) & (t['cp_window'] == win)).sum())
                add = max(0, drawn - existing)
                share = g['item_id'].value_counts(normalize=True)
                qpool = g['quantity_sold'].to_numpy()
                for _ in range(add):
                    iid = int(rng.choice(share.index.to_numpy(), p=share.to_numpy()))
                    add_line(rng, year, win, o.key, iid, qpool, item_stats(iid)[1], days, w)
                targets.append(dict(campaign_year=year, window=win, offer=o.key, item_id='(any Baked Sushi)',
                                    real_lines=len(g), real_span_days=len(base_days), rate_per_day=round(rate, 4),
                                    window_days=len(days), expected_lines=round(e, 2), drawn_target=drawn,
                                    existing_qualifying=existing, added=add))
            # pair_free_item (Offer B): no added paid lines; the free-roll lines follow from the paid ones below

    # ------------------------------------------------------------------ 3. Offer B: complimentary Veggie Salad Rolls
    # One complimentary line per date and channel (several qualifying paid lines on a day would otherwise produce
    # identical lines): quantity = sum of floor(quantity / 2) over that day's qualifying paid lines.
    free = []
    ob = t[(t['cp_offer'] == '2024-maki') & ~t['real']].sort_values('sale_id')
    for (day, channel), g in ob.groupby(['day', 'channel']):
        free.append(dict(day=day, item_id=R.FREE_ROLL_ITEM, qty=int((g['quantity_sold'] // 2).sum()),
                         unit_price=float(price[R.FREE_ROLL_ITEM]) if channel == 'Dine-in' else R.grab_price(price[R.FREE_ROLL_ITEM]),
                         channel=channel, offer='2024-maki', year=2024, win=g['cp_window'].iloc[0], kind='ADDED_FREE_ROLL',
                         paid_sale_id=','.join(str(i) for i in g['sale_id'])))

    # ------------------------------------------------------------------ 4. write the new rows
    adds = sorted(new_rows + free, key=lambda a: (a['day'], a['item_id'], a['channel'], a['kind']))
    next_id = int(t['sale_id'].max()) + 1
    rows = []
    for k, a in enumerate(adds):
        tpl = template(a['item_id']).copy()
        sid = next_id + k
        gross = R.money(a['qty'] * a['unit_price'])
        comp = a['kind'] == 'ADDED_FREE_ROLL'
        if comp:
            disc = gross                                       # 100 % discount: complimentary at list price
        else:
            disc = R.promo_discount(gross, offers[a['offer']][2].rate)
        net = R.money(gross - disc)
        tpl['sale_id'], tpl['sale_date'] = str(sid), a['day'].isoformat()
        tpl['sku'] = tpl['pos_sku'] = str(int(sku[a['item_id']]))
        tpl['quantity_sold'], tpl['gross_sales'], tpl['discount'], tpl['net_sales'] = str(a['qty']), fmt(gross), fmt(disc), fmt(net)
        tpl['taxes'], tpl['unit_price'], tpl['channel'] = '0.0', fmt(a['unit_price']), a['channel']
        tpl['is_complimentary'] = 'True' if comp else 'False'
        rows.append(tpl)
        changes.append(dict(
            sale_id_source=sid, sale_date=a['day'].isoformat(), item_id=a['item_id'], campaign_year=a['year'],
            window=a['win'], offer=a['offer'], quantity_sold=a['qty'], unit_price=a['unit_price'], channel=a['channel'],
            gross_sales=gross, action=a['kind'], discount_before=None, discount_after=disc, net_before=None,
            net_after=net, provenance='SYNTHETIC_ASSUMPTION',
            note=(f"complimentary roll(s) earned by paid sale_id_source {a['paid_sale_id']} (same date and channel); rung at list price, 100% discount"
                  if comp else 'added to reach the item\'s observed promo rate in this window')))
    new_df = pd.DataFrame(rows, columns=raw.columns)
    result = pd.concat([out, new_df], ignore_index=True)

    # ------------------------------------------------------------------ 5. checks before anything is written
    assert result['sale_id'].astype(int).is_unique
    chk = result.copy()
    for c in MONEY + ['quantity_sold']:
        chk[c] = chk[c].astype(float)
    assert ((chk['gross_sales'] - chk['quantity_sold'] * chk['unit_price']).abs() < 0.005).all()
    assert ((chk['gross_sales'] - chk['discount'] - chk['net_sales']).abs() < 0.005).all()
    assert (chk['discount'] <= chk['gross_sales'] + 1e-9).all() and (chk[MONEY] >= 0).all().all()
    nd = pd.to_datetime(new_df['sale_date']).dt.date
    assert nd.between(R.STUDY_START, R.STUDY_END).all() and (nd < R.REAL_POS_START).all()
    assert all(open_day[d] for d in nd)
    keep_cols = [c for c in raw.columns]
    real_after = result[pd.to_datetime(result['sale_date']).dt.date >= R.REAL_POS_START]
    real_before = raw[pd.to_datetime(raw['sale_date']).dt.date >= R.REAL_POS_START]
    assert real_after[keep_cols].reset_index(drop=True).equals(real_before[keep_cols].reset_index(drop=True)), 'a real POS line changed'
    untouched = raw.drop(index=[idx_of[c['sale_id_source']] for c in changes if c['action'] == 'REUSED_DISCOUNT_SET'])
    assert untouched.equals(result.loc[untouched.index, keep_cols]), 'a non-campaign line changed'

    result.to_csv(PRE / 'sales.csv', index=False, lineterminator='\n')
    AUDIT.mkdir(exist_ok=True)
    reg = pd.DataFrame(changes)
    reg.to_csv(AUDIT / 'anniversary_promo_changes.csv', index=False)
    pd.DataFrame(targets).to_csv(AUDIT / 'anniversary_promo_volume_model.csv', index=False)
    old_campaign = PRE / 'promo_campaign.csv'
    if old_campaign.exists():
        old_campaign.unlink()          # superseded item-by-year membership (copy kept in the backup folder)

    summary = dict(rows_before=len(raw), rows_after=len(result), rows_deleted=0,
                   campaign_lines_reused=n_reused, reused_discount_changed=n_modified,
                   real_pos_campaign_lines_kept=n_real_kept, added_paid_lines=len(new_rows),
                   added_free_roll_lines=len(free), real_pos_rows_before=n_real_src,
                   real_pos_rows_after=int(len(real_after)), new_sale_id_first=next_id, new_sale_id_last=next_id + len(adds) - 1)
    (AUDIT / 'anniversary_promo_reorg_summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    print(pd.DataFrame(targets).to_string(index=False))


if __name__ == '__main__':
    main()
