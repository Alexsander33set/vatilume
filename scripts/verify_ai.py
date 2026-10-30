#!/usr/bin/env python3
"""Check the installed AI interface; --paid-smoke explicitly runs one analysis.

Uses the owner's existing local capability without printing it. No credentials
are requested or returned. Paid requests use the installed cumulative ledger.
"""
import argparse
import csv
import http.cookiejar
import io
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--paid-smoke', action='store_true')
    parser.add_argument('--monthly', action='store_true', help='with --paid-smoke, verify the monthly projection question')
    parser.add_argument('--hours-per-day', type=float, default=8, help='daily hours for --monthly (default: 8)')
    args = parser.parse_args()
    link = urllib.parse.urlparse((ROOT / 'var/interface-access.url').read_text().strip())
    if link.scheme != 'http' or link.netloc != '127.0.0.1:8765': raise ValueError('Unexpected local address')
    token = urllib.parse.parse_qs(link.fragment)['access'][0]
    origin = 'http://127.0.0.1:8765'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def api(path, body=None, login=False):
        headers = {'Origin':origin}
        if login:headers['Authorization']='Bearer '+token
        payload = b'' if login else json.dumps(body).encode() if body is not None else None
        if body is not None:headers['Content-Type']='application/json'
        with opener.open(urllib.request.Request(origin+path,data=payload,headers=headers),timeout=35) as response:
            return json.load(response)

    api('/api/session',login=True)
    settings = api('/api/ai/settings')
    collector_before = api('/api/settings')['collector']['values']
    report = {'installed_ai_api':'ok','model':settings['model'],'authorized_total_usd':settings['authorized_total_usd'],
        'estimated_total_usd':settings['usage']['total_usd'],'key_configured':settings['key_configured'],
        'paid_smoke':'not requested'}
    if args.paid_smoke:
        view = api('/api/overview?hours=6')
        question = ('Com os dados que temos, qual seria o meu custo mensal de energia?' if args.monthly else
            'Compare a potência e o uso de CPU/GPU entre as metades do período, verifique cobertura e registre limitações. Investigue desvios quando houver dados suficientes.')
        quote = api('/api/ai/quotes',{**view['window'],'question':question,'hours_per_day':args.hours_per_day})
        if api('/api/ai/settings')['usage']['total_usd'] != settings['usage']['total_usd']:
            raise RuntimeError('Budget changed during the no-call preview; check concurrent activity')
        api('/api/ai/analyses/'+quote['id'],{})
        for _ in range(180):
            item = api('/api/ai/analyses/'+quote['id'])
            if item['state']!='running':break
            time.sleep(.5)
        if item['state']!='complete': raise RuntimeError('Installed analysis not completed: '+str(item.get('error')))
        claims = item['report']['claims']
        if not claims or item['report']['validation']!='server_computed_facts_and_references': raise RuntimeError('Invalid report')
        if args.monthly:
            answer = item['report'].get('answer')
            if not answer or answer['kind'] != 'monthly_projection': raise RuntimeError('Monthly question has no direct projection answer')
            if answer['values']['hours_per_day'] != args.hours_per_day: raise RuntimeError('Daily usage scenario changed')
            if answer['values']['whole_pc_measured']: raise RuntimeError('Components incorrectly presented as whole-PC measurement')
            if answer['text'] != quote['calculation_preview']['text']: raise RuntimeError('Local preview and final calculation differ')
            report.update(monthly_answer=answer['text'], monthly_status=answer['values']['status'],
                projection_hours_per_day=args.hours_per_day, preview_paid_calls=0)
        for claim in claims:
            for identity in claim['evidence_ids']:
                evidence = api('/api/ai/analyses/'+quote['id']+'/evidence/'+identity)
                if evidence['snapshot_sha256']!=quote['snapshot_sha256']:raise RuntimeError('Evidence snapshot mismatch')
        raw_evidence = next(e for e in item['report']['evidence'].values() if e['tool']=='calculate_energy_cost')
        request = urllib.request.Request(origin+'/api/ai/analyses/'+quote['id']+'/evidence/'+raw_evidence['id']+'/raw.csv')
        with opener.open(request,timeout=35) as response:
            reader = csv.DictReader(io.TextIOWrapper(response,encoding='utf-8-sig',newline=''))
            if not {'raw_value','raw_unit','observed_monotonic_ns','counter_max_range'}<=set(reader.fieldnames or []):raise RuntimeError('Raw source columns missing')
            raw_rows = sum(1 for _ in reader)
        if raw_rows<2:raise RuntimeError('Raw source export unexpectedly empty')
        if item['estimated_cost_usd']>quote['maximum_usd']+1e-9 and not quote.get('cached'): raise RuntimeError('Quoted ceiling exceeded')
        report.update(paid_smoke='passed',analysis_id=quote['id'],claims=len(claims),
            evidence_queries=len(item['report']['evidence']),analysis_estimated_usd=item['estimated_cost_usd'],raw_source_rows=raw_rows)
    report['collector_configuration_unchanged'] = api('/api/settings')['collector']['values']==collector_before
    report['collector_state'] = api('/api/status')['state']
    report['estimated_total_usd_after'] = api('/api/ai/settings')['usage']['total_usd']
    report['observed_utc_ms'] = time.time_ns()//1_000_000
    path = ROOT/'var/validation/installed-ai.json'
    path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
