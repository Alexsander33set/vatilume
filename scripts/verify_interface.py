#!/usr/bin/env python3
"""Owner-level validation of the installed local UI, without printing its key.

--verify-configuration temporarily changes the interval by one second and restores
the original configuration. Tariffs and raw telemetry are never written here.
"""
import argparse
import http.cookiejar
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-configuration', action='store_true')
    args = parser.parse_args()
    link = urllib.parse.urlparse((ROOT / 'var/interface-access.url').read_text().strip())
    if link.scheme != 'http' or link.netloc != '127.0.0.1:8765':
        raise ValueError('unexpected access address')
    token = urllib.parse.parse_qs(link.fragment)['access'][0]
    origin = 'http://127.0.0.1:8765'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def api(path, method='GET', body=None, extra=None):
        headers = {'Origin': origin, **(extra or {})}
        data = json.dumps(body).encode() if body is not None else (b'' if method == 'POST' else None)
        if body is not None: headers['Content-Type'] = 'application/json'
        with opener.open(urllib.request.Request(origin + path, data=data, headers=headers, method=method), timeout=35) as response:
            return json.load(response)

    api('/api/session', 'POST', extra={'Authorization': 'Bearer ' + token})
    original = api('/api/settings')
    before = api('/api/status')
    view = api('/api/overview?hours=24')
    if before['state'] not in ('running', 'degraded') or view['sample_count'] < 1:
        raise RuntimeError('installed collector history is not available')
    report = {'version': original['version'], 'installed_api': 'ok', 'sample_count_24h': view['sample_count'],
              'sources': len(view['sensors']), 'tariff_records': len(original['tariffs']),
              'database_bytes': before['database_bytes'], 'scope': view['scope'],
              'configuration_roundtrip': 'not requested', 'original_interval': original['collector']['values']['interval_seconds']}
    if args.verify_configuration:
        original_values = original['collector']['values']
        candidate = dict(original_values)
        candidate['interval_seconds'] += -1 if candidate['interval_seconds'] >= 3600 else 1

        def wait_applied(revision):
            for _ in range(30):
                state = api('/api/status')
                if state['configuration']['applied_revision'] == revision:
                    return
                time.sleep(.25)
            raise RuntimeError('collector did not acknowledge the requested configuration')

        try:
            changed = api('/api/settings/collector', 'PUT', {'revision': original['collector']['revision'], **candidate})
            wait_applied(changed['revision'])
            report['configuration_roundtrip'] = 'applied'
        finally:
            current = api('/api/settings')['collector']
            restored = api('/api/settings/collector', 'PUT', {'revision': current['revision'], **original_values})
            wait_applied(restored['revision'])
            report['configuration_restored'] = True
    final = api('/api/settings')
    report['tariffs_unchanged'] = final['tariffs'] == original['tariffs']
    report['interval_after_validation'] = final['collector']['values']['interval_seconds']
    report['collector_state_after_validation'] = api('/api/status')['state']
    report['observed_utc_ms'] = time.time_ns() // 1_000_000
    output = ROOT / 'var/validation/installed-interface.json'
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
