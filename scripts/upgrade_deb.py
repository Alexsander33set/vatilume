#!/usr/bin/env python3
"""Back up, upgrade and verify an installed Vatilume Debian package.

Use sudo in your own terminal. Never reads passwords or calls AI. Stops only the
Vatilume services briefly, captures verified consistent databases, and preserves
all prior rows, settings, tariff, API key and spending. The local browser token
may rotate once for the 0.8 security fix. Failure after installation attempts a
verified rollback from the private root-owned checkpoint.
"""
from __future__ import annotations
import argparse
from contextlib import closing
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
import time

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from device_observability.config import load_config
from migrate_to_deb import database_state, stable_files, api_settings, wait_collection

STATE=Path('/var/lib/device-observability')
CONFIG=Path('/etc/device-observability/collector.toml')
ACCESS=Path('/var/lib/vatilume-access')
UNITS=('device-observability-web.socket','device-observability-web.service','device-observability.service')
DBS=('telemetry.sqlite3','interface.sqlite3','ai.sqlite3')
VOLATILE={'health.json','writer.lock','ai-active.lock','ai-budget.lock'}
VERSION='0.8.0-1'
PREVIOUS_SHA='292f81ff4b4753ab086810b539b2b13bfd501246bd644c2a558f1a4caaf01173'


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def run(args,log=None):
    result=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,
                          env={**os.environ,'DEBIAN_FRONTEND':'noninteractive','NEEDRESTART_MODE':'l'})
    if log:log.write(result.stdout);log.flush()
    if result.returncode:raise RuntimeError(args[0]+' failed; see private upgrade log')
    return result.stdout.strip()


