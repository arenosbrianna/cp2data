#!/bin/bash
# usage: calib_loop.sh <start ratios.json> <prefix> <rounds> ; runs the chain, then corrects the monthly ratios against the PLAN and the 2021 aim each round
SP="/c/Users/Brianna/AppData/Local/Temp/claude/c--Users-Brianna-Desktop-CAPSTONE2/a21b18c6-216b-43ee-911c-5508c46122ab/scratchpad"; cd "$SP/rebuild20"
run() { ./run_chain.sh "$1" > chain.out 2>&1 || { echo "CHAIN FAILED"; tail -5 chain.out | cut -c1-250; exit 1; }; grep -c "build exit 0" chain.out | grep -q 1 || { echo "build did not finish"; tail -5 chain.out; exit 1; }; }
cp "$1" "$2_0.json"
for i in $(seq 1 "$3"); do
  run "$2_$((i-1)).json"
  py -I update_ratios_plan.py "$2_$((i-1)).json" "$2_$i.json"
  py -I calib2021.py | cut -c1-200
  py -I gen_lock2021.py aim2021.json > /dev/null
done
run "$2_$3.json"
py -I planvsfinal.py | head -1
echo "final run done with ratios $2_$3.json"
