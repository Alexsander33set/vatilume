#!/usr/bin/env python3
"""Migrate the known /opt installation to the tested private Debian package.

sudo python3 scripts/migrate_to_deb.py --apply

The collector pauses briefly. A verified private backup precedes any retirement
of code/units. No AI requests are made. Root is needed only in the user's own
terminal; passwords are never read by this script. --check changes no services.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import http.cookiejar
import json
import os
import pwd
import shutil
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import traceback
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))
from device_observability.config import load_config
from device_observability.deb_access import grant, private_token

STATE = Path('/var/lib/device-observability')
CONFIG = Path('/etc/device-observability/collector.toml')
CURRENT = Path('/opt/device-observability/current')
UNITS = ('device-observability.service', 'device-observability-web.socket', 'device-observability-web.service')
BACKUPS = Path('/var/backups/vatilume')
VERSION = '0.7.0-2'
PACKAGE_SHA256 = '292f81ff4b4753ab086810b539b2b13bfd501246bd644c2a558f1a4caaf01173'
DBS = ('telemetry.sqlite3', 'interface.sqlite3', 'ai.sqlite3')
VOLATILE = {'health.json', 'writer.lock', 'ai-active.lock', 'ai-budget.lock'}
APT_OPTIONS = ['-o', 'DPkg::Lock::Timeout=60', '-o', 'Dpkg::Options::=--force-confdef', '-o', 'Dpkg::Options::=--force-confold']


def call(arguments, *, log=None, check=True, **kwargs):
    result = subprocess.run(arguments, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)
    if log:
        log.write_text(result.stdout)
        log.chmod(0o600)
    if check and result.returncode:
        # Output stays in a private log: it may contain paths or provider details.
        raise RuntimeError(f'{Path(arguments[0]).name} failed (exit {result.returncode}); consult the private migration log')
    return result


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, document):
    temporary = path.with_name('.' + path.name + '.new')
    with temporary.open('x') as stream:
        json.dump(document, stream, indent=2, ensure_ascii=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    temporary.chmod(0o600)
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


def properties(unit):
    result = call(['systemctl', 'show', unit, '-p', 'ActiveState', '-p', 'FragmentPath', '-p', 'UnitFileState', '-p', 'DropInPaths'])
    return dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)


def q(name):
    return '"' + name.replace('"', '""') + '"'


def database_state(path, baseline=None):
    result = {}
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as con:
        assert con.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'SQLite integrity failure'
        con.execute('BEGIN')
        names = [row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        if baseline is not None and set(names) != set(baseline):
            raise ValueError('Unexpected database schema change')
        for name in names:
            maximum = baseline[name]['through_rowid'] if baseline else con.execute(f'SELECT COALESCE(MAX(rowid),0) FROM {q(name)}').fetchone()[0]
            # Source labels may be refreshed during normal rediscovery. Samples,
            # their payloads, original source identities and first-seen stay fixed.
            columns = 'rowid,id,first_seen_utc_ns' if path.name == 'telemetry.sqlite3' and name == 'sources' else 'rowid,*'
            digest = hashlib.sha256(); count = 0
            for row in con.execute(f'SELECT {columns} FROM {q(name)} WHERE rowid<=? ORDER BY rowid', (maximum,)):
                digest.update(json.dumps(row, ensure_ascii=True, allow_nan=False).encode() + b'\n'); count += 1
            result[name] = {'through_rowid': maximum, 'rows': count, 'sha256': digest.hexdigest()}
    return result


def stable_files(directory):
    result = {}
    for path in directory.iterdir():
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError('Unexpected non-regular file in private state directory')
        if path.name not in VOLATILE and not path.name.endswith(('-wal', '-shm', '.lock', '.sqlite3')):
            result[path.name] = sha(path)
    return result


def preflight(package, owner):
    if os.geteuid() != 0: raise PermissionError('Execute with sudo in your terminal; no password is accepted here')
    if not 1000 <= owner.pw_uid < 65534: raise ValueError('Specify the personal desktop owner')
    if sha(package) != PACKAGE_SHA256: raise ValueError('Package differs from the tested 0.7.0-2 artifact')
    for field, expected in (('Package', 'vatilume'), ('Version', VERSION), ('Architecture', 'amd64')):
        if call(['dpkg-deb', '-f', str(package), field]).stdout.strip() != expected: raise ValueError('Wrong package identity')
    installed = call(['dpkg-query', '-W', '-f=${Status}', 'vatilume'], check=False)
    if installed.returncode == 0 and installed.stdout.strip() == 'install ok installed':
        raise ValueError('Debian package already installed; use its existing report instead of migrating again')
    if sys.version_info[:2] != (3, 12) or call(['dpkg', '--print-architecture']).stdout.strip() != 'amd64':
        raise ValueError('This migration targets the tested Python 3.12 amd64 system')
    account = pwd.getpwnam('device-observability')
    if account.pw_uid == 0: raise ValueError('Service account must not be root')
    if STATE.is_symlink() or STATE.stat().st_uid != account.pw_uid: raise ValueError('Unexpected private state owner')
    info = CONFIG.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError('Collector conffile needs ownership/symlink review')
    config = load_config(CONFIG)
    if config.data_dir != STATE: raise ValueError('Custom data_dir requires a separate migration plan')
    if not CURRENT.is_symlink(): raise ValueError('Expected immutable legacy release symlink')
    release = CURRENT.resolve(strict=True)
    if release.parent != Path('/opt/device-observability/releases') or release.stat().st_uid != 0:
        raise ValueError('Unexpected legacy release')
    units = {}
    for unit in UNITS:
        path = Path('/etc/systemd/system') / unit
        if path.is_symlink() or not path.is_file() or path.stat().st_uid != 0 or not path.read_text().startswith('# Managed by device-observability'):
            raise ValueError(f'Unmanaged or missing legacy unit: {unit}')
        units[unit] = properties(unit)
        if units[unit]['FragmentPath'] != str(path) or units[unit]['DropInPaths']:
            raise ValueError('Custom unit/drop-in requires review before migration')
    for unit in UNITS[:2]:
        if units[unit]['ActiveState'] != 'active' or units[unit]['UnitFileState'] != 'enabled':
            raise ValueError('Expected running and enabled legacy collector/socket')
    launcher = Path(owner.pw_dir) / '.local/bin/vatilume'
    if launcher.exists() or launcher.is_symlink():
        if launcher.is_symlink() or launcher.stat().st_uid != owner.pw_uid or '# Managed by device-observability/scripts/install_launcher.py' not in launcher.read_text():
            raise ValueError('Existing user launcher needs review')
    desktop = Path(owner.pw_dir) / '.local/share/applications/vatilume.desktop'
    if desktop.exists() or desktop.is_symlink(): raise ValueError('A user desktop entry would shadow the package; review it first')
    for name in DBS:
        if not (STATE / name).is_file(): raise ValueError(f'Missing expected database: {name}')
    with closing(sqlite3.connect((STATE / 'ai.sqlite3').as_uri() + '?mode=ro', uri=True)) as con:
        if con.execute("SELECT COUNT(*) FROM ai_records WHERE state='running'").fetchone()[0]:
            raise ValueError('An AI analysis is running or needs recovery; finish it before migration')
    stable_files(STATE)
    return {'release': str(release), 'current_link': os.readlink(CURRENT), 'units': units,
            'configuration_hash': sha(CONFIG), 'collector_fingerprint': config.fingerprint,
            'interval_seconds': config.interval_seconds, 'owner_uid': owner.pw_uid, 'owner_gid': owner.pw_gid,
            'owner_home': owner.pw_dir, 'service_uid': account.pw_uid, 'service_gid': account.pw_gid}


def stop():
    for unit in (UNITS[1], UNITS[2], UNITS[0]):
        loaded = call(['systemctl', 'show', unit, '-p', 'LoadState', '--value'], check=False)
        if loaded.stdout.strip() == 'not-found': continue
        if loaded.returncode: raise RuntimeError('Could not inspect service before stopping it')
        call(['systemctl', 'stop', unit])


def resume_legacy(before):
    call(['systemctl', 'daemon-reload'])
    for unit in UNITS:
        if before['units'][unit]['UnitFileState'] == 'enabled': call(['systemctl', 'enable', unit])
    for unit in UNITS:
        if before['units'][unit]['ActiveState'] == 'active': call(['systemctl', 'start', unit])


def backup(bundle, before):
    config = load_config(CONFIG)
    if config.data_dir != STATE: raise ValueError('Data directory changed while preparing migration')
    before.update(configuration_hash=sha(CONFIG), collector_fingerprint=config.fingerprint, interval_seconds=config.interval_seconds)
    stage = bundle / 'snapshot'; stage.mkdir(mode=0o700)
    data = stage / 'state'; data.mkdir(mode=0o700)
    for source in STATE.iterdir():
        if not stat.S_ISREG(source.lstat().st_mode): raise ValueError('Unexpected state entry during capture')
        if source.name in VOLATILE or source.name.endswith(('-wal', '-shm', '.lock')): continue
        target = data / source.name
        if source.name in DBS:
            with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as reader, closing(sqlite3.connect(target)) as writer:
                reader.backup(writer)
        else: shutil.copyfile(source, target)
        info = source.stat(); os.chown(target, info.st_uid, info.st_gid); target.chmod(stat.S_IMODE(info.st_mode))
    before['databases'] = {name: database_state(data / name) for name in DBS}
    before['stable_files'] = stable_files(data)
    if (data / 'ai-limits.json').exists():
        before['effective_ai']['limits'] = json.loads((data / 'ai-limits.json').read_text())
    budget = json.loads((data / 'ai-budget.json').read_text())
    before['effective_ai']['authorized_total_usd'] = budget['cap_usd']
    before['effective_ai']['total_usd'] = sum(float(row.get('actual_usd', row['reserved_usd'])) for row in budget['requests'])
    with closing(sqlite3.connect(data / 'interface.sqlite3')) as con:
        con.row_factory = sqlite3.Row
        before['tariffs'] = [dict(row) for row in con.execute('SELECT * FROM tariffs ORDER BY effective_ms')]
    archive = bundle / 'before.tar.gz'
    with tarfile.open(archive, 'x:gz', compresslevel=1, dereference=False) as tar:
        tar.add(data, arcname='state')
        tar.add(CONFIG, arcname='config/collector.toml')
        for unit in UNITS: tar.add(Path('/etc/systemd/system') / unit, arcname='units/' + unit)
        tar.add(before['release'], arcname='runtime')
        launcher = Path(before['owner_home']) / '.local/bin/vatilume'
        if launcher.exists(): tar.add(launcher, arcname='user/vatilume')
    archive.chmod(0o600)
    # Reopen every regular archive member, then restore and check all three DBs.
    with tarfile.open(archive, 'r:gz') as tar, tempfile.TemporaryDirectory(dir=bundle) as scratch:
        for member in tar:
            if member.isfile():
                with tar.extractfile(member) as stream:
                    while stream.read(1024 * 1024): pass
        for name in DBS:
            target = Path(scratch) / name
            with tar.extractfile('state/' + name) as source, target.open('xb') as stream: shutil.copyfileobj(source, stream)
            if database_state(target) != before['databases'][name]: raise ValueError('Restored backup database differs')
        for name, digest in before['stable_files'].items():
            with tar.extractfile('state/' + name) as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != digest: raise ValueError('Archived credential/settings differ')
    before['archive_sha256'] = sha(archive)
    before['backup'] = 'complete_verified'
    save(bundle / 'before.json', before)
    shutil.rmtree(stage)
    return archive


def preserved(before):
    if sha(CONFIG) != before['configuration_hash']: raise ValueError('Collector conffile changed')
    observed = stable_files(STATE)
    # Legacy installs may have used implicit limits. Materializing those exact
    # values prevents the fresh-package paused defaults from changing behavior.
    if 'ai-limits.json' not in before['stable_files'] and 'ai-limits.json' in observed:
        if json.loads((STATE / 'ai-limits.json').read_text()) != before['effective_ai']['limits']:
            raise ValueError('Implicit AI limits changed')
        observed.pop('ai-limits.json')
    if observed != before['stable_files']: raise ValueError('Credentials, settings or spending ledger changed')
    for name, expected in before['databases'].items():
        if database_state(STATE / name, expected) != expected: raise ValueError(f'Committed history changed: {name}')


def wait_collection(before, version):
    deadline = time.monotonic() + max(120, 3 * before['interval_seconds'] + 30)
    maximum = before['databases']['telemetry.sqlite3']['samples']['through_rowid']
    while time.monotonic() < deadline:
        try:
            health = json.loads((STATE / 'health.json').read_text())
            with closing(sqlite3.connect((STATE / 'telemetry.sqlite3').as_uri() + '?mode=ro', uri=True)) as con:
                rows = con.execute('SELECT COUNT(*) FROM samples WHERE id>? AND session_id=?', (maximum, health['session_id'])).fetchone()[0]
                actual = con.execute('SELECT version FROM sessions WHERE id=?', (health['session_id'],)).fetchone()[0]
            if health['running'] and health['sequence'] >= 2 and rows >= 2 and actual == version:
                if health['write_failures'] or health['dropped_cycles'] or health['config_hash'] != before['collector_fingerprint']:
                    raise ValueError('Collector health/configuration differs')
                return {'new_samples': rows, 'interval_seconds': health['interval_seconds'], 'write_failures': 0, 'dropped_cycles': 0,
                        'sensor_errors_last_cycle': health.get('sensor_errors_last_cycle'),
                        'adapter_timeouts_last_cycle': health.get('adapter_timeouts_last_cycle')}
        except (OSError, KeyError, TypeError, sqlite3.Error): pass
        time.sleep(.5)
    raise TimeoutError('Collector did not commit two new samples within the validation window')


def api_settings():
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    token = (STATE / 'interface-token').read_text().strip()
    request = urllib.request.Request('http://127.0.0.1:8765/api/session', data=b'{}', headers={
        'Origin': 'http://127.0.0.1:8765', 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
    with opener.open(request, timeout=60) as response: assert response.status == 200
    result = {}
    for key, route in (('settings', '/api/settings'), ('ai', '/api/ai/settings')):
        with opener.open('http://127.0.0.1:8765' + route, timeout=60) as response: result[key] = json.load(response)
    return result


def validate(before, owner):
    if call(['dpkg-query', '-W', '-f=${Version}', 'vatilume']).stdout.strip() != VERSION: raise ValueError('Wrong installed version')
    for unit in UNITS[:2]:
        prop = properties(unit)
        if prop['ActiveState'] != 'active' or prop['UnitFileState'] != 'enabled' or Path(prop['FragmentPath']).resolve().parent != Path('/usr/lib/systemd/system'):
            raise ValueError('Package service did not replace the legacy unit')
    if CURRENT.exists() or CURRENT.is_symlink(): raise ValueError('Legacy current symlink still active')
    collection = wait_collection(before, '0.7.0')
    preserved(before)
    settings = api_settings()
    if settings['settings']['version'] != '0.7.0' or settings['settings']['collector']['revision'] != before['collector_fingerprint']:
        raise ValueError('Installed interface or collector revision differs')
    ai = settings['ai']; expected = before['effective_ai']
    if (settings['settings']['tariffs'] != before['tariffs'] or ai['limits'] != expected['limits']
            or ai['key_configured'] != expected['key_configured'] or ai['authorized_total_usd'] != expected['authorized_total_usd']
            or abs(ai['usage']['total_usd'] - expected['total_usd']) > 1e-9):
        raise ValueError('Tariff, key presence, effective AI limits or reported spending differs')
    preserved(before)  # Also checks API startup did not reset any AI history/budget.
    call(['runuser', '-u', owner.pw_name, '--', '/usr/bin/vatilume', '--check'])
    if shutil.which('desktop-file-validate'): call(['desktop-file-validate', '/usr/share/applications/vatilume.desktop'])
    return {**collection, 'history_preserved': True, 'configuration_preserved': True, 'tariffs_preserved': True,
            'ai_key_and_spending_preserved': True, 'launcher': 'ready', 'desktop_entry': 'registered', 'ai_calls': 0}


def restore_member(tar, name, destination):
    member = tar.getmember(name)
    if not member.isfile(): raise ValueError('Only explicit regular files can be restored automatically')
    temporary = destination.with_name('.' + destination.name + '.migration-restore')
    with tar.extractfile(member) as source, temporary.open('xb') as stream:
        shutil.copyfileobj(source, stream); stream.flush(); os.fsync(stream.fileno())
    temporary.chmod(member.mode); os.chown(temporary, member.uid, member.gid)
    os.replace(temporary, destination)


def rollback(bundle, before):
    stop()
    # Keep any tail collected after the switch in a second private archive.
    with tarfile.open(bundle / f'failed-state-{time.time_ns()}.tar.gz', 'x:gz', compresslevel=1, dereference=False) as tar: tar.add(STATE, arcname='state')
    installed = call(['dpkg-query', '-W', '-f=${Status}', 'vatilume'], check=False)
    if installed.returncode == 0 and installed.stdout.split()[-1] in ('installed', 'unpacked', 'half-configured', 'half-installed', 'triggers-awaited', 'triggers-pending'):
        call(['dpkg', '--remove', '--force-remove-reinstreq', 'vatilume'], log=bundle / 'rollback-dpkg.log')
    # This purges ONLY systemd helper metadata, never package/user data.
    helper_environment = {**os.environ, 'DPKG_MAINTSCRIPT_PACKAGE': 'vatilume'}
    call(['deb-systemd-helper', 'purge', *UNITS], env=helper_environment)
    call(['deb-systemd-helper', 'unmask', *UNITS], env=helper_environment)
    archive = bundle / 'before.tar.gz'
    if sha(archive) != before['archive_sha256']: raise ValueError('Backup hash mismatch; automatic restore stopped')
    with tarfile.open(archive, 'r:gz') as tar:
        for path in STATE.iterdir():
            if path.name == 'ai-active.lock': continue
            if not path.is_symlink() and path.is_file(): path.unlink()
            else: raise ValueError('Unexpected state entry during rollback')
        for member in tar.getmembers():
            if member.name.startswith('state/') and member.isfile(): restore_member(tar, member.name, STATE / Path(member.name).name)
        restore_member(tar, 'config/collector.toml', CONFIG)
        for unit in UNITS: restore_member(tar, 'units/' + unit, Path('/etc/systemd/system') / unit)
        launcher = Path(before['owner_home']) / '.local/bin/vatilume'
        if 'user/vatilume' in tar.getnames(): restore_member(tar, 'user/vatilume', launcher)
        elif launcher.is_symlink() and os.readlink(launcher) == '/usr/bin/vatilume': launcher.unlink()
    if CURRENT.exists() or CURRENT.is_symlink(): CURRENT.unlink()
    CURRENT.symlink_to(before['current_link'])
    # Package-created grants are unusable without its launcher; remove only ours.
    (Path('/var/lib/vatilume-access') / f"{before['owner_uid']}.url").unlink(missing_ok=True)
    preserved(before)
    resume_legacy(before)
    wait_collection(before, '0.6.0')
    preserved(before)
    save(bundle / 'rollback.json', {'rollback': 'passed', 'history_preserved': True, 'previous_installation_resumed': True})


def apply(package, owner, *, after_switch=None):
    before = preflight(package, owner)
    BACKUPS.mkdir(mode=0o700, parents=True, exist_ok=True)
    if BACKUPS.is_symlink() or BACKUPS.stat().st_uid != 0 or BACKUPS.stat().st_mode & 0o077: raise ValueError('Backup base must be root-owned and private')
    bundle = BACKUPS / ('migration-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + str(time.time_ns() % 1_000_000))
    bundle.mkdir(mode=0o700)
    protected_package = bundle / package.name
    shutil.copyfile(package, protected_package); protected_package.chmod(0o600)
    if sha(protected_package) != PACKAGE_SHA256: raise ValueError('Package changed while staging')
    (bundle / 'scripts').mkdir(mode=0o700)
    shutil.copyfile(Path(__file__), bundle / 'scripts/migrate_to_deb.py')
    (bundle / 'device_observability').mkdir(mode=0o700)
    module_source = Path(load_config.__code__.co_filename).resolve().parent
    for source in module_source.glob('*.py'):
        shutil.copyfile(source, bundle / 'device_observability' / source.name)
    if not (bundle / 'device_observability/config.py').exists(): raise ValueError('Recovery source copy is incomplete')
    (bundle / 'RESTORE.md').write_text(f'''# Private migration checkpoint

Contains telemetry, tariffs, configuration, API credentials, spending history and
the installed legacy runtime. Keep this directory private. It is a local rollback
checkpoint on the same disk, not an off-device backup or full operating system image.

before.tar.gz is usable only after before.json says backup: complete_verified.
The archive SHA-256 and SQLite table fingerprints are recorded in before.json.
result.json records the completed migration; rollback.json records a recovery.
failed-state-*.tar.gz retains any data collected after a failed switch.
The old /opt release itself is retained in place for immediate rollback.

To return to the legacy installation after a failed migration, from your own terminal:

sudo python3 {bundle}/scripts/migrate_to_deb.py --restore-backup {bundle}

This stops the Vatilume services and returns the managed databases/configuration to
the checkpoint. Newer samples are first archived privately in failed-state-*.tar.gz.
Do not run apt purge for rollback: it deletes managed state. The recovery command
removes only the package and cleans its systemd metadata before restoring old units.
''')
    print(json.dumps({'phase': 'preflight', 'backup': str(bundle), 'package': VERSION}), flush=True)
    call(['apt-get', *APT_OPTIONS, '--download-only', 'install', '-y', '--no-install-recommends', str(protected_package)], log=bundle / 'download.log')
    lock_fd = os.open(STATE / 'ai-active.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    os.fchown(lock_fd, before['service_uid'], before['service_gid'])
    with os.fdopen(lock_fd, 'a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stopped = switched = False
        try:
            original = api_settings()
            if original['settings']['version'] != '0.6.0': raise ValueError('This migration targets the known legacy 0.6.0 installation')
            before['effective_ai'] = {'limits': original['ai']['limits'], 'key_configured': original['ai']['key_configured']}
            stopped = True; stop()
            backup(bundle, before)
            print(json.dumps({'phase': 'backup', 'backup': 'complete_verified', 'bundle': str(bundle)}), flush=True)
            switched = True
            if not (STATE / 'ai-limits.json').exists():
                save(STATE / 'ai-limits.json', before['effective_ai']['limits'])
                os.chown(STATE / 'ai-limits.json', before['service_uid'], before['service_gid'])
            call(['systemctl', 'disable', UNITS[0], UNITS[1]], log=bundle / 'disable-legacy.log')
            for unit in UNITS: (Path('/etc/systemd/system') / unit).unlink()
            CURRENT.unlink()
            call(['systemctl', 'daemon-reload'])
            call(['apt-get', *APT_OPTIONS, 'install', '-y', '--no-install-recommends', str(protected_package)], log=bundle / 'install.log')
            account = pwd.getpwnam('device-observability')
            if (account.pw_uid, account.pw_gid) != (before['service_uid'], before['service_gid']): raise ValueError('Service account changed')
            token = private_token(STATE / 'interface-token', before['service_uid'])
            grant(owner.pw_uid, owner.pw_gid, token)
            launcher = Path(owner.pw_dir) / '.local/bin/vatilume'
            if launcher.exists(): launcher.unlink()
            launcher.symlink_to('/usr/bin/vatilume'); os.lchown(launcher, owner.pw_uid, owner.pw_gid)
            if after_switch: after_switch()
            result = validate(before, owner)
            result.update({'migration': 'passed', 'version': VERSION, 'backup': str(bundle), 'menu_visual_check': 'pending_desktop_launch'})
            save(bundle / 'result.json', result)
            print(json.dumps(result, indent=2), flush=True)
            return bundle
        except BaseException:
            (bundle / 'migration-error.log').write_text(traceback.format_exc())
            if switched:
                try: rollback(bundle, before)
                except BaseException:
                    (bundle / 'rollback-error.log').write_text(traceback.format_exc())
                    print(json.dumps({'migration': 'failed', 'rollback': 'needs_manual_recovery', 'backup': str(bundle)}), flush=True)
                    raise RuntimeError('Migration failed; automatic recovery needs review. The private backup was retained.') from None
                print(json.dumps({'migration': 'failed', 'rollback': 'passed', 'backup': str(bundle)}), flush=True)
            elif stopped: resume_legacy(before)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--restore-backup', type=Path, help='restore a verified migration checkpoint if a migration needs recovery')
    parser.add_argument('--package', type=Path, default=ROOT / 'dist/vatilume_0.7.0-2_amd64.deb')
    parser.add_argument('--owner', default=os.environ.get('SUDO_USER'))
    args = parser.parse_args()
    os.umask(0o077)
    if not args.owner and not args.restore_backup: parser.error('--owner is required when not called with sudo')
    try:
        if args.restore_backup:
            if os.geteuid() != 0: raise PermissionError('Restore requires sudo in your terminal')
            selected = args.restore_backup
            if selected.is_symlink(): raise ValueError('Checkpoint cannot be a symlink')
            bundle = selected.resolve(strict=True)
            if bundle.parent != BACKUPS.resolve(strict=True) or bundle.stat().st_uid != 0 or bundle.stat().st_mode & 0o077:
                raise ValueError('Select a private root-owned checkpoint in /var/backups/vatilume')
            before = json.loads((bundle / 'before.json').read_text())
            if before['backup'] != 'complete_verified' or sha(bundle / 'before.tar.gz') != before['archive_sha256']:
                raise ValueError('Checkpoint is incomplete or damaged')
            account = pwd.getpwnam('device-observability')
            if account.pw_uid != before['service_uid'] or STATE.is_symlink() or STATE.stat().st_uid != account.pw_uid:
                raise ValueError('Review service ownership before restoring')
            with (STATE / 'ai-active.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                rollback(bundle, before)
            print(json.dumps({'restore': 'passed', 'backup': str(bundle), 'previous_installation_resumed': True}))
            return
        owner = pwd.getpwnam(args.owner)
        if args.check:
            before = preflight(args.package.resolve(), owner)
            print(json.dumps({'preflight': 'passed', 'legacy_release': before['release'], 'target': VERSION, 'services_changed': False}))
        else: apply(args.package.resolve(), owner)
    except Exception as error:
        # Curated errors only. No raw URLs, credential values or SQL row payloads.
        text = str(error) if isinstance(error, (ValueError, RuntimeError, PermissionError, TimeoutError)) else 'Migration could not finish; inspect the private backup/logs or report the error type: ' + type(error).__name__
        parser.exit(1, text + '\n')


if __name__ == '__main__': main()
