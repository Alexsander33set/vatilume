#!/usr/bin/env python3
"""Prepare a local, single-commit Git copy; never publish or rewrite the source.

Only the reviewed index is exported. Original repository, remotes, branches and
releases are not copied. Output is private under ignored var/distribution and a
Git bundle under dist. No network operations and no application/runtime data.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parent.parent


def run(args, cwd=ROOT):return subprocess.check_output(args,cwd=cwd,stderr=subprocess.PIPE).decode().strip()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',type=Path,default=ROOT/'dist/vatilume-0.8.0-clean-history.bundle')
    args=parser.parse_args()
    subprocess.run([sys.executable,str(ROOT/'scripts/check_repository.py')],check=True,stdout=subprocess.DEVNULL)
    run(['git','diff','--exit-code','--quiet'])
    parent=ROOT/'var/distribution';parent.mkdir(exist_ok=True,parents=True)
    destination=Path(tempfile.mkdtemp(prefix='clean-repository-',dir=parent))
    run(['git','checkout-index','--all','--prefix='+str(destination)+'/'])
    run(['git','init','--initial-branch=main'],destination)
    run(['git','add','--all'],destination)
    run(['git','-c','user.name=APFS','-c','user.email=contato@apfs.com.br','commit','-m','feat: prepare Vatilume 0.8.0 open source preview'],destination)
    assert run(['git','rev-list','--all','--count'],destination)=='1'
    assert not run(['git','remote'],destination)
    original=run(['git','ls-files','--stage'])
    copied=run(['git','ls-files','--stage'],destination)
    if original!=copied:raise ValueError('Clean repository differs from reviewed index')
    bundle=args.bundle.resolve()
    bundle.parent.mkdir(exist_ok=True,parents=True)
    run(['git','bundle','create',str(bundle),'main'],destination)
    digest=hashlib.sha256(bundle.read_bytes()).hexdigest()
    bundle.with_name(bundle.name+'.sha256').write_text(digest+'  '+bundle.name+'\n')
    result={'clean_repository':str(destination),'commit':run(['git','rev-parse','HEAD'],destination),
            'commits':1,'remote_configured':False,'original_history_preserved':True,
            'bundle':str(bundle),'sha256':digest}
    (ROOT/'var/validation/readiness-clean-repository.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))

if __name__=='__main__':main()
