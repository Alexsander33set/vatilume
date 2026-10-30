"""Stream original CPU/GPU inputs for a saved, bounded analysis snapshot."""
import csv
import io
import json
import sqlite3
import time
from contextlib import closing

from .storage import readonly


def stream_reader(database):
    # ASGI may resume each serialized generator step on a different worker.
    con = sqlite3.connect(database.resolve().as_uri()+'?mode=ro',timeout=2,isolation_level=None,check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA query_only=ON')
    return con


def validate_history(database, provenance, start_ms=None):
    with closing(readonly(database)) as con:
        _validate_reader(con, provenance, start_ms)


def _validate_reader(con, provenance, start_ms):
    highwater = provenance.get('highwater') if provenance else None
    if not highwater: raise ValueError('Este relatório não tem referência às leituras brutas.')
    cutoff=con.execute("SELECT value FROM metadata WHERE key='raw_pruned_max_utc_ns'").fetchone()
    if cutoff and (start_ms is None or start_ms*1_000_000 <= int(cutoff[0])):
        raise ValueError('Os dados brutos deste período expiraram conforme a retenção configurada. O relatório salvo permanece; o CSV original não está mais disponível.')
    previous=provenance.get('previous_sample_id')
    if previous and not con.execute('SELECT 1 FROM samples WHERE id=?',(previous,)).fetchone():
        raise ValueError('Uma leitura de origem necessária expirou conforme a retenção configurada. O relatório salvo permanece disponível.')
    row = con.execute('SELECT id,utc_ns,session_id FROM samples WHERE id=?', (highwater['id'],)).fetchone()
    current = dict(row) if row else None
    if current: current['utc_ns'] = str(current['utc_ns'])
    if current != highwater:
        raise ValueError('O histórico de origem mudou; não é possível confirmar esta exportação.')


def raw_csv(database, frozen):
    provenance, window = frozen['provenance'], frozen['window']
    previous = provenance['previous_sample_id'] or -1
    selected = provenance['selected_sources']
    fields = ['sample_id','session_id','utc_ns','monotonic_ns','boottime_ns','component','source_id','observed_utc_ns',
        'observed_monotonic_ns','raw_value','raw_unit','scale','counter_max_range','reading_quality','adapter_quality',
        'interval_seconds','sensor_timeout_seconds','preceding_window_sample']
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(fields)
    deadline = time.monotonic() + 30
    with closing(stream_reader(database)) as con:
        con.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        con.execute('BEGIN')
        _validate_reader(con, provenance, window['start_ms'])
        yield '\ufeff' + output.getvalue()
        output.seek(0);output.truncate(0)
        configurations = {row['hash']:json.loads(row['document']) for row in con.execute('SELECT hash,document FROM configurations')}
        rows = con.execute('''SELECT * FROM samples WHERE id<=? AND ((utc_ns>=? AND utc_ns<=?) OR id=?)
                              ORDER BY CASE WHEN id=? THEN 0 ELSE 1 END,id LIMIT 400002''',
            (provenance['highwater']['id'],window['start_ms']*1_000_000,window['end_ms']*1_000_000,previous,previous))
        for sample in rows:
            payload = json.loads(sample['collectors_json'])
            config = configurations[sample['config_hash']]
            for component, source in selected.items():
                adapter = payload.get(source['collector'], {})
                reading = next((r for r in adapter.get('readings',[]) if r['source_id']==source['id']), {})
                writer.writerow([sample['id'],sample['session_id'],sample['utc_ns'],sample['monotonic_ns'],sample['boottime_ns'],component,
                    source['id'],adapter.get('observed_utc_ns',sample['utc_ns']),adapter.get('observed_monotonic_ns',sample['monotonic_ns']),
                    reading.get('value'),source['unit'],source.get('scale',1),source.get('max_range'),reading.get('quality','missing'),
                    adapter.get('quality','missing'),config['interval_seconds'],config.get('sensor_timeout_seconds',2),sample['id']==previous])
            yield output.getvalue()
            output.seek(0);output.truncate(0)
