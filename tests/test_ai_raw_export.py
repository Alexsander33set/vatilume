import csv
import io
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from device_observability.analysis import overview
from device_observability.ai_evidence import snapshot
from device_observability.ai_raw_export import raw_csv, validate_history
from test_analysis import synthetic, BASE


class RawEvidenceTests(unittest.TestCase):
    def test_raw_inputs_include_preceding_reading_and_exclude_later_commits_and_nested_core(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = synthetic(temporary)
            view = overview(database,BASE+5000,BASE+20000,[],24)
            frozen = snapshot(view,[])
            with sqlite3.connect(database) as con:
                con.execute('''INSERT INTO samples(session_id,sequence,utc_ns,monotonic_ns,boottime_ns,config_hash,collection_ms,collectors_json)
                    SELECT session_id,99,?,monotonic_ns,boottime_ns,config_hash,collection_ms,collectors_json FROM samples WHERE id=3''',
                    ((BASE+15000)*1_000_000,))
            validate_history(database,frozen['provenance'])
            text = ''.join(raw_csv(database,frozen)).lstrip('\ufeff')
            rows = list(csv.DictReader(io.StringIO(text)))
            self.assertEqual({r['sample_id'] for r in rows},{'1','2','3'})
            self.assertEqual({r['component'] for r in rows},{'cpu','gpu'})
            self.assertNotIn('core',{r['source_id'] for r in rows})
            self.assertEqual(len(rows),6)
            self.assertEqual(rows[0]['utc_ns'],str(BASE*1_000_000))
            self.assertEqual(rows[0]['preceding_window_sample'],'True')
            self.assertEqual(rows[0]['boottime_ns'],'0')
            with sqlite3.connect(database) as con:con.execute('UPDATE samples SET utc_ns=utc_ns+1 WHERE id=3')
            with self.assertRaises(ValueError):validate_history(database,frozen['provenance'])

    def test_asgi_can_resume_readonly_csv_on_different_workers(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = synthetic(temporary)
            frozen = snapshot(overview(database,BASE,BASE+20000,[],24),[])
            stream = raw_csv(database,frozen)
            with ThreadPoolExecutor(max_workers=1) as first, ThreadPoolExecutor(max_workers=1) as second:
                self.assertIn('sample_id',first.submit(next,stream).result())
                self.assertIn('cpu',first.submit(next,stream).result())
                self.assertIn('gpu',second.submit(next,stream).result())
                second.submit(stream.close).result()
