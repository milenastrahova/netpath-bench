#!/usr/bin/env python3
"""Bundle a specific named failover run without modifying or deleting its raw files."""
from __future__ import annotations
import argparse
import pathlib
import re
import zipfile
import sys

REQUIRED=(".json",".csv","-events.json")

def bundle(reports:pathlib.Path,run_id:str,out:pathlib.Path)->pathlib.Path:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}",run_id):
        raise ValueError("Invalid run ID")
    name=f"bgp-failover-udp-{run_id}"
    canonical=("bgp-failover-udp.json", "bgp-failover-udp.csv", "bgp-failover-udp-events.json")
    input_files=[reports/(name+ext) for ext in REQUIRED]
    if not all(x.is_file() for x in input_files):
        raise ValueError(f"Missing raw artifacts for {name}; expected JSON/CSV/events")
    if out.exists(): raise ValueError(f"Refusing to overwrite evidence bundle: {out}")
    if any(x.stat().st_size>12_000_000 for x in input_files):
        raise ValueError("Evidence files too large")
    out.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for src,dst in zip(input_files,canonical):z.write(src,arcname=dst)
    return out

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reports',type=pathlib.Path,default=pathlib.Path('reports'))
    p.add_argument('--run-id',required=True)
    p.add_argument('--output',type=pathlib.Path,required=True)
    a=p.parse_args(argv)
    try:
        print(f'Created: {bundle(a.reports,a.run_id,a.output)}')
        return 0
    except (OSError,ValueError) as exc:
        print(f'ERROR: {exc}',file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
