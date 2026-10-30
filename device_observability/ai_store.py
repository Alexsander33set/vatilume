"""Saved, immutable analysis snapshots and evidence, separate from telemetry."""
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path


class AIStore:
    def __init__(self, path: Path):
        self.path = path
        with closing(self.connect()) as con:
            con.execute('''CREATE TABLE IF NOT EXISTS ai_records(
                id TEXT PRIMARY KEY, created_ms INTEGER NOT NULL, state TEXT NOT NULL,
                snapshot TEXT NOT NULL, question TEXT NOT NULL, report TEXT, error TEXT)''')

    def recover(self):
        # Caller holds the analysis lock; another worker must never interrupt a live job.
        with closing(self.connect()) as con:
            con.execute("UPDATE ai_records SET state='interrupted',error=? WHERE state='running'",
                        ('A aplicação reiniciou durante a análise. Reservas incertas foram preservadas.',))

    def connect(self):
        con = sqlite3.connect(self.path, timeout=3, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('PRAGMA synchronous=FULL')
        return con

    def create(self, identity, snapshot, question):
        with closing(self.connect()) as con:
            con.execute('INSERT INTO ai_records VALUES (?,?,?,?,?,?,?)',
                (identity, time.time_ns() // 1_000_000, 'quoted', json.dumps(snapshot), question, None, None))

    def get(self, identity, snapshot=False):
        with closing(self.connect()) as con:
            row = con.execute('SELECT * FROM ai_records WHERE id=?', (identity,)).fetchone()
            if not row: raise ValueError('Análise não encontrada.')
            item = dict(row)
            if snapshot: item['snapshot'] = json.loads(item['snapshot'])
            else: item.pop('snapshot')
            item['report'] = json.loads(item['report']) if item['report'] else None
            return item

    def start(self, identity):
        with closing(self.connect()) as con:
            row = con.execute('SELECT state,created_ms FROM ai_records WHERE id=?', (identity,)).fetchone()
            if not row or row['state'] != 'quoted': raise ValueError('Esta solicitação já foi usada ou não existe.')
            if time.time_ns() // 1_000_000 - row['created_ms'] > 180_000: raise ValueError('A prévia expirou. Prepare uma nova análise.')
            changed = con.execute("UPDATE ai_records SET state='running' WHERE id=? AND state='quoted'", (identity,)).rowcount
            if changed != 1: raise ValueError('Esta solicitação já foi iniciada.')

    def finish(self, identity, report=None, error=None):
        with closing(self.connect()) as con:
            con.execute('UPDATE ai_records SET state=?,report=?,error=? WHERE id=?',
                ('failed' if error else 'complete', json.dumps(report) if report else None, error, identity))

    def recent(self):
        with closing(self.connect()) as con:
            return [dict(r) for r in con.execute('SELECT id,created_ms,state,question,error FROM ai_records ORDER BY created_ms DESC LIMIT 30')]

    def cached(self, digest, question, model, validator_version):
        with closing(self.connect()) as con:
            for row in con.execute("SELECT id,report FROM ai_records WHERE state='complete' AND question=? ORDER BY created_ms DESC LIMIT 30", (question,)):
                report = json.loads(row['report'])
                if report['snapshot_sha256'] == digest and report['model'] == model and report['validator_version'] == validator_version:
                    return row['id']
        return None
