"""Print the column names of every exported table.

  python columns.py            names only
  python columns.py --detail   adds dtype, non-null count and an example value,
                               and writes data_dictionary.csv
"""

import sys
from pathlib import Path

import pandas as pd

DATA = Path(__file__).parent / "generated"
TABLES = ["sales", "inventory", "waste", "suppliers",
          "menu_items", "ingredients", "recipes", "calendar"]

detail = "--detail" in sys.argv
rows = []

for name in TABLES:
    df = pd.read_csv(DATA / f"{name}.csv", nrows=None if detail else 5)
    print(f"\n{name}  ({len(df.columns)} columns)")
    print("  " + ", ".join(df.columns))
    if detail:
        for col in df.columns:
            s = df[col]
            example = s.dropna().iloc[0] if s.notna().any() else ""
            rows.append({"table": name, "column": col, "dtype": str(s.dtype),
                         "non_null": int(s.notna().sum()), "rows": len(s),
                         "example": example})

if detail:
    dd = pd.DataFrame(rows)
    dd.to_csv("data_dictionary.csv", index=False)
    print(f"\nwrote data_dictionary.csv — {len(dd)} columns across {len(TABLES)} tables")
