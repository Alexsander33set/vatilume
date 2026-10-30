#!/usr/bin/env python3
"""Freeze an anonymized read-only view before inference changes machine load."""
import hashlib
import http.cookiejar
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    path = ROOT / 'var/ai/dataset-real.json'
    if path.exists():
        raise SystemExit('Snapshot already exists; preserve it for reproducibility.')
    link = urllib.parse.urlparse((ROOT / 'var/interface-access.url').read_text().strip())
    if link.scheme != 'http' or link.netloc != '127.0.0.1:8765':
        raise ValueError('unexpected local address')
    token = urllib.parse.parse_qs(link.fragment)['access'][0]
    origin = 'http://127.0.0.1:8765'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def api(route, post=False):
        headers = {'Origin': origin, **({'Authorization': 'Bearer ' + token} if post else {})}
        with opener.open(urllib.request.Request(origin + route, data=b'' if post else None, headers=headers), timeout=35) as response:
            return json.load(response)

    api('/api/session', True)
    view = api('/api/overview?hours=6&points=240')
    keep = {k: view[k] for k in ['window', 'sample_count', 'first_record_ms', 'last_record_ms', 'components', 'latest', 'series', 'quality', 'scope', 'aggregation']}
    for component in keep['components']:
        component.pop('source_id', None)
    keep['sensors'] = [{k: sensor[k] for k in ['collector', 'metric', 'scope', 'unit', 'quality']} for sensor in view['sensors']]
    keep['provenance'] = {'kind': 'real_aggregated', 'captured_utc_ms': time.time_ns() // 1_000_000,
                          'identifiers_removed': ['inventory', 'sensor_ids', 'labels', 'events', 'processes'],
                          'game_start_user_verified': False, 'tariff_origin': 'user_configuration_not_provider_verified'}
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(json.dumps(keep, ensure_ascii=False, indent=2) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({'snapshot': str(path), 'cycles': keep['sample_count'], 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
