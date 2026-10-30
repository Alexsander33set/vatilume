#!/usr/bin/env python3
"""Lifecycle checks ONLY for an explicitly marked disposable Ubuntu 24.04 VM.

Prepare a QEMU guest with systemd, SSH and passwordless test sudo. As guest root,
create /etc/vatilume-disposable-test-vm containing exactly vatilume-deb-test.
Never mark a personal installation. Desktop/menu validation is a separate real
graphical-session step; this script does not pretend an HTTP test is a menu test.

Example: python3 scripts/validate_deb_vm.py --key PRIVATE_TEST_KEY --port 22264
  --phase install --package dist/vatilume_0.7.0-1_amd64.deb
Then validate the desktop, run upgrade with revision 2, reboot the guest and run
verify-reboot, remove, reinstall (revision 2), and purge. No paid AI requests.
"""
from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import os
import pwd
import shlex
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path

STATE = Path('/var/lib/device-observability')
WORK = Path('/root/vatilume-package-validation')
ORIGIN = 'http://127.0.0.1:8765'


def run(arguments):
    if arguments[0] == 'apt-get':
        arguments = [arguments[0], '-o', 'DPkg::Lock::Timeout=300', *arguments[1:]]
    result = subprocess.run(arguments, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f'{arguments[0]} failed: {result.stdout[-4000:]}')
    return result.stdout


def wait_for(operation, seconds=180):
    deadline = time.monotonic() + seconds
    while True:
        try:
            result = operation()
            if result:
                return result
        except (OSError, ValueError, urllib.error.URLError, AssertionError):
            pass
        if time.monotonic() >= deadline:
            raise TimeoutError('Guest readiness deadline exceeded')
        time.sleep(2)


def api_client():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def api(path, body=None, method=None):
        headers = {'Origin': ORIGIN}
        if path == '/api/session':
            headers['Authorization'] = 'Bearer ' + (STATE / 'interface-token').read_text().strip()
        if body is not None:
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(ORIGIN + path, data=json.dumps(body).encode() if body is not None else None,
                                         headers=headers, method=method)
        with opener.open(request, timeout=120) as response:
            return json.load(response)
    wait_for(lambda: api('/api/session', {}))
    return api


def ready():
    def health():
        value = json.loads((STATE / 'health.json').read_text())
        return value if value['running'] and value['boot_id'] == Path('/proc/sys/kernel/random/boot_id').read_text().strip() else None
    value = wait_for(health)
    assert value['write_failures'] == 0 and value['dropped_cycles'] == 0
    assert run(['systemctl', 'is-active', 'device-observability.service']).strip() == 'active'
    assert run(['systemctl', 'is-enabled', 'device-observability.service']).strip() == 'enabled'
    return value


def sample_prefix(maximum=None):
    with closing(sqlite3.connect(f'file:{STATE}/telemetry.sqlite3?mode=ro', uri=True)) as connection:
        assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        if maximum is None:
            maximum = connection.execute('SELECT max(id) FROM samples').fetchone()[0]
        rows = connection.execute('SELECT * FROM samples WHERE id<=? ORDER BY id', (maximum,)).fetchall()
    return {'maximum_id': maximum, 'rows': len(rows), 'sha256': hashlib.sha256(json.dumps(rows).encode()).hexdigest()}


