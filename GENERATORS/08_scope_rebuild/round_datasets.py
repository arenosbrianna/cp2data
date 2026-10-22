"""Rounds every decimal value with more than 4 decimals in every row of every dataset CSV to 4 decimals (2026-10-22, user request).
Works on the text of each cell: only cells that look like a decimal number with 5 or more decimals are changed (round half up); integers, dates, text, booleans and values with at most 4 decimals stay exactly as they are.
Usage (package folder): py round_datasets.py datasets      Prints how many cells changed per file and column."""
import csv, glob, os, re, sys
from decimal import Decimal, ROUND_HALF_UP
D = sys.argv[1].replace(chr(92), '/').rstrip('/') + '/'
LONG = re.compile(r'^-?\d+\.\d{5,}$'); SCI = re.compile(r'^-?\d+(\.\d+)?[eE][+-]?\d+$'); Q = Decimal('0.0001')
total = 0
for f in sorted(glob.glob(D + '*.csv')):
    with open(f, encoding='utf8', newline='') as fh:
        rows = list(csv.reader(fh))
    hdr, body = rows[0], rows[1:]; changed = {}
    for r in body:
        for i, c in enumerate(r):
            if LONG.match(c) or SCI.match(c):
                v = Decimal(c)
                if v == v.quantize(Q, rounding=ROUND_HALF_UP) and not SCI.match(c): continue
                new = format(v.quantize(Q, rounding=ROUND_HALF_UP), 'f')
                if '.' in new: new = new.rstrip('0').rstrip('.') if new.rstrip('0').rstrip('.') != '' else '0'
                if new != c: r[i] = new; changed[hdr[i]] = changed.get(hdr[i], 0) + 1
    if changed:
        with open(f, 'w', encoding='utf8', newline='') as fh:
            w = csv.writer(fh, lineterminator='\n'); w.writerow(hdr); w.writerows(body)
        print(os.path.basename(f), changed); total += sum(changed.values())
print('cells rounded to 4 decimals:', total)
