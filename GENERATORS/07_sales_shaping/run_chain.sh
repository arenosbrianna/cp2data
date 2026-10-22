#!/bin/bash
# usage: run_chain.sh <ratios.json> ; shaping -> stock/sales build on the 20-scope package
set -e
SP="/c/Users/Brianna/AppData/Local/Temp/claude/c--Users-Brianna-Desktop-CAPSTONE2/a21b18c6-216b-43ee-911c-5508c46122ab/scratchpad"; cd "$SP/rebuild20"
cp pre_shape_sales.csv generated_v4_pre_v7/sales.csv
LEVEL_FLAT=1 EXTERNAL=1 LOCK_2021=1 LOCK_FILE=locked_2021_gf.csv GF_COVID=1 SHOCKS=1 NOISE_MULT=2.0 DAY_SD=0.45 py -I shape_noise.py "$SP/rebuild20" "$1" window_corr.json > shape_chain.log 2>&1
grep -E "^phase0d|^phase1b|^rows" shape_chain.log | cut -c1-300
cd v11; SAL_CAP_SCALE=1 SAL_MONTH_CAP=1 SAL_P_CURE=1.0 SAL_BUSY_MONTHS=2,9,10,11,12 SAL_DEMAND_LOT=0 GF_NORM=0 SEEDX=20261010 EXTRA_PORTIONS=CHE:2,EBK:100,PDT:5,TAM:50,TOG:50 NO_STAPLE=TAM,TOG PAR_ALPHA_ITEM=TAM:0.5,TOG:0.5 MAX_PACKS_ITEM=TAM:4,TOG:4 LOSS_NOISE=0.07 VARF_FLOOR=0.85 LOWVOL_END=2022-01-01 LOWVOL_PORTIONS=SAL:500,TUN:3500 py -I build_v11.py > ../build_chain.log 2>&1; echo "build exit $?"
