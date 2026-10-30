#!/usr/bin/env python3
"""Verify and assemble preview assets locally; never publish or change visibility.

Requires a clean, single-commit source repository and its matching source bundle.
Checks all archive entries, corresponding package sources and maintainer scripts.
No runtime state, credentials, backups or original Git history are copied.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parent.parent
VERSION = '0.8.0'
PACKAGE_VERSION = '0.8.0-2'


def git(repository, *arguments):
    return subprocess.check_output(['git', '-C', str(repository), *arguments])


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def source_entries(bundle):
    actual = {}
    manifest = None
    with tarfile.open(bundle, 'r:gz') as archive:
        for entry in archive:
            path = PurePosixPath(entry.name)
            if (not entry.isfile() or path.is_absolute() or '..' in path.parts
                    or not entry.name.startswith('vatilume/') or entry.name in actual):
                raise ValueError('Unsafe, duplicate or nonregular source entry')
            with archive.extractfile(entry) as stream:
                data = stream.read()
            actual[entry.name] = hashlib.sha256(data).hexdigest()
            if entry.name == 'vatilume/SOURCE-MANIFEST.json':
                manifest = json.loads(data)
            elif path.parts[1] in ('.git', 'var', 'dist'):
                raise ValueError('Private or generated source entry')
    if manifest is None:
        raise ValueError('Source manifest missing')
    actual.pop('vatilume/SOURCE-MANIFEST.json')
    if manifest.get('files') != actual:
        raise ValueError('Source archive differs from its manifest')
    return actual


def indexed_entries(repository):
    if git(repository, 'rev-list', '--all', '--count').strip() != b'1':
        raise ValueError('Release repository must have one clean initial commit')
    if git(repository, 'status', '--porcelain').strip():
        raise ValueError('Release repository has uncommitted changes')
    entries = {}
    for row in git(repository, 'ls-files', '--stage', '-z').split(b'\0'):
        if not row:
            continue
        meta, name = row.split(b'\t', 1)
        mode, oid, stage = meta.split()
        if stage != b'0' or mode not in (b'100644', b'100755'):
            raise ValueError('Unmerged or nonregular indexed source')
        entries['vatilume/' + name.decode()] = hashlib.sha256(git(repository, 'cat-file', 'blob', oid.decode())).hexdigest()
    return entries


def verify_sources(repository, bundle):
    actual = source_entries(bundle)
    indexed = indexed_entries(repository)
    for name, expected in indexed.items():
        if actual.get(name) != expected:
            raise ValueError('Bundle differs from reviewed source: ' + name)
    inventory = json.loads(git(repository, 'show', 'HEAD:third_party/inventory.json'))
    upstream = {}
    for row in inventory['components']:
        for key in ('source', 'additional_source', 'notice_source'):
            if row.get(key):
                value = row[key]
                upstream['vatilume/upstream/' + value['archive']] = value['sha256']
    for row in json.loads(git(repository, 'show', 'HEAD:third_party/source-pins.json')):
        upstream['vatilume/upstream/' + row['archive']] = row['sha256']
    for name, expected in upstream.items():
        if actual.get(name) != expected:
            raise ValueError('Upstream source hash mismatch')
    # The only extra inputs are the exact locked wheels, checked below.
    import sys
    sys.path.insert(0, str(ROOT / 'scripts'))
    from build_deb import locked_wheels
    wheels = dict(('vatilume/scripts/wheels/' + path.name, sha)
                  for path, sha in locked_wheels(ROOT / 'scripts/wheels', git(repository, 'show', 'HEAD:backend/requirements.lock').decode()))
    if actual != {**indexed, **upstream, **wheels}:
        raise ValueError('Unexpected source bundle input')
    return actual


def verify_package(package, sources):
    for field, expected in [('Package', 'vatilume'), ('Version', PACKAGE_VERSION), ('Architecture', 'amd64'),
                            ('Homepage', 'https://github.com/Alexsander33set/vatilume')]:
        observed = subprocess.check_output(['dpkg-deb', '-f', str(package), field]).decode().strip()
        if observed != expected:
            raise ValueError('Wrong package metadata: ' + field)
    names = set()
    runtime = set()
    data = subprocess.check_output(['dpkg-deb', '--fsys-tarfile', str(package)])
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for entry in archive:
            name = entry.name.removeprefix('./')
            names.add(name)
            source = None
            if name.startswith('usr/lib/vatilume/device_observability/') and entry.isfile():
                source = 'vatilume/' + name.removeprefix('usr/lib/vatilume/')
                runtime.add(source)
            elif name.startswith('usr/share/doc/vatilume/') and entry.isfile():
                relative = name.removeprefix('usr/share/doc/vatilume/')
                if relative in ('README.md', 'LICENSE', 'NOTICE', 'PRIVACY.md', 'SECURITY.md', 'THIRD_PARTY_NOTICES.md'):
                    source = 'vatilume/' + relative
                elif relative in ('COLETOR.md', 'PACOTE-DEB.md', 'FONTES.md'):
                    source = 'vatilume/docs/' + relative
                elif relative.startswith('third_party/'):
                    source = 'vatilume/' + relative
            if name.startswith(('var/lib/', 'var/backups/', 'home/')):
                raise ValueError('Runtime or personal state in package')
            if source:
                with archive.extractfile(entry) as stream:
                    if hashlib.file_digest(stream, 'sha256').hexdigest() != sources.get(source):
                        raise ValueError('Package differs from source: ' + name)
    expected_runtime = {name for name in sources if name.startswith('vatilume/device_observability/') and name.endswith('.py')}
    if runtime != expected_runtime or 'usr/share/applications/vatilume.desktop' not in names:
        raise ValueError('Package runtime or desktop entry incomplete')
    data = subprocess.check_output(['dpkg-deb', '--ctrl-tarfile', str(package)])
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for name in ('preinst', 'postinst', 'prerm', 'postrm'):
            with archive.extractfile('./' + name) as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != sources['vatilume/packaging/debian/' + name]:
                    raise ValueError('Package maintainer script differs')


def prepare(repository, source, package, output):
    sources = verify_sources(repository, source)
    verify_package(package, sources)
    output.mkdir(parents=True, exist_ok=False)
    assets = []
    for path in (package, source):
        target = output / path.name
        shutil.copyfile(path, target)
        if digest(path) != digest(target):
            raise ValueError('Release asset changed while copying')
        assets.append({'name': target.name, 'bytes': target.stat().st_size, 'sha256': digest(target)})
    manifest = {'format': 1, 'version': VERSION, 'package_version': PACKAGE_VERSION,
                'status': 'preview; draft until maintainer publication',
                'repository': 'https://github.com/Alexsander33set/vatilume',
                'source_commit': git(repository, 'rev-parse', 'HEAD').decode().strip(),
                'license': 'GPL-3.0-or-later', 'maintainer': 'APFS <contato@apfs.com.br>',
                'target': 'Ubuntu 24.04 amd64 / Python 3.12 / systemd',
                'publisher_signature_configured': False, 'reproducible_build_established': False,
                'assets': assets}
    path = output / 'RELEASE-MANIFEST.json'
    path.write_text(json.dumps(manifest, indent=2) + '\n')
    (output / 'SHA256SUMS').write_text(''.join(digest(path) + '  ' + path.name + '\n'
                                            for path in sorted(output.iterdir())))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=ROOT / 'dist/vatilume-0.8.0-source.tar.gz')
    parser.add_argument('--package', type=Path, default=ROOT / 'dist/vatilume_0.8.0-2_amd64.deb')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/preview-0.8.0')
    args = parser.parse_args()
    print(json.dumps(prepare(args.repository.resolve(), args.source.resolve(), args.package.resolve(), args.output.resolve()), indent=2))