def snapshot():
    files = [STATE / name for name in ('interface-token', 'ai-api-key', 'ai-budget.json', 'ai-limits.json', 'collector-overrides.json')]
    files += [Path('/etc/device-observability/collector.toml')]
    files += sorted(Path('/var/lib/vatilume-access').glob('*.url'))
    return {'files': {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files},
            'samples': sample_prefix(), 'tariffs': api_client()('/api/settings')['tariffs'],
            'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}


def preserved(baseline, with_api=True):
    for name, digest in baseline['files'].items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest, f'Changed state: {name}'
    assert sample_prefix(baseline['samples']['maximum_id']) == baseline['samples']
    if with_api:
        api = api_client()
        assert api('/api/settings')['tariffs'] == baseline['tariffs']
        assert api('/api/ai/settings')['usage']['total_usd'] == .0123
        assert not api('/api/ai/settings')['limits']['enabled']
    for name in ('ai-api-key', 'interface-token'):
        result = subprocess.run(['runuser', '-u', 'tester', '--', 'test', '-r', str(STATE / name)])
        assert result.returncode != 0, 'Private service data readable by desktop user'


def guest(phase, package):
    assert os.geteuid() == 0, 'Guest checks need root INSIDE disposable VM'
    assert Path('/etc/vatilume-disposable-test-vm').read_text().strip() == 'vatilume-deb-test'
    assert run(['systemd-detect-virt', '--vm']).strip() == 'qemu'
    release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    assert release['ID'].strip('"') == 'ubuntu' and release['VERSION_ID'].strip('"') == '24.04'
    assert Path('/proc/1/comm').read_text().strip() == 'systemd'
    WORK.mkdir(mode=0o700, exist_ok=True)
    baseline_path = WORK / 'baseline.json'
    baseline = json.loads(baseline_path.read_text()) if baseline_path.exists() else None
    if phase == 'legacy-guard':
        assert package and not STATE.exists(), 'Run the guard check only after purging the test package'
        unit = Path('/etc/systemd/system/device-observability.service')
        assert not unit.exists()
        fixture = '# Simulated development installation: preserve this file\n'
        unit.write_text(fixture)
        try:
            result = subprocess.run(['apt-get', 'install', '-y', '--no-install-recommends', package], text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            assert result.returncode != 0 and 'instalação manual detectada' in result.stdout
            assert unit.read_text() == fixture and not STATE.exists()
        finally:
            unit.unlink()
        detail = {'manual_installation_guard': True, 'existing_unit_unchanged': True}
    elif phase in ('install', 'upgrade', 'reinstall'):
        assert package and Path(package).is_file()
        assert run(['dpkg-deb', '-f', package, 'Package']).strip() == 'vatilume'
        if phase == 'install':
            assert not STATE.exists(), 'Initial guest must not have personal data'
        log = run(['apt-get', 'install', '-y', '--no-install-recommends', package])
        (WORK / f'{phase}.apt.txt').write_text(log)
        ready()
        api = api_client()
        if phase == 'install':
            assert api('/api/settings')['tariffs'] == []
            settings = api('/api/ai/settings')
            assert not settings['key_configured'] and not settings['limits']['enabled'] and settings['usage']['total_usd'] == 0
            api('/api/settings/tariffs', {'price': '1.2345', 'effective_date': '2026-01-01', 'description': 'Synthetic package test'})
            values = api('/api/settings')['collector']
            api('/api/settings/collector', {**values['values'], 'revision': values['revision'], 'interval_seconds': 12,
                'thermal_interval_seconds': 36, 'process_top_n': 3, 'enabled_collectors': ['system', 'processes']}, 'PUT')
            api('/api/ai/key', {'key': 'test-only-invalid-api-credential'}, 'PUT')
            api('/api/ai/settings', {'enabled': False, 'per_analysis_usd': .01, 'daily_usd': .1, 'monthly_usd': .2}, 'PUT')
            ledger = STATE / 'ai-budget.json'
            ledger.write_text(json.dumps({'cap_usd': 5., 'requests': [{'id': 'synthetic-package-test', 'state': 'completed',
                'utc_ms': time.time_ns() // 1_000_000, 'reserved_usd': .02, 'actual_usd': .0123}]}))
            ledger.chmod(0o600)
            account = pwd.getpwnam('device-observability')
            os.chown(ledger, account.pw_uid, account.pw_gid)
            with Path('/etc/device-observability/collector.toml').open('a') as stream:
                stream.write('\n# Synthetic conffile preservation check\n')
            wait_for(lambda: sample_prefix()['rows'] >= 3)
            baseline = snapshot()
            baseline_path.write_text(json.dumps(baseline))
            # Direct unauthenticated access must remain blocked.
            try:
                urllib.request.urlopen(ORIGIN + '/api/status')
                raise AssertionError('Unauthenticated API accessible')
            except urllib.error.HTTPError as error:
                assert error.code == 401
            run(['desktop-file-validate', '/usr/share/applications/vatilume.desktop'])
        else:
            preserved(baseline)
        version = run(['dpkg-query', '-W', '-f=${Version}', 'vatilume'])
        detail = {'package_version': version, 'committed_history_unchanged': True, 'ai_calls': 0}
    elif phase == 'verify-reboot':
        current = ready()
        assert current['boot_id'] != baseline['boot_id'], 'Guest was not rebooted'
        preserved(baseline)
        detail = {'real_guest_reboot': True, 'committed_history_unchanged': True}
    elif phase == 'checkpoint':
        preserved(baseline)
        assert Path('/var/lib/vatilume-access/1000.url').is_file(), 'Validate first menu authorization before checkpoint'
        run(['runuser', '-u', 'tester', '--', '/usr/bin/vatilume', '--check'])
        baseline_path.write_text(json.dumps(snapshot()))
        detail = {'menu_access_grant_included_in_preservation_checks': True}
    elif phase == 'remove':
        (WORK / 'remove.apt.txt').write_text(run(['apt-get', 'remove', '-y', 'vatilume']))
        assert not Path('/usr/bin/vatilume').exists()
        assert not Path('/usr/share/applications/vatilume.desktop').exists()
        preserved(baseline, with_api=False)
        assert subprocess.run(['systemctl', 'is-active', '--quiet', 'device-observability.service']).returncode != 0
        with socket.socket() as connection:
            connection.settimeout(2)
            assert connection.connect_ex(('127.0.0.1', 8765)) != 0
        detail = {'data_preserved': True, 'services_stopped': True, 'menu_entry_removed': True}
    elif phase == 'purge':
        external = Path('/srv/vatilume-external-fixture')
        external.mkdir(exist_ok=True)
        (external / 'preserve.txt').write_text('External data must survive purge')
        config = Path('/etc/device-observability/collector.toml')
        config.write_text(config.read_text().replace('data_dir = "/var/lib/device-observability"',
                                                   'data_dir = "/srv/vatilume-external-fixture"'))
        (WORK / 'purge.apt.txt').write_text(run(['apt-get', 'purge', '-y', 'vatilume']))
        assert not STATE.exists() and not Path('/var/lib/vatilume-access').exists()
        assert not Path('/etc/device-observability/collector.toml').exists()
        assert (external / 'preserve.txt').read_text() == 'External data must survive purge'
        detail = {'managed_data_erased': True, 'external_data_preserved': True}
    else:
        raise ValueError('Unsupported phase')
    report = {'phase': phase, 'result': 'passed', 'environment': 'Ubuntu 24.04 amd64 / QEMU / systemd', **detail}
    (WORK / f'{phase}.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--guest', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=22264)
    parser.add_argument('--user', default='tester')
    parser.add_argument('--key', type=Path)
    parser.add_argument('--known-hosts', type=Path, default=Path('var/validation/deb-vm/known_hosts'))
    parser.add_argument('--phase', required=True, choices=['install', 'checkpoint', 'upgrade', 'verify-reboot', 'remove', 'reinstall', 'purge', 'legacy-guard'])
    parser.add_argument('--package', type=Path)
    args = parser.parse_args()
    if args.guest:
        guest(args.phase, str(args.package) if args.package else None)
        return
    if not args.key:
        parser.error('--key is required for a disposable guest')
    options = ['-i', str(args.key), '-o', f'UserKnownHostsFile={args.known_hosts}', '-o', 'StrictHostKeyChecking=yes']
    destination = f'{args.user}@{args.host}'
    ssh = ['ssh', *options, '-p', str(args.port), destination]
    # The marker must have been deliberately provisioned by the VM owner.
    run([*ssh, 'test "$(cat /etc/vatilume-disposable-test-vm)" = vatilume-deb-test && mkdir -p -m 700 ~/vatilume-validation'])
    inputs = [str(Path(__file__).resolve())]
    if args.package:
        inputs.append(str(args.package.resolve()))
    run(['scp', *options, '-P', str(args.port), *inputs, destination + ':vatilume-validation/'])
    command = ['sudo', 'python3', f'/home/{args.user}/vatilume-validation/validate_deb_vm.py', '--guest', '--phase', args.phase]
    if args.package:
        command += ['--package', f'/home/{args.user}/vatilume-validation/{args.package.name}']
    print(run([*ssh, shlex.join(command)]).strip())


if __name__ == '__main__':
    main()
