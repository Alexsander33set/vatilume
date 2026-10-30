#!/usr/bin/env python3
"""Collect hash-verified upstream sources and full notices, without running them.

Downloads only PyPI source distributions, npm registry archives and crates.io
archives identified by the locked Python/npm inputs and wheel native SBOM.
Archives remain under ignored var/distribution; public inventory/notices contain
no machine telemetry. Registry packages may contain generated JS: do not describe
this cache as a complete GPL corresponding-source release by itself.
"""
from __future__ import annotations
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import email
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import urllib.parse
import urllib.request
import zipfile
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from build_deb import locked_wheels
CACHE = ROOT / 'var/distribution/upstream'
NOTICES = ROOT / 'third_party/licenses'
ALLOWED = {'pypi.org', 'files.pythonhosted.org', 'registry.npmjs.org', 'static.crates.io', 'codeload.github.com'}


def fetch(url):
    if urllib.parse.urlparse(url).scheme != 'https' or urllib.parse.urlparse(url).hostname not in ALLOWED:
        raise ValueError('Unapproved upstream source host')
    with urllib.request.urlopen(url, timeout=60) as response:
        if urllib.parse.urlparse(response.url).hostname not in ALLOWED:
            raise ValueError('Unapproved redirect host')
        data = response.read(100 * 1024 * 1024 + 1)
        if len(data) > 100 * 1024 * 1024: raise ValueError('Archive exceeds download limit')
        return data


def archive(url, filename, algorithm, digest):
    if PurePosixPath(filename).name != filename: raise ValueError('Unsafe archive name')
    path = CACHE / filename
    data = path.read_bytes() if path.is_file() else fetch(url)
    if hashlib.new(algorithm, data).digest() != digest: raise ValueError('Source digest mismatch: ' + filename)
    if not path.exists(): path.write_bytes(data)
    return data, {'archive': filename, 'url': url, 'sha256': hashlib.sha256(data).hexdigest()}


def notices(data, *, zipped=False):
    result = []
    def add(name, size, read):
        name = str(PurePosixPath(name))
        if (re.match(r'^(?:licen[cs]e|copying|copyright|notice|unlicense|authors)(?:[.\-_]|$)', PurePosixPath(name).name, re.I)
                or any(part.lower() in ('licenses', 'licences') for part in PurePosixPath(name).parts[:-1])):
            if size > 2 * 1024 * 1024: raise ValueError('Unreasonably large notice')
            result.append((name, read().decode('utf-8', errors='replace')))
    if zipped:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for item in z.infolist():
                if not item.is_dir(): add(item.filename, item.file_size, lambda i=item: z.read(i))
    else:
        with tarfile.open(fileobj=io.BytesIO(data)) as t:
            for item in t.getmembers():
                if item.isfile(): add(item.name, item.size, lambda i=item: t.extractfile(i).read())
    return sorted(result)


