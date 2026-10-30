#!/usr/bin/env python3
"""Bundle only the reviewed Git index and verified upstream inputs, never var/.

Stage the release sources first. No Git history, credentials, telemetry, models,
VMs or private reports are included. Upstream archives are selected by inventory
and verified again. Run after check_repository.py; keep the result private until
release approval. This is a source provision artifact, not a reproducible-build
or independent legal-certification claim.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
from build_deb import locked_wheels


def safe_name(name):
    path=PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts: raise ValueError('Unsafe source path')
    return str(path)


def build(output):
    subprocess.run([sys.executable,str(ROOT/'scripts/check_repository.py')],cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
    subprocess.run(['git','diff','--exit-code','--quiet'],cwd=ROOT,check=True)
    inventory=json.loads(subprocess.check_output(['git','show',':third_party/inventory.json'],cwd=ROOT))
    sources={}
    for row in inventory['components']:
        for key in ('source','additional_source','notice_source'):
            source=row.get(key)
            if source: sources[source['archive']]=source
    for row in json.loads(subprocess.check_output(['git','show',':third_party/source-pins.json'],cwd=ROOT)):
        sources[row['archive']]=row
    output.parent.mkdir(parents=True,exist_ok=True)
    manifest={'format':1,'scope':'Git index snapshot, locked wheels and verified upstream source archives; no Git history or host state','files':{}}
    with tarfile.open(output,'w:gz',format=tarfile.PAX_FORMAT) as bundle:
        def add(name,data,mode=0o644):
            name='vatilume/'+safe_name(name)
            info=tarfile.TarInfo(name);info.size=len(data);info.mode=mode;info.mtime=0
            bundle.addfile(info,io.BytesIO(data))
            manifest['files'][name]=hashlib.sha256(data).hexdigest()
        entries=subprocess.check_output(['git','ls-files','--stage','-z'],cwd=ROOT).decode().split('\0')
        for entry in filter(None,entries):
            meta,name=entry.split('\t',1);mode,oid,stage=meta.split()
            if stage!='0' or mode not in ('100644','100755'):raise ValueError('Unmerged or nonregular source')
            add(name,subprocess.check_output(['git','cat-file','blob',oid],cwd=ROOT),0o755 if mode=='100755' else 0o644)
        for name,row in sorted(sources.items()):
            if PurePosixPath(name).name!=name:raise ValueError('Unsafe archive name')
            data=(ROOT/'var/distribution/upstream'/name).read_bytes()
            if hashlib.sha256(data).hexdigest()!=row['sha256']:raise ValueError('Upstream source changed')
            add('upstream/'+name,data)
        for wheel,digest in locked_wheels(ROOT/'scripts/wheels',(ROOT/'backend/requirements.lock').read_text()):
            add('scripts/wheels/'+wheel.name,wheel.read_bytes())
        add('SOURCE-MANIFEST.json',(json.dumps(manifest,indent=2)+'\n').encode())
    digest=hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_name(output.name+'.sha256').write_text(digest+'  '+output.name+'\n')
    print(json.dumps({'source_bundle':str(output),'sha256':digest,'bytes':output.stat().st_size,'upstream_archives':len(sources)}))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'dist/vatilume-0.8.0-source.tar.gz')
    build(parser.parse_args().output.resolve())
