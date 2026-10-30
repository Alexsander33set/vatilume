#!/usr/bin/env python3
"""Compare supported models using synthetic cases and the installed spending ledger.

Run with --apply in the owner's terminal. Root only stages code and drops identity;
API work runs as the service account. Never copies keys or creates another budget.
"""
import argparse
from collections import defaultdict
import fcntl
import hashlib
import json
import math
import stat
import os
from pathlib import Path
import pwd
import shutil
import statistics
import sys
import tempfile
import time
import uuid

ROOT=Path(__file__).resolve().parent.parent


def run(directory,installed,ceiling,repetitions,anchor=None,case_names=None):
    from device_observability.ai_service import AIService
    from device_observability.ai_models import MODELS
    from device_observability.benchmark_cases import cases
    # The installed UI uses this same non-blocking lock; collection continues.
    with (installed/'ai-active.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        service=AIService(directory,ledger_path=installed/'ai-budget.json',limits_path=installed/'ai-limits.json',key_path=installed/'ai-api-key')
        before=service.ledger.status()['usage']['total_usd']
        anchor=before if anchor is None else anchor
        if type(anchor) not in (int,float) or not math.isfinite(anchor) or not 0<=anchor<=before:raise ValueError('Invalid comparison baseline')
        ceiling=min(ceiling,max(0,.30-(before-anchor)))
        rows=[]
        for repeat in range(repetitions):
            for name,question,base in cases():
                if case_names and name not in case_names:continue
                # Rotate model order to reduce systematic time-of-run bias.
                models=list(MODELS);models=models[repeat%len(models):]+models[:repeat%len(models)]
                for model in models:
                    spent=service.ledger.status()['usage']['total_usd']-before
                    remaining=ceiling-spent
                    if remaining<.001:break
                    frozen={**base,'model':model}
                    frozen['sha256']=hashlib.sha256(json.dumps({k:v for k,v in frozen.items() if k!='sha256'},sort_keys=True).encode()).hexdigest()
                    frozen['approval_max_usd']=min(remaining,service.ledger.status()['limits']['per_analysis_usd'])
                    identity='comparison-'+uuid.uuid4().hex
                    started=time.monotonic()
                    row={'case':name,'repeat':repeat+1,'model':model,'analysis_id':identity}
                    try:
                        report=service.analyze(identity,frozen,question)
                        row.update(state='complete',answer=report['answer'],claims=report['claims'],evidence=report['evidence'])
                    except Exception as error:
                        row.update(state='blocked',error=str(error) if isinstance(error,ValueError) else type(error).__name__)
                    row.update(elapsed_seconds=time.monotonic()-started,estimated_cost_usd=service.ledger.run_cost(identity))
                    rows.append(row)
                    save_report(directory,rows,before,service,ceiling,anchor)
        return save_report(directory,rows,before,service,ceiling,anchor)


def save_report(directory,rows,before,service,ceiling,anchor):
    summary={}
    for model in {r['model'] for r in rows}:
        selected=[r for r in rows if r['model']==model]
        summary[model]={'completed':sum(r['state']=='complete' for r in selected),'attempts':len(selected),
                        'median_seconds':statistics.median(r['elapsed_seconds'] for r in selected),
                        'estimated_usd':sum(r['estimated_cost_usd'] for r in selected)}
    document={'synthetic_only':True,'human_quality_review':'pending','additional_ceiling_usd':ceiling,
              'comparison_anchor_total_usd':anchor,'total_before_usd':before,'total_after_usd':service.ledger.status()['usage']['total_usd'],
              'models':summary,'runs':rows}
    from device_observability.ai_cost import atomic_json
    atomic_json(directory/'report.json',document)
    os.chmod(directory/'report.json',0o640)
    return document


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--case',choices=['monthly','comparison','coverage','missing_tariff'],action='append',help='Limit the verification to selected cases')
    parser.add_argument('--resume-report',type=Path,help='Reuse a prior benchmark baseline; preserve its original US$0.30 ceiling')
    args=parser.parse_args()
    if not args.apply:
        print(json.dumps({'plan':str(len(args.case) if args.case else 4)+' synthetic cases × 3 repetitions × 3 models','additional_ceiling_usd':.30,
                          'models':['gpt-5.4-mini-2026-03-17','gpt-6-luna','gpt-6.1-terra'],
                          'budget':'shared installed ledger; all existing limits apply','automatic_retries':False}));return
    if os.geteuid()!=0:parser.error('Execute com sudo no seu terminal para usar a conta protegida do serviço.')
    account=pwd.getpwnam('device-observability')
    owner_gid=int(os.environ.get('SUDO_GID',account.pw_gid))
    stage=Path(tempfile.mkdtemp(prefix='vatilume-model-comparison-',dir='/var/tmp'))
    os.chown(stage,account.pw_uid,owner_gid);os.chmod(stage,0o750)
    shutil.copytree(ROOT/'device_observability',stage/'device_observability',ignore=shutil.ignore_patterns('__pycache__'))
    os.setgroups([]);os.setgid(owner_gid);os.setuid(account.pw_uid);os.umask(0o027)
    sys.path.insert(0,str(stage))
    anchor=None
    if args.resume_report:
        info=args.resume_report.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o022 or info.st_size>8*1024**2:raise ValueError('Unsafe comparison report')
        previous=json.loads(args.resume_report.read_text())
        if previous.get('synthetic_only') is not True:raise ValueError('Expected a synthetic comparison report')
        anchor=previous.get('comparison_anchor_total_usd',previous['total_before_usd'])
    report=run(stage,Path('/var/lib/device-observability'),.30,3,anchor=anchor,case_names=args.case)
    print(json.dumps({'comparison':'complete','report':str(stage/'report.json'),'models':report['models'],
                      'additional_estimated_usd':report['total_after_usd']-report['total_before_usd'],
                      'human_quality_review':'pending'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
