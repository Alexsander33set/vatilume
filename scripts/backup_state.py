#!/usr/bin/env python3
"""Private project checkpoint, then privileged online snapshots of installed state.

python3 scripts/backup_state.py --project
sudo python3 scripts/backup_state.py --system --bundle /absolute/checkpoint/path
Archives contain private data and credentials. Never upload them as a release.
No service is stopped and no live database is replaced.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import pwd
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import time
from contextlib import ExitStack, closing
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / 'var/backups'


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4*1024*1024), b''): value.update(block)
    return value.hexdigest()


def durable_json(path, value, owner=None):
    temporary = path.with_suffix('.new')
    with temporary.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n');stream.flush();os.fsync(stream.fileno())
    temporary.chmod(0o600)
    if owner:os.chown(temporary,*owner)
    os.replace(temporary,path)
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def sqlite_info(path):
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as con:
        if con.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('SQLite integrity failure')
        names=[row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        counts={name:con.execute('SELECT COUNT(*) FROM "'+name.replace('"','""')+'"').fetchone()[0] for name in names}
        return {'integrity_check':'ok','tables':counts,'schema_version':con.execute('PRAGMA user_version').fetchone()[0]}


def online_sqlite(source, destination):
    deadline=time.monotonic()+60
    def progress(status,remaining,total):
        if time.monotonic()>deadline:raise TimeoutError('Online backup exceeded 60 seconds')
    with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)) as reader, closing(sqlite3.connect(destination)) as writer:
        reader.backup(writer,pages=256,progress=progress,sleep=.01)
    destination.chmod(0o600)
    return sqlite_info(destination)


def project():
    if os.geteuid()==0:raise ValueError('Run --project as the project owner, without sudo')
    if not shutil.which('zstd'):raise ValueError('zstd is required')
    BASE.mkdir(mode=0o700,parents=True,exist_ok=True)
    stamp=datetime.now(ZoneInfo('America/Sao_Paulo')).strftime('%Y%m%dT%H%M%S%z')
    target=BASE/('vatilume-0.6.0-'+stamp)
    target.mkdir(mode=0o700)
    archive=target/'project.tar.zst'
    command=['tar','--use-compress-program=zstd -T2 -1','--file',str(archive),
             '--directory',str(ROOT),'--exclude=./var/backups',
             '--exclude=./var/validation/service-backup-*']
    print(json.dumps({'phase':'archiving_project','bundle':str(target),'includes_local_models':True}),flush=True)
    subprocess.run([*command,'--create','.'],check=True)
    archive.chmod(0o600)
    # Full decompression and comparison against every archived source member.
    subprocess.run([*command,'--compare'],check=True)
    manifest={'format':1,'version':'0.6.0','created_utc_ns':time.time_ns(),'project_root':str(ROOT),
        'installed_release':str(Path('/opt/device-observability/current').resolve()),
        'scope':'project including model weights, environments, assets, local state and private credentials; var/backups and privileged service-backup-* validation snapshots excluded; the latter are captured in the system archive',
        'project':{'file':archive.name,'bytes':archive.stat().st_size,'sha256':digest(archive),'source_compare':'passed'},
        'system':{'status':'pending_privileged_capture'},'private':True,'off_device_copy':False}
    durable_json(target/'manifest.json',manifest)
    (target/'RESTORE.md').write_text('''# Vatilume 0.6.0, checkpoint privado

Este diretório contém dados pessoais e credenciais da API e da interface. Não é um pacote público.
Mantenha permissões privadas. O backup no mesmo disco é um checkpoint, não proteção contra perda do disco.
Copie este diretório completo para outro armazenamento sob seu controle.

`project.tar.zst` inclui o projeto, modelos locais e ambientes, exceto a própria pasta de backups e os
snapshots antigos protegidos `var/validation/service-backup-*`, incluídos na etapa privilegiada.
A comparação integral com a origem e o SHA-256 estão no manifest.json. Antes de restaurar, confira o hash.
Restaure primeiro em uma pasta vazia: `tar --zstd -xf project.tar.zst -C /pasta/vazia`.
Não execute instaladores, serviços ou programas extraídos antes de revisar a configuração e os caminhos.

`system.tar.gz`, depois da etapa privilegiada, contém o release instalado, configuração, unidades,
lançador e snapshots online consistentes dos bancos, com WAL incorporado pela API SQLite.
O manifesto informa a abertura/verificação das cópias restauradas e contagens de tabelas.
Cada banco tem seu próprio ponto consistente; não é uma imagem atômica do sistema inteiro.
Não se incluem SO, drivers, interpretador Python do sistema ou todos os demais releases/backups de /opt.
Os arquivos WAL/SHM e os locks de execução não devem ser restaurados.

Para recuperação operacional, mantenha o destino original intacto até testar a cópia em ambiente separado.
Reinstale o release/configuração em um Linux compatível e, com os serviços parados, restaure os bancos,
JSON de configurações/orçamento e chaves com a conta device-observability e permissões originais privadas.
Recrie /opt/device-observability/current apontando ao release e habilite as unidades do systemd.
O lançador pode conter um caminho absoluto do projeto; revise-o se mudar a localização.
Confira histórico, tarifa, limite cumulativo, gasto e chave configurada antes de permitir chamadas de IA.
O teste de abertura dos snapshots não equivale a uma reinstalação completa ou teste de boot.
''')
    (target/'RESTORE.md').chmod(0o600)
    print(json.dumps({'backup':'project_verified','bundle':str(target),'manifest':str(target/'manifest.json'),
                      'archive_bytes':archive.stat().st_size,'system_capture':'pending'},indent=2),flush=True)


def system(bundle):
    if os.geteuid()!=0:raise PermissionError('Run --system with sudo in your terminal')
    target=bundle.resolve(strict=True)
    if target.parent!=BASE.resolve() or target.is_symlink():raise ValueError('Unexpected checkpoint directory')
    manifest_path=target/'manifest.json'
    manifest=json.loads(manifest_path.read_text())
    if manifest['system']['status']!='pending_privileged_capture':raise ValueError('System capture already exists')
    archive_project=target/manifest['project']['file']
    if digest(archive_project)!=manifest['project']['sha256']:raise ValueError('Project archive hash mismatch')
    owner=pwd.getpwnam(os.environ['SUDO_USER'])
    identity=(owner.pw_uid,owner.pw_gid)
    data=Path('/var/lib/device-observability')
    release=Path('/opt/device-observability/current').resolve(strict=True)
    if str(release)!=manifest['installed_release']:raise ValueError('Installed release changed after project checkpoint')
    database_info={}
    archive=target/'system.tar.gz'
    if archive.exists():raise ValueError('Refusing to overwrite a system archive')
    with ExitStack() as stack:
        # Do not interrupt an AI request. Budget mutations wait until capture ends.
        for name in ('ai-active.lock','ai-budget.lock'):
            lock=stack.enter_context((data/name).open('r+'))
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise RuntimeError('An AI operation is active; retry after it finishes')
        with tempfile.TemporaryDirectory(prefix='.runtime-stage-',dir=target) as temporary:
            stage=Path(temporary);saved=stage/'rootfs/var/lib/device-observability';saved.mkdir(parents=True,mode=0o700)
            for path in sorted(data.iterdir()):
                if not path.is_file() or path.is_symlink() or path.name.endswith(('-wal','-shm','.lock')):continue
                destination=saved/path.name
                if path.suffix=='.sqlite3':database_info[path.name]=online_sqlite(path,destination)
                else:shutil.copy2(path,destination)
            # Older root-owned recovery-test snapshots are not readable in project mode.
            protected=stage/'project-protected/var/validation'
            protected.mkdir(parents=True,mode=0o700)
            for path in sorted((ROOT/'var/validation').glob('service-backup-*.sqlite3')):
                online_sqlite(path,protected/path.name)
            budget=json.loads((saved/'ai-budget.json').read_text())
            budget_hash=digest(saved/'ai-budget.json')
            with tarfile.open(archive,'x:gz',compresslevel=1) as tar:
                tar.add(stage/'rootfs',arcname='rootfs')
                tar.add(stage/'project-protected',arcname='project-protected')
                tar.add(release,arcname='rootfs'+str(release))
                tar.add('/opt/device-observability/current',arcname='rootfs/opt/device-observability/current')
                tar.add('/etc/device-observability',arcname='rootfs/etc/device-observability')
                for name in ('device-observability.service','device-observability-web.service','device-observability-web.socket'):
                    path=Path('/etc/systemd/system')/name
                    if path.exists():tar.add(path,arcname='rootfs'+str(path))
                for relative in ('.local/bin/vatilume','.local/share/applications/vatilume.desktop'):
                    path=Path(owner.pw_dir)/relative
                    if path.exists():tar.add(path,arcname='rootfs'+str(path))
            archive.chmod(0o600)
    # Reopen archive and restore the saved DBs into a scratch directory for verification.
    with tempfile.TemporaryDirectory(prefix='.restore-check-',dir=target) as temporary, tarfile.open(archive,'r:gz') as tar:
        for name,expected in database_info.items():
            destination=Path(temporary)/name
            with tar.extractfile('rootfs/var/lib/device-observability/'+name) as source,destination.open('xb') as output:
                shutil.copyfileobj(source,output)
            if sqlite_info(destination)!=expected:raise ValueError('Restored SQLite snapshot differs')
        with tar.extractfile('rootfs/var/lib/device-observability/ai-budget.json') as stream:
            if hashlib.sha256(stream.read()).hexdigest()!=budget_hash:raise ValueError('Restored spending ledger differs')
        # Read all regular payloads so gzip CRC/truncation checks cover the archive.
        for member in tar:
            if member.isfile():
                with tar.extractfile(member) as stream:
                    while stream.read(4*1024*1024):pass
    os.chown(archive,*identity)
    spent=sum(float(row.get('actual_usd',row['reserved_usd'])) for row in budget['requests'])
    manifest['system']={'status':'verified','file':archive.name,'bytes':archive.stat().st_size,
        'sha256':digest(archive),'captured_utc_ns':time.time_ns(),'installed_release':str(release),
        'databases':database_info,'restored_snapshots':'passed','budget_sha256':budget_hash,
        'budget_requests':len(budget['requests']),'authorized_total_usd':budget['cap_usd'],'estimated_spent_usd':spent,
        'contains_private_credentials':True,'services_stopped':False,'full_machine_restore_tested':False}
    durable_json(manifest_path,manifest,identity)
    print(json.dumps({'backup':'complete_verified','bundle':str(target),'manifest':str(manifest_path),
                     'databases_restored_and_checked':list(database_info),'estimated_spent_usd':spent,
                     'authorized_total_usd':budget['cap_usd'],'services_stopped':False},indent=2))


if __name__=='__main__':
    os.umask(0o077)
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--project',action='store_true');mode.add_argument('--system',action='store_true')
    parser.add_argument('--bundle',type=Path)
    args=parser.parse_args()
    if args.project:project()
    elif not args.bundle:parser.error('--system requires --bundle')
    else:system(args.bundle)
