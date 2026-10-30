#!/usr/bin/env python3
"""Build an offline-runtime .deb for Ubuntu 24.04 amd64, without root.

Run the frontend build and download the hash-locked cp312 wheels first. Inputs
are explicitly selected; no var/, credentials, models or host state are copied.
"""
from __future__ import annotations

import argparse
import email
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent


def normalized(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def locked_wheels(directory, lock):
    pins = {normalized(name): version for name, version in re.findall(r'^([\w-]+)==([^\s\\]+)', lock, re.M)}
    hashes = set(re.findall(r'--hash=sha256:([a-f0-9]{64})', lock))
    selected = {}
    for wheel in sorted(directory.glob('*.whl')):
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        if digest not in hashes:
            raise ValueError(f'Wheel is not hash-locked: {wheel.name}')
        if not (wheel.name.endswith('-py3-none-any.whl') or
                re.search(r'-cp312-cp312-manylinux[^/]*x86_64[^/]*\.whl$', wheel.name)):
            raise ValueError(f'Unsupported wheel target: {wheel.name}')
        with zipfile.ZipFile(wheel) as archive:
            names = [name for name in archive.namelist() if name.endswith('.dist-info/METADATA')]
            if len(names) != 1:
                raise ValueError('Wheel metadata is ambiguous')
            metadata = email.message_from_bytes(archive.read(names[0]))
        name = normalized(metadata['Name'])
        if name in selected or pins.get(name) != metadata['Version']:
            raise ValueError(f'Duplicate or mismatched wheel: {wheel.name}')
        selected[name] = (wheel, digest)
    if selected.keys() != pins.keys():
        raise ValueError('Wheel set must contain exactly the locked dependencies')
    return list(selected.values())


def unpack_wheel(wheel, destination):
    with zipfile.ZipFile(wheel) as archive:
        for item in archive.infolist():
            path = PurePosixPath(item.filename)
            if path.is_absolute() or '..' in path.parts or not path.parts or any(part.endswith('.data') for part in path.parts):
                raise ValueError('Unsupported wheel path')
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Wheel symlinks are not allowed')
            if item.is_dir():
                continue
            target = destination.joinpath(*path.parts)
            if target.exists():
                raise ValueError('Overlapping wheel files')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(item))
            target.chmod(0o644)


