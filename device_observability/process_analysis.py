"""Bounded, local process evidence and temporal overlap, never causal attribution."""
from __future__ import annotations

import math
from .applications import group_entries, identify

PROCESS_METRICS = {'cpu_w':('potência reportada da CPU','W'), 'gpu_w':('potência reportada da GPU','W'),
                   'cpu_percent':('uso da CPU','%'), 'gpu_percent':('uso da GPU','%')}


def checked_cpu(entry, context):
    """Recheck the stored calculation from its counters; missing baselines remain unknown."""
    try:
        hz, cores, elapsed = context['clock_ticks_per_second'], context['machine_cpu_count'], entry['elapsed_ns']
        old, current = entry['previous_cpu_ticks'], entry['cpu_ticks']
        if any(type(value) is not int for value in (hz,cores,elapsed,old,current)):
            return None
        if min(hz,cores,elapsed) <= 0 or old < 0 or current < old:
            return None
        if not 0 < elapsed <= (context['interval_seconds']*2.5+2)*1e9:
            return None
        if entry['interval_start_ms'] is None or abs((entry['interval_end_ms']-entry['interval_start_ms'])*1e6-elapsed) >= 2e9:
            return None
        value = (current-old)/hz/(elapsed/1e9)/cores*100
        reported = entry['cpu_percent']
        if type(reported) not in (int,float) or not math.isfinite(reported) or not 0 <= value <= 100.01 or abs(reported-min(value,100)) > 1e-6:
            return None
        return min(value,100.0)
    except (KeyError,TypeError,ValueError,OverflowError):
        return None


class ProcessHistory:
    def __init__(self, start_ms, end_ms, points):
        self.start, self.end, self.width = start_ms, end_ms, (end_ms-start_ms)/points
        self.cells = [None] * points
        self.scans = self.failed = self.partial = self.warmup = 0

    def add(self, row, result):
        self.scans += 1
        context = result.get('context')
        if result['quality'] != 'ok' or not isinstance(context, dict):
            self.failed += 1
            return
        context = {**context, 'entries':[{**entry,'cpu_percent':checked_cpu(entry,context)} for entry in context['entries'][:20]]}
        context['applications'] = group_entries(context['entries'])
        stamp = result.get('observed_utc_ns', row['utc_ns']) // 1_000_000
        if not self.start <= stamp <= self.end:
            return
        partial = context['truncated'] or context['permission_denied'] or context['parse_errors']
        self.partial += bool(partial)
        self.warmup += context['cpu_intervals'] == 0
        index = min(len(self.cells)-1, int((stamp-self.start)/self.width))
        item = {'sample_id':row['id'], 'session_id':row['session_id'], 'time_ms':stamp,
                'quality':'partial' if partial else 'ok', 'context':context}
        center = self.start+(index+.5)*self.width
        old = self.cells[index]
        if old is None or abs(stamp-center) < abs(old['time_ms']-center):
            self.cells[index] = item

    def document(self):
        snapshots = [item for item in self.cells if item]
        return {'available':bool(snapshots), 'scans':self.scans, 'failed_scans':self.failed,
                'partial_scans':self.partial, 'warmup_scans':self.warmup,
                'retained_snapshots':len(snapshots), 'bucket_seconds':self.width/1000,
                'sampling_method':'Uma varredura por intervalo agregado, a mais próxima do centro. Sem preencher lacunas.',
                'snapshots':snapshots}


def process_aliases(history):
    identities = sorted({identify(entry)['id'] for item in history.get('snapshots', []) for entry in item['context']['entries'][:20]})
    return {identity:f'A{i+1:03d}' for i, identity in enumerate(identities)}


def coincidences(series, history, window, metric):
    if metric not in PROCESS_METRICS:
        raise ValueError('Métrica não permitida para investigar processos.')
    title, unit = PROCESS_METRICS[metric]
    aliases = process_aliases(history)
    valid = [(i,p) for i,p in enumerate(series) if type(p.get(metric)) in (int,float) and math.isfinite(p[metric])]
    chosen = []
    for index, point in sorted(valid, key=lambda pair:(-pair[1][metric],pair[0])):
        if all(abs(index-old[0]) >= 2 for old in chosen):
            chosen.append((index,point))
        if len(chosen) == 3:
            break
    width = (window['end_ms']-window['start_ms'])/max(1,len(series))
    peaks = []
    for index, point in chosen:
        left, right = window['start_ms']+index*width, window['start_ms']+(index+1)*width
        candidates = []
        for item in history.get('snapshots', []):
            checked = [{**entry,'cpu_percent':checked_cpu(entry,item['context'])} for entry in item['context']['entries'][:20]]
            entries = [entry for entry in checked if entry['cpu_percent'] is not None
                and entry['cpu_percent'] > 0 and entry['interval_start_ms'] is not None
                and entry['interval_start_ms'] >= window['start_ms'] and entry['interval_end_ms'] <= window['end_ms']
                and entry['interval_start_ms'] < right and entry['interval_end_ms'] > left]
            if entries:
                candidates.append((item,entries))
        selected = min(candidates,key=lambda pair:abs(pair[0]['time_ms']-point['time_ms'])) if candidates else None
        groups = group_entries(selected[1]) if selected else []
        matches = [{**group, 'alias':aliases[group['id']]} for group in groups[:3]]
        peaks.append({'index':index,'time_ms':point['time_ms'],'start_ms':left,'end_ms':right,
            'value':point[metric], 'matches':matches, 'sample_id':selected[0]['sample_id'] if selected else None,
            'session_id':selected[0]['session_id'] if selected else None,
            'scan':{k:v for k,v in selected[0]['context'].items() if k!='entries'} if selected else None,
            'scan_quality':selected[0]['quality'] if selected else None})
    return {'metric':metric,'title':title,'unit':unit,'peaks':peaks,'history_available':history.get('available',False),
        'bucket_seconds':width/1000,'causality_proven':False,'per_process_gpu_available':False,
        'method':'Até três maiores médias dos intervalos do painel, separados por ao menos um intervalo. '
            'Seleciona a varredura retida mais próxima com um intervalo de CPU efetivamente sobreposto. '
            'Agrupa nomes reconhecidos por regras locais e auxiliares por vínculos de parentesco registrados na varredura. '
            'Desconhecidos ficam separados por PID/início; nomes não autenticam o executável. '
            'CPU é porcentagem da capacidade total da máquina. Soma somente os processos retidos, não o total de cada aplicativo. RSS pode repetir páginas compartilhadas. '
            'Coincidência de intervalos não atribui energia nem comprova causa; não há uso de GPU por processo.'}
