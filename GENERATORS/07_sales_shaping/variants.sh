#!/bin/bash
# test stock-policy variants for tamago (TAM) and bean sprouts (TOG): build only (sales input unchanged), then measure
SP="/c/Users/Brianna/AppData/Local/Temp/claude/c--Users-Brianna-Desktop-CAPSTONE2/a21b18c6-216b-43ee-911c-5508c46122ab/scratchpad"; cd "$SP/rebuild20"
SALENV="SAL_CAP_SCALE=1 SAL_MONTH_CAP=1 SAL_P_CURE=1.0 SAL_BUSY_MONTHS=2,9,10,11,12 SAL_DEMAND_LOT=0 GF_NORM=0 SEEDX=20261010"
runv() { name="$1"; shift; (cd v11 && env $SALENV "$@" py -I build_v11.py > ../variant_$name.log 2>&1) || { echo "variant $name FAILED"; tail -3 variant_$name.log; return 1; }; rm -rf "variant_$name"; cp -r generated_v4 "variant_$name"; }
runv v0
runv v1 EXTRA_PORTIONS=CHE:2,EBK:100,PDT:5,TAM:50,TOG:50
runv v2 NO_STAPLE=TAM,TOG
runv v3 EXTRA_PORTIONS=CHE:2,EBK:100,PDT:5,TAM:50,TOG:50 NO_STAPLE=TAM,TOG
echo done