def write(path, content, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(mode)


def build(output, revision, wheels):
    version = re.search(r'__version__\s*=\s*[\'"]([^\'"]+)', (ROOT / 'device_observability/__init__.py').read_text())[1]
    if not re.fullmatch(r'[1-9][0-9]*', revision) or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Invalid Debian version')
    if not (ROOT / 'backend/static/index.html').is_file():
        raise ValueError('Build the frontend before packaging')
    dependencies = locked_wheels(wheels, (ROOT / 'backend/requirements.lock').read_text())
    output.mkdir(parents=True, exist_ok=True)
    package = output / f'vatilume_{version}-{revision}_amd64.deb'
    with tempfile.TemporaryDirectory(prefix='vatilume-deb-') as temporary:
        stage = Path(temporary)
        app = stage / 'usr/lib/vatilume'
        (app / 'device_observability').mkdir(parents=True)
        for source in sorted((ROOT / 'device_observability').glob('*.py')):
            shutil.copyfile(source, app / 'device_observability' / source.name)
        shutil.copytree(ROOT / 'backend/static', app / 'backend/static', ignore=shutil.ignore_patterns('.*'))
        for wheel, _ in dependencies:
            unpack_wheel(wheel, app / 'vendor')
        boot = '#!/usr/bin/python3 -I\nimport sys\nsys.dont_write_bytecode = True\nsys.path.insert(0, "/usr/lib/vatilume")\n'
        write(stage / 'usr/bin/vatilume', boot + 'from device_observability.deb_launcher import main\nsys.exit(main())\n', 0o755)
        write(app / 'grant-access', boot + 'from device_observability.deb_access import main\nsys.exit(main())\n', 0o755)
        write(app / 'runtime', boot + 'sys.path.insert(1, "/usr/lib/vatilume/vendor")\nimport runpy\nmodule = sys.argv.pop(1)\nif module not in ("device_observability", "device_observability.web"):\n    raise SystemExit("Unsupported runtime module")\nrunpy.run_module(module, run_name="__main__", alter_sys=True)\n', 0o755)
        shutil.copyfile(ROOT / 'packaging/debian/initialize-state', app / 'initialize-state')
        (app / 'initialize-state').chmod(0o755)
        for name in ('device-observability.service', 'device-observability-web.service', 'device-observability-web.socket'):
            unit = (ROOT / 'systemd' / name).read_text()
            unit = re.sub(r'^# Managed by.*\n', '# Managed by the Vatilume Debian package\n', unit)
            unit = unit.replace('/opt/device-observability/current/.venv/bin/python -m device_observability.web', '/usr/lib/vatilume/runtime device_observability.web')
            unit = unit.replace('/usr/bin/python3 -m device_observability ', '/usr/lib/vatilume/runtime device_observability ')
            unit = unit.replace('/opt/device-observability/current/docs/COLETOR.md', '/usr/share/doc/vatilume/COLETOR.md')
            unit = unit.replace('/opt/device-observability/current', '/usr/lib/vatilume')
            unit = unit.replace('Device Observability', 'Vatilume')
            write(stage / 'usr/lib/systemd/system' / name, unit)
        write(stage / 'etc/device-observability/collector.toml', (ROOT / 'config/service.toml').read_text())
        for source, target in (
            ('packaging/debian/vatilume.desktop', 'usr/share/applications/vatilume.desktop'),
            ('packaging/debian/org.vatilume.access.policy', 'usr/share/polkit-1/actions/org.vatilume.access.policy'),
            ('frontend/src/assets/vatilume.svg', 'usr/share/icons/hicolor/scalable/apps/vatilume.svg'),
            ('README.md', 'usr/share/doc/vatilume/README.md'),
            ('docs/COLETOR.md', 'usr/share/doc/vatilume/COLETOR.md'),
            ('docs/PACOTE-DEB.md', 'usr/share/doc/vatilume/PACOTE-DEB.md'),
            ('docs/FONTES.md', 'usr/share/doc/vatilume/FONTES.md'),
            ('LICENSE', 'usr/share/doc/vatilume/LICENSE'),
            ('NOTICE', 'usr/share/doc/vatilume/NOTICE'),
            ('PRIVACY.md', 'usr/share/doc/vatilume/PRIVACY.md'),
            ('SECURITY.md', 'usr/share/doc/vatilume/SECURITY.md'),
            ('THIRD_PARTY_NOTICES.md', 'usr/share/doc/vatilume/THIRD_PARTY_NOTICES.md'),
        ):
            write(stage / target, (ROOT / source).read_text())
        for name in ('LICENSE', 'PRIVACY.md', 'SECURITY.md', 'THIRD_PARTY_NOTICES.md'):
            shutil.copyfile(ROOT / name, app / name)
        shutil.copytree(ROOT/'docs', stage/'usr/share/doc/vatilume/docs',
                        ignore=shutil.ignore_patterns('validation','commercial'))
        inventory_path = ROOT / 'third_party/inventory.json'
        if not inventory_path.is_file():
            raise ValueError('Run scripts/prepare_third_party.py before building the distribution')
        inventory = json.loads(inventory_path.read_text())
        for name, digest in inventory['inputs'].items():
            if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
                raise ValueError('Third-party inventory is stale; regenerate it')
        shutil.copytree(ROOT / 'third_party', stage / 'usr/share/doc/vatilume/third_party')
        write(stage / 'usr/share/doc/vatilume/copyright',
              'Vatilume — Copyright (C) 2026 APFS <contato@apfs.com.br>\n'
              'License: GPL-3.0-or-later; see LICENSE and NOTICE in this directory.\n'
              'Third-party Python notices and licenses are included in\n'
              '/usr/lib/vatilume/vendor/*.dist-info/.\n'
              'Frontend dependency notices: frontend-licenses.json in this directory.\n')
        frontend = json.loads((ROOT / 'frontend/package-lock.json').read_text())
        notices = {name: {key: row.get(key) for key in ('version', 'license', 'resolved')} for name, row in frontend['packages'].items() if name}
        write(stage / 'usr/share/doc/vatilume/frontend-licenses.json', json.dumps(notices, indent=2) + '\n')
        for name in frontend['packages']:
            if not name:
                continue
            directory = ROOT / 'frontend' / name
            if not directory.is_dir():
                continue
            for source in directory.iterdir():
                if source.is_file() and source.name.lower().split('.')[0] in ('license', 'licence', 'copying', 'notice'):
                    target = stage / 'usr/share/doc/vatilume/licenses/frontend' / name.replace('/', '__') / source.name
                    write(target, source.read_text(errors='replace'))
        manifest = {'version': f'{version}-{revision}', 'target': 'Ubuntu 24.04 amd64 / CPython 3.12',
                    'wheels': [{'name': path.name, 'sha256': digest} for path, digest in dependencies]}
        write(stage / 'usr/share/doc/vatilume/build-inputs.json', json.dumps(manifest, indent=2) + '\n')
        size = sum(path.stat().st_size for path in stage.rglob('*') if path.is_file())
        write(stage / 'DEBIAN/control', f'''Package: vatilume
Version: {version}-{revision}
Section: utils
Priority: optional
Architecture: amd64
Maintainer: APFS <contato@apfs.com.br>
Installed-Size: {(size + 1023) // 1024}
Depends: python3 (>= 3.12), python3 (<< 3.13), python3-gi, libc6 (>= 2.35), libgcc-s1, systemd, init-system-helpers, adduser, tzdata, pkexec, polkitd, xdg-utils
Recommends: desktop-file-utils, policykit-1-gnome
Homepage: https://github.com/Alexsander33set/vatilume
Description: Local PC energy and telemetry history
 Lightweight Linux collector and a local browser interface with optional BYOK AI.
 CPU/GPU telemetry does not measure whole-PC wall consumption.
 Preview for Ubuntu 24.04 amd64. No Docker, Node or pip needed at install.
''')
        write(stage / 'DEBIAN/conffiles', '/etc/device-observability/collector.toml\n')
        for name in ('preinst', 'postinst', 'prerm', 'postrm'):
            write(stage / 'DEBIAN' / name, (ROOT / 'packaging/debian' / name).read_text(), 0o755)
        # Stable public code modes even when the builder uses umask 077.
        stage.chmod(0o755)
        for path in stage.rglob('*'):
            if path.is_dir():
                path.chmod(0o755)
            elif not path.stat().st_mode & 0o111:
                path.chmod(0o644)
        # dpkg owns root permissions without requiring a privileged build.
        subprocess.run(['dpkg-deb', '--root-owner-group', '-Zxz', '--build', str(stage), str(package)], check=True)
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    package.with_suffix('.deb.sha256').write_text(f'{digest}  {package.name}\n')
    print(json.dumps({'package': str(package), 'sha256': digest, 'bytes': package.stat().st_size}))
    return package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    parser.add_argument('--revision', default='2')
    parser.add_argument('--wheels', type=Path, default=ROOT / 'scripts/wheels')
    args = parser.parse_args()
    build(args.output.resolve(), args.revision, args.wheels)


if __name__ == '__main__':
    main()
