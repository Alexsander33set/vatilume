"""Daily time observed by the collector, including idle, never user presence."""
from contextlib import closing
from datetime import datetime, timedelta
import json
import time
from zoneinfo import ZoneInfo
from .storage import readonly

ZONE = ZoneInfo('America/Sao_Paulo')


def observed_usage(database, end_ms, days=30):
    end = datetime.fromtimestamp(end_ms / 1000, ZONE)
    start = (end - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    totals, previous, count = {}, None, 0
    deadline = time.monotonic() + 8
    with closing(readonly(database)) as con:
        con.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        con.execute('BEGIN')
        configs = {r['hash']: json.loads(r['document']) for r in con.execute('SELECT * FROM configurations')}
        cursor = con.execute('SELECT id,session_id,utc_ns,monotonic_ns,boottime_ns,config_hash FROM samples WHERE utc_ns>=? AND utc_ns<=? ORDER BY id LIMIT 400001',
                             (int(start.timestamp()*1e9), end_ms * 1_000_000))
        for row in cursor:
            count += 1
            if count > 400000 or time.monotonic() > deadline:
                raise ValueError('Há muitos dados para calcular o tempo observado. Use uma cadência maior ou informe horas explicitamente.')
            instant = row['utc_ns'] / 1e9
            date = datetime.fromtimestamp(instant, ZONE).date().isoformat()
            totals.setdefault(date, 0.)
            if previous is not None:
                dt = (row['monotonic_ns']-previous['monotonic_ns'])/1e9
                cfg = configs[row['config_hash']]
                valid = (row['session_id']==previous['session_id'] and 0 < dt <= cfg['interval_seconds']*2.5+cfg.get('sensor_timeout_seconds',2)
                         and abs((row['utc_ns']-previous['utc_ns'])/1e9-dt)<2
                         and abs((row['boottime_ns']-previous['boottime_ns'])/1e9-dt)<1)
                if valid:
                    left = previous['utc_ns']/1e9
                    while left < instant:
                        at = datetime.fromtimestamp(left, ZONE)
                        right = min(instant,(at+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0).timestamp())
                        portion = dt*(right-left)/(instant-previous['utc_ns']/1e9)
                        key = at.date().isoformat();totals[key]=totals.get(key,0.)+portion
                        left=right
            previous=row
    entries=[{'date':d,'observed_hours':min(24,s/3600),'partial':d==end.date().isoformat()} for d,s in sorted(totals.items())]
    # Prefer completed days; the first recorded day may be installation mid-day.
    completed=entries[1:] if len(entries)>1 else []
    completed=[d for d in completed if not d['partial'] and d['observed_hours']>0]
    chosen=completed or [d for d in entries if d['observed_hours']>0]
    hours=sum(d['observed_hours'] for d in chosen)/len(chosen) if chosen else None
    return {'hours_per_day':hours,'days_observed':len(chosen),'daily':entries,'basis':'collector_valid_intervals_including_idle',
            'timezone':str(ZONE),'partial_base':not bool(completed),'lookback_days':days,
            'note':'Tempo observado, não presença do usuário. Dias sem leituras são desconhecidos; não comprovam PC desligado. A base parcial pode subestimar a rotina.'}
