#!/usr/bin/env python3
"""Merge read-only profile/coverage metadata and the reviewed mapping table.

This reads no production health data directly. It does not compute health scores.
"""

import argparse
import json
import re
from pathlib import Path


STATUSES={"READY","PARTIAL","BLOCKED","PROFILE_REQUIRED","NOT_APPLICABLE"}


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--inventory',type=Path,required=True)
    p.add_argument('--coverage',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    inventory=json.loads(a.inventory.read_text())
    coverage=json.loads(a.coverage.read_text())
    algorithms={}
    for line in a.report.read_text().splitlines():
        if not line.startswith('| #'):
            continue
        cells=[x.strip() for x in line.strip().strip('|').split('|')]
        if len(cells)!=9:
            raise ValueError(f'Expected 9 mapping cells: {line[:80]}')
        match=re.match(r'#(\d+[a-z]?)\s+(.+)',cells[0])
        if not match:
            raise ValueError(f'Bad catalog id: {cells[0]}')
        key=match.group(1)
        if key in algorithms or cells[6] not in STATUSES:
            raise ValueError(f'Duplicate id or bad status: {key}/{cells[6]}')
        algorithms[key]={"catalog_line":int(re.match(r'\d+',key).group()),"metric":match.group(2),"project":cells[1],"algorithm":cells[2],"required_inputs":cells[3],"available_inputs":cells[4],"coverage_reference":cells[5],"status":cells[6],"missing":cells[7],"notes":cells[8]}
    inventory['signals']=coverage['signals']
    inventory['algorithms']=algorithms
    inventory['coverage']=coverage
    inventory['classification']={"true_hrv":"NO_REAL_HRV_FOUND","source_scan_stable":inventory['stable_during_scan']}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(inventory,ensure_ascii=False,indent=2)+'\n')
    print(f'algorithms={len(algorithms)} output={a.output}')


if __name__=='__main__':main()
