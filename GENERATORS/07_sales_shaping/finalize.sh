#!/bin/bash
# port the finished scratch build into outpkg, enforce the 2021 channel mix, merge price-conflict lines, copy into REBUILT_SCOPE20
set -e; unset MSYS_NO_PATHCONV
SP="/c/Users/Brianna/AppData/Local/Temp/claude/c--Users-Brianna-Desktop-CAPSTONE2/a21b18c6-216b-43ee-911c-5508c46122ab/scratchpad"; C=/c/Users/Brianna/Desktop/CAPSTONE2; V14="$C/OTHER_PROJECT_FILES/CURRENT WORKING DIRECTORY_v14_perishable_scope"; NEW="$C/OTHER_PROJECT_FILES/v14"; O="$SP/outpkg"
rm -rf "$O"; mkdir -p "$O/datasets" "$O/v14" "$O/v12/stock_rebuild"; cp "$V14"/datasets/*.csv "$O/datasets/"; cp "$V14/MANIFEST_final.csv" "$O/"; cp "$C/GENERATORS/08_scope_rebuild/port_scope_rebuild.py" "$NEW/apply_scope20_inputs.py" "$NEW/renumber_ingredient_ids_scope20.py" "$O/v14/"; cp "$SP/rebuild20/v14/ingredient_scope_register.csv" "$O/v14/"; cd "$O"
py -I v14/apply_scope20_inputs.py datasets v14/ingredient_scope_register.csv > port.log 2>&1
py -I -c "
import pandas as pd
i=pd.read_csv('datasets/ingredients.csv'); i.loc[i.ingredient_code=='SAL','standard_unit_cost']=1.8182; i.to_csv('datasets/ingredients.csv',index=False,lineterminator='\n')"
py -I v14/port_scope_rebuild.py "$SP/rebuild20/generated_v4" > port2.log 2>&1; tail -1 port2.log | cut -c1-120
py -I v14/renumber_ingredient_ids_scope20.py datasets
py -I "$C/GENERATORS/08_scope_rebuild/set_small_packs.py" datasets
cp "$C/OTHER_PROJECT_FILES/UPDATED FILES/datasets/menu_items.csv" datasets/menu_items.csv
py -I "$C/GENERATORS/08_scope_rebuild/enforce_covid_channel_mix.py" datasets
py -I "$C/GENERATORS/08_scope_rebuild/dedupe_sales_lines.py" datasets
py -I "$C/GENERATORS/08_scope_rebuild/round_datasets.py" datasets
cp datasets/*.csv $C/REBUILT_SCOPE20/datasets/; cp "$C/OTHER_PROJECT_FILES/UPDATED FILES/datasets/"{MANIFEST,storage_locations}.csv $C/REBUILT_SCOPE20/datasets/; cp "$SP/rebuild20/noise_events.json" "$SP/rebuild20/year_variation.json" $C/REBUILT_SCOPE20/
cd $C/REBUILT_SCOPE20 && py -I audit_consistency.py datasets | tail -3