def write_notices(identifier, parts):
    if not parts: raise ValueError('No full notice found for ' + identifier)
    path = NOTICES / (identifier + '.txt')
    content = '\n\n'.join('=== ' + name + ' ===\n' + text for name, text in parts) + '\n'
    # Source guard bounds individual files to 1 MiB.
    if len(content.encode()) > 1024 * 1024: raise ValueError('Split large notice before publication')
    path.write_text(content)
    return str(path.relative_to(ROOT))


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    CACHE.mkdir(parents=True, exist_ok=True); NOTICES.mkdir(parents=True, exist_ok=True)
    pins = json.loads((ROOT/'third_party/source-pins.json').read_text())
    pinned = {}
    for row in pins:
        data, record = archive(row['url'], row['archive'], 'sha256', bytes.fromhex(row['sha256']))
        pinned[row['name']] = (data, record)
    lock = (ROOT / 'backend/requirements.lock').read_text()
    wheels = locked_wheels(ROOT / 'scripts/wheels', lock)
    hashes = set(re.findall(r'--hash=sha256:([a-f0-9]{64})', lock))
    jobs = []
    native = []
    for wheel, digest in wheels:
        with zipfile.ZipFile(wheel) as z:
            meta = email.message_from_bytes(z.read(next(n for n in z.namelist() if n.endswith('.dist-info/METADATA'))))
            for n in z.namelist():
                if n.endswith('.cyclonedx.json'): native.extend(json.loads(z.read(n))['components'])
        name, version = meta['Name'], meta['Version']
        identifier = 'python-' + name.replace('_','-') + '-' + version
        jobs.append(('python', name, version, identifier, wheel, digest, meta.get('License-Expression') or meta.get('License')))
    def python_job(job):
        ecosystem,name,version,identifier,wheel,digest,license = job
        metadata = json.loads(fetch('https://pypi.org/pypi/' + name + '/' + version + '/json'))
        source = next(row for row in metadata['urls'] if row['packagetype'] == 'sdist')
        if source['digests']['sha256'] not in hashes: raise ValueError('Source is not hash-locked: ' + name)
        data, record = archive(source['url'], source['filename'], 'sha256', bytes.fromhex(source['digests']['sha256']))
        # Preserve wheel notices as shipped and source notices, including nested notices.
        parts = [('wheel/' + n, text) for n,text in notices(wheel.read_bytes(), zipped=True)]
        parts += [('source/' + n, text) for n,text in notices(data, zipped=source['filename'].endswith('.zip'))]
        return {'ecosystem':ecosystem,'name':name,'version':version,'license':license,
                'wheel_sha256':digest,'source':record,'notices':write_notices(identifier,parts),'scope':'runtime'}
    def cargo_job(c):
        name, version = c['name'], c['version']
        digest = next(h['content'] for h in c['hashes'] if h['alg']=='SHA-256')
        data, record = archive(f'https://static.crates.io/crates/{name}/{name}-{version}.crate', f'{name}-{version}.crate', 'sha256', bytes.fromhex(digest))
        parts = notices(data)
        extra = None
        if not parts and name == 'wit-bindgen-rt' and version == '0.39.0':
            # This crate omits license files. Its .cargo_vcs_info.json pins this
            # exact upstream commit, from which the full notices are collected.
            with tarfile.open(fileobj=io.BytesIO(data)) as source:
                vcs = json.loads(source.extractfile(f'{name}-{version}/.cargo_vcs_info.json').read())
            pin = next(p for p in pins if p['name']=='wit-bindgen')
            if vcs['git']['sha1'] != pin['commit']: raise ValueError('Native upstream source pin changed')
            upstream, extra = pinned['wit-bindgen']
            parts = notices(upstream)
        return {'ecosystem':'cargo','name':name,'version':version,'license':c.get('licenses'),
                'source':record,'additional_source':extra,'notices':write_notices('cargo-'+name+'-'+version,parts), 'scope':'pydantic-core native/build dependency'}
    packages = json.loads((ROOT/'frontend/package-lock.json').read_text())['packages']
    def npm_job(item):
        path,row = item; name = path.split('node_modules/')[-1]; version=row['version']
        algorithm, expected = row['integrity'].split('-',1)
        data, record = archive(row['resolved'], 'npm-' + name.replace('/','-').replace('@','') + '-' + version + '.tgz',algorithm,base64.b64decode(expected))
        parts = notices(data)
        origin = None
        if not parts and name.startswith('@rolldown/binding-'):
            parent = packages['node_modules/rolldown']
            if parent['version'] != version or parent.get('license') != row.get('license'):
                raise ValueError('Native npm license/version mismatch')
            alg, expected_parent = parent['integrity'].split('-',1)
            source, origin = archive(parent['resolved'], 'npm-rolldown-'+version+'.tgz', alg, base64.b64decode(expected_parent))
            parts = notices(source)
        return {'ecosystem':'npm','name':name,'version':version,'license':row.get('license'),
                'source':record,'notice_source':origin,'notices':write_notices('npm-'+name.replace('/','-').replace('@','')+'-'+version, parts),
                'scope':'development' if row.get('dev') else 'runtime/build'}
    with ThreadPoolExecutor(max_workers=4) as pool:
        inventory = list(pool.map(python_job, jobs))
        inventory += list(pool.map(cargo_job, native))
        inventory += list(pool.map(npm_job, [(p,r) for p,r in packages.items() if p]))
    inventory.sort(key=lambda r:(r['ecosystem'],r['name'],r['version']))
    manifest = {'schema':1, 'project_license':'GPL-3.0-or-later', 'limitations':
        'Upstream registry sources and native wheel SBOM. npm archives can contain generated code; verify preferred sources before a public binary release. Not a reproducible-build claim.',
        'inputs':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ('backend/requirements.lock','frontend/package-lock.json','third_party/source-pins.json')},
        'preferred_frontend_sources':[row for row in pins if row['name'] in ('vue-core','lucide')],
        'components':inventory}
    (ROOT/'third_party/inventory.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'third_party':'prepared','components':len(inventory),'upstream_archives':len(list(CACHE.iterdir()))}))

if __name__=='__main__':main()
