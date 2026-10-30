#!/usr/bin/env python3
"""Verify installed process collection and, optionally, one budgeted AI analysis."""
import argparse
import csv
import http.cookiejar
import io
import json
import math
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wait-seconds',type=int,default=90)
    parser.add_argument('--paid-smoke',action='store_true')
    parser.add_argument('--applications',action='store_true',help='Require the installed application grouping and parent metadata')
    parser.add_argument('--metric',choices=('cpu_w','gpu_w'),default='cpu_w')
    args=parser.parse_args()
    link=urllib.parse.urlparse((ROOT/'var/interface-access.url').read_text().strip())
    if link.scheme!='http' or link.netloc!='127.0.0.1:8765':raise ValueError('Unexpected local origin')
    token=urllib.parse.parse_qs(link.fragment)['access'][0]
    origin='http://127.0.0.1:8765'
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def api(path,body=None,login=False):
        headers={'Origin':origin}
        if login:headers['Authorization']='Bearer '+token
        payload=b'' if login else json.dumps(body).encode() if body is not None else None
        if body is not None:headers['Content-Type']='application/json'
        with opener.open(urllib.request.Request(origin+path,data=payload,headers=headers),timeout=35) as response:return json.load(response)
    api('/api/session',login=True)
    settings=api('/api/settings')
    before=api('/api/ai/settings')
    if 'processes' not in settings['collector']['values']['enabled_collectors']:raise ValueError('Habilite o grupo Processos antes de verificar.')
    start=api('/api/status')['latest_session']['started_utc_ns']//1_000_000
    deadline=time.monotonic()+args.wait_seconds
    while True:
        end=time.time_ns()//10_000_000_000*10000
        if end-start<1000:time.sleep(1);continue
        view=api(f'/api/overview?start_ms={start}&end_ms={end}')
        history=view['processes']
        if any(entry['cpu_percent'] is not None for item in history['snapshots'] for entry in item['context']['entries']):break
        if time.monotonic()>=deadline:raise ValueError('Ainda não há duas leituras válidas de CPU por processo. Verifique permissões e cadência.')
        time.sleep(3)
    peaks=api(f'/api/processes/coincidences?start_ms={start}&end_ms={end}&metric={args.metric}')
    report={'version':settings['version'],'process_collection':'passed','metric':args.metric,'window':view['window'],
        'scans':history['scans'],'partial_scans':history['partial_scans'],'retained_snapshots':history['retained_snapshots'],
        'readable_processes_max':max(item['context']['readable'] for item in history['snapshots']),
        'cpu_intervals_max':max(item['context']['cpu_intervals'] for item in history['snapshots']),
        'coincidences':sum(bool(peak['matches']) for peak in peaks['peaks']),
        'paid_smoke':'not requested','estimated_total_usd_before':before['usage']['total_usd']}
    if args.applications:
        for item in history['snapshots']:
            context=item['context']
            if context.get('application_catalog_version')!=1:raise ValueError('O serviço instalado ainda não registra o parentesco necessário.')
            groups=context.get('applications')
            if not isinstance(groups,list):raise ValueError('O agrupamento não está disponível.')
            identities=[]
            for group in groups:
                entries=group['entries']
                identities.extend((entry['pid'],entry['start_ticks']) for entry in entries)
                known=[entry['cpu_percent'] for entry in entries if entry['cpu_percent'] is not None]
                if group['cpu_percent'] is None:
                    if known:raise ValueError('CPU disponível omitida no grupo.')
                elif not known or not math.isclose(group['cpu_percent'],sum(known),abs_tol=1e-9):raise ValueError('Soma de CPU incorreta.')
                if group['rss_bytes']!=sum(entry['rss_bytes'] for entry in entries):raise ValueError('Soma RSS incorreta.')
                if not group['members_only']:raise ValueError('O grupo foi apresentado indevidamente como uso total do aplicativo.')
            original={(entry['pid'],entry['start_ticks']) for entry in context['entries']}
            if len(identities)!=len(set(identities)) or set(identities)!=original:raise ValueError('Agrupamento omitiu ou duplicou processos.')
        report.update(application_grouping='passed',authorized_total_usd=before['authorized_total_usd'],
            recognized_groups_max=max(sum(g['recognized'] for g in item['context']['applications']) for item in history['snapshots']),
            parent_identifications=sum(entry.get('application',{}).get('method')=='parent_rule' for item in history['snapshots'] for group in item['context']['applications'] for entry in group['entries']))
    if args.paid_smoke:
        component='GPU' if args.metric=='gpu_w' else 'CPU'
        question=f'Quais aplicativos coincidiram com os maiores intervalos médios de potência da {component} neste período? Mostre coincidência e limites, sem afirmar causa ou consumo total por aplicativo.'
        quote=api('/api/ai/quotes',{**view['window'],'question':question})
        api('/api/ai/analyses/'+quote['id'],{})
        for _ in range(180):
            record=api('/api/ai/analyses/'+quote['id'])
            if record['state']!='running':break
            time.sleep(.5)
        if record['state']!='complete':raise ValueError('A análise instalada não concluiu: '+str(record.get('error')))
        answer=record['report']['answer']
        if report['coincidences'] and answer['kind']!='process_coincidence':raise ValueError('A resposta omitiu a coincidência disponível.')
        proofs=[item for item in record['report']['evidence'].values() if item['tool']=='inspect_process_activity']
        if not proofs:raise ValueError('A consulta de processos não foi registrada.')
        proof=next((item for item in proofs if any(peak['matches'] for peak in item['data']['peaks'])),proofs[0])
        if proof['data']['causality_proven']:raise ValueError('Causalidade indevida.')
        with opener.open(origin+'/api/ai/analyses/'+quote['id']+'/evidence/'+proof['id']+'/processes.csv',timeout=35) as response:
            reader=csv.DictReader(io.TextIOWrapper(response,encoding='utf-8-sig',newline=''))
            if not {'elapsed_ns','previous_cpu_ticks','machine_cpu_count'}<=set(reader.fieldnames or []):raise ValueError('Contadores de origem ausentes.')
            if args.applications and not {'application_name','application_method','ancestors_json','ppid'}<=set(reader.fieldnames or []):raise ValueError('Identificação ausente do CSV.')
            rows=sum(1 for _ in reader)
        if report['coincidences'] and rows==0:raise ValueError('Exportação vazia apesar de coincidências.')
        if record['estimated_cost_usd']>quote['maximum_usd'] and not quote.get('cached'):raise ValueError('Teto excedido.')
        report.update(paid_smoke='passed',analysis_id=quote['id'],answer_kind=answer['kind'],claims=len(record['report']['claims']),
            process_csv_rows=rows,analysis_estimated_usd=record['estimated_cost_usd'],elapsed_seconds=record['report']['elapsed_seconds'])
    final=api('/api/settings')
    if final['collector']['values']!=settings['collector']['values'] or final['tariffs']!=settings['tariffs']:raise ValueError('Configuração ou tarifas mudaram durante a validação.')
    after=api('/api/ai/settings')
    report.update(collector_configuration_preserved=True,tariffs_preserved=True,collector_state=api('/api/status')['state'],
        estimated_total_usd_after=after['usage']['total_usd'],pending_usd=after['usage']['pending_usd'],observed_utc_ms=time.time_ns()//1_000_000)
    name=f'installed-applications-{args.metric}.json' if args.applications else 'installed-processes.json'
    (ROOT/'var/validation'/name).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
