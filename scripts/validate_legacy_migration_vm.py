#!/usr/bin/env python3
"""Prepare/test a synthetic legacy 0.6 install ONLY inside the marked QEMU VM.

Never copy personal state into the guest. Supply source archives from git archive
and the tested .deb. Actions: prepare, rollback (injected failure), success.
"""
import argparse
import importlib.util
import json
import os
import pwd
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path


def run(args):
    return subprocess.check_output(args, text=True).strip()


def prepare(args):
    assert not Path('/opt/device-observability/current').exists()
    status = subprocess.run(['dpkg-query', '-W', '-f=${Status}', 'vatilume'], capture_output=True, text=True)
    assert status.stdout.strip() != 'install ok installed'
    stage = Path('/root/vatilume-legacy-fixture'); stage.mkdir(mode=0o700, exist_ok=True)
    run(['dpkg-deb', '-x', str(args.package), str(stage / 'package')])
    release = Path('/opt/device-observability/releases/migration-fixture-06')
    release.mkdir(parents=True)
    with tarfile.open(args.legacy_source) as tar: tar.extractall(release, filter='data')
    assert '0.6.0' in (release / 'device_observability/__init__.py').read_text()
    app = stage / 'package/usr/lib/vatilume'
    shutil.copytree(app / 'vendor', release / 'vendor')
    shutil.copytree(app / 'backend/static', release / 'backend/static')
    interpreter = release / '.venv/bin/python'; interpreter.parent.mkdir(parents=True)
    interpreter.write_text('#!/bin/sh\nexport PYTHONPATH=/opt/device-observability/current/vendor\nexec /usr/bin/python3 "$@"\n')
    interpreter.chmod(0o755)
    Path('/opt/device-observability/current').symlink_to(release)
    if subprocess.run(['getent', 'passwd', 'device-observability'], stdout=subprocess.DEVNULL).returncode:
        run(['adduser', '--system', '--group', '--home', '/var/lib/device-observability', '--no-create-home', 'device-observability'])
    account = pwd.getpwnam('device-observability')
    data = Path('/var/lib/device-observability'); data.mkdir(mode=0o750)
    os.chown(data, account.pw_uid, account.pw_gid)
    config = Path('/etc/device-observability/collector.toml'); config.parent.mkdir(exist_ok=True)
    shutil.copyfile(release / 'config/service.toml', config); config.chmod(0o640); os.chown(config, 0, account.pw_gid)
    for unit in ('device-observability.service', 'device-observability-web.service', 'device-observability-web.socket'):
        shutil.copyfile(release / 'systemd' / unit, Path('/etc/systemd/system') / unit)
    token = data / 'interface-token'; token.write_text(secrets.token_urlsafe(32)); token.chmod(0o600); os.chown(token, account.pw_uid, account.pw_gid)
    run(['systemctl', 'daemon-reload'])
    run(['systemctl', 'enable', '--now', 'device-observability.service', 'device-observability-web.socket'])
    with urllib.request.urlopen('http://127.0.0.1:8765/', timeout=120) as response: assert response.status == 200
    import validate_deb_vm as validator
    api = validator.api_client()
    api('/api/settings/tariffs', {'price': '1.3456', 'effective_date': '2026-01-01', 'description': 'Synthetic migration tariff'})
    current = api('/api/settings')['collector']
    api('/api/settings/collector', {**current['values'], 'revision': current['revision'], 'interval_seconds': 2,
        'thermal_interval_seconds': 6, 'process_interval_seconds': 5, 'process_top_n': 2, 'enabled_collectors': ['system', 'processes']}, 'PUT')
    api('/api/ai/key', {'key': 'migration-test-invalid-api-credential'}, 'PUT')
    api('/api/ai/settings', {'enabled': True, 'per_analysis_usd': .013, 'daily_usd': .045, 'monthly_usd': .123}, 'PUT')
    ledger = data / 'ai-budget.json'
    ledger.write_text(json.dumps({'cap_usd': 5., 'requests': [{'id': 'fixture-migration-spending', 'state': 'completed',
        'utc_ms': time.time_ns() // 1_000_000, 'reserved_usd': .02, 'actual_usd': .0123}]}))
    ledger.chmod(0o600); os.chown(ledger, account.pw_uid, account.pw_gid)
    with sqlite3.connect(data / 'ai.sqlite3') as con:
        con.execute('INSERT INTO ai_records VALUES(?,?,?,?,?,?,?)', ('fixture-ai-analysis', 123, 'complete', '{}', 'Synthetic question', '{}', None))
    owner = pwd.getpwnam('tester'); home = Path(owner.pw_dir)
    source = home / 'legacy-source'; source.mkdir(mode=0o755)
    access = source / 'access.url'; access.write_text('http://127.0.0.1:8765/#access=' + token.read_text()); access.chmod(0o600)
    script = source / 'open.py'
    script.write_text('import sys\nfrom pathlib import Path\nsys.path.insert(0,"/opt/device-observability/current")\nfrom device_observability.launcher import main\nsys.exit(main(access_path=Path("/home/tester/legacy-source/access.url")))\n')
    launcher = home / '.local/bin/vatilume'; launcher.parent.mkdir(parents=True, exist_ok=True)
    launcher.write_text('#!/bin/sh\n# Managed by device-observability/scripts/install_launcher.py\nexec /usr/bin/python3 /home/tester/legacy-source/open.py "$@"\n'); launcher.chmod(0o755)
    for path in (home / '.local', home / '.local/bin', launcher, source, access, script): os.chown(path, owner.pw_uid, owner.pw_gid)
    validator.wait_for(lambda: validator.sample_prefix()['rows'] >= 3)
    print(json.dumps({'fixture': 'legacy_0.6_prepared', 'personal_data_used': False, 'paid_ai_calls': 0}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'rollback', 'install-failure', 'success'])
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--legacy-source', type=Path)
    parser.add_argument('--implicit-limits', action='store_true', help='VM fixture only: exercise the legacy implicit AI defaults')
    args = parser.parse_args()
    assert os.geteuid() == 0
    assert Path('/etc/vatilume-disposable-test-vm').read_text().strip() == 'vatilume-deb-test'
    assert run(['systemd-detect-virt', '--vm']) == 'qemu'
    if args.action == 'prepare':
        prepare(args); return
    spec = importlib.util.spec_from_file_location('migration', Path(__file__).with_name('migrate_to_deb.py'))
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    if args.action in ('rollback', 'install-failure'):
        def injected_failure(): raise RuntimeError('Synthetic failure after installing package; exercise real rollback')
        if args.action == 'install-failure':
            real_call = migration.call
            def failed_install(arguments, **kwargs):
                if arguments[0] == 'apt-get' and 'install' in arguments and '--download-only' not in arguments:
                    raise RuntimeError('Synthetic failure before package installation')
                return real_call(arguments, **kwargs)
            migration.call = failed_install
        try: migration.apply(args.package.resolve(), pwd.getpwnam('tester'), after_switch=injected_failure if args.action == 'rollback' else None)
        except RuntimeError as error:
            assert str(error).startswith('Synthetic failure'), 'Automatic rollback did not succeed'
        else: raise AssertionError('The injected failure was not exercised')
        assert migration.CURRENT.is_symlink()
        assert migration.properties('device-observability.service')['ActiveState'] == 'active'
        assert not (Path('/home/tester/.local/bin/vatilume')).is_symlink()
        result = {'test': 'legacy_migration_' + args.action, 'result': 'passed', 'previous_installation_resumed': True}
    else:
        if args.implicit_limits:
            (Path('/var/lib/device-observability') / 'ai-limits.json').unlink()
        bundle = migration.apply(args.package.resolve(), pwd.getpwnam('tester'))
        result = {'test': 'legacy_migration_success', 'result': 'passed', 'report': str(bundle / 'result.json')}
    Path('/root/vatilume-legacy-fixture/' + args.action + '-result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == '__main__': main()
