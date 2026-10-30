#!/usr/bin/env python3
"""Sequential, isolated collector measurements with processes disabled/enabled."""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=int,default=120)
    parser.add_argument('--compare-source',type=Path,help='Compare installed prior release with current source, both with processes enabled')
    args=parser.parse_args()
    if args.seconds<90:parser.error('Use pelo menos 90 segundos para observar três varreduras padrão.')
    directory=ROOT/'var/validation'/('process-benchmark-'+str(time.time_ns()))
    directory.mkdir(parents=True)
    reports={}
    for enabled,name in ((False,'baseline'),(True,'processes')):
        data=directory/(name+'-data')
        config=directory/(name+'.toml')
        groups=['system','powercap','gpu','thermal']+(['processes'] if enabled or args.compare_source else [])
        config.write_text('data_dir='+json.dumps(str(data))+'\ninterval_seconds=10\nthermal_interval_seconds=30\nprocess_interval_seconds=30\nprocess_top_n=5\nenabled_collectors='+json.dumps(groups)+'\n')
        target=directory/name
        with (directory/(name+'-report.log')).open('w') as output:
            source = args.compare_source if name=='baseline' and args.compare_source else ROOT
            subprocess.run([sys.executable,str(ROOT/'scripts/benchmark.py'),'--config',str(config),'--seconds',str(args.seconds),'--output',str(target),'--source-root',str(source)],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,check=True)
        reports[name]=json.loads((target/'summary.json').read_text())
        fields=('cpu_percent_of_one_core','rss_peak_mib','collection_p95_ms','process_scans','process_scan_p95_ms','processes_readable_max','process_payload_estimated_bytes_per_day','source_unchanged_during_measurement','meets_cpu_target','meets_memory_target','integrity_check')
        print(json.dumps({'case':name,**{key:reports[name][key] for key in fields}},ensure_ascii=False),flush=True)
    result={'directory':str(directory),'duration_each_seconds':args.seconds,'comparison':'sequential observational runs, not a controlled workload experiment',
        'prior_source':str(args.compare_source) if args.compare_source else None,
        'cpu_increment_percentage_points':reports['processes']['cpu_percent_of_one_core']-reports['baseline']['cpu_percent_of_one_core'],
        'peak_rss_increment_mib':reports['processes']['rss_peak_mib']-reports['baseline']['rss_peak_mib'],
        'passed':all(r['meets_cpu_target'] and r['meets_memory_target'] and r['integrity_check']=='ok' and r['source_unchanged_during_measurement'] for r in reports.values())}
    (directory/'comparison.json').write_text(json.dumps(result,indent=2)+'\n')
    (ROOT/'var/validation/process-benchmark-latest.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2),flush=True)
    if not result['passed']:raise SystemExit(1)


if __name__=='__main__':main()