def save(path,value):
    with path.open('x') as stream:
        json.dump(value,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    path.chmod(0o600)


def copy_owned(source,target):
    info=source.lstat()
    if not stat.S_ISREG(info.st_mode):raise ValueError('Unexpected nonregular private state entry')
    shutil.copyfile(source,target);os.chown(target,info.st_uid,info.st_gid);target.chmod(stat.S_IMODE(info.st_mode))


def stop():
    for unit in UNITS:run(['systemctl','stop',unit])


def start():
    run(['systemctl','start','device-observability.service','device-observability-web.socket'])


def capture(bundle,previous):
    snapshot=bundle/'snapshot';snapshot.mkdir(mode=0o700)
    data=snapshot/'state';data.mkdir(mode=0o700)
    info=STATE.stat();os.chown(data,info.st_uid,info.st_gid);data.chmod(stat.S_IMODE(info.st_mode))
    for path in STATE.iterdir():
        if not stat.S_ISREG(path.lstat().st_mode):raise ValueError('Unexpected state entry')
        if path.name in VOLATILE or path.name.endswith(('-wal','-shm','.lock')):continue
        target=data/path.name
        if path.name in DBS:
            with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as reader, closing(sqlite3.connect(target)) as writer:reader.backup(writer)
            info=path.stat();os.chown(target,info.st_uid,info.st_gid);target.chmod(stat.S_IMODE(info.st_mode))
        else:copy_owned(path,target)
    copy_owned(CONFIG,snapshot/'collector.toml')
    grants=snapshot/'access';grants.mkdir(mode=0o700)
    for path in ACCESS.iterdir():copy_owned(path,grants/path.name)
    config=load_config(CONFIG)
    before={'previous_version':previous,'configuration_hash':sha(CONFIG),'collector_fingerprint':config.fingerprint,
            'interval_seconds':config.interval_seconds,'databases':{name:database_state(data/name) for name in DBS},
            'stable_files':stable_files(data),'grants':{p.name:sha(p) for p in grants.iterdir()},
            'expected_rotation':not (data/'interface-auth-version').exists()}
    with closing(sqlite3.connect(data/'interface.sqlite3')) as con:
        con.row_factory=sqlite3.Row;before['tariffs']=[dict(r) for r in con.execute('SELECT * FROM tariffs ORDER BY effective_ms')]
    ledger=json.loads((data/'ai-budget.json').read_text())
    before['effective_ai']={'authorized_total_usd':ledger['cap_usd'],
        'total_usd':sum(float(row.get('actual_usd',row['reserved_usd'])) for row in ledger['requests']),
        'limits':json.loads((data/'ai-limits.json').read_text()),'key_configured':(data/'ai-api-key').exists()}
    hashes={str(p.relative_to(snapshot)):sha(p) for p in snapshot.rglob('*') if p.is_file()}
    archive=bundle/'before.tar.gz'
    with tarfile.open(archive,'x:gz',compresslevel=1) as tar:tar.add(snapshot,arcname='snapshot')
    archive.chmod(0o600)
    with tarfile.open(archive,'r:gz') as tar, tempfile.TemporaryDirectory(dir=bundle) as scratch:
        for name,digest in hashes.items():
            with tar.extractfile('snapshot/'+name) as stream:
                if hashlib.file_digest(stream,'sha256').hexdigest()!=digest:raise ValueError('Backup hash verification failed')
        for name in DBS:
            path=Path(scratch)/name
            with tar.extractfile('snapshot/state/'+name) as source,path.open('xb') as target:shutil.copyfileobj(source,target)
            if database_state(path)!=before['databases'][name]:raise ValueError('Backup database verification failed')
    before.update(backup='complete_verified',archive_sha256=sha(archive))
    save(bundle/'before.json',before)
    return before


def preserved(before,rotation):
    if sha(CONFIG)!=before['configuration_hash']:raise ValueError('Configuration changed')
    observed=stable_files(STATE);expected=dict(before['stable_files'])
    for name in ('interface-token','interface-auth-version'):
        if rotation:observed.pop(name,None);expected.pop(name,None)
    if observed!=expected:raise ValueError('Settings, key or spending changed')
    for name,baseline in before['databases'].items():
        if database_state(STATE/name,baseline)!=baseline:raise ValueError('Committed database history changed: '+name)
    if rotation:
        if (STATE/'interface-auth-version').read_text().strip()!='2':raise ValueError('Missing authentication migration')
        if sha(STATE/'interface-token')==before['stable_files']['interface-token']:raise ValueError('Expected token rotation missing')
        token=(STATE/'interface-token').read_text().strip()
        if set(p.name for p in ACCESS.iterdir())!=set(before['grants']):raise ValueError('Desktop grants changed unexpectedly')
        for name in before['grants']:
            if '#access='+token not in (ACCESS/name).read_text():raise ValueError('Desktop grant not refreshed')
    else:
        if {p.name:sha(p) for p in ACCESS.iterdir()}!=before['grants']:raise ValueError('Desktop grants changed')


def verify(before,owner):
    if run(['dpkg-query','-W','-f=${Version}','vatilume'])!=VERSION:raise ValueError('Wrong installed version')
    collection=wait_collection(before,'0.8.0')
    preserved(before,before['expected_rotation'])
    actual=api_settings();ai=actual['ai'];expected=before['effective_ai']
    if actual['settings']['version']!='0.8.0' or actual['settings']['tariffs']!=before['tariffs']:raise ValueError('Interface/tariff changed')
    if ai['limits']!=expected['limits'] or ai['key_configured']!=expected['key_configured'] or ai['authorized_total_usd']!=expected['authorized_total_usd'] or abs(ai['usage']['total_usd']-expected['total_usd'])>1e-9:raise ValueError('AI settings or spending changed')
    for unit in ('device-observability.service','device-observability-web.socket'):
        if run(['systemctl','is-active',unit])!='active' or run(['systemctl','is-enabled',unit])!='enabled':raise ValueError('Service not active/enabled')
    run(['runuser','-u',owner.pw_name,'--','/usr/bin/vatilume','--check'])
    if shutil.which('desktop-file-validate'):run(['desktop-file-validate','/usr/share/applications/vatilume.desktop'])
    preserved(before,before['expected_rotation'])
    return {**collection,'history_preserved':True,'configuration_preserved':True,'tariff_preserved':True,
            'ai_key_and_spending_preserved':True,'launcher':'ready','desktop_entry':'registered','ai_calls':0}


def restore(bundle,before,log):
    stop()
    run(['apt-get','install','-y','--allow-downgrades','--reinstall',str(bundle/'previous.deb')],log)
    stop()
    snapshot=bundle/'snapshot'
    STATE.rename(bundle/'failed-state')
    shutil.copytree(snapshot/'state',STATE)
    for source in (snapshot/'state').rglob('*'):
        target=STATE/source.relative_to(snapshot/'state');info=source.stat();os.chown(target,info.st_uid,info.st_gid)
    info=(snapshot/'state').stat();os.chown(STATE,info.st_uid,info.st_gid)
    copy_owned(snapshot/'collector.toml',CONFIG)
    for path in ACCESS.iterdir():path.unlink()
    for path in (snapshot/'access').iterdir():copy_owned(path,ACCESS/path.name)
    start();preserved(before,False)
    if run(['dpkg-query','-W','-f=${Version}','vatilume'])!=before['previous_version']:raise ValueError('Rollback version differs')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true');parser.add_argument('--owner',type=int)
    args=parser.parse_args()
    if not args.apply:parser.error('Use --apply after reviewing this script')
    if os.geteuid()!=0:raise PermissionError('Use sudo in your terminal; no password is accepted here')
    lock_fd=os.open('/run/lock/vatilume-upgrade.lock',os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK,0o600)
    lock_info=os.fstat(lock_fd)
    if not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid!=0 or lock_info.st_mode&0o077:
        raise ValueError('Unsafe upgrade lock')
    try:fcntl.flock(lock_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise ValueError('Another upgrade is already running') from None
    uid=args.owner if args.owner is not None else int(os.environ.get('SUDO_UID','0'))
    if not 1000<=uid<65534:raise ValueError('Specify the desktop owner UID')
    owner=pwd.getpwuid(uid)
    if run(['dpkg-query','-W','-f=${Status}','vatilume'])!='install ok installed':raise ValueError('Vatilume Debian package is not installed')
    previous=run(['dpkg-query','-W','-f=${Version}','vatilume'])
    if previous not in ('0.7.0-2',VERSION):raise ValueError('Unsupported source package version')
    if load_config(CONFIG).data_dir!=STATE or STATE.is_symlink():raise ValueError('Unexpected state path')
    package=ROOT/'dist/vatilume_0.8.0-1_amd64.deb'
    manifest=json.loads((ROOT/'dist/vatilume-0.8.0-manifest.json').read_text())
    expected=next(r['sha256'] for r in manifest['files'] if r['name']==package.name)
    if sha(package)!=expected:raise ValueError('Candidate differs from verified manifest')
    prior=ROOT/'dist/vatilume_0.7.0-2_amd64.deb' if previous=='0.7.0-2' else package
    if sha(prior)!=(PREVIOUS_SHA if previous=='0.7.0-2' else expected):raise ValueError('Rollback package differs from verified artifact')
    base=Path('/var/backups/vatilume');base.mkdir(exist_ok=True,mode=0o700)
    info=base.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode&0o077:raise ValueError('Backup directory must be private and root-owned')
    bundle=base/('upgrade-'+str(time.time_ns()));bundle.mkdir(mode=0o700)
    with (STATE/'ai-active.lock').open('a') as lock, (bundle/'upgrade.log').open('x') as log:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Wait for the running AI analysis before upgrading') from None
        with closing(sqlite3.connect((STATE/'ai.sqlite3').as_uri()+'?mode=ro',uri=True)) as con:
            if con.execute("SELECT COUNT(*) FROM ai_records WHERE state='running'").fetchone()[0]:raise ValueError('AI analysis needs completion/recovery first')
        shutil.copyfile(package,bundle/'candidate.deb');shutil.copyfile(prior,bundle/'previous.deb')
        if sha(bundle/'candidate.deb')!=expected:raise ValueError('Candidate changed during capture')
        if sha(bundle/'previous.deb')!=(PREVIOUS_SHA if previous=='0.7.0-2' else expected):raise ValueError('Rollback package changed during capture')
        stopped=installed=False;before=None
        try:
            stopped=True;stop()
            before=capture(bundle,previous)
            print(json.dumps({'backup':'complete_verified','path':str(bundle)}),flush=True)
            installed=True
            run(['apt-get','install','-y','--reinstall',str(bundle/'candidate.deb')],log)
            start()
            result=verify(before,owner)
            result.update(upgrade='passed',version=VERSION,backup=str(bundle),menu_visual_check='pending_desktop_launch')
            save(bundle/'result.json',result);print(json.dumps(result,indent=2));return 0
        except Exception:
            if installed and before is not None:
                try:restore(bundle,before,log)
                except Exception:
                    print(json.dumps({'upgrade':'failed','rollback':'needs_manual_recovery','backup':str(bundle)}),flush=True)
                    raise RuntimeError('Upgrade failed and automatic recovery needs review; verified backup retained') from None
                print(json.dumps({'upgrade':'failed','rollback':'passed','backup':str(bundle)}),flush=True)
            elif stopped:start()
            raise

if __name__=='__main__':
    try:sys.exit(main())
    except (ValueError,RuntimeError,PermissionError) as e:print(str(e),file=sys.stderr);sys.exit(1)
